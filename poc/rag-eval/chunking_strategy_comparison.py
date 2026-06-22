"""Compare 5 chunking strategies on 28 ML papers using fixed dense-only retrieval
to select the best chunking approach for the retrieval strategy experiment.

Each strategy produces different chunk boundaries and sizes, which directly affects
whether a ground-truth passage lands in a single retrievable chunk or gets split
across boundaries.

Fixed conditions (to isolate chunking as the only variable):
  - Retrieval: dense-only, nomic-embed-text, similarity_top_k=10
  - Evaluation: Recall@5 and nDCG@5 on 112 positive GT samples
  - No LLM calls

Chunking strategies compared (5 total):
  1. sentence_splitter_default      — LlamaIndex default SentenceSplitter (baseline)
  2. semantic_splitter              — SemanticSplitterNodeParser (embedding-based boundaries)
  3. markdown_element_splitter      — MarkdownElementNodeParser (table-aware, llm=None)
  4. docling_hybrid_chunker_512     — Docling HybridChunker with 512-token limit
  5. docling_hierarchical_chunker   — Docling HierarchicalChunker (section hierarchy)

Run from repo root (research-agent-docling-rag-pipeline/):

    # Fresh run (overwrites log):
    micromamba run -n py3.12 python poc/rag-eval/chunking_strategy_comparison.py 2>&1 | tee poc/rag-eval/chunking_strategy_comparison.log

    # Resume from a strategy (appends to existing log):
    micromamba run -n py3.12 python poc/rag-eval/chunking_strategy_comparison.py --start-from docling_hybrid_chunker_512 2>&1 >> poc/rag-eval/chunking_strategy_comparison.log

Output: [WINNER] line in chunking_strategy_comparison.log
"""
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import click

sys.path.insert(0, ".")        # repo root — poc.poc_base
sys.path.insert(0, "backend") # backend imports

from docling.chunking import HybridChunker
from docling_core.types.doc import DoclingDocument
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.node_parser import (
    SentenceSplitter,
    SemanticSplitterNodeParser,
)
from llama_index.core.node_parser.relational.markdown_element import MarkdownElementNodeParser
from llama_index.core.schema import Document
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.embeddings.litellm import LiteLLMEmbedding
from llama_index.llms.litellm import LiteLLM
from llama_index.vector_stores.qdrant import QdrantVectorStore
from poc.poc_base import (
    ContextualDoclingNodeParser,
    ExperimentLogger,
    MetricsCalculator,
    PaperCorpus,
)
from qdrant_client import QdrantClient
from services.docling_chunker import DoclingChunker
from tools.filter_tools import ChunkFilter
import unicodedata
from transformers import AutoTokenizer

# bert-base-uncased is the tokenizer used internally by nomic-embed-text.
# Loading it here lets us pre-check BERT token counts before sending to Ollama,
# preventing HTTP 400 errors when a node exceeds the 2048 BERT token limit.
# Only tokenizer config files (~700 KB) are downloaded, not model weights.
BERT_TOKENIZER = AutoTokenizer.from_pretrained("bert-base-uncased")
BERT_MAX_TOKENS = 1900  # 2048 hard limit − 2 (CLS/SEP) − 7% buffer for GGUF tokenizer drift

# MarkdownElementNodeParser uses an LLM to summarize tables into natural language.
# The default LlamaIndex prompt asks for a "very concise summary" which loses all
# specific numbers — bad for Factual and Keyword-heavy retrieval queries.
# This prompt explicitly instructs the model to preserve every numeric value.
RETRIEVAL_TABLE_SUMMARY_PROMPT = (
    "Summarize this table for document retrieval. Preserve ALL specific values "
    "without exception: every number, percentage, model name, dataset name, "
    "benchmark score, and metric value mentioned in the table. "
    "Write in natural language sentences. Do not omit any numeric value or proper noun."
)

# Populated in main() after all imports are resolved — see build_chunking_strategies()
CHUNKING_STRATEGIES: list[tuple[str, object]] = []

TOP_K_RETRIEVE = 10
EVAL_K = 5


