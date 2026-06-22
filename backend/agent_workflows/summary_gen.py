import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import ClassVar, Optional, Union

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
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc import DoclingDocument

from agent_workflows.events import *
from agent_workflows.hitl_workflow import HumanInTheLoopWorkflow, LOCAL_LLM_RETRY_POLICY
from agent_workflows.paper_scraping import (
    Paper,
    PaperRelevanceFilter,
    PaperRelevanceResult,
    download_paper_pdf,
    fetch_candidate_papers,
    parse_pdf_with_docling,
)
from agent_workflows.schemas import IntentResult, PaperCandidate, SearchParams
from prompts.prompts import (
    CLASSIFY_INTENT_PMT,
    PAPER_QUESTION_PMT,
    SEARCH_PARAMS_EXTRACTION_PMT,
    SUMMARIZE_PAPER_PMT,
)
from services.docling_chunker import DoclingChunker
from services.model_factory import model_factory
from services.rag_index_builder import RAGIndexBuilder
from services.vector_store import PaperVectorStore
from tools.filter_tools import ChunkFilter
from tools.paper_tools import PaperSearchToolSpec
from utils.logger import get_logger

logger = get_logger(__name__)


_RETRIEVAL_QUERIES = [
    "What problem does this paper address and what is the proposed solution?",
    "What is the key approach, model architecture, or algorithm introduced?",
    "What are the key components or steps in the method?",
    "How was the model trained or finetuned, including loss functions and optimization?",
    "What datasets were used, including size, type, source, and availability?",
    "What evaluation methods, benchmarks, and metrics were used?",
    "What are the conclusions, significance, limitations, and suggested future work?",
    "Who are the authors and what is the publication year?",
]


def _get_paper_id(paper: Paper) -> str:
    """Return document_id (and filename stem) for a paper.

    Uses ArXiv ID when available — stable, matches PDF filename convention.
    Falls back to OpenAlex ID for non-ArXiv papers.
    """
    arxiv_id = (paper.external_ids or {}).get("ArXiv")
    if arxiv_id:
        return arxiv_id
    return paper.entry_id.rstrip("/").split("/")[-1]


def _build_docling_converter() -> DocumentConverter:
    """Build the Docling DocumentConverter singleton with M1-compatible options."""
    opts = PdfPipelineOptions()
    opts.do_ocr = False
    opts.do_table_structure = True
    opts.table_structure_options = TableStructureOptions(
        mode=TableFormerMode.ACCURATE, do_cell_matching=True
    )
    opts.do_formula_enrichment = True
    opts.do_code_enrichment = True
    opts.do_picture_classification = True
    opts.generate_picture_images = True
    opts.images_scale = 2.0
    opts.do_picture_description = False
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )


