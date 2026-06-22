"""Summarization Comparison — VLM vs RAG Experiment

Compare four strategies for generating paper summaries from ML research PDFs:

  1. vlm                — Convert every PDF page to a PNG image and pass all pages
                          directly to a vision-language model. Zero chunking or retrieval.
                          Baseline for comparing against RAG-based approaches.

  2. rag_fixed_queries  — Chunk each paper with Docling HybridChunker (512 tokens),
                          store in Qdrant, retrieve with 9 fixed queries covering different
                          aspects of the paper (problem, method, training, results, etc.),
                          then summarize the retrieved chunks with an LLM.

  3. rag_with_expansion — Same as rag_fixed_queries, but each of the 9 queries is expanded
                          into 4 LLM-generated variants and results are fused via reciprocal
                          rank fusion. Aims to improve coverage when query phrasing diverges
                          from document wording.

  4. rag_winner_no_filter — Same as rag_with_expansion, but WITHOUT the boilerplate filter
                             (References, Acknowledgements sections are kept). Tests whether
                             filtering actually helps for summarization (vs retrieval).

All configs use the same 8 papers spanning short (9 pages), long (46 pages), and
appendix-heavy (39–45 pages) papers to stress-test each strategy across paper types.

Run from the repo root:
    micromamba run -n py3.12 python poc/rag-eval/summarization_comparison.py
    micromamba run -n py3.12 python poc/rag-eval/summarization_comparison.py --config vlm
    micromamba run -n py3.12 python poc/rag-eval/summarization_comparison.py --paper 1608.06993
    micromamba run -n py3.12 python poc/rag-eval/summarization_comparison.py --index-only
"""

import os
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"  # must be set before any torch/transformers import

# ragas 0.4.x imports ChatVertexAI at module level in ragas/llms/base.py even when only
# LlamaIndex is used. These stub modules prevent ImportError. ChatVertexAI/VertexAI are
# only referenced in a type-check list inside ragas and are never actually instantiated.
try:
    from langchain_community.chat_models import ChatVertexAI  # noqa: F401
    from langchain_community.embeddings import VertexAIEmbeddings  # noqa: F401
except ImportError:
    import sys as _sys
    import types as _types
    _vx = _types.ModuleType("langchain_community.chat_models.vertexai")
    _vx.ChatVertexAI = type("ChatVertexAI", (), {})
    _sys.modules["langchain_community.chat_models.vertexai"] = _vx
    _vx2 = _types.ModuleType("langchain_community.llms.vertexai")
    _vx2.VertexAI = type("VertexAI", (), {})
    _sys.modules["langchain_community.llms.vertexai"] = _vx2

import sys
sys.path.insert(0, ".")        # repo root — makes poc.poc_base importable
sys.path.insert(0, "backend")  # backend modules — makes services, tools, utils importable

import nest_asyncio
nest_asyncio.apply()
# QueryFusionRetriever uses asyncio internally. Without this patch, Python raises
# RuntimeError when an async call is made inside an already-running event loop.

import json
import time
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import click
import tiktoken
from docling.chunking import HybridChunker
from llama_index.core import VectorStoreIndex, StorageContext, SimpleDirectoryReader
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.schema import TextNode, Document, ImageDocument
from llama_index.embeddings.litellm import LiteLLMEmbedding
from llama_index.llms.litellm import LiteLLM
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from agent_workflows.summary_gen import _RETRIEVAL_QUERIES, SUMMARIZE_PAPER_PMT
from services.docling_chunker import DoclingChunker
from services.multimodal import LiteLLMMultiModal
from tools.filter_tools import ChunkFilter
from utils.file_processing import pdf2images
from poc.poc_base import ExperimentLogger, PaperCorpus, ContextualDoclingNodeParser


# ── Qdrant on-disk directories — one per filter config to avoid collection conflicts ─────────────

QDRANT_DIR_WITH_CHUNK_FILTER = Path("poc/rag-eval/qdrant_summarization_with_filter")
QDRANT_DIR_WITHOUT_CHUNK_FILTER = Path("poc/rag-eval/qdrant_summarization_no_filter")

# Output directory where per-config summary .txt files are saved
SUMMARIES_DIR = Path("poc/rag-eval/summarization_summaries")