def truncate_to_bert_limit(text: str) -> str:
    """Normalize and truncate text to fit within nomic-embed-text's 2048 BERT token limit.

    Two-step approach required because HuggingFace bert-base-uncased and Ollama's
    GGUF build of nomic-embed-text tokenize some Unicode characters differently —
    e.g. U+2026 (…) counts as 1 token in HuggingFace but 2 tokens in GGUF.

    Step 1 — NFKC normalization: converts Unicode compatibility characters to their
    ASCII equivalents before tokenizing (e.g. … → ..., ﬁ → fi). Both tokenizers
    agree on ASCII, so this eliminates the cross-tokenizer mismatch.

    Step 2 — Truncate to 1900 tokens: BERT_MAX_TOKENS=1900 provides a 7% buffer
    below the 2048 hard limit to absorb any residual GGUF tokenizer drift for
    characters not covered by NFKC (e.g. certain Devanagari combining marks).
    """
    text = unicodedata.normalize("NFKC", text)
    ids = BERT_TOKENIZER.encode(text, add_special_tokens=False)
    if len(ids) <= BERT_MAX_TOKENS:
        return text
    return BERT_TOKENIZER.decode(ids[:BERT_MAX_TOKENS], skip_special_tokens=True)


from llama_index.core.bridge.pydantic import PrivateAttr


class TruncatingEmbeddingWrapper(BaseEmbedding):
    """Wraps LiteLLMEmbedding and applies truncate_to_bert_limit() before every embed call.

    Needed for SemanticSplitterNodeParser, which calls get_text_embedding_batch()
    internally during chunking to detect semantic boundaries. Individual "sentences"
    from Docling's markdown output (e.g. full markdown tables) can exceed BERT_MAX_TOKENS.
    Without this wrapper those texts crash Ollama with HTTP 400 inside SemanticSplitter's
    call stack, before our explicit embedding loop has a chance to truncate them.

    The other 4 strategies (SentenceSplitter, MarkdownElementNodeParser, both Docling
    parsers) do not call embed_model during chunking, so they do not need this wrapper.
    """

    _inner: Any = PrivateAttr()

    def __init__(self, inner: LiteLLMEmbedding):
        super().__init__(model_name=inner.model_name)
        self._inner = inner

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._inner._get_text_embedding(truncate_to_bert_limit(text))

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return self._inner._get_text_embeddings(
            [truncate_to_bert_limit(t) for t in texts]
        )

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._inner._get_query_embedding(truncate_to_bert_limit(query))

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return await self._inner._aget_query_embedding(truncate_to_bert_limit(query))

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return await self._inner._aget_text_embedding(truncate_to_bert_limit(text))


def build_dense_index(
    paper_id: str,
    nodes: list,
    embed_model: LiteLLMEmbedding,
) -> VectorStoreIndex:
    """Build a fresh in-memory Qdrant index for one paper using dense-only retrieval.

    A new QdrantClient(":memory:") is created per call so each paper gets an isolated
    collection with no cross-paper contamination.
    """
    client = QdrantClient(":memory:")
    vector_store = QdrantVectorStore(
        client=client,
        collection_name=paper_id,
    )
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    return VectorStoreIndex(
        nodes=nodes,
        storage_context=storage_context,
        embed_model=embed_model,
    )


def build_chunking_strategies(
    chunk_filter: ChunkFilter,
    embed_model: LiteLLMEmbedding,
) -> list[tuple[str, object]]:
    """Construct the 5 chunking strategies to compare.

    The baseline SentenceSplitter uses LlamaIndex defaults. SemanticSplitterNodeParser
    adaptively determines chunk boundaries using embedding similarity rather than fixed
    token counts. MarkdownElementNodeParser is table-aware and parses markdown structure
    without an LLM. Docling-based parsers additionally leverage document structure
    (headings, section hierarchy) which plain text splitters cannot access.
    """
    tokenizer_512 = DoclingChunker._TokenizerAdapter(max_tokens=512)
    return [
        (
            "sentence_splitter_default",
            SentenceSplitter(),
        ),
        (
            "semantic_splitter",
            SemanticSplitterNodeParser(
                embed_model=TruncatingEmbeddingWrapper(embed_model),
                buffer_size=1,
                breakpoint_percentile_threshold=95,
            ),
        ),
        (
            "markdown_element_splitter",
            MarkdownElementNodeParser(
                llm=LiteLLM(model="ollama/ministral-3:14b-cloud"),
                summary_query_str=RETRIEVAL_TABLE_SUMMARY_PROMPT,
            ),
        ),
        (
            "docling_hierarchical_chunker",
            ContextualDoclingNodeParser(chunk_filter=chunk_filter),
        ),
        (
            "docling_hybrid_chunker_512",
            ContextualDoclingNodeParser(
                chunker=HybridChunker(tokenizer=tokenizer_512),
                chunk_filter=chunk_filter,
            ),
        ),
        (
            "docling_hybrid_chunker_512_no_context",
            ContextualDoclingNodeParser(
                chunker=HybridChunker(tokenizer=tokenizer_512),
                chunk_filter=chunk_filter,
                use_contextualize=False,
            ),
        ),
        (
            "docling_hybrid_chunker_512_prose_embed",
            ContextualDoclingNodeParser(
                chunker=HybridChunker(tokenizer=tokenizer_512),
                chunk_filter=chunk_filter,
                use_contextualize=True,
                prose_only_embed=True,
            ),
        ),
    ]


