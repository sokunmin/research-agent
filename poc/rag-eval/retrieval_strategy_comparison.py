import os
os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
# Must be set before PyTorch or any ML library loads.
# bge-reranker-large uses ops not natively supported on Apple M1 MPS;
# this env var causes those ops to fall back to CPU automatically.

# ragas 0.4.x imports ChatVertexAI at module level in ragas/llms/base.py even when
# only LlamaIndex is used. langchain-community 0.4.x removed vertexai from chat_models.
# These stubs prevent the ImportError. ChatVertexAI/VertexAI are only referenced in a
# type-check list inside ragas and are never actually instantiated in LlamaIndex workflows.
import sys
import types as _types
_vx = _types.ModuleType("langchain_community.chat_models.vertexai")
_vx.ChatVertexAI = type("ChatVertexAI", (), {})
sys.modules["langchain_community.chat_models.vertexai"] = _vx
_vx2 = _types.ModuleType("langchain_community.llms.vertexai")
_vx2.VertexAI = type("VertexAI", (), {})
sys.modules["langchain_community.llms.vertexai"] = _vx2

import nest_asyncio
nest_asyncio.apply()
# QueryFusionRetriever uses asyncio internally. Without this, Python raises
# RuntimeError when an async call is made inside an already-running event loop.

"""Retrieval Strategy Comparison — RAG Pipeline Experiment

This experiment compares 6 retrieval configurations to find the best retrieval
mechanism for an ML paper summarization pipeline. The pipeline takes PDF papers,
chunks them into text segments, stores them in a vector database (Qdrant), and
retrieves relevant segments to answer queries or generate summaries.

WHAT WE ARE COMPARING

Six retrieval configurations are evaluated. Each differs in one or more of three
independently togglable mechanisms:

  1. BM25 hybrid retrieval (use_hybrid_bm25):
       Adds sparse keyword matching (BM25) on top of dense vector similarity.
       BM25 is a statistical algorithm that scores documents by term frequency —
       no neural network, purely lexical. It improves recall for Factual and
       Keyword-heavy queries where exact term matching outperforms semantic similarity
       (e.g. querying for "BLEU score" with BM25 finds chunks containing "BLEU" directly).

  2. Query expansion with RRF fusion (num_query_variants=4):
       An LLM generates 3 additional alternative phrasings of the user's query.
       All 4 queries are run independently, and the results are merged using
       Reciprocal Rank Fusion (RRF) — a score that combines rankings across queries.
       Improves recall when the user's phrasing differs from the document's wording
       (e.g. user asks "accuracy" but paper says "top-1 error rate").
       num_query_variants=1 means no LLM is called — the original query is used directly.

  3. Cross-encoder reranking (use_reranker):
       After retrieving 10 candidate chunks, a bge-reranker-large cross-encoder
       re-scores all 10 and returns the top 5. Unlike dense retrieval (which scores
       query and chunk independently via dot product), a cross-encoder concatenates
       query + chunk and scores them jointly. This is slower but more precise.

The 6 configs are arranged so each mechanism can be isolated:
  BM25 effect:              dense_only vs hybrid_bm25 (same query count, no reranker)
  Query expansion effect:   dense_only vs dense_with_query_expansion (no BM25, no reranker)
  Reranker effect:          hybrid_bm25 vs hybrid_bm25_with_reranker (same query count)
  Full stack:               hybrid_bm25_query_expansion_and_reranker combines all three

FIXED CONDITIONS

The following are held constant across all 6 configs, having been selected by prior
experiments on the same 28-paper corpus:

  - Chunking strategy: docling_hybrid_chunker_512
      Selected by comparing 7 chunking strategies (sentence splitter, semantic splitter,
      markdown element parser, Docling hierarchical, Docling hybrid 512-token) on 28 ML
      papers using dense-only retrieval. docling_hybrid_chunker_512 achieved the best
      Recall@5=0.61. It uses Docling's structure-aware HybridChunker with a 512-token
      limit and prepends the section heading path to each chunk for context.

  - Sparse model: Qdrant/bm25 (BM25)
      Selected by comparing BM25, miniCOIL, and SPLADE sparse models on the same corpus.
      BM25 achieved Recall@5=0.78. miniCOIL matched BM25 in recall (0.76) but was 15x
      slower (204s vs 13.5s). SPLADE achieved 0.70. BM25 was selected for the best
      recall-to-latency ratio.

  - Embedding model: ollama/nomic-embed-text (768-dimensional dense vectors)
  - Corpus: 28 ML research papers, parsed by Docling

GROUND-TRUTH DATASET

140 samples total across 28 papers (5 per paper):
  - 112 positive (answerable) samples: each has gt_passages (relevant text spans) and
    gt_answer (reference answer). These are the samples evaluated in this experiment.
  -  28 negative (unanswerable) samples: skipped because Recall/nDCG are mathematically
     undefined when there are no ground-truth passages, and RAGAS requires a reference
     answer which negative samples do not have.

METRICS

For each of the 112 positive samples, five metrics are computed:

  Recall@5:          Fraction of relevant chunks found in the top 5 retrieved results.
                     E.g. if 3 relevant chunks exist and 2 appear in top-5, Recall@5 = 0.67.

  nDCG@5:            Normalized Discounted Cumulative Gain at rank 5. Rewards retrieving
                     relevant chunks at higher ranks. A relevant chunk at rank 1 contributes
                     more than the same chunk at rank 5.

  context_recall:    RAGAS LLM-judge metric. Measures whether the retrieved context covers
                     all claims in the reference answer. Score 1.0 = all reference claims
                     are supported by the retrieved context.

  faithfulness:      RAGAS LLM-judge metric. Measures whether the generated answer is
                     grounded in the retrieved context. Score 1.0 = every claim in the
                     generated answer is supported by the context.

  context_precision: RAGAS LLM-judge metric. Measures whether the most relevant chunks
                     are ranked near the top. Score 1.0 = all top-ranked chunks are relevant.

  RAGAS uses nemotron-3-super:cloud as the judge LLM (~0.9s per call via Ollama).

HOW TO RUN

Run from the dev/ repo root (the parent of backend/):

    # Build the Qdrant index for all 28 papers, then exit:
    micromamba run -n py3.12 python poc/rag-eval/retrieval_strategy_comparison.py --index-only

    # Run all 6 configs (auto-resumes if interrupted):
    micromamba run -n py3.12 python poc/rag-eval/retrieval_strategy_comparison.py 2>&1 | tee poc/rag-eval/retrieval_strategy_comparison.log

    # Run one specific config:
    micromamba run -n py3.12 python poc/rag-eval/retrieval_strategy_comparison.py --config hybrid_bm25_with_reranker

    # Re-run a config from scratch (ignore existing results):
    micromamba run -n py3.12 python poc/rag-eval/retrieval_strategy_comparison.py --config dense_only --force

    # Rebuild the Qdrant index from scratch and then run all configs:
    micromamba run -n py3.12 python poc/rag-eval/retrieval_strategy_comparison.py --rebuild-index

HOW RESUME WORKS

Results for each config are stored in:
    poc/rag-eval/retrieval-strategy-results/<config_name>.json

Each JSON file tracks per-sample status (success or failed). When the script is
re-run, it skips samples that already have status="success" and retries failed ones.
When all samples for a config complete successfully, mark_config_complete() sets
status="complete" in the JSON. On the next run, the entire config is skipped unless
--force is passed. The log file is a human-readable record but is NOT used for
resume logic — the JSON files are the single source of truth.

OUTPUT

Look for [WINNER] in the log to find the best-performing retrieval config by Recall@5.
Per-config summaries are under [SUMMARY] tags.
The [SANITY] tag shows whether the dense_only Recall@5 is consistent with the
chunking experiment baseline — a large gap (> 0.05) indicates a bug in node ID
consistency or embedding truncation.
"""

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import click
from docling.chunking import HybridChunker
from docling_core.types.doc import DoclingDocument
from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.core.vector_stores import MetadataFilter, MetadataFilters
from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.schema import Document
from llama_index.embeddings.litellm import LiteLLMEmbedding
from llama_index.llms.litellm import LiteLLM