# 8 papers selected to cover a range of lengths and content types:
#   Short papers  (≤12 pages): 1608.06993 (NAS with RL, 9p), 1801.06146 (ELMo, 12p)
#   Long papers   (40-48 pages): 2103.00020 (CLIP), 2109.01652 (FLAN)
#   Math/table-heavy: 2303.01469 (LLaMA), 2201.11903 (chain-of-thought survey)
#   Appendix-heavy: 2109.07958 (BIG-Bench), 2112.10752 (DALL-E 2 / multimodal)
PAPER_IDS_FOR_SUMMARIZATION_COMPARISON = [
    "1608.06993",  # NAS with RL (Zoph & Le) — short paper, 9 pages
    "1801.06146",  # ELMo — short paper, 12 pages
    "2103.00020",  # CLIP — long paper, 48 pages
    "2109.01652",  # FLAN — long paper, 46 pages
    "2303.01469",  # LLaMA — math/table-heavy, 42 pages
    "2201.11903",  # chain-of-thought survey — math/table-heavy, 43 pages
    "2109.07958",  # BIG-Bench — appendix-heavy, 39 pages
    "2112.10752",  # DALL-E 2 / multimodal — appendix-heavy, 45 pages
]


@dataclass
class SummarizationExperimentConfig:
    name: str                  # identifier used in log output and output directory names
    use_vlm: bool              # True → summarize from PDF images; False → summarize from retrieved text chunks
    apply_chunk_filter: bool   # whether boilerplate (References, Acknowledgements) is removed before indexing
    use_query_expansion: bool  # whether each retrieval query is expanded into 4 variants via LLM
    qdrant_dir: Path | None    # on-disk Qdrant directory; None for VLM config (no index needed)


SUMMARIZATION_EXPERIMENT_CONFIGS = [
    SummarizationExperimentConfig(
        name="vlm",
        use_vlm=True,
        apply_chunk_filter=False,
        use_query_expansion=False,
        qdrant_dir=None,
    ),
    SummarizationExperimentConfig(
        name="rag_fixed_queries",
        use_vlm=False,
        apply_chunk_filter=True,
        use_query_expansion=False,
        qdrant_dir=QDRANT_DIR_WITH_CHUNK_FILTER,
    ),
    SummarizationExperimentConfig(
        name="rag_with_expansion",
        use_vlm=False,
        apply_chunk_filter=True,
        use_query_expansion=True,
        qdrant_dir=QDRANT_DIR_WITH_CHUNK_FILTER,
    ),
    SummarizationExperimentConfig(
        name="rag_winner_no_filter",
        use_vlm=False,
        apply_chunk_filter=False,
        use_query_expansion=False,
        qdrant_dir=QDRANT_DIR_WITHOUT_CHUNK_FILTER,
    ),
]


# ── Retrieval queries — 9 total ────────────────────────────────────────────────────────────────

# 9 queries: 8 from production pipeline + 1 added for results coverage.
# Q1-Q8 cover problem/solution, architecture, method, training, datasets, evaluation,
# conclusions, and authors — sourced directly from the production summarization pipeline.
# Q9 added because Q6 retrieves evaluation *setup* chunks (which benchmarks were used),
# not *results* chunks (what the numbers were) — these live in different paper sections.
RETRIEVAL_QUERIES_FOR_SUMMARIZATION = list(_RETRIEVAL_QUERIES) + [
    "What are the main findings, results, and key outcomes of this work?"
]


# ── Index management — build once per paper, load from disk on subsequent runs ────────────────

def is_paper_indexed_in_qdrant(qdrant_client: QdrantClient, paper_id: str) -> bool:
    """Return True if this paper's Qdrant collection exists and contains vectors."""
    try:
        collection_info = qdrant_client.get_collection(paper_id)
        return collection_info.points_count > 0
    except Exception:
        return False


