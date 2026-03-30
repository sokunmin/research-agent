import asyncio
import uuid

import click

from config import settings
from services.llms import llm, new_fast_llm
from services.embeddings import embedder
import logging
from llama_index.core import Settings
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
from agent_workflows.hitl_workflow import HumanInTheLoopWorkflow
from agent_workflows.paper_scraping import (
    fetch_candidate_papers,
    download_paper_pdfs,
    PaperRelevanceFilter,
    PaperRelevanceResult,
)
from agent_workflows.summary_using_images import (
    summarize_paper_images,
    save_summary_as_markdown,
)
from prompts.prompts import ACADEMIC_QUERY_REFORMULATION_PMT
from services.model_factory import model_factory


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


Settings.llm = llm
Settings.embed_model = embedder


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
        self._relevance_filter = PaperRelevanceFilter(
            embed_model=model_factory.relevance_embed_model(),
            llm=new_fast_llm(temperature=0.0),
        )
        self._search_tool = FunctionTool.from_defaults(
            fn=fetch_candidate_papers,
            name="search_academic_papers",
            description=(
                "Search OpenAlex for recent open-access academic papers on a research topic. "
                "Returns Papers sorted by citation count."
            ),
        )
        # _search_tool is stored for potential LLM agent use; the workflow step calls
        # fetch_candidate_papers directly for type-safe access to the Paper list.

    @step
    async def discover_candidate_papers(
        self, ctx: Context, ev: StartEvent
    ) -> PaperEvent:
        """Reformulate user query for academic search, then fetch candidate papers from OpenAlex."""
        topic = ev.user_query
        async with ctx.store.edit_state() as state:
            state["research_topic"] = topic

        self._emit_message(ctx, "discover_candidate_papers", f"Searching papers on: {topic}")

        search_query = await _generate_search_query(topic, new_fast_llm(temperature=0.0))
        logger.info(f"Search query reformulated: '{topic}' → '{search_query}'")

        # fetch_candidate_papers is also available as self._search_tool for LLM agent use
        papers = fetch_candidate_papers(search_query)
        papers = list({p.entry_id: p for p in papers}.values())  # deduplicate

        async with ctx.store.edit_state() as state:
            state["n_all_papers"] = len(papers)

        self._emit_message(
            ctx, "discover_candidate_papers", f"Found {len(papers)} candidate papers"
        )
        for paper in papers:
            ctx.send_event(PaperEvent(paper=paper))

    @step(num_workers=settings.NUM_WORKERS_FAST)
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
            f"Downloading {len(top_papers)} relevant papers: "
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
        self._emit_message(ctx, "paper2summary", f"Summarizing: {ev.pdf_path.name}")
        pdf2images(ev.pdf_path, ev.image_output_dir)
        summary_txt = await summarize_paper_images(ev.image_output_dir)
        save_summary_as_markdown(summary_txt, ev.summary_path)
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

        self._emit_message(ctx, "finish", f"All {len(ready)} paper summaries stored.")
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
            result="workflow_artifacts/SummaryGenerationWorkflow/5sn92wndsx/data/paper_summaries"
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
