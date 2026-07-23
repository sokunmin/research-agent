import asyncio
from datetime import date
import json
import shutil
import uuid
from pathlib import Path
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict

import click

from config import settings
from llama_index.core.llms import ChatMessage
from llama_index.core.program import LLMTextCompletionProgram
from llama_index.core.tools import FunctionTool
from llama_index.core.workflow import (
    Context,
    StartEvent,
    StopEvent,
    step,
)

from agent_workflows.events import *
from agent_workflows.hitl_workflow import HumanInTheLoopWorkflow, LOCAL_LLM_RETRY_POLICY
from agent_workflows.paper_scraping import (
    Paper,
    PaperRelevanceFilter,
    PaperRelevanceResult,
    PaperDownloader,
    fetch_candidate_papers,
)
from agent_workflows.schemas import IntentResult, PaperCandidate, SearchParams
from prompts.prompts import (
    CLASSIFY_INTENT_PMT,
    PAPER_QUESTION_PMT,
    RETRIEVAL_QUERIES,
    SEARCH_PARAMS_EXTRACTION_PMT,
    SUMMARIZE_PAPER_PMT,
)
from services.docling_pipeline import DoclingPipeline
from services.model_factory import model_factory
from services.paper_store import PaperStore, build_qdrant_clients
from tools.paper_tools import PaperSearchToolSpec
from utils.logger import get_logger

logger = get_logger(__name__)


def _get_paper_id(paper: Paper) -> str:
    """Return document_id (and filename stem) for a paper.

    Uses ArXiv ID when available — stable, matches PDF filename convention.
    Falls back to OpenAlex ID for non-ArXiv papers.
    """
    arxiv_id = (paper.external_ids or {}).get("ArXiv")
    if arxiv_id:
        return arxiv_id
    return paper.entry_id.rstrip("/").split("/")[-1]