def build_paper_index_on_disk(
    paper_id: str,
    corpus: PaperCorpus,
    qdrant_client: QdrantClient,
    embed_model,
    chunk_filter,  # ChunkFilter instance or None (for rag_winner_no_filter)
) -> tuple:
    """
    Parse paper → chunk → embed → store in a Qdrant collection named after paper_id.

    Uses Docling HybridChunker with a 512-token limit (the chunking strategy that
    achieved the highest Recall@5=0.61 in the prior chunking ablation experiment).
    Node IDs are uuid5 deterministic strings — Qdrant rejects non-UUID node IDs.

    Returns (VectorStoreIndex, chunk_count).
    """
    tokenizer_512_tokens = DoclingChunker._TokenizerAdapter(max_tokens=512)
    docling_parser = ContextualDoclingNodeParser(
        chunker=HybridChunker(tokenizer=tokenizer_512_tokens),
        chunk_filter=chunk_filter,
    )
    docling_doc = corpus.load_doc(paper_id)
    llama_index_doc = Document(text=docling_doc.model_dump_json(), metadata={"paper_id": paper_id})
    raw_nodes = docling_parser.parse_nodes([llama_index_doc])

    # Assign deterministic uuid5 IDs — Qdrant rejects plain strings as point IDs.
    # uuid5 is deterministic: same paper_id + chunk index → same UUID across runs.
    nodes_with_uuid_ids = [
        TextNode(
            text=node.text,
            id_=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{paper_id}_chunk_{i}")),
        )
        for i, node in enumerate(raw_nodes)
    ]

    vector_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=paper_id,
        enable_hybrid=True,
        fastembed_sparse_model="Qdrant/bm25",  # BM25 won the sparse model ablation: best recall at 15x less latency than miniCOIL
    )
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex(
        nodes=nodes_with_uuid_ids,
        embed_model=embed_model,
        storage_context=storage_context,
        show_progress=False,
    )
    return index, len(nodes_with_uuid_ids)


def load_paper_index_from_disk(paper_id: str, qdrant_client: QdrantClient, embed_model) -> VectorStoreIndex:
    """Load an already-built Qdrant index from disk. Zero embedding cost."""
    vector_store = QdrantVectorStore(
        client=qdrant_client,
        collection_name=paper_id,
        enable_hybrid=True,
        fastembed_sparse_model="Qdrant/bm25",
    )
    return VectorStoreIndex.from_vector_store(vector_store, embed_model=embed_model)


def get_or_build_paper_index(
    paper_id: str,
    exp_config: SummarizationExperimentConfig,
    corpus: PaperCorpus,
    qdrant_client: QdrantClient,
    embed_model,
    chunk_filter,
    force_rebuild: bool = False,
) -> tuple:
    """Return (index, chunk_count_or_none). Builds index only if not already on disk."""
    if not force_rebuild and is_paper_indexed_in_qdrant(qdrant_client, paper_id):
        return load_paper_index_from_disk(paper_id, qdrant_client, embed_model), None
    return build_paper_index_on_disk(paper_id, corpus, qdrant_client, embed_model, chunk_filter)


# ── Retrieval — fixed queries and query expansion ─────────────────────────────────────────────

def retrieve_chunks_fixed_queries(index: VectorStoreIndex, similarity_top_k: int = 10) -> list[str]:
    """
    Run all 9 retrieval queries directly against the index. No query expansion.

    Goal is COVERAGE — each query targets a different paper section (problem, method,
    training, datasets, evaluation, results, conclusions, authors, findings).
    Direct loop is correct here; QueryFusionRetriever would wrongly generate variants
    of one topic instead of covering all 9 distinct aspects.
    """
    retriever = index.as_retriever(
        vector_store_query_mode="hybrid",
        similarity_top_k=similarity_top_k,
    )
    seen_node_ids = set()
    unique_chunks = []
    for query in RETRIEVAL_QUERIES_FOR_SUMMARIZATION:
        for node_with_score in retriever.retrieve(query):
            if node_with_score.node_id not in seen_node_ids:
                seen_node_ids.add(node_with_score.node_id)
                unique_chunks.append(node_with_score.text)
    return unique_chunks