sys.path.insert(0, ".")                                                              # dev/ repo root
sys.path.insert(0, "../research-agent-docling-rag-pipeline")                        # for poc.poc_base (full version with ExperimentLogger)
sys.path.insert(0, "../research-agent-docling-rag-pipeline/backend")                # for backend services

from poc.poc_base import (
    ExperimentLogger,
    PaperCorpus,
    MetricsCalculator,
    ContextualDoclingNodeParser,
    QdrantPaperIndex,
    ConfigResultTracker,
    RAGASEvaluator,
    truncate_to_bert_limit,
)
from services.docling_chunker import DoclingChunker
from tools.filter_tools import ChunkFilter


# Paths (all relative to dev/ repo root where this script is run from)
QDRANT_INDEX_DIR   = Path("poc/rag-eval/qdrant_ml_papers_retrieval_index")
RESULTS_DIR        = Path("poc/rag-eval/retrieval-strategy-results")
FILTER_CONFIG_PATH = Path("poc/rag-filtering/filter_config.json")

# Recall@5 achieved by docling_hybrid_chunker_512 with dense-only retrieval on 28 ML papers.
# Used as the sanity check baseline: this experiment's dense_only config uses identical
# chunking and retrieval, so its Recall@5 should be within SANITY_CHECK_MAX_DIFF of this value.
# Source: chunking_strategy_comparison experiment (28 papers, 112 positive GT samples).
CHUNKING_EXPERIMENT_DENSE_BASELINE_RECALL_AT_5 = 0.61

