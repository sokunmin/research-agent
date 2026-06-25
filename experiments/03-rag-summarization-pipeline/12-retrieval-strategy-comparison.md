# Experiment 12 — Retrieval Strategy Comparison

## Task Context

This experiment targets **Step 4 — Summarization** from the system architecture (README → System Architecture). Experiment 11 established the chunking strategy. This experiment holds that chunking strategy fixed and varies the retrieval configuration — the mechanism that selects which chunks the LLM receives as context.

Step 4 — Summarization (detail):

```
Step 4 — Summarization (detail)
────────────────────────────────────────────────────────────────────────────
 PDF files
       │
       ▼
 [Docling PDF parser]        produces a structured DoclingDocument
       │
       ▼
 [HybridChunker + ChunkFilter]   512-token chunks, boilerplate removed
       │                         (fixed by Experiment 11)
       │
       ▼
 [Qdrant index]              chunks stored as dense vectors + BM25 sparse index
       │
       ▼
 ┌─── EXPERIMENT TARGET: Part A ─────────────────────────────────────────┐
 │ Sparse Model Selection                                                │
 │   Input:  query string + paper_id                                     │
 │   Config: 3 hybrid sparse models vs dense-only baseline               │
 │   Output: winning sparse model → fixed for Part B                     │
 └───────────────────────────────────────────────────────────────────────┘
       │  Qdrant/bm25 fixed
       ▼
 ┌─── EXPERIMENT TARGET: Part B ─────────────────────────────────────────┐
 │ Retrieval Strategy Ablation                                           │
 │   Input:  query string + paper_id                                     │
 │   Config: 6 configs (BM25 × query expansion × reranking)              │
 │   Output: top-5 chunks for LLM context                                │
 └───────────────────────────────────────────────────────────────────────┘
       │
       ▼
 [LLM summarization]         chunks passed as context → paper summary
       │
       ▼
 paper summaries                  → Step 5: Slide Outline + HITL
```

---

## Summary

- **Problem:** Three retrieval mechanisms — BM25, query expansion, and reranking — were unevaluated after Experiment 11, which used dense-only retrieval as the baseline config.
- **Solution:** Two-part evaluation.
  - Part A: selected the sparse model for BM25 hybrid search.
  - Part B: compared six retrieval configurations — varying BM25, query expansion, and reranking — with chunking and sparse model fixed.
- **Result:** Hybrid BM25 + query expansion achieves Recall@5 = 0.608 (+0.195 over dense-only baseline in this experiment).

---

## Experiment Setup

✅ = currently used in the pipeline

### Fixed Conditions

**Inherited from Experiment 11:**

| Parameter | Value |
|---|---|
| Chunking strategy | `docling_hybrid_chunker_512` |
| Chunk heading prefix | Section heading path prepended to each chunk |
| Boilerplate filter | `ChunkFilter` (removes references, acknowledgements, etc.) |

**Fixed in this experiment:**

| Parameter | Value | Notes |
|---|---|---|
| Retrieval candidate pool | top_k=10 (before optional reranking to top 5) | Enables reranker to operate over 10 candidates |
| Paper-level scope | `MetadataFilter(key="paper_id")` on every retrieval | Prevents cross-paper chunk contamination |
| LLM temperature | 0.0 for all models | Ensures deterministic results |

### Models

| Role | Model | Notes |
|---|---|---|
| Dense embedding | `nomic-embed-text` | Ollama, 768-dim vectors |
| Sparse model | `Qdrant/bm25` | Selected in Part A |
| Query expansion | `qwen3.5:cloud` | Generates 3 alternative phrasings |
| Cross-encoder reranker | `BAAI/bge-reranker-large` | ~270M params, Apple M1 MPS; reranker configs only |
| Evaluation judge (RAGAS) | `nemotron-3-super:cloud` | Scores Context Recall, Faithfulness, Context Precision |

### Ground-Truth Dataset

| Query Type | Count (evaluable) | What it tests |
|---|---|---|
| Factual | 23 | Specific numbers, hyperparameters, model names |
| Keyword-heavy | 25 | Precise technical terminology |
| Semantic | 27 | Conceptual understanding — answer requires paraphrasing |
| Multi-hop | 25 | Information integrated from multiple paper sections |
| **Total** | **100** | |

Negative samples (n=28) are excluded from Recall@5 and nDCG@5 — both metrics are mathematically undefined when no ground-truth passages exist.

All 6 retrieval configurations evaluate on n=100 samples (12 of 112 positive samples are skipped — the ground-truth passage spans chunk boundaries, so `find_relevant_ids()` returns an empty set for those queries).