def retrieve_chunks_with_query_expansion(
    index: VectorStoreIndex,
    query_expansion_llm,
    similarity_top_k: int = 10,
) -> list[str]:
    """
    For each of the 9 queries, generate 4 LLM variants and fuse results via reciprocal rank.

    Per-query expansion preserves each query's topical focus — a single global expansion
    would mix all 9 topics and lose section-level targeting.

    use_async=False is required: local Qdrant file mode uses portalocker to prevent
    concurrent writes. Async retrieval would open multiple file handles simultaneously,
    causing lock contention. Sequential execution adds ~2-4s per paper vs async,
    with no effect on metric values.
    """
    base_retriever = index.as_retriever(
        vector_store_query_mode="hybrid",
        similarity_top_k=similarity_top_k,
    )
    seen_node_ids = set()
    unique_chunks = []
    for query in RETRIEVAL_QUERIES_FOR_SUMMARIZATION:
        fusion_retriever = QueryFusionRetriever(
            [base_retriever],
            num_queries=4,
            mode="reciprocal_rerank",
            use_async=False,  # local Qdrant file mode cannot handle concurrent async client access
            llm=query_expansion_llm,
        )
        for node_with_score in fusion_retriever.retrieve(query):
            if node_with_score.node_id not in seen_node_ids:
                seen_node_ids.add(node_with_score.node_id)
                unique_chunks.append(node_with_score.text)
    return unique_chunks


# ── Summarization — VLM path and RAG path ─────────────────────────────────────────────────────

def _count_output_tokens(resp) -> int:
    """Get output token count — prefer API-reported count, fall back to tiktoken estimate."""
    try:
        return resp.raw.usage.completion_tokens  # resp.raw is a typed object, not a dict
    except AttributeError:
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(resp.text))


# Ollama's local HTTP server has a hardcoded 16 MB request body limit.
# At DPI=200, each page is ~0.89 MB base64-encoded, so 19+ pages exceed the limit.
# Fix: split pages into chunks of MAX_VLM_PAGES_PER_CHUNK, summarize each chunk
# separately, then merge the partial summaries with a text-only LLM call.
MAX_VLM_PAGES_PER_CHUNK = 15  # 15 pages × 0.89 MB ≈ 13.4 MB — safe margin under 16 MB limit

def summarize_paper_with_vlm(pdf_path: Path, vlm_model, merge_llm, max_pages_per_chunk: int = 15, dpi: int = 200) -> tuple[str, float, int]:
    """
    Summarize a PDF by passing page images to the VLM.

    For papers with more than MAX_VLM_PAGES_PER_CHUNK pages, the PDF is split into
    page-range batches. Each batch is sent to the VLM independently, then the
    partial summaries are merged into a final summary via a text-only LLM call.

    This is required because Ollama 0.30.x has a hardcoded 16 MB HTTP body limit —
    sending all pages of a 48-page paper at DPI=200 would produce a ~42 MB request.

    Returns (summary_text, latency_seconds, output_token_count).
    """
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp_image_dir:
        all_page_files = sorted(pdf2images(pdf_path, Path(tmp_image_dir), dpi=dpi))
        total_pages = len(all_page_files)

        if total_pages <= max_pages_per_chunk:
            # Short paper: single VLM call, no chunking needed
            image_documents = [ImageDocument(image_path=f) for f in all_page_files]
            response = vlm_model.complete(
                prompt=SUMMARIZE_PAPER_PMT, image_documents=image_documents
            )
            latency_seconds = time.perf_counter() - t0
            return response.text, latency_seconds, _count_output_tokens(response)

        # Long paper: split into chunks, summarize each, then merge
        page_chunks = [
            all_page_files[i:i + max_pages_per_chunk]
            for i in range(0, total_pages, max_pages_per_chunk)
        ]
        partial_summaries = []
        for chunk_idx, chunk_files in enumerate(page_chunks):
            page_start = chunk_idx * max_pages_per_chunk + 1
            page_end = page_start + len(chunk_files) - 1
            image_documents = [ImageDocument(image_path=f) for f in chunk_files]
            chunk_prompt = (
                f"This is pages {page_start}–{page_end} of a {total_pages}-page ML research paper. "
                f"Summarize the key content from these pages only. "
                f"Focus on methods, results, datasets, and findings visible in these pages."
            )
            resp = vlm_model.complete(prompt=chunk_prompt, image_documents=image_documents)
            partial_summaries.append(
                f"[Pages {page_start}–{page_end}]\n{resp.text}"
            )

    # Merge partial summaries with a text-only LLM call (no images needed)
    merged_context = "\n\n---\n\n".join(partial_summaries)
    merge_prompt = (
        SUMMARIZE_PAPER_PMT
        + "\n\nBelow are partial summaries of different page ranges from the same paper. "
        "Synthesize them into a single coherent summary following the structure above.\n\n"
        + merged_context
    )
    final_response = merge_llm.complete(merge_prompt)
    latency_seconds = time.perf_counter() - t0
    return final_response.text, latency_seconds, _count_output_tokens(final_response)


