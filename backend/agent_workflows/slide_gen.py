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
from llama_index.core import SimpleDirectoryReader
from llama_index.core.workflow import (
    Context,
    StartEvent,
    StopEvent,
    step,
)
from llama_index.core.llms import ChatMessage
from llama_index.core.program import (
    FunctionCallingProgram,
    LLMTextCompletionProgram,
)

from config import settings
from prompts.prompts import (
    SUMMARY2OUTLINE_PMT,
    AUGMENT_LAYOUT_PMT,
    SLIDE_VALIDATION_PMT,
    MODIFY_SUMMARY2OUTLINE_PMT,
    CONTENT_FIX_PMT,
)
from services.model_factory import model_factory
from tools.pptx_tools import PptxLayoutToolSpec, PptxConversionToolSpec, PptxRenderer
from agent_workflows.events import *
from agent_workflows.hitl_workflow import HumanInTheLoopWorkflow, CLOUD_LLM_RETRY_POLICY
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

        # ToolSpec instances — each domain's tools are managed by its own class.
        self.pptx_spec            = PptxLayoutToolSpec(self.slide_template_path)
        self.pptx_conversion_spec = PptxConversionToolSpec()
        self.renderer             = PptxRenderer(self.slide_template_path, self.workflow_artifacts_path)

        self.parent_workflow = None
        self.user_input_future = asyncio.Future()
        self.user_input = None

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
            + "\n\nWhat is the unifying research theme across all these papers, "
              "expressed as an academic presentation title (max 10 words)? "
              "Output the title only."
        )
        resp = await self._fast_llm.achat(
            [ChatMessage(role="user", content=prompt)]
        )
        return resp.message.content.strip()

    async def _generate_subtitle(
        self, paper_titles: list[str], presentation_title: str
    ) -> str:
        """Generate a concise presentation subtitle from paper titles and the already-generated title."""
        prompt = (
            f"Presentation title: '{presentation_title}'\n"
            "Research paper titles:\n"
            + "\n".join(f"- {t}" for t in paper_titles)
            + "\n\nGenerate a concise subtitle (max 8 words) that complements "
              "the presentation title above. "
              "Output the subtitle only, no explanation."
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

    @step(num_workers=settings.NUM_WORKERS_FAST, retry_policy=CLOUD_LLM_RETRY_POLICY)
    async def summary2outline(
        self, ctx: Context, ev: SummaryEvent | OutlineFeedbackEvent
    ) -> OutlineEvent:
        """Convert the summary content of one paper to a PaperSlideOutline containing
        a section title slide plus 4 content slides per paper.
        """
        await asyncio.sleep(settings.DELAY_SECONDS_FAST)
        self._emit_message(ctx, inspect.currentframe().f_code.co_name,
                           message="Making summary to slide outline...")
        if isinstance(ev, OutlineFeedbackEvent):
            program = self._text_program(PaperSlideOutline, MODIFY_SUMMARY2OUTLINE_PMT)
            response = await program.acall(
                summary_txt=ev.summary,
                outline_txt=ev.paper_outline.model_dump(),
                feedback=ev.feedback,
            )

        else:
            program = self._text_program(PaperSlideOutline, SUMMARY2OUTLINE_PMT)
            response = await program.acall(
                summary=ev.summary,
            )
        # async for response in generator:
        #     # Allow the workflow to stream this piece of response
        json_resp = {"original_summary": ev.summary}
        json_resp.update(json.loads(response.json()))

        return OutlineEvent(summary=ev.summary, paper_outline=response)

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
            paper_outline=ev.paper_outline.dict(),
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
                return OutlineOkEvent(summary=ev.summary, paper_outline=ev.paper_outline)
            else:
                return OutlineFeedbackEvent(
                    summary=ev.summary, paper_outline=ev.paper_outline, feedback=feedback
                )
        else:
            logger.info("User input future is already done, skipping await.")

    @step(retry_policy=CLOUD_LLM_RETRY_POLICY)
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

        # Inject front page and thank-you slide deterministically so the agent
        # only needs to loop the JSON without conditional logic.
        cover_layout = self.pptx_spec.find_cover_layout_name()
        idx_title, idx_content = self.pptx_spec.get_placeholder_indices(cover_layout)

        # add layout to outline
        program = self._text_program(SlideOutlineWithLayout, AUGMENT_LAYOUT_PMT)
        slides_w_layout = []
        for ev in ready:
            # Paper section title slide — paper title + "authors, year" as subtitle
            slides_w_layout.append(SlideOutlineWithLayout(
                title=ev.paper_outline.paper_title,
                content=[ParagraphItem(
                    text=f"{ev.paper_outline.paper_authors}, {ev.paper_outline.paper_year}",
                    level=0,
                )],
                layout_name=cover_layout,
                idx_title_placeholder=idx_title,
                idx_content_placeholder=idx_content,
            ))
            # 4 content slides — augment each with layout
            for slide in ev.paper_outline.content_slides:
                response = await program.acall(
                    slide_content=slide.model_dump(),
                    available_layout_names=all_layout_names,
                    available_layouts=self.pptx_spec.all_layout,
                )
                slides_w_layout.append(response)

        paper_titles = [ev.paper_outline.paper_title for ev in ready]
        presentation_title = await self._generate_title(paper_titles)
        presentation_subtitle = await self._generate_subtitle(
            paper_titles, presentation_title
        )
        front_slide = SlideOutlineWithLayout(
            title=presentation_title,
            content=[ParagraphItem(text=presentation_subtitle, level=0)],
            layout_name=cover_layout,
            idx_title_placeholder=idx_title,
            idx_content_placeholder=idx_content,
        )
        thankyou_slide = SlideOutlineWithLayout(
            title="Thank You",
            content=[ParagraphItem(text="Questions and Discussion", level=0)],
            layout_name=cover_layout,
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
        self._emit_message(ctx, "slide_gen", message="Generating slide deck...")
        with open(ev.outlines_fpath) as f:
            outlines = json.load(f)
        output_path = self.renderer.generate_pptx(outlines, self.generated_slide_fname)
        self._emit_message(
            ctx, "slide_gen", message=f"Slide deck generated: {output_path.name}"
        )
        return SlideGeneratedEvent(
            pptx_fpath=output_path.as_posix(),
            outlines_fpath=str(ev.outlines_fpath),
        )

    @step(num_workers=settings.NUM_WORKERS_VISION)
    async def validate_slides(
        self, ctx: Context, ev: SlideGeneratedEvent
    ) -> StopEvent | ContentFixEvent | ContentMissingFixEvent | VisualFixEvent:
        """Validate generated slides with two-layer check.

        Layer A (cheap): programmatic content integrity check — no VLM.
        Layer B (expensive): VLM visual validation with structured issue_type.
        Triage routes to the appropriate fix step based on issue_type priority.
        """
        await asyncio.sleep(settings.DELAY_SECONDS_VISION)
        async with ctx.store.edit_state() as state:
            state["n_retry"] = state.get("n_retry", 0) + 1
            state["latest_pptx_file"] = Path(ev.pptx_fpath).name
        n_retry = await ctx.store.get("n_retry")
        outlines_fpath = ev.outlines_fpath or str(
            self.workflow_artifacts_path / self.slide_outlines_fname
        )
        with open(outlines_fpath) as f:
            outlines = json.load(f)

        self._emit_message(
            ctx, "validate_slides", message=f"{n_retry}th validation pass..."
        )

        # ── Step 1: content integrity check (programmatic, no VLM) ─────────────
        empty_indices = self.renderer.content_integrity_check(
            Path(ev.pptx_fpath), outlines
        )
        if empty_indices:
            self._emit_message(
                ctx, "validate_slides",
                message=f"Step 1: {len(empty_indices)} empty slides found, re-rendering...",
            )
            return ContentMissingFixEvent(outlines_fpath=outlines_fpath)

        # ── Step 2: VLM visual validation ────────────────────────────────────
        img_dir = self.pptx_conversion_spec.pptx2images(Path(ev.pptx_fpath))
        image_documents = SimpleDirectoryReader(img_dir).load_data()
        needs_modify: list[SlideNeedModifyResult] = []
        for i, img_doc in enumerate(image_documents):
            response = await self._vlm.acomplete(
                prompt=SLIDE_VALIDATION_PMT,
                image_documents=[img_doc],
                response_format=SlideValidationResult,
            )
            result = SlideValidationResult.model_validate_json(response.text)
            if not result.is_valid:
                needs_modify.append(
                    SlideNeedModifyResult(
                        slide_idx=i,
                        issue_type=result.issue_type,
                        suggestion_to_fix=result.suggestion_to_fix,
                    )
                )

        if not needs_modify:
            self._emit_message(ctx, "validate_slides", message="Slides validated!")
            self.copy_final_slide(await ctx.store.get("latest_pptx_file"))
            return StopEvent(str(self.workflow_artifacts_path / "final.pptx"))

        # ── Max retries reached: stop with warning ────────────────────────────
        if n_retry >= self.max_validation_retries:
            self._emit_message(
                ctx, "validate_slides",
                message=f"Max retries ({self.max_validation_retries}) reached, stopping.",
            )
            self.copy_final_slide(await ctx.store.get("latest_pptx_file"))
            return StopEvent(str(self.workflow_artifacts_path / "final.pptx"))

        # ── Triage: content issues take priority over visual ──────────────────
        content_issues = [
            r for r in needs_modify
            if r.issue_type in ("content_too_long", "content_missing")
        ]
        visual_issues = [r for r in needs_modify if r.issue_type == "visual_overlap"]

        if content_issues:
            too_long = [r for r in content_issues if r.issue_type == "content_too_long"]
            if too_long:
                self._emit_message(
                    ctx, "validate_slides",
                    message=f"Content too long on {len(too_long)} slides, trimming...",
                )
                return ContentFixEvent(
                    results=too_long,
                    pptx_fpath=ev.pptx_fpath,
                    outlines_fpath=outlines_fpath,
                )
            else:
                self._emit_message(
                    ctx, "validate_slides", message="Content missing (VLM), re-rendering..."
                )
                return ContentMissingFixEvent(outlines_fpath=outlines_fpath)

        if visual_issues:
            self._emit_message(
                ctx, "validate_slides",
                message=f"Visual overlap on {len(visual_issues)} slides, fixing...",
            )
            return VisualFixEvent(results=visual_issues, pptx_fpath=ev.pptx_fpath)

        # Fallback — should not reach here
        self.copy_final_slide(await ctx.store.get("latest_pptx_file"))
        return StopEvent(str(self.workflow_artifacts_path / "final.pptx"))

    @step(retry_policy=CLOUD_LLM_RETRY_POLICY)
    async def content_fix(
        self, ctx: Context, ev: ContentFixEvent
    ) -> SlideGeneratedEvent:
        """Trim content_too_long slides: LLM shortens JSON text, then re-render."""
        with open(ev.outlines_fpath) as f:
            outlines = json.load(f)
        for issue in ev.results:
            messages = [
                ChatMessage(
                    role="user",
                    content=CONTENT_FIX_PMT.format(
                        slide_idx=issue.slide_idx,
                        current_content=json.dumps(
                            outlines[issue.slide_idx].get("content", []),
                            ensure_ascii=False,
                        ),
                    ),
                )
            ]
            response = await self._fast_llm.achat(messages)
            try:
                outlines[issue.slide_idx]["content"] = json.loads(
                    response.message.content.strip()
                )
            except json.JSONDecodeError:
                logger.warning(
                    f"content_fix: JSON parse failed for slide {issue.slide_idx}, keeping original"
                )
            self._emit_message(
                ctx, "content_fix",
                message=f"Trimmed content for slide {issue.slide_idx}",
            )
        with open(ev.outlines_fpath, "w") as f:
            json.dump(outlines, f, indent=4)
        output_path = self.renderer.generate_pptx(outlines, self.generated_slide_fname)
        return SlideGeneratedEvent(
            pptx_fpath=output_path.as_posix(),
            outlines_fpath=ev.outlines_fpath,
        )

    @step
    async def content_missing_fix(
        self, ctx: Context, ev: ContentMissingFixEvent
    ) -> SlideGeneratedEvent:
        """Re-render from JSON only — no LLM. JSON content is correct."""
        with open(ev.outlines_fpath) as f:
            outlines = json.load(f)
        output_path = self.renderer.generate_pptx(outlines, self.generated_slide_fname)
        self._emit_message(
            ctx, "content_missing_fix", message="Re-rendered slides from JSON."
        )
        return SlideGeneratedEvent(
            pptx_fpath=output_path.as_posix(),
            outlines_fpath=ev.outlines_fpath,
        )

    @step
    async def visual_fix(
        self, ctx: Context, ev: VisualFixEvent
    ) -> SlideGeneratedEvent:
        """Adjust placeholder positions for visual_overlap slides — no LLM."""
        n_retry = await ctx.store.get("n_retry")
        output_fname = f"{Path(self.generated_slide_fname).stem}_v{n_retry}.pptx"
        output_path = self.renderer.apply_visual_fix(
            Path(ev.pptx_fpath), ev.results, output_fname
        )
        outlines_fpath = str(self.workflow_artifacts_path / self.slide_outlines_fname)
        self._emit_message(
            ctx, "visual_fix", message=f"Adjusted placeholder positions → {output_fname}"
        )
        return SlideGeneratedEvent(
            pptx_fpath=output_path.as_posix(),
            outlines_fpath=outlines_fpath,
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