# Sanity check threshold: dense_only Recall@5 should be within this margin of the
# chunking experiment baseline. A larger gap indicates a bug in truncation or UUID consistency.
SANITY_CHECK_MAX_DIFF = 0.05  # warn if dense_only Recall@5 deviates >5% from chunking experiment baseline


@dataclass
class RetrievalConfig:
    """Defines one retrieval configuration to evaluate.

    Each config is a combination of three independently togglable mechanisms:

      use_hybrid_bm25 — BM25 sparse retrieval on top of dense vector search.
          Dense retrieval computes an embedding for the query and finds the nearest
          chunk embeddings by cosine similarity. BM25 is a complementary lexical
          method: it scores chunks by term-frequency / inverse-document-frequency
          with no neural network. Combining both (hybrid) improves recall for Factual
          and Keyword-heavy queries where the exact query term appears verbatim in
          the relevant chunk (e.g. a specific model name or dataset acronym).

      num_query_variants — Number of total queries to run and fuse (Reciprocal Rank Fusion).
          num_query_variants=1: the original query is used directly. No LLM call.
          num_query_variants=4: an LLM generates 3 alternative phrasings of the query.
          All 4 queries are sent to the retriever independently. Their result lists are
          merged using Reciprocal Rank Fusion (RRF): each chunk's score is 1/(rank+60)
          and scores are summed across all query result lists. This promotes chunks that
          rank highly across multiple phrasings. Improves recall when the user's wording
          diverges from the document's vocabulary (e.g. "error rate" vs "accuracy").

      use_reranker — Cross-encoder reranker (bge-reranker-large, ~270M XLM-RoBERTa params).
          The dense retriever retrieves 10 candidate chunks scored independently
          (query embedding · chunk embedding). The cross-encoder then scores each
          candidate by reading the full concatenated (query, chunk) pair jointly,
          which is more accurate but cannot be precomputed. The top 5 by cross-encoder
          score are returned. Improves precision for ML papers where a chunk that
          mentions the query topic superficially ranks above the chunk that actually
          answers the question.
    """
    name: str
    use_hybrid_bm25: bool
    num_query_variants: int
    use_reranker: bool


