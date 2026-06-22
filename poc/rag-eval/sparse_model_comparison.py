"""Compare sparse retrieval models (BM25, miniCOIL, SPLADE) against a dense-only baseline
to select the best sparse model for hybrid retrieval experiments.

Run from repo root (research-agent-docling-rag-pipeline/):
    micromamba run -n py3.12 python poc/rag-eval/sparse_model_comparison.py 2>&1 | tee poc/rag-eval/sparse_comparison.log

Output: [WINNER] line in sparse_comparison.log — used by the retrieval experiment script
to set the fastembed_sparse_model parameter for hybrid retrieval configs.
"""
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, ".")        # repo root — poc.poc_base
sys.path.insert(0, "backend") # backend imports

from docling.chunking import HybridChunker
from docling_core.types.doc import DoclingDocument
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import Document
from llama_index.embeddings.litellm import LiteLLMEmbedding
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

# ── Config ────────────────────────────────────────────────────────────────────

SPARSE_CONFIGS: list[tuple[str, str | None]] = [
    ("E0-baseline", None),                          # dense only
    ("H-BM25",      "Qdrant/bm25"),
    ("H-miniCOIL",  "Qdrant/minicoil-v1"),
    ("H-SPLADE",    "prithivida/Splade_PP_en_v1"),
]

TOP_K_RETRIEVE = 10
EVAL_K         = 5


def build_index(
    paper_id: str,
    nodes: list,
    embed_model: LiteLLMEmbedding,
    sparse_model: str | None,
) -> VectorStoreIndex:
    """Build a fresh in-memory Qdrant index for one paper and one sparse config."""
    client = QdrantClient(":memory:")
    if sparse_model:
        vector_store = QdrantVectorStore(
            client=client,
            collection_name=paper_id,
            enable_hybrid=True,
            fastembed_sparse_model=sparse_model,
        )
    else:
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