def generate_rag_summary_from_chunks(chunks: list[str], rag_llm) -> tuple[str, int]:
    """Concatenate retrieved chunks as context and generate summary with SUMMARIZE_PAPER_PMT."""
    context_text = "\n\n---\n\n".join(chunks)
    response = rag_llm.complete(SUMMARIZE_PAPER_PMT + f"\n\n{context_text}")
    return response.text, _count_output_tokens(response)


# ── Summary resume logic — skip papers already summarized ────────────────────────────────────

def is_summary_already_done(config_name: str, paper_id: str) -> bool:
    """Return True if a non-empty summary file already exists for this config+paper."""
    summary_path = SUMMARIES_DIR / config_name / f"{paper_id}.txt"
    return summary_path.exists() and summary_path.stat().st_size > 0


def save_summary_to_disk(config_name: str, paper_id: str, summary_text: str) -> None:
    """Atomically write summary to disk using tmp-then-rename to avoid partial writes."""
    output_dir = SUMMARIES_DIR / config_name
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = output_dir / f"{paper_id}.tmp"
    tmp_path.write_text(summary_text, encoding="utf-8")
    tmp_path.rename(output_dir / f"{paper_id}.txt")


# ── Model initialization — called once at script start ───────────────────────────────────────

def initialize_models():
    """Initialize all models used in this experiment. Called once at script start."""
    embed_model = LiteLLMEmbedding(
        model_name="ollama/nomic-embed-text",
        embed_batch_size=32,  # 3x fewer Ollama HTTP round-trips vs default batch_size=10
    )
    vlm_model = LiteLLMMultiModal(
        model="ollama/gemma4:31b-cloud",
        max_tokens=4096,
        temperature=0.0,
        additional_kwargs={"num_ctx": 262144},  # 256k context: 48 pages × ~1500 visual tokens ≈ 72k
    )
    rag_llm = LiteLLM(
        model="ollama/gemma4:31b-cloud",
        max_tokens=4096,
        temperature=0.0,
        additional_kwargs={"num_ctx": 262144},
    )
    # Same model for VLM and RAG paths — only input modality differs, not model capability.
    # Separate variable for clarity and to allow swapping one path independently.
    query_expansion_llm = LiteLLM(
        model="ollama/qwen3.5:cloud",
        temperature=0.0,
        additional_kwargs={"think": False, "num_ctx": 262144},
    )
    return embed_model, vlm_model, rag_llm, query_expansion_llm


# ── CLI entry point ────────────────────────────────────────────────────────────────────────────

@click.command()
@click.option(
    "--config",
    type=click.Choice(["vlm", "rag_fixed_queries", "rag_with_expansion", "rag_winner_no_filter"]),
    default=None,
    help="Run only this config. Default: run all configs in order.",
)
@click.option("--paper", default=None, help="Run only this paper ID, e.g. 1608.06993")
@click.option("--index-only", is_flag=True, help="Build Qdrant indexes only, skip summarization.")
@click.option("--rebuild-index", is_flag=True, help="Force rebuild Qdrant index even if it exists.")
@click.option("--vlm-pages-per-chunk", default=15, type=int,
              help="Max PDF pages per VLM call. Reduce for math/table-heavy papers. Default: 15.")
@click.option("--vlm-dpi", default=200, type=click.IntRange(50, 200),
              help="DPI for PDF-to-image conversion in VLM path. Range: 50–200. Default: 200.")
@click.option("--query-expansion", is_flag=True, default=False,
              help="Enable query expansion via QueryFusionRetriever. Default: off.")
