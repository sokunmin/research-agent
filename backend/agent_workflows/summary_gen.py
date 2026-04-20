import asyncio
import uuid

import click

from config import settings
from llama_index.core import SimpleDirectoryReader
from llama_index.core.llms import ChatMessage
from llama_index.core.tools import FunctionTool
from llama_index.core.workflow import (
    Context,
    StartEvent,
    StopEvent,
    step,
)

from utils.file_processing import pdf2images
from agent_workflows.events import *
from agent_workflows.hitl_workflow import HumanInTheLoopWorkflow, LOCAL_LLM_RETRY_POLICY
from agent_workflows.paper_scraping import (
    download_paper_pdfs,
    PaperRelevanceFilter,
    PaperRelevanceResult,
)
from tools.paper_tools import PaperSearchToolSpec
from prompts.prompts import ACADEMIC_QUERY_REFORMULATION_PMT, SUMMARIZE_PAPER_PMT
from services.model_factory import model_factory
from utils.logger import get_logger

logger = get_logger(__name__)


async def _generate_search_query(user_query: str, llm) -> str:
    """Reformulate a user's research interest into a BM25-optimised academic search term."""
    messages = [
        ChatMessage(role="system", content=ACADEMIC_QUERY_REFORMULATION_PMT),
        ChatMessage(role="user", content=user_query),
    ]
    response = await llm.achat(messages)
    return response.message.content.strip()