# These 6 configs are arranged so each retrieval mechanism can be isolated:
#   BM25 effect:              dense_only vs hybrid_bm25 (same query count, no reranker)
#   Query expansion effect:   dense_only vs dense_with_query_expansion (no BM25, no reranker)
#   Reranker effect:          hybrid_bm25 vs hybrid_bm25_with_reranker (same query count)
#   Full stack:               hybrid_bm25_query_expansion_and_reranker combines all three
RETRIEVAL_CONFIGS = [
    RetrievalConfig(
        name="dense_only",
        use_hybrid_bm25=False, num_query_variants=1, use_reranker=False,
    ),
    RetrievalConfig(
        name="dense_with_query_expansion",
        use_hybrid_bm25=False, num_query_variants=4, use_reranker=False,
    ),
    RetrievalConfig(
        name="hybrid_bm25",
        use_hybrid_bm25=True,  num_query_variants=1, use_reranker=False,
    ),
    RetrievalConfig(
        name="hybrid_bm25_with_query_expansion",
        use_hybrid_bm25=True,  num_query_variants=4, use_reranker=False,
    ),
    RetrievalConfig(
        name="hybrid_bm25_with_reranker",
        use_hybrid_bm25=True,  num_query_variants=1, use_reranker=True,
    ),
    RetrievalConfig(
        name="hybrid_bm25_query_expansion_and_reranker",
        use_hybrid_bm25=True,  num_query_variants=4, use_reranker=True,
    ),
]


def chunk_paper(paper_id: str, corpus: PaperCorpus, chunk_filter: ChunkFilter) -> list:
    """Parse and chunk one paper's Docling JSON into LlamaIndex TextNodes.

    Uses docling_hybrid_chunker_512: HybridChunker with 512-token limit and heading-path
    prefix via contextualize(). This chunking strategy was selected by comparing 7 strategies
    on 28 ML papers — it achieved the best Recall@5=0.61. ChunkFilter removes boilerplate sections
    (references, acknowledgements, etc.) that add noise without retrieval value.

    Re-chunking is always performed on every run (even when the Qdrant index exists)
    because the in-memory nodes list is required by MetricsCalculator.find_relevant_ids()
    for GT passage substring matching. Re-chunking takes ~2 min for all 28 papers
    (no LLM or embed calls — just JSON parsing and text splitting).

    Returns list of TextNode objects with node.text = heading prefix + chunk text.
    """
    from llama_index.core.schema import Document

    tokenizer_512 = DoclingChunker._TokenizerAdapter(max_tokens=512)
    parser = ContextualDoclingNodeParser(
        chunker=HybridChunker(tokenizer=tokenizer_512),
        chunk_filter=chunk_filter,
    )

    dl_doc = corpus.load_doc(paper_id)
    li_doc = Document(
        text=dl_doc.model_dump_json(),
        metadata={"paper_id": paper_id},
    )
    return parser.parse_nodes([li_doc])


def build_retriever(
    index: VectorStoreIndex,
    config: RetrievalConfig,
    query_expansion_llm: LiteLLM,
    paper_id: str,
) -> QueryFusionRetriever:
    """Build a retriever for one retrieval configuration.

    All 6 configs use QueryFusionRetriever as the unified interface:
    - num_query_variants=1: no LLM called, original query passed through directly.
      (Confirmed in LlamaIndex source: if num_queries <= 1, _get_queries() is skipped.)
    - num_query_variants=4: LLM generates 3 additional query variants; all 4 results
      are fused using Reciprocal Rank Fusion (RRF) before returning top chunks.

    vector_store_query_mode:
    - "hybrid": combines dense vector similarity + BM25 sparse term matching.
    - "default": dense vector similarity only (BM25 vectors in Qdrant are ignored).

    paper_id filter: restricts Qdrant search to chunks belonging to this paper only,
    preventing cross-paper contamination when all 28 papers share a single collection.
    """
    base_retriever = index.as_retriever(
        vector_store_query_mode="hybrid" if config.use_hybrid_bm25 else "default",
        similarity_top_k=10,
        filters=MetadataFilters(filters=[
            MetadataFilter(key="paper_id", value=paper_id)
        ]),
    )
    return QueryFusionRetriever(
        [base_retriever],
        num_queries=config.num_query_variants,
        mode="reciprocal_rerank",
        use_async=False,
        llm=query_expansion_llm if config.num_query_variants > 1 else None,
    )