def main():
    logger = ExperimentLogger("sparse_model_comparison")
    corpus = PaperCorpus()

    # ── Setup chunker + filter (fixed across all configs) ─────────────────────
    chunk_filter = ChunkFilter(
        config_path=Path("poc/rag-filtering/filter_config.json")
    )
    tokenizer = DoclingChunker._TokenizerAdapter(max_tokens=512)
    node_parser = ContextualDoclingNodeParser(
        chunker=HybridChunker(tokenizer=tokenizer),
        chunk_filter=chunk_filter,
    )

    # ── Embed model (instantiated once; embeddings pre-computed per paper) ────
    embed_model = LiteLLMEmbedding(
        model_name="ollama/nomic-embed-text",
        embed_batch_size=32,
    )

    # ── Load corpus + GT ──────────────────────────────────────────────────────
    paper_ids = corpus.paper_ids()
    gt_samples = corpus.load_gt(exclude_negative=True)

    logger.header(
        embed="ollama/nomic-embed-text",
        sparse_configs=len(SPARSE_CONFIGS),
        retrieve_k=TOP_K_RETRIEVE,
        eval_k=EVAL_K,
    )
    print(f"[CORPUS] {len(paper_ids)} papers, {len(gt_samples)} positive GT samples")

    # ── Per-paper node cache (parse + embed once) ─────────────────────────────
    # paper_id → list[TextNode] with node.embedding pre-populated
    paper_nodes: dict[str, list] = {}

    print("[PHASE] Pre-computing chunks and embeddings for all papers ...")
    for paper_id in paper_ids:
        json_path = corpus.PARSED_DIR / f"{paper_id}.json"
        if not json_path.exists():
            logger.error(paper=paper_id, stage="load", msg="parsed JSON not found; run phase0_parse.py first")
            continue
        dl_doc = DoclingDocument.model_validate(json.loads(json_path.read_text()))
        li_doc = Document(
            text=dl_doc.model_dump_json(),
            metadata={"paper_id": paper_id},
        )
        nodes = node_parser.parse_nodes([li_doc])
        if not nodes:
            logger.error(paper=paper_id, stage="chunk", msg="no nodes produced")
            continue
        # Pre-compute dense embeddings once — VectorStoreIndex skips re-embedding
        # when node.embedding is already set.
        for node in nodes:
            node.embedding = embed_model.get_text_embedding(node.text)
        paper_nodes[paper_id] = nodes

    # ── Per-config metrics accumulator ────────────────────────────────────────
    # config_name → query_type → [recall5, ndcg5]
    scores: dict[str, dict[str, list[float]]] = {
        cfg: defaultdict(list) for cfg, _ in SPARSE_CONFIGS
    }
    latency: dict[str, float] = {cfg: 0.0 for cfg, _ in SPARSE_CONFIGS}

    # ── Main evaluation loop ──────────────────────────────────────────────────
    for cfg_name, sparse_model in SPARSE_CONFIGS:
        print(f"\n[PHASE] Evaluating config={cfg_name} sparse_model={sparse_model}")
        t_cfg_start = time.perf_counter()

        # Group GT samples by paper so we build the index once per paper per config
        samples_by_paper: dict[str, list[dict]] = defaultdict(list)
        for sample in gt_samples:
            samples_by_paper[sample["paper_id"]].append(sample)

        for paper_id, paper_samples in samples_by_paper.items():
            nodes = paper_nodes.get(paper_id)
            if not nodes:
                for sample in paper_samples:
                    logger.skip(
                        paper=paper_id,
                        config=cfg_name,
                        reason="nodes_not_available",
                    )
                continue

            # Build fresh index for this paper + config combination
            try:
                index = build_index(paper_id, nodes, embed_model, sparse_model)
            except Exception as exc:
                logger.error(paper=paper_id, config=cfg_name, stage="index_build", msg=str(exc))
                for sample in paper_samples:
                    logger.skip(paper=paper_id, config=cfg_name, reason="index_build_failed")
                continue

            query_mode = "hybrid" if sparse_model else "default"
            retriever = index.as_retriever(
                vector_store_query_mode=query_mode,
                similarity_top_k=TOP_K_RETRIEVE,
            )
            for sample in paper_samples:
                query_type = sample.get("query_type", "Unknown")
                relevant_ids = MetricsCalculator.find_relevant_ids(
                    nodes, sample["gt_passages"]
                )

                if not relevant_ids:
                    logger.skip(
                        paper=paper_id,
                        config=cfg_name,
                        reason="no_relevant_ids_found",
                    )
                    continue

                try:
                    retrieved = retriever.retrieve(sample["query"])
                except Exception as exc:
                    logger.error(
                        paper=paper_id,
                        config=cfg_name,
                        stage="retrieve",
                        msg=str(exc),
                    )
                    continue

                retrieved_ids = [n.node_id for n in retrieved[:EVAL_K]]
                recall5 = MetricsCalculator.recall_at_k(retrieved_ids, relevant_ids, k=EVAL_K)
                ndcg5   = MetricsCalculator.ndcg_at_k(retrieved_ids, relevant_ids, k=EVAL_K)

                if recall5 is None or ndcg5 is None:
                    logger.skip(
                        paper=paper_id,
                        config=cfg_name,
                        reason="metrics_returned_none",
                    )
                    continue

                scores[cfg_name][query_type].append(recall5)
                scores[cfg_name]["ALL"].append(recall5)

                logger.result(
                    paper=paper_id,
                    config=cfg_name,
                    query_type=query_type,
                    recall5=f"{recall5:.3f}",
                    ndcg5=f"{ndcg5:.3f}",
                )

        latency[cfg_name] = time.perf_counter() - t_cfg_start

    # ── Per-config summary ────────────────────────────────────────────────────
    config_agg: dict[str, dict[str, float]] = {}

    for cfg_name, _ in SPARSE_CONFIGS:
        cfg_scores = scores[cfg_name]
        query_types = [qt for qt in cfg_scores if qt != "ALL"]
        for qt in query_types:
            vals = cfg_scores[qt]
            if vals:
                mean_r = sum(vals) / len(vals)
                logger.summary(
                    config=cfg_name,
                    query_type=qt,
                    recall5=f"{mean_r:.2f}",
                    n=len(vals),
                )

        all_vals = cfg_scores.get("ALL", [])
        if all_vals:
            mean_r_all = sum(all_vals) / len(all_vals)
            logger.summary(
                config=cfg_name,
                query_type="ALL",
                recall5=f"{mean_r_all:.2f}",
                n=len(all_vals),
                latency_s=f"{latency[cfg_name]:.1f}",
            )
            config_agg[cfg_name] = {"recall5": mean_r_all}
        else:
            config_agg[cfg_name] = {"recall5": 0.0}

    # ── Winner selection ──────────────────────────────────────────────────────
    if config_agg:
        winner_config = max(config_agg, key=lambda c: config_agg[c]["recall5"])

        # Tiebreaker: prefer BM25 over miniCOIL when improvement is negligible
        bm25_recall    = config_agg.get("H-BM25",     {}).get("recall5", 0.0)
        minicoil_recall = config_agg.get("H-miniCOIL", {}).get("recall5", 0.0)
        if 0 < minicoil_recall - bm25_recall < 0.02:
            winner_config = "H-BM25"

        winner_sparse = dict(SPARSE_CONFIGS)[winner_config]
        winner_recall = config_agg[winner_config]["recall5"]

        # Warn when no hybrid config meaningfully outperforms the dense baseline
        baseline_recall = config_agg.get("E0-baseline", {}).get("recall5", 0.0)
        hybrid_recalls  = [
            config_agg[c]["recall5"]
            for c, sm in SPARSE_CONFIGS
            if sm is not None and c in config_agg
        ]
        if hybrid_recalls and all(r - baseline_recall < 0.02 for r in hybrid_recalls):
            print(
                "[WARNING] All hybrid configs within 0.02 recall of dense baseline"
                " — sparse models may not benefit this corpus"
            )

        logger.winner(
            sparse_model=winner_sparse,
            config=winner_config,
            recall5=f"{winner_recall:.2f}",
        )

    logger.end()


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