class SummaryGenerationWorkflow(HumanInTheLoopWorkflow):
    wid: Optional[uuid.UUID] = uuid.uuid4()
    num_max_final_papers: int = settings.NUM_MAX_FINAL_PAPERS

    _PAPERS_SUBDIR = "papers"
    _IMAGES_SUBDIR = "papers_images"

    def __init__(self, wid: Optional[uuid.UUID] = uuid.uuid4(), *args, **kwargs):
        self.wid = wid
        super().__init__(*args, **kwargs)
        self.workflow_artifacts_path = (
            Path(settings.WORKFLOW_ARTIFACTS_ROOT)
            / self.__class__.__name__
            / str(self.wid)
        )
        self.papers_download_path = self.workflow_artifacts_path / self._PAPERS_SUBDIR
        self.papers_download_path.mkdir(parents=True, exist_ok=True)
        self.papers_images_path = self.workflow_artifacts_path / self._IMAGES_SUBDIR
        self.papers_images_path.mkdir(parents=True, exist_ok=True)
        self.paper_summary_path = self.papers_images_path
        self.paper_summary_path.mkdir(parents=True, exist_ok=True)
        self._fast_llm = model_factory.fast_llm(temperature=0.0)
        self._vlm = model_factory.vision_llm()
        self._relevance_filter = PaperRelevanceFilter(
            embed_model=model_factory.relevance_embed_model(),
            llm=self._fast_llm,
        )
        self.paper_search_spec = PaperSearchToolSpec()
        # fetch_candidate_papers is called directly by discover_candidate_papers step;
        # paper_search_spec.to_tool_list() is available if a future agent needs search.

    def to_tool_list(self) -> list[FunctionTool]:
        """Assemble tools exposed to a SummaryGenerationWorkflow ReActAgent.

        Currently returns an empty list: workflow steps call functions directly.
        To expose paper search to an agent, uncomment the line below.
        """
        return []
        # + self.paper_search_spec.to_tool_list()

    @step
    async def discover_candidate_papers(
        self, ctx: Context, ev: StartEvent
    ) -> PaperEvent:
        """Reformulate user query for academic search, then fetch candidate papers from OpenAlex."""
        topic = ev.user_query
        async with ctx.store.edit_state() as state:
            state["research_topic"] = topic

        self._emit_message(ctx, "discover_candidate_papers", message=f"Searching papers on: {topic}")

        if settings.ENABLE_QUERY_REFORMULATION:
            search_query = await _generate_search_query(topic, self._fast_llm)
            logger.info(f"Search query reformulated: '{topic}' → '{search_query}'")
        else:
            search_query = topic
            logger.info(f"Query reformulation disabled, using original query: '{topic}'")

        papers = self.paper_search_spec.fetch_papers(search_query)
        papers = list({p.entry_id: p for p in papers}.values())  # deduplicate

        async with ctx.store.edit_state() as state:
            state["n_all_papers"] = len(papers)

        self._emit_message(
            ctx, "discover_candidate_papers", message=f"Found {len(papers)} candidate papers"
        )
        for paper in papers:
            ctx.send_event(PaperEvent(paper=paper))

    @step(num_workers=settings.NUM_WORKERS_FAST, retry_policy=LOCAL_LLM_RETRY_POLICY)
    async def filter_papers(self, ctx: Context, ev: PaperEvent) -> FilteredPaperEvent:
        research_topic = await ctx.store.get("research_topic")
        is_relevant, similarity_score = self._relevance_filter.assess_relevance(
            ev.paper, research_topic
        )
        return FilteredPaperEvent(
            paper=ev.paper,
            relevance=PaperRelevanceResult(
                is_relevant=is_relevant, similarity_score=similarity_score
            ),
        )

    @step
    async def download_papers(
        self, ctx: Context, ev: FilteredPaperEvent
    ) -> Paper2SummaryDispatcherEvent:
        n_all_papers = await ctx.store.get("n_all_papers")
        ready = ctx.collect_events(ev, [FilteredPaperEvent] * n_all_papers)
        if ready is None:
            return None

        top_papers = sorted(
            (e for e in ready if e.relevance.is_relevant),
            key=lambda e: e.relevance.similarity_score,
            reverse=True,
        )[: self.num_max_final_papers]

        self._emit_message(
            ctx, "download_papers",
            message=f"Downloading {len(top_papers)} relevant papers: "
            f"{' | '.join(e.paper.title for e in top_papers)}",
        )
        download_paper_pdfs(
            [e.paper for e in top_papers], self.papers_download_path
        )
        return Paper2SummaryDispatcherEvent(
            papers_path=self.papers_download_path.as_posix()
        )

    @step
    async def paper2summary_dispatcher(
        self, ctx: Context, ev: Paper2SummaryDispatcherEvent
    ) -> Paper2SummaryEvent:
        pdf_files = list(Path(ev.papers_path).glob("*.pdf"))
        async with ctx.store.edit_state() as state:
            state["n_pdfs"] = len(pdf_files)
        for pdf_path in pdf_files:
            img_output_dir = self.papers_images_path / pdf_path.stem
            img_output_dir.mkdir(exist_ok=True, parents=True)
            ctx.send_event(
                Paper2SummaryEvent(
                    pdf_path=pdf_path,
                    image_output_dir=img_output_dir,
                    summary_path=self.paper_summary_path / f"{pdf_path.stem}.md",
                )
            )

    @step(num_workers=settings.NUM_WORKERS_VISION)
    async def paper2summary(
        self, ctx: Context, ev: Paper2SummaryEvent
    ) -> SummaryStoredEvent:
        await asyncio.sleep(settings.DELAY_SECONDS_VISION)
        self._emit_message(ctx, "paper2summary", message=f"Summarizing: {ev.pdf_path.name}")
        pdf2images(ev.pdf_path, ev.image_output_dir)
        # Summarize paper page images using VLM
        image_documents = SimpleDirectoryReader(ev.image_output_dir).load_data()
        response = await self._vlm.acomplete(
            prompt=SUMMARIZE_PAPER_PMT,
            image_documents=image_documents,
        )
        # removeprefix/removesuffix strips substring (str.strip() strips individual chars — bug)
        text = response.text.strip()
        text = text.removeprefix("```markdown").removeprefix("```")
        summary_txt = text.removesuffix("```").strip()
        # Persist summary as markdown
        with open(ev.summary_path, "w") as f:
            f.write(summary_txt)
        logger.info(f"Summary saved to {ev.summary_path}")
        return SummaryStoredEvent(fpath=ev.summary_path)

    @step
    async def finish(self, ctx: Context, ev: SummaryStoredEvent) -> StopEvent:
        n_pdfs = await ctx.store.get("n_pdfs")
        ready = ctx.collect_events(ev, [SummaryStoredEvent] * n_pdfs)
        if ready is None:
            return None

        missing = [e.fpath for e in ready if not e.fpath.is_file()]
        if missing:
            logger.warning(f"Missing summary files: {missing}")

        self._emit_message(ctx, "finish", message=f"All {len(ready)} paper summaries stored.")
        logger.info(f"All {len(ready)} paper summaries stored.")
        return StopEvent(result=self.paper_summary_path.as_posix())


# workflow for debugging purpose
class SummaryGenerationDummyWorkflow(HumanInTheLoopWorkflow):
    def __init__(self, wid: Optional[uuid.UUID] = uuid.uuid4(), *args, **kwargs):
        self.wid = wid
        super().__init__(*args, **kwargs)

    @step
    async def dummy_start_step(self, ev: StartEvent) -> DummyEvent:
        return DummyEvent(result="dummy")

    @step
    async def dummy_stop_step(self, ev: DummyEvent) -> StopEvent:
        return StopEvent(
            result="workflow_artifacts/SummaryGenerationWorkflow/dummy-id/papers_images"
        )


async def run_workflow(user_query: str):
    wf = SummaryGenerationWorkflow(timeout=1200, verbose=True)
    result = await wf.run(
        user_query=user_query,
    )
    print(result)


@click.command()
@click.option(
    "--user-query",
    "-q",
    required=False,
    help="The user query",
    default="powerpoint slides automation",
)
def main(user_query: str):
    asyncio.run(run_workflow(user_query))


if __name__ == "__main__":
    # os.environ["MLFLOW_DEFAULT_ARTIFACT_ROOT"] = "/mlruns"
    from llama_index.utils.workflow import draw_all_possible_flows
    draw_all_possible_flows(
        SummaryGenerationWorkflow, filename="summary_gen_flows.html"
    )
    main()
