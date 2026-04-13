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
from llama_index.core.agent.workflow import ReActAgent, AgentStream, ToolCall, ToolCallResult
from llama_index.core.llms import ChatMessage
from llama_index.core.program import (
    FunctionCallingProgram,
    LLMTextCompletionProgram,
)

from config import settings
from prompts.prompts import (
    SLIDE_GEN_PMT,
    REACT_PROMPT_SUFFIX,
    SANDBOX_STOP_RULE_PMT,
    SUMMARY2OUTLINE_PMT,
    AUGMENT_LAYOUT_PMT,
    SLIDE_VALIDATION_PMT,
    SLIDE_MODIFICATION_PMT,
    MODIFY_SUMMARY2OUTLINE_PMT,
)
from services.model_factory import model_factory
from tools.sandbox_tools import LlmSandboxToolSpec, SANDBOX_DIR
from tools.pptx_tools import PptxLayoutToolSpec, PptxConversionToolSpec
from tools.debug_tools import WorkflowDebugToolSpec
from agent_workflows.events import *
from agent_workflows.hitl_workflow import HumanInTheLoopWorkflow
import mlflow
from utils.logger import get_logger

logger = get_logger(__name__)

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
        self._fast_llm = model_factory.fast_llm(temperature=0.1)
        self._smart_llm = model_factory.smart_llm(temperature=0.1)
        self._vlm = model_factory.vision_llm()
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
        # ToolSpec instances — each domain's tools are managed by its own class.
        # to_tool_list() controls which specs are exposed to the ReActAgent.
        self.pptx_spec            = PptxLayoutToolSpec(self.slide_template_path)
        self.pptx_conversion_spec = PptxConversionToolSpec()
        self.debug_spec           = WorkflowDebugToolSpec(self.workflow_artifacts_path)

        self.parent_workflow = None
        self.user_input_future = asyncio.Future()
        self.user_input = None

    def __del__(self) -> None:
        try:
            self.sandbox.close()
        except Exception:
            pass

    def _fc_program(self, output_cls, prompt_template_str, llm=None):
        """FunctionCallingProgram factory — structured output via tool calling API."""
        return FunctionCallingProgram.from_defaults(
            llm=llm if llm is not None else self._fast_llm,
            output_cls=output_cls,
            prompt_template_str=prompt_template_str,
            verbose=True,
        )

    def _text_program(self, output_cls, prompt_template_str, llm=None):
        """LLMTextCompletionProgram factory — structured output via JSON text completion."""
        return LLMTextCompletionProgram.from_defaults(
            llm=llm if llm is not None else self._smart_llm,
            output_cls=output_cls,
            prompt_template_str=prompt_template_str,
            verbose=True,
        )

    async def _generate_title(self, paper_titles: list[str]) -> str:
        """Generate a concise presentation title from paper titles using fast LLM."""
        prompt = (
            "Given these research paper titles:\n"
            + "\n".join(f"- {t}" for t in paper_titles)
            + "\n\nGenerate a concise academic presentation title "
              "(max 10 words). Output the title only, no explanation."
        )
        resp = await self._fast_llm.achat(
            [ChatMessage(role="user", content=prompt)]
        )
        return resp.message.content.strip()

    def copy_final_slide(self, latest_pptx_filename: str):
        """
        Copy the latest validated pptx (identified by latest_pptx_filename) to final.pptx
        in self.workflow_artifacts_path.  The filename is supplied by the caller (validate_slides)
        which already has the correct versioned name stored in state["latest_pptx_file"].
        """
        final_file = self.workflow_artifacts_path / latest_pptx_filename
        if not final_file.exists():
            raise FileNotFoundError(
                f"Expected pptx file not found: {final_file}"
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
                logger.info(f"[Tool call] {ev.tool_name}({ev.tool_kwargs})")
            elif isinstance(ev, ToolCallResult):
                logger.info(f"[Tool result] {ev.tool_name}: {ev.tool_output}")
        response = await handler
        self._emit_message(wf_ctx, "react_agent", message=f"Agent response: {response}")

    def to_tool_list(self) -> list[FunctionTool]:
        """Assemble tools exposed to the slide generation ReActAgent.

        Each tool domain is managed by its own ToolSpec class.
        To re-enable a disabled tool domain, uncomment the corresponding line.
        """
        return (
            self.sandbox.to_tool_list()
            # + self.pptx_spec.to_tool_list()    # disabled: agent reads layout from JSON
            # + self.debug_spec.to_tool_list()   # disabled: debug tools not for agent
        )

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
        if isinstance(ev, OutlineFeedbackEvent):
            program = self._fc_program(SlideOutline, MODIFY_SUMMARY2OUTLINE_PMT)
            response = await program.acall(
                summary_txt=ev.summary,
                outline_txt=ev.outline.model_dump(),
                feedback=ev.feedback,
                description="Data model for the slide page outline",
            )

        else:
            program = self._fc_program(SlideOutline, SUMMARY2OUTLINE_PMT)
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
        all_layout_names = [layout["layout_name"] for layout in self.pptx_spec.all_layout]

        # add layout to outline
        program = self._text_program(SlideOutlineWithLayout, AUGMENT_LAYOUT_PMT)
        slides_w_layout = []
        for n, ev in enumerate(ready):
            response = await program.acall(
                slide_content=ev.outline.model_dump(),
                available_layout_names=all_layout_names,
                available_layouts=self.pptx_spec.all_layout,
            )
            slides_w_layout.append(response)

        # Inject front page and thank-you slide deterministically so the agent
        # only needs to loop the JSON without conditional logic.
        idx_title, idx_content = self.pptx_spec.get_placeholder_indices("TITLE_SLIDE")
        presentation_title = await self._generate_title(
            [s.title for s in slides_w_layout]
        )
        front_slide = SlideOutlineWithLayout(
            title=presentation_title,
            content="Research Paper Survey",
            layout_name="TITLE_SLIDE",
            idx_title_placeholder=idx_title,
            idx_content_placeholder=idx_content,
        )
        thankyou_slide = SlideOutlineWithLayout(
            title="Thank You",
            content="Questions and Discussion",
            layout_name="TITLE_SLIDE",
            idx_title_placeholder=idx_title,
            idx_content_placeholder=idx_content,
        )
        slides_w_layout = [front_slide] + slides_w_layout + [thankyou_slide]

        # store the slide outlines as json file
        slide_outlines_json = self.workflow_artifacts_path.joinpath(
            self.slide_outlines_fname
        )
        with slide_outlines_json.open("w") as f:
            json.dump([o.model_dump() for o in slides_w_layout], f, indent=4)
        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message=f"{len(slides_w_layout)} outlines with layout are ready! "
                           f"Stored in {slide_outlines_json}")

        return OutlinesWithLayoutEvent(
            outlines_fpath=slide_outlines_json,
            # slides_w_layout[0] is front_slide (TITLE_SLIDE, idx_content may differ).
            # Use [1] (first content slide) as the representative example for the agent.
            outline_example=slides_w_layout[1],
        )

    @step
    async def slide_gen(
        self, ctx: Context, ev: OutlinesWithLayoutEvent
    ) -> SlideGeneratedEvent:
        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message="Agent is generating slide deck...")
        agent = ReActAgent(
            tools=self.to_tool_list(),
            llm=self._smart_llm,
            verbose=True,
            timeout=300,
        )
        # Build REACT_PROMPT_SUFFIX with the sandbox stop rule injected before
        # "## Current Conversation". Uses str.replace() to avoid conflicting with
        # LlamaIndex's {tool_desc}/{tool_names} template substitution.
        react_suffix = REACT_PROMPT_SUFFIX.replace(
            "{sandbox_stop_rule}",
            SANDBOX_STOP_RULE_PMT.format(max_retries=settings.SLIDE_GEN_MAX_RETRY_ATTEMPTS),
        )
        system_prompt = (
            SLIDE_GEN_PMT.format(
                json_file_path=f"{SANDBOX_DIR}/{ev.outlines_fpath.name}",
                template_fpath=f"{SANDBOX_DIR}/{Path(self.slide_template_path).name}",
                generated_slide_fname=self.generated_slide_fname,
            )
            + react_suffix
        )
        agent.update_prompts({"react_header": PromptTemplate(system_prompt)})

        # Upload both input files so the agent can access them at /sandbox/<filename>
        upload_result = self.sandbox.upload_file(local_file_path=self.slide_template_path)
        logger.info(upload_result)
        upload_result = self.sandbox.upload_file(local_file_path=str(ev.outlines_fpath))
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
        img_dir = self.pptx_conversion_spec.pptx2images(Path(ev.pptx_fpath))
        logger.info(f"[validate_slides] Storing pptx as images in" f" {img_dir}...")
        # upload image w. prompt for validation to llm and get structured response
        image_documents = SimpleDirectoryReader(img_dir).load_data()
        fn_name = inspect.currentframe().f_code.co_name

        self._emit_message(ctx, fn_name, message=f"{n_retry}th try for validating the generated slide deck...")
        needs_modify = []
        for img_doc in image_documents:
            response = await self._vlm.acomplete(
                prompt=SLIDE_VALIDATION_PMT,
                image_documents=[img_doc],
                response_format=SlideValidationResult,
            )
            result = SlideValidationResult.model_validate_json(response.text)
            if result.is_valid:
                continue
            page_idx = Path(img_doc.metadata.get("file_name", "")).stem.split("_")[-1]
            needs_modify.append(
                SlideNeedModifyResult(
                    slide_idx=int(page_idx),
                    suggestion_to_fix=result.suggestion_to_fix,
                )
            )

        if needs_modify and n_retry < self.max_validation_retries:
            self._emit_message(ctx, fn_name, message="The slides are not fixed, retrying...")
            return SlideValidationEvent(results=needs_modify)

        validation_passed = not needs_modify
        self._emit_message(
            ctx, fn_name,
            message=(
                "The slides are fixed!"
                if validation_passed
                else f"The slides are not fixed after {self.max_validation_retries} retries!"
            ),
        )
        self.copy_final_slide(await ctx.store.get("latest_pptx_file"))
        return StopEvent(
            str(self.workflow_artifacts_path / "final.pptx")
            if validation_passed
            else f"The slides are not fixed after {self.max_validation_retries} retries!"
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

        latest_filename = await ctx.store.get("latest_pptx_file")
        n_retry = await ctx.store.get("n_retry")
        slide_pptx_path = f"{SANDBOX_DIR}/{latest_filename}"
        modified_pptx_path = f"{Path(self.generated_slide_fname).stem}_v{n_retry}.pptx"
        logger.info(f"[modify_slides] slide_pptx_path={slide_pptx_path}, modified={modified_pptx_path}")

        react_suffix = REACT_PROMPT_SUFFIX.replace(
            "{sandbox_stop_rule}",
            SANDBOX_STOP_RULE_PMT.format(max_retries=settings.SLIDE_GEN_MAX_RETRY_ATTEMPTS),
        )
        agent = ReActAgent(
            # TODO: all_layout_tool removed — modify step does not need to query layouts.
            # Confirm with end-to-end test, then remove the commented reference.
            tools=self.to_tool_list(),
            llm=self._smart_llm,
            verbose=True,
            timeout=300,
        )
        agent.update_prompts(
            {"react_header": PromptTemplate(SLIDE_MODIFICATION_PMT + react_suffix)}
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