def load_scores_from_log(
    log_path: Path,
    strategy_names: list[str],
) -> tuple[dict, dict, dict]:
    """Parse completed [RESULT] lines from an existing log to restore scores.

    Returns (scores, chunk_counts, latency) dicts pre-populated for the given
    strategy names. latency cannot be recovered from [RESULT] lines so it is
    set to 0.0 for all loaded strategies.

    Called when --start-from is used so the final [SUMMARY] and [WINNER] include
    all strategies, not just the ones run in the current session.
    """
    from collections import defaultdict

    scores: dict[str, dict[str, list[tuple[float, float]]]] = {
        name: defaultdict(list) for name in strategy_names
    }
    chunk_counts: dict[str, list[int]] = {name: [] for name in strategy_names}
    latency: dict[str, float] = {name: 0.0 for name in strategy_names}

    # Track (paper, strategy) pairs to avoid double-counting chunk_count
    seen_paper_strategy: set[tuple[str, str]] = set()

    if not log_path.exists():
        return scores, chunk_counts, latency

    for line in log_path.read_text().splitlines():
        if not line.startswith("[RESULT]"):
            continue
        kv = dict(
            p.split("=", 1) for p in line[len("[RESULT] "):].split(" | ") if "=" in p
        )
        if "recall5" not in kv:
            continue
        strategy = kv.get("strategy")
        if strategy not in strategy_names:
            continue
        query_type = kv.get("query_type")
        recall5 = float(kv["recall5"])
        ndcg5 = float(kv["ndcg5"])
        scores[strategy][query_type].append((recall5, ndcg5))
        scores[strategy]["ALL"].append((recall5, ndcg5))

        paper = kv.get("paper", "")
        pair = (paper, strategy)
        if pair not in seen_paper_strategy and "chunk_count" in kv:
            chunk_counts[strategy].append(int(kv["chunk_count"]))
            seen_paper_strategy.add(pair)

    return scores, chunk_counts, latency