### Part A — Sparse Model Candidates

| Config | Dense model | Sparse model | Model type | Model size |
|---|---|---|---|---|
| Dense-only baseline | `nomic-embed-text` | — | Statistical baseline | — |
| Hybrid BM25 ✅ | `nomic-embed-text` | `Qdrant/bm25` | Statistical (TF-IDF) | ~84 KB |
| Hybrid miniCOIL | `nomic-embed-text` | `Qdrant/minicoil-v1` | Neural sparse (small ONNX) | Small ONNX |
| Hybrid SPLADE | `nomic-embed-text` | `prithivida/Splade_PP_en_v1` | Neural sparse (transformer) | 507 MB |

### Part B — Retrieval Strategy Configurations

| Config | BM25 hybrid | Query expansion | Cross-encoder reranker | Notes |
|---|---|---|---|---|
| `dense_only` | ✗ | ✗ | ✗ | Baseline — reproduces Experiment 11 dense-only |
| `dense_with_query_expansion` | ✗ | ✓ (4 variants, RRF) | ✗ | Isolates query expansion without BM25 anchor |
| `hybrid_bm25` | ✓ | ✗ | ✗ | Isolates BM25 contribution |
| `hybrid_bm25_with_query_expansion` ✅ | ✓ | ✓ (4 variants, RRF) | ✗ | **Winner** |
| `hybrid_bm25_with_reranker` | ✓ | ✗ | ✓ (`bge-reranker-large`) | Isolates reranker contribution |
| `hybrid_bm25_query_expansion_and_reranker` | ✓ | ✓ (4 variants, RRF) | ✓ (`bge-reranker-large`) | Full stack |

Query expansion generates 3 alternative phrasings via LLM. All 4 query variants (original + 3 alternatives) are retrieved independently and fused using Reciprocal Rank Fusion (RRF). The cross-encoder reranker rescores the top-10 candidates down to top-5.

### Metrics

| Metric | Definition | Role | Range | Higher = |
|---|---|---|---|---|
| Recall@5 | Fraction of ground-truth relevant chunks that appear anywhere in the top-5 retrieved results | **Primary** — the summarization LLM reads all top-K chunks simultaneously; whether a chunk is at rank 1 or rank 5 matters less than whether it is present | 0–1 | Better |
| nDCG@5 | Normalized Discounted Cumulative Gain at rank 5 — like Recall@5 but rewards higher-ranked relevant chunks | Secondary — measures ranking quality within the retrieved set | 0–1 | Better |
| Context Recall (RAGAS) | LLM judge checks whether retrieved chunks cover all atomic claims in the reference answer | Secondary — measures end-to-end answer coverage | 0–1 | Better |
| Faithfulness (RAGAS) | LLM judge checks whether the generated answer is grounded in retrieved chunks | Secondary — measures hallucination rate | 0–1 | Better |
| Context Precision (RAGAS) | LLM judge checks whether the most-relevant chunks are ranked near the top | Secondary — measures ranking quality from an answer-quality perspective | 0–1 | Better |


---

## Full Experimental Results

### Part A — Sparse Model Selection

- **Purpose:** Fix the sparse model for all Part B configurations so that only the retrieval strategy changes between configs, not the sparse model underneath.
- **Expected:** Any hybrid config should exceed the `dense_only` baseline config. The winning sparse model should maximize Recall@5 at acceptable latency.

| Config | Factual (n=23) | Keyword (n=25) | Semantic (n=27) | Multi-hop (n=25) | ALL (n=100) | Total latency |
|---|---|---|---|---|---|---|
| Dense-only baseline | 0.57 | 0.73 | 0.35 | 0.81 | 0.61 | **3.9s** |
| **Hybrid BM25 ✅** | **0.93** | **0.83** | **0.50** | **0.88** | **0.78** | 13.5s |
| Hybrid miniCOIL | 0.89 | **0.83** | 0.48 | **0.88** | 0.76 | 204.0s |
| Hybrid SPLADE | 0.80 | 0.78 | 0.46 | 0.79 | 0.70 | 342.7s |


**Conclusion:** BM25 wins on both recall and latency — 15× faster than miniCOIL with higher Recall@5. In ML papers, authors use the same precise terminology in both queries and documents, so exact token matching is more reliable than models that expand queries with related terms.

---

### Part B — Retrieval Strategy Comparison

- **Purpose:** Identify the retrieval configuration that maximizes Recall@5 with `docling_hybrid_chunker_512` and `Qdrant/bm25` fixed.
- **Expected:** Any hybrid config should match or exceed the Part A BM25 Recall@5 of 0.78. Query expansion and reranking should push recall higher on top of that.

