import asyncio
import inspect
import uuid

import click
from tavily import TavilyClient

from config import settings
from services.llms import llm, new_fast_llm
from services.embeddings import embedder
import logging
from llama_index.core import Settings
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
    get_paper_with_citations,
    process_citation,
    download_relevant_citations,
)
from agent_workflows.summary_using_images import (
    summarize_paper_images,
    save_summary_as_markdown,
)


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


class SummaryGenerationWorkflow(HumanInTheLoopWorkflow):
    wid: Optional[uuid.UUID] = uuid.uuid4()
    tavily_max_results: int = 2
    n_max_final_papers: int = 5

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

    @step
    async def tavily_query(self, ctx: Context, ev: StartEvent) -> TavilyResultsEvent:
        async with ctx.store.edit_state() as state:
            state["research_topic"] = ev.user_query
        query = f"arxiv papers about the state of the art of {ev.user_query}"
        ctx.write_event_to_stream(
            Event(
                msg=WorkflowStreamingEvent(
                    event_type="server_message",
                    event_sender=inspect.currentframe().f_code.co_name,
                    event_content={"message": f"Querying Tavily with: '{query}'"},
                ).model_dump()
            )
        )
        tavily_client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = tavily_client.search(query, max_results=self.tavily_max_results)
        results = [TavilySearchResult(**d) for d in response["results"]]
        logger.info(f"tavily results: {results}")
        return TavilyResultsEvent(results=results)

    @step
    async def get_paper_with_citations(
        self, ctx: Context, ev: TavilyResultsEvent
    ) -> PaperEvent:
        papers = []
        for r in ev.results:
            p = get_paper_with_citations(r.title)
            papers += p
        # deduplicate papers
        papers = list({p.entry_id: p for p in papers}.values())
        async with ctx.store.edit_state() as state:
            state["n_all_papers"] = len(papers)
        logger.info(f"papers found: {[p.title for p in papers]}")
        for paper in papers:
            ctx.write_event_to_stream(
                Event(
                    msg=WorkflowStreamingEvent(
                        event_type="server_message",
                        event_sender=inspect.currentframe().f_code.co_name,
                        event_content={
                            "message": f"Found related paper: {paper.title}"
                        },
                    ).model_dump()
                )
            )
            ctx.send_event(PaperEvent(paper=paper))

    @step(num_workers=settings.NUM_WORKERS_FAST)
    async def filter_papers(self, ctx: Context, ev: PaperEvent) -> FilteredPaperEvent:
        llm = new_fast_llm(temperature=0.0)
        research_topic = await ctx.store.get("research_topic")
        _, response = await process_citation(
            0, research_topic, ev.paper, llm
        )
        return FilteredPaperEvent(paper=ev.paper, is_relevant=response)

    @step
    async def download_papers(
        self, ctx: Context, ev: FilteredPaperEvent
    ) -> Paper2SummaryDispatcherEvent:
        n_all_papers = await ctx.store.get("n_all_papers")
        ready = ctx.collect_events(ev, [FilteredPaperEvent] * n_all_papers)
        if ready is None:
            return None
        papers = sorted(
            ready,
            key=lambda x: (
                x.is_relevant.score,  # prioritize papers with higher score
                "ArXiv"
                in (
                    x.paper.external_ids or {}
                ),  # prioritize papers can be found on ArXiv
            ),
            reverse=True,
        )[: self.n_max_final_papers]
        papers_dict = {
            i: {"citation": p.paper, "is_relevant": p.is_relevant}
            for i, p in enumerate(papers)
        }
        ctx.write_event_to_stream(
            Event(
                msg=WorkflowStreamingEvent(
                    event_type="server_message",
                    event_sender=inspect.currentframe().f_code.co_name,
                    event_content={
                        "message": f"Downloading filtered relevant papers:\n"
                        f"{' | '.join([p.paper.title for p in papers])}"
                    },
                ).model_dump()
            )
        )
        download_relevant_citations(papers_dict, Path(self.papers_download_path))
        return Paper2SummaryDispatcherEvent(
            papers_path=self.papers_download_path.as_posix()
        )

    @step
    async def paper2summary_dispatcher(
        self, ctx: Context, ev: Paper2SummaryDispatcherEvent
    ) -> Paper2SummaryEvent:
        async with ctx.store.edit_state() as state:
            state["n_pdfs"] = 0
        for pdf_name in Path(ev.papers_path).glob("*.pdf"):
            img_output_dir = self.papers_images_path / pdf_name.stem
            img_output_dir.mkdir(exist_ok=True, parents=True)
            summary_fpath = self.paper_summary_path / f"{pdf_name.stem}.md"
            async with ctx.store.edit_state() as state:
                state["n_pdfs"] = state.get("n_pdfs", 0) + 1
            ctx.send_event(
                Paper2SummaryEvent(
                    pdf_path=pdf_name,
                    image_output_dir=img_output_dir,
                    summary_path=summary_fpath,
                )
            )

    @step(num_workers=settings.NUM_WORKERS_VISION)
    async def paper2summary(
        self, ctx: Context, ev: Paper2SummaryEvent
    ) -> SummaryStoredEvent:
        pdf2images(ev.pdf_path, ev.image_output_dir)
        summary_txt = await summarize_paper_images(ev.image_output_dir)
        save_summary_as_markdown(summary_txt, ev.summary_path)
        ctx.write_event_to_stream(
            Event(
                msg=WorkflowStreamingEvent(
                    event_type="server_message",
                    event_sender=inspect.currentframe().f_code.co_name,
                    event_content={"message": f"Summarizing paper: {ev.pdf_path}"},
                ).model_dump()
            )
        )
        return SummaryStoredEvent(fpath=ev.summary_path)

    @step
    async def finish(self, ctx: Context, ev: SummaryStoredEvent) -> StopEvent:
        n_pdfs = await ctx.store.get("n_pdfs")
        ready = ctx.collect_events(ev, [SummaryStoredEvent] * n_pdfs)
        if ready is None:
            return None
        for e in ready:
            assert e.fpath.is_file()
        logger.info(f"All summary are stored!")
        return StopEvent(result=e.fpath.parent.as_posix())


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
