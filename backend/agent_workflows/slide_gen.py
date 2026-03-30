import asyncio
import json
import random
import shutil
import string
import uuid
from pathlib import Path
from typing import Optional

import click

import inspect
from llama_index.core import (
    Settings,
    SimpleDirectoryReader,
    PromptTemplate,
)
from llama_index.core.workflow import (
    Context,
    StartEvent,
    StopEvent,
    step,
)
from llama_index.core.tools import FunctionTool
from llama_index.core.agent.workflow import ReActAgent, AgentStream, ToolCall
from llama_index.core.output_parsers import PydanticOutputParser
from llama_index.core.program import (
    FunctionCallingProgram,
    MultiModalLLMCompletionProgram,
)

from config import settings
from prompts.prompts import (
    SLIDE_GEN_PMT,
    REACT_PROMPT_SUFFIX,
    SUMMARY2OUTLINE_PMT,
    AUGMENT_LAYOUT_PMT,
    SLIDE_VALIDATION_PMT,
    SLIDE_MODIFICATION_PMT,
    MODIFY_SUMMARY2OUTLINE_PMT,
)
from services.embeddings import embedder
from services.sandbox import LlmSandboxToolSpec, SANDBOX_DIR
from services.llms import (
    llm,
    new_llm,
    new_fast_llm,
    new_vlm,
)
from utils.tools import get_all_layouts_info
from utils.file_processing import pptx2images
from agent_workflows.events import *
from agent_workflows.hitl_workflow import HumanInTheLoopWorkflow
import mlflow
from utils.logger import get_logger

logger = get_logger(__name__)

Settings.llm = llm
Settings.embed_model = embedder


def read_summary_content(file_path: Path):
    """
    Read the content of the summary file
    :param file_path: Path to the summary file
    :return: Content of the summary file
    """
    with file_path.open("r") as file:
        return file.read()