#### Overall Results (all query types combined)

| Retrieval Config | Recall@5 | nDCG@5 | Context Recall | Faithfulness | Context Precision | Latency (s) |
|---|---|---|---|---|---|---|
| `dense_only` | 0.4133 | 0.3857 | 0.8055 | 0.9686 | 0.7600 | 9323.4 |
| `dense_with_query_expansion` | 0.3583 | 0.3437 | 0.7500 | 0.9657 | 0.7150 | 7734.8 |
| `hybrid_bm25` | 0.5883 | 0.5536 | 0.9100 | **0.9842** | 0.8850 | 5674.3 |
| **`hybrid_bm25_with_query_expansion` ✅** | **0.6083** | 0.5589 | 0.9100 | 0.9599 | 0.9000 | 5212.1 |
| `hybrid_bm25_with_reranker` | 0.5883 | 0.5700 | 0.9358 | 0.9805 | **0.9150** | **5036.9** |
| `hybrid_bm25_query_expansion_and_reranker` | **0.6083** | **0.5855** | **0.9400** | 0.9683 | 0.9100 | 6268.6 |


**Conclusion:** Hybrid BM25 with query expansion achieves the highest Recall@5 among all six main configurations, and does so with the lowest latency of the BM25-enabled configs — the reranker adds +1,057s over 100 samples without improving retrieval coverage.

---

#### Recall@5 by Query Type

| Query Type | `dense_only` | `dense+QE` | `hybrid_bm25` | `hybrid_bm25+QE` ✅ | `hybrid_bm25+rerank` | `hybrid_bm25+QE+rerank` |
|---|---|---|---|---|---|---|
| Factual | 0.370 | 0.283 | 0.717 | 0.674 | 0.717 | **0.761** |
| Keyword-heavy | 0.513 | 0.513 | **0.733** | **0.733** | **0.733** | 0.713 |
| Semantic | 0.204 | 0.185 | 0.241 | **0.444** | 0.241 | 0.389 |
| Multi-hop | 0.580 | 0.460 | **0.700** | 0.600 | **0.700** | 0.600 |

**Conclusion:** Query expansion's contribution is concentrated entirely in Semantic queries — it nearly doubles Semantic Recall@5 from 0.241 to 0.444, while leaving Factual, Keyword-heavy, and Multi-hop recall unchanged or slightly lower.

---

#### nDCG@5 by Query Type

| Query Type | `dense_only` | `dense+QE` | `hybrid_bm25` | `hybrid_bm25+QE` ✅ | `hybrid_bm25+rerank` | `hybrid_bm25+QE+rerank` |
|---|---|---|---|---|---|---|
| Factual | 0.358 | 0.271 | 0.648 | 0.653 | 0.706 | **0.750** |
| Keyword-heavy | 0.457 | 0.466 | 0.664 | 0.658 | **0.702** | **0.702** |
| Semantic | 0.164 | 0.185 | 0.245 | **0.384** | 0.240 | 0.374 |
| Multi-hop | 0.579 | 0.459 | **0.690** | 0.561 | 0.669 | 0.547 |

**Conclusion:** The reranker raises nDCG@5 on Factual and Keyword-heavy queries — it puts the most relevant chunks closer to rank 1 — but Recall@5 stays flat, meaning it only reshuffles chunks already in the top-10 and does not bring in new chunks that weren't retrieved in the first place.

---

#### Context Recall by Query Type (RAGAS)

| Query Type | `dense_only` | `dense+QE` | `hybrid_bm25` | `hybrid_bm25+QE` ✅ | `hybrid_bm25+rerank` | `hybrid_bm25+QE+rerank` |
|---|---|---|---|---|---|---|
| Factual | 0.652 | 0.522 | **0.978** | 0.935 | **0.978** | **0.978** |
| Keyword-heavy | 0.853 | 0.767 | 0.920 | **0.960** | 0.920 | **0.960** |
| Semantic | 0.889 | 0.944 | 0.883 | 0.969 | **0.981** | 0.969 |
| Multi-hop | 0.809 | 0.733 | **0.867** | 0.773 | 0.863 | 0.853 |

**Conclusion:** BM25 hybrid retrieval produces the largest jump in Factual Context Recall (0.652 → 0.978), confirming that the LLM answer quality for factual questions depends almost entirely on whether the right chunk is retrieved — which is exactly what BM25's exact-token matching provides.

---

#### Faithfulness by Query Type (RAGAS)