def run_evaluation(
    config: RetrievalConfig,
    paper_index: dict,
    gt_samples: list,
    reranker: SentenceTransformerRerank,
    answer_generation_llm: LiteLLM,
    query_expansion_llm: LiteLLM,
    ragas_evaluator: RAGASEvaluator,
    logger: ExperimentLogger,
    tracker: ConfigResultTracker,
    force: bool,
) -> None:
    """Core evaluation loop for this retrieval strategy comparison experiment.

    Evaluates one retrieval config across all 112 positive GT samples.
    Skips Negative query samples (is_negative=True): they have no gt_passages,
    making Recall/nDCG mathematically undefined, and no gt_answer for RAGAS.

    Skips samples already marked success in the JSON tracker (resume support).

    Per-sample flow:
      1. Retrieve top-10 chunks using the config's retrieval mechanism.
      2. Optionally rerank to top-5 using bge-reranker-large cross-encoder.
      3. Compute Recall@5 and nDCG@5 (no LLM needed).
      4. Generate an answer from retrieved context using qwen3.5:cloud.
      5. Evaluate with RAGAS judge (context_recall, faithfulness, context_precision).
      6. Write result to per-config JSON immediately (never batch).

    The reranker is applied in this function, NOT inside build_retriever().
    Patching the retriever object would cause double-reranking if build_retriever()
    is called multiple times for the same config.
    """
    logger.log("CONFIG_START", retrieval_config=config.name)
    config_start_time = time.perf_counter()
    evaluated_count = 0

    for sample in gt_samples:
        if sample["is_negative"]:
            logger.skip(
                retrieval_config=config.name,
                paper=sample["paper_id"],
                query_type=sample["query_type"],
                reason="negative_query_no_gt_passages",
            )
            continue

        paper_id = sample["paper_id"]
        query_type = sample["query_type"]

        if not force and tracker.is_sample_done(paper_id, query_type):
            continue

        index, nodes = paper_index[paper_id]

        # Step 1: retrieve top-10 chunks
        retriever = build_retriever(index, config, query_expansion_llm, paper_id=paper_id)
        retrieved_nodes = retriever.retrieve(sample["query"])

        # Step 2: optionally rerank to top-5
        # Applied here (not inside build_retriever) to avoid double-reranking bugs.
        if config.use_reranker:
            retrieved_nodes = reranker.postprocess_nodes(
                retrieved_nodes, query_str=sample["query"]
            )
        contexts = [n.text for n in retrieved_nodes]

        # Step 3: retrieval quality metrics (no LLM)
        relevant_node_ids = MetricsCalculator.find_relevant_ids(nodes, sample["gt_passages"])
        if not relevant_node_ids:
            logger.skip(
                retrieval_config=config.name,
                paper=paper_id,
                query_type=query_type,
                reason="no_relevant_ids_found",
            )
            continue

        retrieved_node_ids = [n.node_id for n in retrieved_nodes[:5]]
        recall_at_5 = MetricsCalculator.recall_at_k(retrieved_node_ids, relevant_node_ids, k=5)
        ndcg_at_5   = MetricsCalculator.ndcg_at_k(retrieved_node_ids, relevant_node_ids, k=5)

        # Step 4: generate answer from retrieved context (required for RAGAS)
        context_str = "\n\n---\n\n".join(contexts)
        generated_answer = answer_generation_llm.complete(
            f"Answer the question based only on the context below.\n\n"
            f"Context:\n{context_str}\n\nQuestion: {sample['query']}"
        ).text

        # Step 5: RAGAS evaluation (LLM-judge)
        try:
            ragas_scores = ragas_evaluator.evaluate(
                query=sample["query"],
                generated_answer=generated_answer,
                retrieved_contexts=contexts,
                reference_answer=sample["gt_answer"],
            )
            tracker.write_result(
                paper_id=paper_id,
                query_type=query_type,
                recall_at_5=recall_at_5,
                ndcg_at_5=ndcg_at_5,
                generated_answer=generated_answer,
                **ragas_scores,
            )
            logger.result(
                retrieval_config=config.name,
                paper=paper_id,
                query_type=query_type,
                recall_at_5=f"{recall_at_5:.4f}",
                ndcg_at_5=f"{ndcg_at_5:.4f}",
                context_recall=f"{ragas_scores['context_recall']:.4f}",
                faithfulness=f"{ragas_scores['faithfulness']:.4f}",
                context_precision=f"{ragas_scores['context_precision']:.4f}",
            )
            evaluated_count += 1

        except Exception as exc:
            tracker.write_error(paper_id=paper_id, query_type=query_type, error=str(exc))
            logger.error(
                retrieval_config=config.name,
                paper=paper_id,
                query_type=query_type,
                stage="ragas",
                msg=str(exc),
            )

    # Compute and log per-config summary
    successful = [s for s in tracker._data["samples"] if s["status"] == "success"]
    if successful:
        avg = lambda key: sum(s[key] for s in successful) / len(successful)
        logger.summary(
            retrieval_config=config.name,
            query_type="ALL",
            recall_at_5=f"{avg('recall_at_5'):.4f}",
            ndcg_at_5=f"{avg('ndcg_at_5'):.4f}",
            context_recall=f"{avg('context_recall'):.4f}",
            faithfulness=f"{avg('faithfulness'):.4f}",
            context_precision=f"{avg('context_precision'):.4f}",
            n=len(successful),
            latency_s=f"{time.perf_counter() - config_start_time:.1f}",
        )

    tracker.mark_config_complete()
    logger.log("CONFIG_END", retrieval_config=config.name, status="complete")