def main(config, paper, index_only, rebuild_index, vlm_pages_per_chunk, vlm_dpi, query_expansion):
    logger = ExperimentLogger("summarization_comparison")
    corpus = PaperCorpus()
    embed_model, vlm_model, rag_llm, query_expansion_llm = initialize_models()

    # ChunkFilter removes boilerplate sections (References, Acknowledgements, page headers)
    # before indexing. Config file defines exact heading matches and keyword substrings to skip.
    chunk_filter_for_rag = ChunkFilter(
        config_path=Path("poc/rag-filtering/filter_config.json")
    )

    # One QdrantClient per directory for the entire run.
    # Local Qdrant uses portalocker (exclusive file lock) — only one client per directory allowed.
    # Creating a new client per paper would crash on the second paper (lock already held).
    QDRANT_DIR_WITH_CHUNK_FILTER.mkdir(parents=True, exist_ok=True)
    QDRANT_DIR_WITHOUT_CHUNK_FILTER.mkdir(parents=True, exist_ok=True)
    qdrant_client_with_filter = QdrantClient(path=str(QDRANT_DIR_WITH_CHUNK_FILTER))
    qdrant_client_no_filter   = QdrantClient(path=str(QDRANT_DIR_WITHOUT_CHUNK_FILTER))

    configs_to_run = [c for c in SUMMARIZATION_EXPERIMENT_CONFIGS if config is None or c.name == config]
    for cfg in configs_to_run:
        cfg.use_query_expansion = query_expansion
    papers_to_run = [paper] if paper else PAPER_IDS_FOR_SUMMARIZATION_COMPARISON

    logger.header(
        vlm="gemma4:31b-cloud",
        rag_llm="gemma4:31b-cloud",
        query_expansion="qwen3.5:cloud",
        corpus=f"{len(papers_to_run)} papers",
    )

    for exp_config in configs_to_run:
        for paper_id in papers_to_run:
            # ── Index phase: build or load Qdrant index for RAG configs ──────────────────
            if not exp_config.use_vlm:
                qdrant_client = (
                    qdrant_client_with_filter
                    if exp_config.apply_chunk_filter
                    else qdrant_client_no_filter
                )
                chunk_filter = chunk_filter_for_rag if exp_config.apply_chunk_filter else None
                index, chunk_count = get_or_build_paper_index(
                    paper_id, exp_config, corpus, qdrant_client, embed_model, chunk_filter, rebuild_index
                )
                if chunk_count is not None:
                    print(f"[INDEX] config={exp_config.name} | paper={paper_id} | chunks={chunk_count}")
                else:
                    print(f"[INDEX] config={exp_config.name} | paper={paper_id} | loaded_from_disk=True")

            if index_only:
                continue

            # ── Summarization phase ───────────────────────────────────────────────────────
            if is_summary_already_done(exp_config.name, paper_id):
                logger.skip(config=exp_config.name, paper=paper_id, reason="already_done")
                continue

            t0 = time.perf_counter()
            try:
                if exp_config.use_vlm:
                    pdf_path = corpus.PDF_DIR / f"{paper_id}.pdf"
                    summary, latency, output_tokens = summarize_paper_with_vlm(pdf_path, vlm_model, rag_llm, vlm_pages_per_chunk, dpi=vlm_dpi)
                    retrieved_chunk_count = None
                    context_tokens = None
                else:
                    if exp_config.use_query_expansion:
                        chunks = retrieve_chunks_with_query_expansion(index, query_expansion_llm)
                    else:
                        chunks = retrieve_chunks_fixed_queries(index)
                    retrieved_chunk_count = len(chunks)
                    context_text = "\n\n---\n\n".join(chunks)
                    context_tokens = len(tiktoken.get_encoding("cl100k_base").encode(context_text))
                    summary, output_tokens = generate_rag_summary_from_chunks(chunks, rag_llm)
                    latency = time.perf_counter() - t0

                save_summary_to_disk(exp_config.name, paper_id, summary)

                log_kwargs = dict(
                    config=exp_config.name,
                    paper=paper_id,
                    output_tokens=output_tokens,
                    latency_s=round(latency, 1),
                )
                if retrieved_chunk_count is not None:
                    log_kwargs["retrieved_chunk_count"] = retrieved_chunk_count
                    log_kwargs["context_tokens"] = context_tokens
                logger.result(**log_kwargs)

            except Exception as e:
                logger.error(config=exp_config.name, paper=paper_id, stage="summarize", msg=str(e))

    logger.end()


if __name__ == "__main__":
    main()