class SlideGenerationWorkflow(HumanInTheLoopWorkflow):
    wid: Optional[uuid.UUID] = uuid.uuid4()
    max_validation_retries: int = 2
    slide_template_path: str = settings.SLIDE_TEMPLATE_PATH

    _GENERATED_SLIDE_FNAME = "paper_summaries.pptx"
    _SLIDE_OUTLINE_FNAME = "slide_outlines.json"

    def __init__(self, wid: Optional[uuid.UUID] = uuid.uuid4(), *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.wid = wid
        self.generated_slide_fname = self._GENERATED_SLIDE_FNAME
        self.slide_outlines_fname = self._SLIDE_OUTLINE_FNAME
        self.workflow_artifacts_path = (
            Path(settings.WORKFLOW_ARTIFACTS_ROOT)
            / self.__class__.__name__
            / str(self.wid)
        )
        self.workflow_artifacts_path.mkdir(parents=True, exist_ok=True)

        self.sandbox = LlmSandboxToolSpec(
            local_save_path=self.workflow_artifacts_path.as_posix(),
        )
        self.pdf2images_tool = FunctionTool.from_defaults(fn=pptx2images)
        self.save_python_code_tool = FunctionTool.from_defaults(
            fn=self.save_python_code
        )
        self.all_layout = get_all_layouts_info(self.slide_template_path)
        self.all_layout_tool = FunctionTool.from_defaults(fn=self.get_all_layout)

        self.parent_workflow = None
        self.user_input_future = asyncio.Future()
        self.user_input = None

    def __del__(self) -> None:
        try:
            self.sandbox.close()
        except Exception:
            pass

    def copy_final_slide(self):
        """
        Go through all the pptx files in self.workflow_artifacts_path, find the final file
        and copy it to settings.WORKFLOW_ARTIFACTS_ROOT as final.pptx.
        """
        pptx_files = list(
            self.workflow_artifacts_path.glob(
                f"{Path(self.generated_slide_fname).stem}*.pptx"
            )
        )
        if not pptx_files:
            raise FileNotFoundError(
                "No pptx files found in the workflow artifacts path."
            )

        # Find the file with the largest version number
        final_file = None
        max_version = -1
        for file in pptx_files:
            if file.stem == "paper_summaries":
                final_file = file
                break
            else:
                try:
                    version = int(file.stem.split("_v")[-1])
                    if version > max_version:
                        max_version = version
                        final_file = file
                except ValueError:
                    continue

        if not final_file:
            raise FileNotFoundError(
                "No valid pptx files found in the workflow artifacts path."
            )

        # Copy the final file to the destination
        destination = self.workflow_artifacts_path / "final.pptx"
        shutil.copy(final_file, destination)
        logger.info(f"Copied final slide to {destination}")

        # Construct the corresponding PDF file path
        final_pdf_file = final_file.with_suffix(".pdf")
        if final_pdf_file.exists():
            # Copy the final PDF file to the destination
            destination_pdf = self.workflow_artifacts_path / "final.pdf"
            shutil.copy(final_pdf_file, destination_pdf)
            logger.info(f"Copied final PDF to {destination_pdf}")
        else:
            logger.warning(f"Corresponding PDF file {final_pdf_file} not found.")

    def get_all_layout(self):
        """Get all layout information"""
        return self.all_layout

    def download_all_files_from_session(self) -> list[str]:
        """Download all files from the sandbox container to the workflow artifacts path."""
        local_files = []
        for f in self.sandbox.list_files():
            local_path = f"{self.workflow_artifacts_path.as_posix()}/{f.filename}"
            logger.info(f"Downloading sandbox file: {f.file_full_path} → {local_path}")
            self.sandbox.download_file_to_local(
                remote_file_path=f.file_full_path,
                local_file_path=local_path,
            )
            local_files.append(local_path)
        return local_files

    def save_python_code(self, code: str):
        """Save the python code to file"""
        with open(f"{self.workflow_artifacts_path}/code.py", "w") as f:
            f.write(code)

    async def run_react_agent(
        self, agent: ReActAgent, prompt: str, wf_ctx: Context
    ) -> None:
        """Run agent and forward streaming events to the workflow context.

        Uses llama-index 0.14.x event streaming API:
          handler = agent.run(prompt)
          async for ev in handler.stream_events(): ...
          response = await handler
        """
        handler = agent.run(prompt)
        async for ev in handler.stream_events():
            if isinstance(ev, AgentStream) and ev.delta:
                self._emit_message(wf_ctx, "react_agent", message=ev.delta)
            elif isinstance(ev, ToolCall):
                logger.info(f"[Tool] {ev.tool_name}({ev.tool_kwargs})")
        response = await handler
        self._emit_message(wf_ctx, "react_agent", message=f"Agent response: {response}")

    @step(num_workers=1)
    async def get_summaries(self, ctx: Context, ev: StartEvent) -> SummaryEvent:
        """Entry point of the workflow. Read the content of the summary files from provided
        directory. For each summary file, send a SummaryEvent to the next step."""

        markdown_files = list(Path(ev.get("file_dir")).glob("*.md"))
        async with ctx.store.edit_state() as state:
            state["n_retry"] = 0  # keep count of slide validation retries
            state["n_summaries"] = len(markdown_files)
        n_summaries = await ctx.store.get("n_summaries")
        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message=f"Reading {n_summaries} summaries from markdown files...")
        for i, f in enumerate(markdown_files):
            s = read_summary_content(f)
            self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                               message=f"Sending {i}th summaries...")
            ctx.send_event(SummaryEvent(summary=s))

    @step(num_workers=settings.NUM_WORKERS_FAST)
    async def summary2outline(
        self, ctx: Context, ev: SummaryEvent | OutlineFeedbackEvent
    ) -> OutlineEvent:
        """Convert the summary content of one paper to slide outline of one page, mainly
        condense and shorten the elaborated summary content to short sentences or bullet points.
        """
        await asyncio.sleep(settings.DELAY_SECONDS_FAST)
        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message="Making summary to slide outline...")
        llm = new_fast_llm(0.1)
        if isinstance(ev, OutlineFeedbackEvent):
            program = FunctionCallingProgram.from_defaults(
                llm=llm,
                output_cls=SlideOutline,
                prompt_template_str=MODIFY_SUMMARY2OUTLINE_PMT,
                verbose=True,
            )
            response = await program.acall(
                summary_txt=ev.summary,
                outline_txt=ev.outline.model_dump(),
                feedback=ev.feedback,
                description="Data model for the slide page outline",
            )

        else:
            program = FunctionCallingProgram.from_defaults(
                llm=llm,
                output_cls=SlideOutline,
                prompt_template_str=SUMMARY2OUTLINE_PMT,
                verbose=True,
            )
            response = await program.acall(
                summary=ev.summary,
                description="Data model for the slide page outline",
            )
        # async for response in generator:
        #     # Allow the workflow to stream this piece of response
        json_resp = {"original_summary": ev.summary}
        json_resp.update(json.loads(response.json()))

        return OutlineEvent(summary=ev.summary, outline=response)

    @step
    async def gather_feedback_outline(
        self, ctx: Context, ev: OutlineEvent
    ) -> OutlineFeedbackEvent | OutlineOkEvent:
        """Present user the original paper summary and the outlines generated, gather feedback from user"""
        # ready = ctx.collect_events(ev, [OutlineEvent] * ctx.data["n_summaries"])
        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message="Gathering feedback on the outline...")

        # Send a special event indicating that user input is needed
        self._emit_message(
            ctx,
            inspect.currentframe().f_code.co_name,
            event_type="request_user_input",
            eid="".join(random.choices(string.ascii_lowercase + string.digits, k=10)),
            summary=ev.summary,
            outline=ev.outline.dict(),
            message="Do you approve this outline? If not, please provide feedback.",
        )
        # Initialize the future if it's None
        if self.user_input_future is None:
            logger.info(
                "self.user_input_future is None, initializing user input future"
            )
            self.user_input_future = self.loop.create_future()

        # Wait for user input
        if not self.user_input_future.done():
            logger.info(f"gather_feedback_outline: Event loop id {id(self.loop)}")
            logger.info("gather_feedback_outline: Waiting for user input")
            user_response = await self.user_input_future
            logger.info(f"gather_feedback_outline: Got user response: {user_response}")

            # Reset the input future
            if self.parent_workflow:
                logger.info(
                    "Resetting user input future by self.parent_workflow.reset_user_input_future()"
                )
                await self.parent_workflow.reset_user_input_future()
                self.user_input_future = self.parent_workflow.user_input_future
            else:
                logger.info("Resetting user input future by self.loop.create_future()")
                self.user_input_future = self.loop.create_future()

            # Process user_response, which should be a JSON string
            try:
                response_data = json.loads(user_response)
                approval = response_data.get("approval", "").lower().strip()
                feedback = response_data.get("feedback", "").strip()
            except json.JSONDecodeError:
                # Handle invalid JSON
                logger.error("Invalid user response format")
                raise Exception("Invalid user response format")

            if approval == ":material/thumb_up:":
                return OutlineOkEvent(summary=ev.summary, outline=ev.outline)
            else:
                return OutlineFeedbackEvent(
                    summary=ev.summary, outline=ev.outline, feedback=feedback
                )
        else:
            logger.info("User input future is already done, skipping await.")

    @step
    async def outlines_with_layout(
        self, ctx: Context, ev: OutlineOkEvent
    ) -> OutlinesWithLayoutEvent:
        """Given a list of slide page outlines, augment each outline with layout information.
        The layout information includes the layout name, the index of the title placeholder,
        and the index of the content placeholder. Return an event with the augmented outlines.
        """
        n_summaries = await ctx.store.get("n_summaries")
        ready = ctx.collect_events(ev, [OutlineOkEvent] * n_summaries)
        if ready is None:
            return None
        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message="Outlines for all papers are ready! Adding layout info...")
        all_layout_names = [layout["layout_name"] for layout in self.all_layout]

        # add layout to outline
        llm = new_llm(0.1)
        program = FunctionCallingProgram.from_defaults(
            llm=llm,
            output_cls=SlideOutlineWithLayout,
            prompt_template_str=AUGMENT_LAYOUT_PMT,
            verbose=True,
        )
        slides_w_layout = []
        for n, ev in enumerate(ready):
            response = await program.acall(
                slide_content=ev.outline.model_dump(),
                available_layout_names=all_layout_names,
                available_layouts=self.all_layout,
                description="Data model for the slide page outline with layout",
            )
            slides_w_layout.append(response)

        # store the slide outlines as json file
        slide_outlines_json = self.workflow_artifacts_path.joinpath(
            self.slide_outlines_fname
        )
        with slide_outlines_json.open("w") as f:
            json.dump([o.json() for o in slides_w_layout], f, indent=4)
        # ctx.data["slide_outlines_json"] = slide_outlines_json
        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message=f"{len(slides_w_layout)} outlines with layout are ready! "
                           f"Stored in {slide_outlines_json}")

        return OutlinesWithLayoutEvent(
            outlines_fpath=slide_outlines_json, outline_example=slides_w_layout[0]
        )

    @step
    async def slide_gen(
        self, ctx: Context, ev: OutlinesWithLayoutEvent
    ) -> SlideGeneratedEvent:
        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message="Agent is generating slide deck...")
        agent = ReActAgent(
            tools=self.sandbox.to_tool_list() + [self.all_layout_tool],
            llm=new_llm(0.1),
            verbose=True,
            timeout=300,
        )
        system_prompt = (
            SLIDE_GEN_PMT.format(
                json_file_path=ev.outlines_fpath.as_posix(),
                template_fpath=self.slide_template_path,
                generated_slide_fname=self.generated_slide_fname,
            )
            + REACT_PROMPT_SUFFIX
        )
        agent.update_prompts({"react_header": PromptTemplate(system_prompt)})

        upload_result = self.sandbox.upload_file(local_file_path=self.slide_template_path)
        logger.info(upload_result)

        await self.run_react_agent(
            agent,
            f"An example of outline item in json is {ev.outline_example.model_dump()},"
            f" generate a slide deck",
            ctx,
        )
        local_files = self.download_all_files_from_session()
        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message=f"Agent finished! Downloaded files to local path: {local_files}")
        expected_pptx = self.workflow_artifacts_path / self.generated_slide_fname
        if not expected_pptx.exists():
            raise RuntimeError(
                f"[slide_gen] Agent did not produce expected file: {expected_pptx}. "
                "Agent may have misunderstood the task or failed to execute run_code."
            )
        return SlideGeneratedEvent(pptx_fpath=expected_pptx.as_posix())

    @step(num_workers=settings.NUM_WORKERS_VISION)
    async def validate_slides(
        self, ctx: Context, ev: SlideGeneratedEvent
    ) -> StopEvent | SlideValidationEvent:
        """Validate the generated slide deck"""
        await asyncio.sleep(settings.DELAY_SECONDS_VISION)
        async with ctx.store.edit_state() as state:
            state["n_retry"] = state.get("n_retry", 0) + 1
            state["latest_pptx_file"] = Path(ev.pptx_fpath).name
        n_retry = await ctx.store.get("n_retry")
        latest_pptx_file = await ctx.store.get("latest_pptx_file")
        logger.info(f"[validate_slides] the retry count is: {n_retry}")
        logger.info(
            f"[validate_slides] Validating the generated slide deck"
            f" {Path(ev.pptx_fpath).name} | {latest_pptx_file}..."
        )
        # slide to images
        img_dir = pptx2images(Path(ev.pptx_fpath))
        logger.info(f"[validate_slides] Storing pptx as images in" f" {img_dir}...")
        # upload image w. prompt for validation to llm and get structured response
        image_documents = SimpleDirectoryReader(img_dir).load_data()

        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message=f"{n_retry}th try for validating the generated slide deck...")
        needs_modify = []
        for img_doc in image_documents:
            program = MultiModalLLMCompletionProgram.from_defaults(
                output_parser=PydanticOutputParser(SlideValidationResult),
                image_documents=[img_doc],
                prompt_template_str=SLIDE_VALIDATION_PMT,
                multi_modal_llm=new_vlm(),
                verbose=True,
            )
            response = program()
            if response.is_valid:
                continue
            else:
                page_idx = (
                    img_doc.metadata.get("file_name", "")
                    .rstrip(".png")
                    .split("_")[-1]
                    .split(".")[0]
                )
                needs_modify.append(
                    SlideNeedModifyResult(
                        slide_idx=int(page_idx),
                        suggestion_to_fix=response.suggestion_to_fix,
                    )
                )

        if not needs_modify:
            self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                               message="The slides are fixed!")
            self.copy_final_slide()
            return StopEvent(
                self.workflow_artifacts_path.joinpath(self.generated_slide_fname)
            )
        else:
            if n_retry < self.max_validation_retries:
                self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                                   message="The slides are not fixed, retrying...")
                return SlideValidationEvent(results=needs_modify)
            else:
                self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                                   message=f"The slides are not fixed after {self.max_validation_retries} retries!")
                self.copy_final_slide()
                return StopEvent(
                    f"The slides are not fixed after {self.max_validation_retries} retries!"
                )

    @step
    async def modify_slides(
        self, ctx: Context, ev: SlideValidationEvent
    ) -> SlideGeneratedEvent:
        """Modify the slides based on the validation feedback"""

        # give agent code_interpreter and get_layout tools
        # use feedback as prompt to agent
        # agent make changes to the slides and save slide
        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message="Modifying the slides based on the feedback...")

        # Locate the current pptx in the sandbox (fall back to default path if not found)
        latest_filename = await ctx.store.get("latest_pptx_file")
        n_retry = await ctx.store.get("n_retry")
        slide_pptx_path = f"{SANDBOX_DIR}/{latest_filename}"
        for f in self.sandbox.list_files():
            if f.filename == self.generated_slide_fname:
                slide_pptx_path = f.file_full_path
                break
        modified_pptx_path = f"{Path(slide_pptx_path).stem}_v{n_retry}.pptx"
        logger.info(f"[modify_slides] slide_pptx_path={slide_pptx_path}, modified={modified_pptx_path}")

        agent = ReActAgent(
            tools=self.sandbox.to_tool_list() + [self.all_layout_tool],
            llm=new_llm(0.1),
            verbose=True,
            timeout=300,
        )
        agent.update_prompts(
            {"react_header": PromptTemplate(SLIDE_MODIFICATION_PMT + REACT_PROMPT_SUFFIX)}
        )

        await self.run_react_agent(
            agent,
            f"The latest version of the slide deck is at `{slide_pptx_path}`.\n"
            f"The feedback is: '{ev.model_dump()}'\n"
            f"Save the modified slide deck as `{modified_pptx_path}`.",
            ctx,
        )

        self.download_all_files_from_session()
        return SlideGeneratedEvent(
            pptx_fpath=f"{self.workflow_artifacts_path.as_posix()}/{Path(modified_pptx_path).name}"
        )


async def run_workflow(file_dir: str):
    wf = SlideGenerationWorkflow(timeout=1200, verbose=True)
    result = await wf.run(
        file_dir=file_dir,
    )
    print(result)


@click.command()
@click.option(
    "--file_dir",
    "-d",
    required=False,
    help="Path to the directory that contains paper summaries for generating slide outlines",
    default="./data/summaries_test",
)
def main(file_dir: str):
    mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)
    mlflow.set_experiment("research-agent-slide-gen-wf")
    mlflow.llama_index.autolog()
    mlflow.start_run()

    asyncio.run(run_workflow(file_dir))

    mlflow.end_run()


if __name__ == "__main__":
    main()