class SentenceSplitterExperiment:
    """Sentence splitter chunking with full retrieval stack (BM25 + query expansion + reranker).

    Uses its own isolated Qdrant index directory and collection, separate from the
    docling_hybrid_512 index used by the other retrieval configs.
    Purpose: compare chunking strategy effect while holding retrieval stack constant.

    The other retrieval configs fix chunking (docling_hybrid_512) and vary retrieval mechanism.
    This experiment fixes the retrieval stack (BM25 + query expansion + reranker) and varies
    chunking (sentence_splitter), isolating whether Semantic recall weakness is a chunking
    or retrieval problem.
    """

    CONFIG_NAME = "sentence_splitter_full_stack"
    QDRANT_DIR  = Path("poc/rag-eval/qdrant_ml_papers_sentence_splitter_index")
    COLLECTION  = "ml_papers_sentence_splitter_retrieval"

    def __init__(self, corpus, embed_model, query_expansion_llm,
                 reranker, answer_llm, ragas_evaluator, results_dir, logger):
        self._corpus              = corpus
        self._embed_model         = embed_model
        self._query_expansion_llm = query_expansion_llm
        self._reranker            = reranker
        self._answer_llm          = answer_llm
        self._ragas_evaluator     = ragas_evaluator
        self._tracker             = ConfigResultTracker(results_dir, self.CONFIG_NAME)
        self._logger              = logger
        self._qdrant_index        = QdrantPaperIndex(
            self.QDRANT_DIR, embed_model, collection_name=self.COLLECTION
        )

    def _chunk_paper(self, paper_id: str) -> list:
        md_text = (self._corpus.PARSED_DIR / f"{paper_id}.md").read_text()
        nodes = SentenceSplitter().get_nodes_from_documents(
            [Document(text=md_text, metadata={"paper_id": paper_id})]
        )
        for i, node in enumerate(nodes):
            node.node_id = str(uuid.uuid5(
                uuid.NAMESPACE_DNS, f"{paper_id}_ss_chunk_{i}"
            ))
            node.metadata["paper_id"] = paper_id
        return nodes

    def build_index(self) -> dict:
        paper_index = {}
        for paper_id in self._corpus.paper_ids():
            nodes = self._chunk_paper(paper_id)
            index, nodes, _ = self._qdrant_index.build_or_load(paper_id, nodes)
            paper_index[paper_id] = (index, nodes)
        return paper_index

    def rebuild_index(self):
        self._qdrant_index.rebuild_all()

    def run(self, force: bool = False):
        if self._tracker.is_config_done() and not force:
            self._logger.skip(
                retrieval_config=self.CONFIG_NAME, reason="already_complete"
            )
            return
        if force:
            self._tracker.reset()

        paper_index = self.build_index()

        full_stack_config = RetrievalConfig(
            name=self.CONFIG_NAME,
            use_hybrid_bm25=True,
            num_query_variants=4,
            use_reranker=True,
        )
        run_evaluation(
            config=full_stack_config,
            paper_index=paper_index,
            gt_samples=self._corpus.load_gt(exclude_negative=True),
            query_expansion_llm=self._query_expansion_llm,
            reranker=self._reranker,
            answer_generation_llm=self._answer_llm,
            ragas_evaluator=self._ragas_evaluator,
            tracker=self._tracker,
            logger=self._logger,
            force=force,
        )