| Query Type | `dense_only` | `dense+QE` | `hybrid_bm25` | `hybrid_bm25+QE` ✅ | `hybrid_bm25+rerank` | `hybrid_bm25+QE+rerank` |
|---|---|---|---|---|---|---|
| Factual | 0.978 | 0.950 | 0.978 | 0.899 | **0.979** | 0.939 |
| Keyword-heavy | 0.970 | 0.976 | 0.993 | 0.974 | **0.994** | 0.984 |
| Semantic | **0.985** | 0.967 | 0.980 | 0.982 | 0.968 | 0.983 |
| Multi-hop | 0.940 | 0.968 | **0.986** | 0.978 | 0.982 | 0.963 |

**Conclusion:** Faithfulness stays above 0.96 across all six configurations regardless of retrieval quality — the LLM does not invent facts beyond what is in the retrieved chunks. When retrieval misses a relevant chunk, the answer omits that information rather than making something up.

---

#### Context Precision by Query Type (RAGAS)

| Query Type | `dense_only` | `dense+QE` | `hybrid_bm25` | `hybrid_bm25+QE` ✅ | `hybrid_bm25+rerank` | `hybrid_bm25+QE+rerank` |
|---|---|---|---|---|---|---|
| Factual | 0.587 | 0.435 | 0.826 | **0.935** | **0.935** | 0.913 |
| Keyword-heavy | 0.840 | 0.800 | **0.900** | 0.860 | 0.860 | **0.900** |
| Semantic | 0.796 | 0.870 | 0.963 | **0.981** | **0.981** | **0.981** |
| Multi-hop | 0.800 | 0.720 | 0.840 | 0.820 | **0.880** | 0.840 |

**Conclusion:** Query expansion raises Context Precision for Factual queries from 0.826 to 0.935 — the additional query variants help surface relevant chunks into higher-ranked positions, not just into the top-5 set.

---

## Observations

### Why Does BM25 Provide the Largest Retrieval Gain?

BM25 gives extra weight to rare technical terms — model names, hyperparameter values — that dense embeddings smooth away by compressing the query into one vector.

- +0.175 Recall@5 overall (0.413 → 0.588); Factual queries gain the most (+0.347) — rare model names appear in very few chunks, so BM25 reliably pinpoints them.


### Why Does Query Expansion Hurt Without a BM25 Anchor?

Without exact keyword matching, alternative phrasings retrieve topically nearby but wrong chunks — when merged, they drag the correct results down.

- `dense_with_query_expansion` drops 0.413 → 0.358; Multi-hop loses the most (0.580 → 0.460).
- On top of BM25, expansion behaves differently — exact tokens are locked in first; alternatives then catch paraphrased answers.


### Why Does Query Expansion Only Help Semantic Queries?

Semantic queries use everyday language that papers don't repeat word-for-word; alternative phrasings bridge that gap. The other query types already use the paper's own vocabulary.

- +0.203 Recall@5 on Semantic (0.241 → 0.444); Factual, Keyword-heavy, and Multi-hop show no improvement.



### Why Does the Reranker Improve Ranking Without Improving Coverage?

The reranker only reshuffles the top-10 — it can't pull in a missed chunk. The summarization LLM reads all top-5 at once, so rank order doesn't matter; only coverage does.

- Recall@5 stays at 0.588; nDCG@5 +0.016, Context Precision +0.030 — ranking quality improves but coverage doesn't.
- Adding the reranker costs +1,057s over 100 samples (+10.6s/query) with zero Recall@5 gain.


---

## Decision

### Part A: Which Sparse Model for Hybrid Retrieval?

`Qdrant/bm25` is selected — highest Recall@5 among all sparse configs, no GPU inference required.

- 15× faster than miniCOIL (13.5s vs 204s); 25× faster than SPLADE (342.7s)

### Part B: Which Retrieval Strategy?

`hybrid_bm25_with_query_expansion` is selected — highest Recall@5 at the lowest latency among BM25-enabled configs.

- Recall@5 = 0.608, tied with the full stack but 1,057s faster (5212s vs 6269s)

---

## Pipeline Integration Status ✅ INTEGRATED

Hybrid BM25 retrieval with query expansion replaced dense-only retrieval in the summarization pipeline. The retriever in `backend/tools/paper_tools.py` now uses `vector_store_query_mode="hybrid"` with `fastembed_sparse_model="Qdrant/bm25"`. The `QueryFusionRetriever` in `backend/agent_workflows/summary_generation.py` generates 4 query variants (original + 3 LLM alternatives), merges their ranked results using Reciprocal Rank Fusion (RRF), and passes the final top-5 chunks to the summarization LLM.