class PaperFileStore(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    workflow_root: Path
    workflow_name: str
    run_id: str

    def model_post_init(self, __context) -> None:
        for d in [self.run_summaries_dir, self.cache_summaries_dir,
                  self.cache_parsed_dir, self.papers_download_dir]:
            d.mkdir(parents=True, exist_ok=True)

    @property
    def _run_root(self) -> Path:
        return self.workflow_root / self.workflow_name / self.run_id

    @property
    def _cache_root(self) -> Path:
        return self.workflow_root / "_cache"

    @property
    def run_summaries_dir(self) -> Path:
        return self._run_root / "summaries"

    @property
    def cache_summaries_dir(self) -> Path:
        return self._cache_root / "summaries"

    @property
    def cache_parsed_dir(self) -> Path:
        return self._cache_root / "parsed_papers"

    @property
    def papers_download_dir(self) -> Path:
        return self._run_root / "papers"

    def run_summary(self, paper_id: str) -> Path:
        return self.run_summaries_dir / f"{paper_id}.md"

    def cached_summary(self, paper_id: str) -> Path:
        return self.cache_summaries_dir / f"{paper_id}.md"

    def cached_json(self, paper_id: str) -> Path:
        return self.cache_parsed_dir / paper_id / f"{paper_id}.json"

    def pdf(self, paper_id: str) -> Path:
        return self.papers_download_dir / f"{paper_id}.pdf"

    def has_cached_summary(self, paper_id: str) -> bool:
        return self.cached_summary(paper_id).exists()

    def has_cached_json(self, paper_id: str) -> bool:
        return self.cached_json(paper_id).exists()

    def copy_summary_to_run(self, paper_id: str) -> None:
        shutil.copy2(self.cached_summary(paper_id), self.run_summary(paper_id))

    def save_summary(self, paper_id: str, text: str) -> None:
        self.cached_summary(paper_id).write_text(text, encoding="utf-8")
        self.run_summary(paper_id).write_text(text, encoding="utf-8")


class SummaryGenerationWorkflow(HumanInTheLoopWorkflow):
    wid: Optional[uuid.UUID] = uuid.uuid4()
    num_max_final_papers: int = settings.NUM_MAX_FINAL_PAPERS

    def __init__(self, wid: Optional[uuid.UUID] = uuid.uuid4(), *args, **kwargs):
        self.wid = wid
        super().__init__(*args, **kwargs)
        self._files = PaperFileStore(
            workflow_root=Path(settings.WORKFLOW_ARTIFACTS_ROOT),
            workflow_name=self.__class__.__name__,
            run_id=str(self.wid),
        )

        self._fast_llm = model_factory.fast_llm(temperature=0.0)
        self._smart_llm = model_factory.smart_llm(temperature=0.0)

        self._embed_model = model_factory.embed_model()
        self._relevance_filter = PaperRelevanceFilter(
            embed_model=self._embed_model,
            llm=self._fast_llm,
        )

        self._docling = DoclingPipeline(
            max_tokens=settings.RAG_CHUNK_SIZE,
            filter_config_path=Path(settings.CHUNK_FILTER_CONFIG_PATH),
        )
        _client, _aclient = build_qdrant_clients()
        self._paper_store = PaperStore(self._docling, self._embed_model, _client, _aclient)
        self._paper_search_spec = PaperSearchToolSpec()
        # fetch_candidate_papers is called directly by supervisor_search step;
        # _paper_search_spec.to_tool_list() is available if a future agent needs search.
        self._search_params_program = LLMTextCompletionProgram.from_defaults(
            llm=self._smart_llm,
            output_cls=SearchParams,
            prompt_template_str=SEARCH_PARAMS_EXTRACTION_PMT,
            verbose=False,
        )
        self._classify_intent_program = LLMTextCompletionProgram.from_defaults(
            llm=self._smart_llm,
            output_cls=IntentResult,
            prompt_template_str=CLASSIFY_INTENT_PMT,
            verbose=False,
        )
        self._paper_candidates_cache: list = []   # PaperCandidate dicts sent to frontend
        self._paper_qa_context: list = []         # {title, abstract} for handle_paper_question; uses original abstract

    def to_tool_list(self) -> list[FunctionTool]:
        """Assemble tools exposed to a SummaryGenerationWorkflow ReActAgent.

        Currently returns an empty list: workflow steps call functions directly.
        To expose paper search to an agent, uncomment the line below.
        """
        return []
        # + self._paper_search_spec.to_tool_list()

    @step
    async def supervisor_search(self, ctx: Context, ev: StartEvent) -> PaperEvent:
        logger.info("[DIAG] entering supervisor_search")
        user_query = ev.user_query

        intent_result: IntentResult = await self._classify_intent_program.acall(
            current_phase="idle",
            phase_context="User is on the start screen, no search started yet.",
            valid_intents="research_query | greeting_or_help | ambiguous | out_of_scope",
            user_message=user_query,
        )
        if intent_result.intent != "research_query":
            fixed_responses = {
                "greeting_or_help": "Hi! I search academic papers and generate slides. Enter a research topic to get started.",
                "ambiguous": "The topic is not clear. Could you describe the research topic? e.g. 'LoRA fine-tuning for LLMs'",
                "out_of_scope": "I can search academic papers or answer questions about downloaded papers.",
            }
            message = fixed_responses.get(intent_result.intent, "Please enter a research topic to get started.")
            self._emit_message(ctx, "supervisor_search", event_type="supervisor_response", message=message)
            logger.info("[DIAG] leaving supervisor_search: non-research intent=%s", intent_result.intent)
            return StopEvent(result=None)

        self._emit_message(ctx, "supervisor_search", message="Analyzing your research topic...")

        params: SearchParams = await self._search_params_program.acall(
            user_query=user_query,
            current_year=date.today().year
        )

        if not params.has_identifiable_topic:
            message = (
                f"The topic is not clear. {params.topic_missing_reason or ''} "
                "Could you describe the research topic? "
                "e.g. 'LoRA fine-tuning for LLMs'"
            ).strip()
            self._emit_message(
                ctx, "supervisor_search",
                event_type="supervisor_response",
                message=message
            )
            logger.info("[DIAG] leaving supervisor_search: no identifiable topic")
            return StopEvent(result=None)

        async with ctx.store.edit_state() as state:
            state["search_params"] = params.model_dump()
            state["original_query"] = user_query
            state["research_topic"] = params.clean_topic

        self._emit_message(
            ctx, "supervisor_search",
            message=(
                f"Searching: '{params.clean_topic}' | "
                f"last {params.year_window} years | cited > {params.min_citations}"
            )
        )

        logger.info("[DIAG] supervisor_search: calling fetch_candidate_papers")
        papers = fetch_candidate_papers(
            topic=params.clean_topic,
            year_window=params.year_window,
            min_citations=params.min_citations,
        )
        papers = list({p.entry_id: p for p in papers}.values())  # deduplicate
        logger.info("[DIAG] supervisor_search: fetch_candidate_papers returned %d papers", len(papers))

        if not papers:
            self._emit_message(
                ctx, "supervisor_search",
                event_type="no_results",
                message=(
                    f"No papers found for '{params.clean_topic}' "
                    f"in last {params.year_window} years with cited > {params.min_citations}."
                ),
                suggestions=[
                    "Try a broader topic",
                    f"Extend year window to {params.year_window + 2}",
                    f"Lower citation threshold to {max(10, params.min_citations // 2)}",
                ],
            )
            logger.info("[DIAG] leaving supervisor_search: no papers found")
            return StopEvent(result=None)

        async with ctx.store.edit_state() as state:
            state["n_all_papers"] = len(papers)
            state["n_filtered"] = 0

        self._emit_message(
            ctx, "supervisor_search",
            message=f"Found {len(papers)} candidates, filtering for relevance..."
        )

        logger.info("[DIAG] supervisor_search: dispatching %d PaperEvent(s)", len(papers))
        for paper in papers:
            ctx.send_event(PaperEvent(paper=paper))
        logger.info("[DIAG] leaving supervisor_search")

    @step(num_workers=settings.NUM_WORKERS_FAST, retry_policy=LOCAL_LLM_RETRY_POLICY)
    async def filter_papers(self, ctx: Context, ev: PaperEvent) -> FilteredPaperEvent:
        logger.info("[DIAG] entering filter_papers: paper=%s", ev.paper.title)
        research_topic = await ctx.store.get("research_topic")
        n_all = await ctx.store.get("n_all_papers")

        is_relevant, similarity_score = self._relevance_filter.assess_relevance(
            ev.paper, research_topic
        )

        async with ctx.store.edit_state() as state:
            state["n_filtered"] = state.get("n_filtered", 0) + 1
            n_done = state["n_filtered"]

        if n_done % 10 == 0 or n_done == n_all:
            self._emit_message(
                ctx, "filter_papers",
                message=f"Filtering for relevance: {n_done}/{n_all} papers checked..."
            )

        logger.info("[DIAG] leaving filter_papers: paper=%s relevant=%s score=%.3f", ev.paper.title, is_relevant, similarity_score)
        return FilteredPaperEvent(
            paper=ev.paper,
            relevance=PaperRelevanceResult(
                is_relevant=is_relevant, similarity_score=similarity_score
            ),
        )

    @step
    async def present_paper_candidates(
        self, ctx: Context, ev: FilteredPaperEvent
    ) -> SelectedPapersEvent | StopEvent:
        logger.info("[DIAG] entering present_paper_candidates")
        n_all_papers = await ctx.store.get("n_all_papers")

        ready = ctx.collect_events(ev, [FilteredPaperEvent] * n_all_papers)
        if ready is None:
            logger.info("[DIAG] present_paper_candidates: not all FilteredPaperEvents collected yet, waiting")
            return None  # not all events collected yet — LlamaIndex will call again

        self._emit_message(ctx, "present_paper_candidates", message="Preparing paper selection...")

        relevant = sorted(
            [e for e in ready if e.relevance.is_relevant],
            key=lambda e: (e.paper.cited_by_count or 0, e.relevance.similarity_score),
            reverse=True,
        )

        if not relevant:
            search_params = await ctx.store.get("search_params")
            self._emit_message(
                ctx, "present_paper_candidates",
                event_type="no_results",
                message="No relevant papers found after relevance filtering.",
                search_params=search_params,
                suggestions=[
                    "Try a different topic",
                    "Broaden the year window",
                    "Lower the citation threshold",
                ],
            )
            logger.info("[DIAG] leaving present_paper_candidates: no relevant papers")
            return StopEvent(result=None)

        candidates = []
        for e in relevant[: settings.NUM_MAX_FINAL_PAPERS * 3]:
            paper = e.paper
            authors_str = (
                f"{paper.authors[0].split()[-1]} et al."
                if paper.authors
                else "Unknown"
            )
            resp = await self._smart_llm.achat(
                [ChatMessage(role="user", content=f"Summarize in 1-2 sentences (max 40 words). Plain text only, no markdown, no bold, no asterisks:\n\n{paper.summary}")]
            )
            candidates.append(
                PaperCandidate(
                    entry_id=paper.entry_id,
                    title=paper.title,
                    authors=authors_str,
                    year=int(paper.published[:4]) if paper.published else 0,
                    abstract_summary=resp.message.content.strip(),
                    similarity_score=e.relevance.similarity_score,
                    cited_by_count=paper.cited_by_count,
                ).model_dump()
            )

        self._paper_qa_context = [
            {"title": e.paper.title, "abstract": e.paper.summary or "(no abstract)"}
            for e in relevant[: settings.NUM_MAX_FINAL_PAPERS * 3]
        ]
        self._paper_candidates_cache = candidates
        search_params = await ctx.store.get("search_params")
        self._emit_message(
            ctx,
            "present_paper_candidates",
            event_type="paper_candidates",
            candidates=candidates,
            search_params=search_params,
            message=f"Found {len(candidates)} relevant papers. Select which to include in your slides.",
        )

        if self.user_input_future is None:
            self.user_input_future = self.loop.create_future()

        user_response_str = await self.user_input_future

        if self.parent_workflow:
            await self.parent_workflow.reset_user_input_future()
            self.user_input_future = self.parent_workflow.user_input_future
        else:
            self.user_input_future = self.loop.create_future()

        response = json.loads(user_response_str)
        action = response.get("action")

        if action == "select":
            selected_ids = set(response.get("selected_entry_ids", []))
            selected_papers = [
                e.paper for e in relevant if e.paper.entry_id in selected_ids
            ]
            logger.info("[DIAG] leaving present_paper_candidates: user selected %d papers", len(selected_papers))
            return SelectedPapersEvent(
                selected_entry_ids=list(selected_ids),
                papers=[p.model_dump() for p in selected_papers],
            )
        else:
            logger.info("[DIAG] leaving present_paper_candidates: user cancelled (action=%s)", action)
            return StopEvent(result=None)

    @step
    async def check_paper_status(
        self, ctx: Context, ev: SelectedPapersEvent
    ) -> Optional[DownloadPapersEvent]:
        logger.info("[DIAG] entering check_paper_status: %d papers selected", len(ev.papers))
        papers = [Paper(**p) for p in ev.papers]
        n_total = len(papers)

        async with ctx.store.edit_state() as state:
            state["n_pdfs"] = n_total

        paper_map: dict[str, dict] = {}
        papers_needing_work: list[Paper] = []

        for paper in papers:
            document_id = _get_paper_id(paper)
            if self._paper_store.is_indexed(document_id) and self._files.has_cached_summary(document_id):
                self._files.copy_summary_to_run(document_id)
                logger.info(f"Already fully processed, fast-path: document_id={document_id}")
                self._emit_message(ctx, "check_paper_status",
                    message=f"✓ Already processed (cached): {paper.title}")
                ctx.send_event(SummaryStoredEvent(fpath=self._files.run_summary(document_id)))
            else:
                paper_map[document_id] = {"document_id": document_id, "title": paper.title}
                papers_needing_work.append(paper)

        if not papers_needing_work:
            logger.info("[DIAG] leaving check_paper_status: all papers already fully processed (fast-path)")
            return None

        self._emit_message(
            ctx, "check_paper_status",
            message=f"{len(papers_needing_work)} of {n_total} papers need processing."
        )
        logger.info("[DIAG] leaving check_paper_status: %d of %d papers need processing", len(papers_needing_work), n_total)
        return DownloadPapersEvent(
            papers=[p.model_dump() for p in papers_needing_work],
            paper_map=paper_map,
        )

    @step
    async def download_papers(
        self, ctx: Context, ev: DownloadPapersEvent
    ) -> Paper2SummaryDispatcherEvent:
        logger.info("[DIAG] entering download_papers: %d papers to download", len(ev.papers))
        papers = [Paper(**p) for p in ev.papers]

        self._emit_message(
            ctx, "download_papers",
            message=f"Downloading up to {len(papers)} papers..."
        )
        for paper in papers:
            document_id = _get_paper_id(paper)
            if self._files.has_cached_json(document_id):
                logger.info(f"JSON cache exists, skipping download: {paper.title}")
                continue
            success = PaperDownloader.download_pdf(paper, self._files.papers_download_dir)
            msg = (
                f"✓ Downloaded: {paper.title}"
                if success
                else f"⚠ Skipped (no open access PDF): {paper.title}"
            )
            self._emit_message(ctx, "download_papers", message=msg)

        logger.info("[DIAG] leaving download_papers: dispatching Paper2SummaryDispatcherEvent")
        return Paper2SummaryDispatcherEvent(
            papers_path=self._files.papers_download_dir.as_posix(),
            paper_map=ev.paper_map,
        )

    @step
    async def paper2summary_dispatcher(
        self, ctx: Context, ev: Paper2SummaryDispatcherEvent
    ) -> Union[Paper2SummaryEvent, None]:
        logger.info("[DIAG] entering paper2summary_dispatcher: %d papers in paper_map", len(ev.paper_map))
        for document_id, info in ev.paper_map.items():
            paper_title = info["title"]
            has_shared_summary = self._files.has_cached_summary(document_id)
            needs_vector_indexing = (
                not self._paper_store.is_indexed(document_id)
                or not self._paper_store._is_rag_indexed(document_id)
            )

            logger.info(
                "[DIAG] paper2summary_dispatcher: dispatching document_id=%s title=%r needs_summarization=%s needs_vector_indexing=%s",
                document_id, paper_title, not has_shared_summary, needs_vector_indexing,
            )
            ctx.send_event(Paper2SummaryEvent(
                pdf_path=self._files.pdf(document_id),
                run_summary_path=self._files.run_summary(document_id),
                document_id=document_id,
                paper_title=paper_title,
                needs_summarization=not has_shared_summary,
                needs_vector_indexing=needs_vector_indexing,
            ))
        logger.info("[DIAG] leaving paper2summary_dispatcher: all Paper2SummaryEvent(s) dispatched")

    @step(num_workers=settings.NUM_WORKERS_SMART)
    async def paper2summary(
        self, ctx: Context, ev: Paper2SummaryEvent
    ) -> SummaryStoredEvent:
        logger.info("[DIAG] entering paper2summary: document_id=%s title=%r", ev.document_id, ev.paper_title)

        json_path = self._files.cached_json(ev.document_id)
        if not json_path.exists():
            self._emit_message(ctx, "paper2summary", message=f"Parsing PDF: {ev.paper_title}")
            json_path = self._docling.parse_pdf(ev.pdf_path, self._files.cache_parsed_dir)
            if json_path is None:
                logger.warning(f"Skipping {ev.document_id}: PDF unavailable or parse failed")
                self._emit_message(ctx, "paper2summary", message=f"⚠ Skipped: {ev.paper_title} — PDF unavailable or parse failed")
                logger.info("[DIAG] leaving paper2summary: skipped document_id=%s (no PDF/parse failure)", ev.document_id)
                return SummaryStoredEvent(fpath=ev.run_summary_path)
        else:
            self._emit_message(ctx, "paper2summary", message=f"✓ PDF already parsed (cached): {ev.paper_title}")

        try:
            if ev.needs_summarization or ev.needs_vector_indexing:
                doc = self._docling.load_document(json_path)
                self._emit_message(ctx, "paper2summary", message=f"Indexing to database: {ev.paper_title}")
                await self._paper_store.index_paper(doc, ev.document_id, ev.paper_title)
            else:
                self._emit_message(ctx, "paper2summary", message=f"✓ Already indexed (cached): {ev.paper_title}")

            if ev.needs_summarization:
                self._emit_message(ctx, "paper2summary", message=f"Generating summary: {ev.paper_title}")
                summary_txt = await self._summarize_with_rag(ev.document_id)
                self._files.save_summary(ev.document_id, summary_txt)
                logger.info(f"Summary saved to {ev.run_summary_path}")
            else:
                self._emit_message(ctx, "paper2summary", message=f"✓ Summary already exists (cached): {ev.paper_title}")
        except Exception as e:
            self._emit_message(ctx, "paper2summary", message=f"✗ Failed: {ev.paper_title} — {e}")
            logger.exception(f"Failed to process {ev.document_id}: {e}")

        logger.info("[DIAG] leaving paper2summary: document_id=%s", ev.document_id)
        return SummaryStoredEvent(fpath=ev.run_summary_path)

    async def _summarize_with_rag(self, paper_id: str) -> str:
        context = "\n\n---\n\n".join(
            self._paper_store.retrieve_context(
                paper_id, RETRIEVAL_QUERIES, settings.RAG_SIMILARITY_TOP_K
            )
        )
        response = await self._smart_llm.acomplete(
            SUMMARIZE_PAPER_PMT + f"\n\n{context}",
            strip_fences="markdown",
        )
        return response.text

    @step
    async def finish(self, ctx: Context, ev: SummaryStoredEvent) -> StopEvent:
        logger.info("[DIAG] entering finish")
        n_pdfs = await ctx.store.get("n_pdfs")
        ready = ctx.collect_events(ev, [SummaryStoredEvent] * n_pdfs)
        if ready is None:
            logger.info("[DIAG] finish: not all SummaryStoredEvents collected yet, waiting")
            return None

        missing = [e.fpath for e in ready if not e.fpath.is_file()]
        if missing:
            logger.warning(f"Missing summary files: {missing}")

        self._emit_message(ctx, "finish", message=f"All {len(ready)} paper summaries stored.")
        logger.info(f"All {len(ready)} paper summaries stored.")
        logger.info("[DIAG] leaving finish: workflow complete, summaries_dir=%s", self._files.run_summaries_dir)
        return StopEvent(result=self._files.run_summaries_dir.as_posix())

    async def handle_paper_question(self, message: str) -> str:
        if not getattr(self, "_paper_qa_context", None):
            return "No papers available to answer questions about."

        paper_abstracts = "\n\n".join(
            f"Paper {i+1}: {c['title']}\nAbstract: {c['abstract']}"
            for i, c in enumerate(self._paper_qa_context)
        )
        paper_titles = ", ".join(
            f"Paper {i+1}: {c['title']}"
            for i, c in enumerate(self._paper_qa_context)
        )

        intent_result: IntentResult = await self._classify_intent_program.acall(
            current_phase="search",
            phase_context=f"User is reviewing {len(self._paper_qa_context)} candidate papers: {paper_titles}",
            valid_intents="paper_question | new_research | off_topic | ambiguous",
            user_message=message,
        )
        intent = intent_result.intent

        if intent == "paper_question":
            answer_prompt = PAPER_QUESTION_PMT.format(
                paper_abstracts=paper_abstracts,
                user_question=message,
            )
            resp = await self._smart_llm.achat([ChatMessage(role="user", content=answer_prompt)])
            return resp.message.content.strip()
        elif intent == "new_research":
            return 'To search a different topic, use the "🔍 New search" button in the card above.'
        else:
            return (
                "I'm helping you select papers. "
                "· Ask me about any listed paper "
                "· Click ▶ Generate to proceed "
                "· Click 🔍 New search to start over"
            )


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
            result="workflow_artifacts/SummaryGenerationWorkflow/dummy-id/summaries"
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