@click.command()
@click.option("--config", default=None,
              help="Run one specific retrieval config by name (e.g. hybrid_bm25_with_reranker). "
                   "Omit to run all configs.")
@click.option("--force", is_flag=True, default=False,
              help="Re-run the specified config from scratch, clearing any existing results in the JSON tracker.")
@click.option("--index-only", is_flag=True, default=False,
              help="Build the Qdrant index for all 28 papers and exit without running evaluation.")
@click.option("--rebuild-index", is_flag=True, default=False,
              help="Drop the existing Qdrant collection and rebuild the index from scratch.")
def main(config, force, index_only, rebuild_index):
    """Retrieval Strategy Comparison — compares multiple retrieval configurations on 28 ML papers.

    Finds the best retrieval mechanism for RAG-based paper summarization. Fixed conditions:
    docling_hybrid_chunker_512 chunking strategy (best among 7 strategies, Recall@5=0.61),
    Qdrant/bm25 sparse model (best recall-to-latency ratio among BM25/miniCOIL/SPLADE),
    nomic-embed-text embeddings.

    The Qdrant index is built once and shared across all configs. Evaluation resumes
    automatically from the last successful sample if the script is interrupted and re-run.
    """
    Settings.llm = LiteLLM(model="ollama/ministral-3:14b-cloud", temperature=0.0)
    logger = ExperimentLogger("retrieval_strategy_comparison")
    corpus = PaperCorpus()

    embed_model = LiteLLMEmbedding(
        model_name="ollama/nomic-embed-text",
        embed_batch_size=32,
        # embed_batch_size=32 reduces Ollama HTTP round-trips by 3x vs the default of 10.
        # Values above 64 don't improve throughput — Ollama processes embeddings serially.
    )

    chunk_filter = ChunkFilter(config_path=FILTER_CONFIG_PATH)
    qdrant_index = QdrantPaperIndex(QDRANT_INDEX_DIR, embed_model)
    try:
        logger.header(
            experiment="retrieval_strategy_comparison",
            embed_model="ollama/nomic-embed-text",
            chunking_strategy="docling_hybrid_chunker_512",
            sparse_model="Qdrant/bm25",
            corpus_papers=28,
            gt_samples=140,
            positive_gt_samples=112,
        )

        # ── Index building ────────────────────────────────────────────────────────
        if rebuild_index:
            logger.log("INFO", msg="rebuild_index_flag_set_dropping_existing_collection")
            qdrant_index.rebuild_all(corpus.paper_ids())

        paper_index: dict = {}
        for paper_id in corpus.paper_ids():
            nodes = chunk_paper(paper_id, corpus, chunk_filter)
            index, nodes, already_indexed = qdrant_index.build_or_load(paper_id, nodes)
            paper_index[paper_id] = (index, nodes)
            action = "loaded" if already_indexed else "indexed"
            logger.log("INDEX", paper=paper_id, chunks=len(nodes), action=action)

        if index_only:
            logger.log("INFO", msg="index_only_flag_set_skipping_evaluation")
            logger.end()
            return

        # ── Evaluation ────────────────────────────────────────────────────────────
        # load_gt() returns all 140 samples; negative samples are filtered inside run_evaluation()
        gt_samples = corpus.load_gt()

        # LLMs initialized once and shared across all configs to avoid repeated model loading.
        query_expansion_llm = LiteLLM(model="ollama/qwen3.5:cloud", temperature=0.0, additional_kwargs={"think": False})
        answer_generation_llm = LiteLLM(
            model="ollama/qwen3.5:cloud",
            temperature=0.0,
            additional_kwargs={"think": False},
        )
        ragas_evaluator = RAGASEvaluator()

        # bge-reranker-large: XLM-RoBERTa cross-encoder, scores query+chunk jointly.
        # device="mps" must be explicit — LlamaIndex defaults to CPU on Apple M1 without it.
        # PYTORCH_ENABLE_MPS_FALLBACK=1 (set at top) handles ops not natively on MPS.
        reranker = SentenceTransformerRerank(
            model="BAAI/bge-reranker-large",
            top_n=5,
            device="mps",
        )

        # Select which configs to run
        configs_to_run = RETRIEVAL_CONFIGS
        if config is not None:
            matching = [c for c in RETRIEVAL_CONFIGS if c.name == config]
            if not matching and config != SentenceSplitterExperiment.CONFIG_NAME:
                valid = [c.name for c in RETRIEVAL_CONFIGS] + [SentenceSplitterExperiment.CONFIG_NAME]
                raise click.BadParameter(
                    f"Unknown config '{config}'. Valid options: {valid}"
                )
            configs_to_run = matching

        best_config_name = None
        best_recall = -1.0

        for retrieval_config in configs_to_run:
            tracker = ConfigResultTracker(RESULTS_DIR, retrieval_config.name)
            if force:
                tracker.reset()
            if tracker.is_config_done() and not force:
                logger.skip(
                    retrieval_config=retrieval_config.name,
                    reason="already_complete",
                )
                continue

            run_evaluation(
                config=retrieval_config,
                paper_index=paper_index,
                gt_samples=gt_samples,
                reranker=reranker,
                answer_generation_llm=answer_generation_llm,
                query_expansion_llm=query_expansion_llm,
                ragas_evaluator=ragas_evaluator,
                logger=logger,
                tracker=tracker,
                force=force,
            )

            # Track best config by Recall@5 for the [WINNER] log line
            successful = [s for s in tracker._data["samples"] if s["status"] == "success"]
            if successful:
                mean_recall = sum(s["recall_at_5"] for s in successful) / len(successful)
                if mean_recall > best_recall:
                    best_recall = mean_recall
                    best_config_name = retrieval_config.name

            # Sanity check: dense_only uses the same chunking (docling_hybrid_chunker_512) and
            # retrieval (dense-only, single query) as the chunking experiment's baseline config.
            # Their Recall@5 should match within SANITY_CHECK_MAX_DIFF. A larger gap indicates
            # a bug in embedding truncation or UUID consistency between the nodes list and Qdrant.
            if retrieval_config.name == "dense_only" and successful:
                mean_recall_dense = sum(s["recall_at_5"] for s in successful) / len(successful)
                diff = abs(mean_recall_dense - CHUNKING_EXPERIMENT_DENSE_BASELINE_RECALL_AT_5)
                sanity_status = "OK" if diff <= SANITY_CHECK_MAX_DIFF else "WARNING"
                logger.log(
                    "SANITY",
                    retrieval_config="dense_only",
                    recall_at_5=f"{mean_recall_dense:.4f}",
                    chunking_experiment_baseline_recall_at_5=CHUNKING_EXPERIMENT_DENSE_BASELINE_RECALL_AT_5,
                    diff=f"{diff:.4f}",
                    status=sanity_status,
                )
                if sanity_status == "WARNING":
                    logger.error(
                        retrieval_config="dense_only",
                        stage="sanity_check",
                        msg=(
                            "dense_only recall differs from the chunking experiment baseline by more than 0.05. "
                            "Check that truncate_to_bert_limit() is applied before embedding "
                            "and that deterministic node IDs (uuid5) match between nodes list and Qdrant."
                        ),
                    )

        if best_config_name:
            logger.winner(
                retrieval_config=best_config_name,
                recall_at_5=f"{best_recall:.4f}",
            )

        # Sentence splitter experiment — uses its own isolated index
        if config is None or config == SentenceSplitterExperiment.CONFIG_NAME:
            ss_exp = SentenceSplitterExperiment(
                corpus=corpus,
                embed_model=embed_model,
                query_expansion_llm=query_expansion_llm,
                reranker=reranker,
                answer_llm=answer_generation_llm,
                ragas_evaluator=ragas_evaluator,
                results_dir=RESULTS_DIR,
                logger=logger,
            )
            if rebuild_index:
                ss_exp.rebuild_index()
            elif index_only:
                ss_exp.build_index()
            else:
                ss_exp.run(force=force)
    finally:
        qdrant_index.close()
    logger.end()


if __name__ == "__main__":
    main()