class SummaryGenerationWorkflow(HumanInTheLoopWorkflow):
    wid: Optional[uuid.UUID] = uuid.uuid4()
    num_max_final_papers: int = settings.NUM_MAX_FINAL_PAPERS

    _PAPERS_SUBDIR: ClassVar[str] = "papers"
    _SUMMARIES_SUBDIR: ClassVar[str] = "summaries"

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
        self.paper_summary_path = self.workflow_artifacts_path / self._SUMMARIES_SUBDIR
        self.paper_summary_path.mkdir(parents=True, exist_ok=True)

        shared_cache_root = Path(settings.SHARED_CACHE_ROOT)
        self._shared_parsed_papers_dir = shared_cache_root / "parsed_papers"
        self._shared_summaries_dir = shared_cache_root / "summaries"
        self._shared_parsed_papers_dir.mkdir(parents=True, exist_ok=True)
        self._shared_summaries_dir.mkdir(parents=True, exist_ok=True)

        self._fast_llm = model_factory.fast_llm(temperature=0.0)
        self._smart_llm = model_factory.smart_llm(temperature=0.0)
        self._vlm = model_factory.vision_llm()

        self._embed_model = model_factory.embed_model()
        self._relevance_filter = PaperRelevanceFilter(
            embed_model=self._embed_model,
            llm=self._fast_llm,
        )

        chunk_filter = ChunkFilter(config_path=Path(settings.CHUNK_FILTER_CONFIG_PATH))
        chunker = DoclingChunker(max_tokens=settings.RAG_CHUNK_SIZE)
        self._summarization_index_builder = RAGIndexBuilder(chunker, chunk_filter)
        self._paper_vector_store = PaperVectorStore(chunker, chunk_filter, self._embed_model)
        self._docling_converter = _build_docling_converter()
        self.paper_search_spec = PaperSearchToolSpec()
        # fetch_candidate_papers is called directly by supervisor_search step;
        # paper_search_spec.to_tool_list() is available if a future agent needs search.
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
        # + self.paper_search_spec.to_tool_list()

    @step
    async def supervisor_search(self, ctx: Context, ev: StartEvent) -> PaperEvent:
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
                "ambiguous": "Could you describe the research topic? e.g. 'LoRA fine-tuning for LLMs'",
                "out_of_scope": "I can search academic papers or answer questions about downloaded papers.",
            }
            message = fixed_responses.get(intent_result.intent, "Please enter a research topic to get started.")
            self._emit_message(ctx, "supervisor_search", event_type="supervisor_response", message=message)
            return StopEvent(result=None)

        self._emit_message(ctx, "supervisor_search", message="Analyzing your research topic...")

        params: SearchParams = await self._search_params_program.acall(user_query=user_query)

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

        papers = fetch_candidate_papers(
            topic=params.clean_topic,
            year_window=params.year_window,
            min_citations=params.min_citations,
        )
        papers = list({p.entry_id: p for p in papers}.values())  # deduplicate

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
            return StopEvent(result=None)

        async with ctx.store.edit_state() as state:
            state["n_all_papers"] = len(papers)

        self._emit_message(
            ctx, "supervisor_search",
            message=f"Found {len(papers)} candidates, filtering for relevance..."
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
    async def present_paper_candidates(
        self, ctx: Context, ev: FilteredPaperEvent
    ) -> SelectedPapersEvent | StopEvent:
        n_all_papers = await ctx.store.get("n_all_papers")

        ready = ctx.collect_events(ev, [FilteredPaperEvent] * n_all_papers)
        if ready is None:
            return None  # not all events collected yet — LlamaIndex will call again

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
            return SelectedPapersEvent(
                selected_entry_ids=list(selected_ids),
                papers=[p.model_dump() for p in selected_papers],
            )
        else:
            return StopEvent(result=None)

    @step
    async def check_paper_status(
        self, ctx: Context, ev: SelectedPapersEvent
    ) -> Optional[DownloadPapersEvent]:
        papers = [Paper(**p) for p in ev.papers]
        n_total = len(papers)

        async with ctx.store.edit_state() as state:
            state["n_pdfs"] = n_total

        paper_map: dict[str, dict] = {}
        papers_needing_work: list[Paper] = []

        for paper in papers:
            document_id = _get_paper_id(paper)
            paper_map[document_id] = {"document_id": document_id, "title": paper.title}

            shared_summary = self._shared_summaries_dir / f"{document_id}.md"
            run_summary_path = self.paper_summary_path / f"{document_id}.md"

            if self._paper_vector_store.is_indexed(document_id) and shared_summary.exists():
                shutil.copy2(shared_summary, run_summary_path)
                logger.info(f"Already fully processed, fast-path: document_id={document_id}")
                ctx.send_event(SummaryStoredEvent(fpath=run_summary_path))
            else:
                papers_needing_work.append(paper)

        if not papers_needing_work:
            return None

        self._emit_message(
            ctx, "check_paper_status",
            message=f"{len(papers_needing_work)} of {n_total} papers need processing."
        )
        return DownloadPapersEvent(
            papers=[p.model_dump() for p in papers_needing_work],
            paper_map=paper_map,
        )

    @step
    async def download_papers(
        self, ctx: Context, ev: DownloadPapersEvent
    ) -> Paper2SummaryDispatcherEvent:
        papers = [Paper(**p) for p in ev.papers]

        self._emit_message(
            ctx, "download_papers",
            message=f"Downloading up to {len(papers)} papers..."
        )
        for paper in papers:
            document_id = _get_paper_id(paper)
            json_path = self._shared_parsed_papers_dir / document_id / f"{document_id}.json"
            if json_path.exists():
                logger.info(f"JSON cache exists, skipping download: {paper.title}")
                continue
            success = download_paper_pdf(paper, self.papers_download_path)
            msg = (
                f"✓ Downloaded: {paper.title}"
                if success
                else f"⚠ Skipped (no open access PDF): {paper.title}"
            )
            self._emit_message(ctx, "download_papers", message=msg)

        return Paper2SummaryDispatcherEvent(
            papers_path=self.papers_download_path.as_posix(),
            paper_map=ev.paper_map,
        )

    @step
    async def paper2summary_dispatcher(
        self, ctx: Context, ev: Paper2SummaryDispatcherEvent
    ) -> Union[Paper2SummaryEvent, None]:
        for document_id, info in ev.paper_map.items():
            paper_title = info["title"]
            run_summary_path = self.paper_summary_path / f"{document_id}.md"
            shared_summary = self._shared_summaries_dir / f"{document_id}.md"
            pdf_path = Path(ev.papers_path) / f"{document_id}.pdf"

            is_indexed = self._paper_vector_store.is_indexed(document_id)
            has_shared_summary = shared_summary.exists()

            ctx.send_event(Paper2SummaryEvent(
                pdf_path=pdf_path,
                run_summary_path=run_summary_path,
                document_id=document_id,
                paper_title=paper_title,
                needs_summarization=not has_shared_summary,
                needs_vector_indexing=not is_indexed,
            ))

    @step(num_workers=settings.NUM_WORKERS_VISION)
    async def paper2summary(
        self, ctx: Context, ev: Paper2SummaryEvent
    ) -> SummaryStoredEvent:
        await asyncio.sleep(settings.DELAY_SECONDS_VISION)
        self._emit_message(ctx, "paper2summary", message=f"Summarizing: {ev.pdf_path.name}")

        json_path = self._shared_parsed_papers_dir / ev.document_id / f"{ev.document_id}.json"
        if not json_path.exists():
            parse_pdf_with_docling(
                ev.pdf_path, self._shared_parsed_papers_dir, self._docling_converter
            )

        if ev.needs_summarization:
            if settings.SUMMARY_STRATEGY == "rag":
                summary_txt = await self._summarize_with_rag(json_path)
            else:
                summary_txt = await self._summarize_with_vlm(ev.pdf_path)
            ev.run_summary_path.write_text(summary_txt, encoding="utf-8")
            (self._shared_summaries_dir / f"{ev.document_id}.md").write_text(
                summary_txt, encoding="utf-8"
            )
            logger.info(f"Summary saved to {ev.run_summary_path}")

        if ev.needs_vector_indexing:
            doc = DoclingDocument.model_validate(
                json.loads(json_path.read_text())
            )
            await self._paper_vector_store.index_document_async(
                doc, ev.document_id, ev.paper_title
            )

        return SummaryStoredEvent(fpath=ev.run_summary_path)

    async def _summarize_with_rag(self, json_path: Path) -> str:
        doc = DoclingDocument.model_validate(json.loads(json_path.read_text()))
        index = self._summarization_index_builder.build(doc, self._embed_model)
        retriever = index.as_retriever(similarity_top_k=settings.RAG_SIMILARITY_TOP_K)

        seen_ids: set[str] = set()
        context_chunks: list[str] = []
        for query in _RETRIEVAL_QUERIES:
            for node in retriever.retrieve(query):
                if node.node_id not in seen_ids:
                    seen_ids.add(node.node_id)
                    context_chunks.append(node.text)

        context = "\n\n---\n\n".join(context_chunks)
        response = await self._smart_llm.acomplete(
            SUMMARIZE_PAPER_PMT + f"\n\n{context}",
            strip_fences="markdown",
        )
        return response.text

    async def _summarize_with_vlm(self, pdf_path: Path) -> str:
        # Legacy VLM image-based path; retained for baseline comparison.
        import tempfile
        from llama_index.core import SimpleDirectoryReader
        from utils.file_processing import pdf2images

        with tempfile.TemporaryDirectory() as tmp_dir:
            image_output_dir = Path(tmp_dir)
            pdf2images(pdf_path, image_output_dir)
            image_documents = SimpleDirectoryReader(str(image_output_dir)).load_data()
        response = await self._vlm.acomplete(
            prompt=SUMMARIZE_PAPER_PMT,
            image_documents=image_documents,
            strip_fences="markdown",
        )
        return response.text

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