@click.command()
@click.option(
    "--start-from",
    default=None,
    help=(
        "Resume from this strategy name, skipping all strategies before it. "
        "Already-completed results are loaded from the existing log file. "
        "Valid values: sentence_splitter_default | semantic_splitter | "
        "markdown_element_splitter | docling_hybrid_chunker_512 | docling_hierarchical_chunker"
    ),
)
def main(start_from: str | None):
    logger = ExperimentLogger("chunking_strategy_comparison")
    corpus = PaperCorpus()

    # ── Setup filter and embed model ──────────────────────────────────────────
    chunk_filter = ChunkFilter(
        config_path=Path("poc/rag-filtering/filter_config.json")
    )

    # LiteLLMEmbedding uses the ollama/ prefix path — do not substitute OllamaEmbedding,
    # which uses a different internal request path and is not consistent with production.
    embed_model = LiteLLMEmbedding(
        model_name="ollama/nomic-embed-text",
        embed_batch_size=32,
    )

    # ── Load corpus + ground-truth dataset ───────────────────────────────────
    paper_ids = corpus.paper_ids()
    gt_samples = corpus.load_gt(exclude_negative=True)

    # ── Build strategy list after imports are resolved ────────────────────────
    global CHUNKING_STRATEGIES
    CHUNKING_STRATEGIES = build_chunking_strategies(chunk_filter, embed_model)

    logger.header(
        embed="ollama/nomic-embed-text",
        strategies=len(CHUNKING_STRATEGIES),
        retrieve_k=TOP_K_RETRIEVE,
        eval_k=EVAL_K,
    )
    print(f"[CORPUS] {len(paper_ids)} papers, {len(gt_samples)} positive GT samples")

    # ── Per-strategy metrics accumulator ─────────────────────────────────────
    # strategy_name → query_type → [recall5, ndcg5] pairs
    scores: dict[str, dict[str, list[tuple[float, float]]]] = {
        strategy_name: defaultdict(list)
        for strategy_name, _ in CHUNKING_STRATEGIES
    }
    latency: dict[str, float] = {
        strategy_name: 0.0 for strategy_name, _ in CHUNKING_STRATEGIES
    }
    # strategy_name → list of chunk counts per paper (to compute average)
    chunk_counts: dict[str, list[int]] = {
        strategy_name: [] for strategy_name, _ in CHUNKING_STRATEGIES
    }

    # ── Determine which strategies to run ────────────────────────────────────
    strategy_names = [name for name, _ in CHUNKING_STRATEGIES]
    if start_from is not None:
        if start_from not in strategy_names:
            print(f"[ERROR] Unknown strategy '{start_from}'. Valid: {strategy_names}")
            sys.exit(1)
        start_idx = strategy_names.index(start_from)
        strategies_to_skip = strategy_names[:start_idx]
        strategies_to_run = CHUNKING_STRATEGIES[start_idx:]
        print(f"[RESUME] Skipping {strategies_to_skip}, starting from '{start_from}'")

        # Load existing results for skipped strategies
        log_path = Path("poc/rag-eval/chunking_strategy_comparison.log")
        loaded_scores, loaded_chunks, loaded_latency = load_scores_from_log(
            log_path, strategies_to_skip
        )
        # Pre-populate accumulators
        for name in strategies_to_skip:
            scores[name] = loaded_scores[name]
            chunk_counts[name] = loaded_chunks[name]
            latency[name] = loaded_latency[name]
        print(f"[RESUME] Loaded results for: {strategies_to_skip}")
    else:
        strategies_to_run = CHUNKING_STRATEGIES

    # ── Main evaluation loop — one pass per chunking strategy ─────────────────
    for strategy_name, node_parser in strategies_to_run:
        print(f"\n[PHASE] Evaluating strategy={strategy_name}")
        t_strategy_start = time.perf_counter()

        # Group GT samples by paper so the index is built once per paper
        samples_by_paper: dict[str, list[dict]] = defaultdict(list)
        for sample in gt_samples:
            samples_by_paper[sample["paper_id"]].append(sample)

        for paper_id, paper_samples in samples_by_paper.items():
            json_path = corpus.PARSED_DIR / f"{paper_id}.json"
            if not json_path.exists():
                logger.error(
                    paper=paper_id,
                    strategy=strategy_name,
                    stage="load",
                    msg="parsed JSON not found; run phase0_parse.py first",
                )
                continue

            dl_doc = DoclingDocument.model_validate(
                json.loads(json_path.read_text())
            )
            # ContextualDoclingNodeParser reconstructs DoclingDocument from JSON internally.
            # All other parsers (SentenceSplitter, SemanticSplitterNodeParser,
            # MarkdownElementNodeParser) are plain-text parsers and receive markdown.
            if isinstance(node_parser, ContextualDoclingNodeParser):
                li_doc = Document(
                    text=dl_doc.model_dump_json(),
                    metadata={"paper_id": paper_id},
                )
            else:
                li_doc = Document(
                    text=dl_doc.export_to_markdown(),
                    metadata={"paper_id": paper_id},
                )

            # MarkdownElementNodeParser returns TextNode (prose) and IndexNode (tables).
            # IndexNode is a TextNode subclass — node.text and node.node_id work on both.
            t_chunk_start = time.perf_counter()
            nodes = [n for n in node_parser.get_nodes_from_documents([li_doc]) if n.text.strip()]
            chunk_latency_s = time.perf_counter() - t_chunk_start

            if not nodes:
                logger.error(
                    paper=paper_id,
                    strategy=strategy_name,
                    stage="chunk",
                    msg=f"no nodes produced (chunk_latency_s={chunk_latency_s:.2f})",
                )
                continue

            chunk_counts[strategy_name].append(len(nodes))

            # Pre-compute dense embeddings once — VectorStoreIndex skips re-embedding
            # when node.embedding is already populated.
            for node in nodes:
                text_to_embed = truncate_to_bert_limit(
                    node.metadata.get("_embed_text", node.text)
                )
                if text_to_embed != node.text:
                    logger.result(
                        paper=paper_id,
                        strategy=strategy_name,
                        event="truncated",
                        original_bert_tokens=len(BERT_TOKENIZER.encode(node.text, add_special_tokens=False)),
                        truncated_to=BERT_MAX_TOKENS,
                    )
                node.embedding = embed_model.get_text_embedding(text_to_embed)

            try:
                index = build_dense_index(paper_id, nodes, embed_model)
            except Exception as exc:
                logger.error(
                    paper=paper_id,
                    strategy=strategy_name,
                    stage="index_build",
                    msg=str(exc),
                )
                for sample in paper_samples:
                    logger.skip(
                        paper=paper_id,
                        strategy=strategy_name,
                        reason="index_build_failed",
                    )
                continue

            retriever = index.as_retriever(similarity_top_k=TOP_K_RETRIEVE)

            for sample in paper_samples:
                query_type = sample.get("query_type", "Unknown")

                # Pass the nodes list directly — docstore is always empty with
                # QdrantVectorStore (known Issue #6), so iterating docstore would
                # yield zero relevant IDs for every query.
                relevant_ids = MetricsCalculator.find_relevant_ids(
                    nodes, sample["gt_passages"]
                )

                if not relevant_ids:
                    logger.skip(
                        paper=paper_id,
                        strategy=strategy_name,
                        reason="no_relevant_ids_found",
                    )
                    continue

                try:
                    retrieved = retriever.retrieve(sample["query"])
                except Exception as exc:
                    logger.error(
                        paper=paper_id,
                        strategy=strategy_name,
                        stage="retrieve",
                        msg=str(exc),
                    )
                    continue

                retrieved_ids = [n.node_id for n in retrieved[:EVAL_K]]
                recall5 = MetricsCalculator.recall_at_k(
                    retrieved_ids, relevant_ids, k=EVAL_K
                )
                ndcg5 = MetricsCalculator.ndcg_at_k(
                    retrieved_ids, relevant_ids, k=EVAL_K
                )

                if recall5 is None or ndcg5 is None:
                    logger.skip(
                        paper=paper_id,
                        strategy=strategy_name,
                        reason="metrics_returned_none",
                    )
                    continue

                scores[strategy_name][query_type].append((recall5, ndcg5))
                scores[strategy_name]["ALL"].append((recall5, ndcg5))

                logger.result(
                    paper=paper_id,
                    strategy=strategy_name,
                    query_type=query_type,
                    recall5=f"{recall5:.3f}",
                    ndcg5=f"{ndcg5:.3f}",
                    chunk_count=len(nodes),
                )

        latency[strategy_name] = time.perf_counter() - t_strategy_start

    # ── Per-strategy summary ──────────────────────────────────────────────────
    strategy_agg: dict[str, dict[str, float]] = {}

    for strategy_name, _ in CHUNKING_STRATEGIES:
        strategy_scores = scores[strategy_name]
        query_types = [qt for qt in strategy_scores if qt != "ALL"]

        for qt in sorted(query_types):
            pairs = strategy_scores[qt]
            if pairs:
                mean_recall = sum(r for r, _ in pairs) / len(pairs)
                mean_ndcg = sum(d for _, d in pairs) / len(pairs)
                logger.summary(
                    strategy=strategy_name,
                    query_type=qt,
                    recall5=f"{mean_recall:.2f}",
                    ndcg5=f"{mean_ndcg:.2f}",
                    n=len(pairs),
                )

        all_pairs = strategy_scores.get("ALL", [])
        counts = chunk_counts[strategy_name]
        avg_chunks = sum(counts) / len(counts) if counts else 0.0

        if all_pairs:
            mean_recall_all = sum(r for r, _ in all_pairs) / len(all_pairs)
            mean_ndcg_all = sum(d for _, d in all_pairs) / len(all_pairs)
            logger.summary(
                strategy=strategy_name,
                query_type="ALL",
                recall5=f"{mean_recall_all:.2f}",
                ndcg5=f"{mean_ndcg_all:.2f}",
                n=len(all_pairs),
                latency_s=f"{latency[strategy_name]:.1f}",
                avg_chunks_per_paper=f"{avg_chunks:.1f}",
            )
            strategy_agg[strategy_name] = {
                "recall5": mean_recall_all,
                "ndcg5": mean_ndcg_all,
            }
        else:
            strategy_agg[strategy_name] = {"recall5": 0.0, "ndcg5": 0.0}

    # ── Winner selection ──────────────────────────────────────────────────────
    if strategy_agg:
        winner_strategy = max(
            strategy_agg, key=lambda s: strategy_agg[s]["recall5"]
        )
        winner_recall = strategy_agg[winner_strategy]["recall5"]
        winner_ndcg = strategy_agg[winner_strategy]["ndcg5"]

        logger.winner(
            strategy=winner_strategy,
            recall5=f"{winner_recall:.2f}",
            ndcg5=f"{winner_ndcg:.2f}",
        )

    logger.end()


if __name__ == "__main__":
    main()  # click handles argument parsing
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
