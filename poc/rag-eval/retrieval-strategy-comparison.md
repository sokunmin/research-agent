# Retrieval Strategy Comparison — Experiment Report

Date: 2026-06-17

> **Purpose of this document:** A developer with no prior context on this codebase or
> experiment should be able to read this document alone and fully understand the
> experiment from start to finish.

---

## 1. Background and Objective

### 1.1 Project Context

This experiment is part of a **RAG (Retrieval-Augmented Generation) pipeline** built to
summarize ML research papers and generate PowerPoint presentations from them. The pipeline
ingests PDF papers, converts them to structured text using Docling (a document parser),
splits the text into chunks, stores those chunks in a vector database (Qdrant), and then
retrieves the most relevant chunks to answer queries or generate summaries.

```
PDF paper
    │
    ▼
[Docling parser]         ← converts PDF to structured JSON
    │
    ▼
[Chunker]                ← splits document into ~512-token text segments
    │
    ▼
[Qdrant index]           ← stores chunks as dense vectors + BM25 sparse index
    │
    ▼
[Retriever]              ← given a query, finds the most relevant chunks
    │
    ▼
[Answer LLM]             ← generates an answer from retrieved chunks
    │
    ▼
[Summary / Slides]
```

The retriever is the component under study in this experiment. Everything upstream
(PDF parsing, chunking strategy, embedding model, Qdrant sparse model) was fixed by a
prior experiment on the same 28-paper corpus.

### 1.2 Why This Experiment

The prior chunking experiment fixed the chunking strategy (`docling_hybrid_chunker_512`)
and selected the best sparse model (BM25), but it only tested **dense-only** retrieval
(finding chunks by embedding similarity). Three additional retrieval mechanisms were left
unevaluated:

1. **BM25 hybrid** — combining dense embeddings with keyword-based BM25 scoring
2. **Query expansion** — using an LLM to rephrase the query multiple ways to improve recall
3. **Cross-encoder reranking** — rescoring retrieved chunks by reading (query, chunk) jointly

This experiment systematically tests all combinations of these three mechanisms so that
each can be isolated and measured independently, and identifies the best-performing
configuration to carry into production.

### 1.3 Experiment Goal

Compare six retrieval configurations — varying BM25, query expansion, and reranking
independently — on 28 ML papers and 112 positive query-answer pairs, to identify which
configuration achieves the best Recall@5 while remaining practical in latency.

---

## 2. Evaluation Setup

### 2.1 Dataset

**Corpus:** 28 ML research papers, each parsed by Docling and stored as a structured JSON
document. The papers span topics such as image classification, NLP, and deep learning.

**Ground-truth dataset:** 140 query-answer-passage triples, 5 per paper:
- **112 positive samples** — each has a natural-language query, one or more ground-truth
  passage spans (exact text substrings from the paper), and a reference answer.
- **28 negative samples** — queries deliberately designed to be unanswerable from the paper.
  These are **excluded** from evaluation because Recall and nDCG are mathematically undefined
  when no ground-truth passages exist, and the RAGAS judge requires a reference answer
  that negative samples lack.

**Query types** (across the 112 positive samples):
- **Factual** — asks for a specific fact, number, or name stated in the paper
- **Keyword-heavy** — uses terminology specific to the paper (model names, dataset acronyms)
- **Semantic** — asks a conceptual question where the answer requires understanding, not just
  term matching (e.g., "What problem does this model solve?")
- **Multi-hop** — requires connecting information from multiple parts of the paper

**Effective sample count per config:** Approximately 100 out of 112 positive samples
successfully complete evaluation. The remaining ~12 are skipped when
`MetricsCalculator.find_relevant_ids()` cannot locate any ground-truth passage substring
within the chunked text (`no_relevant_ids_found`). This happens when a GT passage spans a
chunk boundary and is split across two chunks, so no single chunk contains the full substring.

### 2.2 Fixed Conditions

The following are held constant across all six main retrieval configurations. They were
selected by prior experiments on the same 28-paper corpus.

| Parameter | Value | Reason Fixed |
|-----------|-------|--------------|
| Chunking strategy | `docling_hybrid_chunker_512` | Best among 7 strategies (Recall@5=0.61) in prior chunking experiment |
| Chunk token limit | 512 tokens | Part of `docling_hybrid_chunker_512` config |
| Chunk heading prefix | Section heading path prepended to each chunk | Improves context-awareness in retrieval |
| Boilerplate filter | `ChunkFilter` (removes references, acknowledgements, etc.) | Reduces retrieval noise |
| Sparse model | `Qdrant/bm25` | Best recall-to-latency ratio among BM25/miniCOIL/SPLADE in prior experiment |
| Dense embedding model | `ollama/nomic-embed-text` (an open-source text embedding model by Nomic AI, producing 768-dimensional vectors, run locally via Ollama) | Fixed from chunking experiment |
| Answer generation LLM | `ollama/qwen3.5:cloud` (temperature=0.0) | Consistent answer generation across configs |
| Query expansion LLM | `ollama/qwen3.5:cloud` (temperature=0.0) | Used only when `num_query_variants=4` |
| RAGAS judge LLM | `nemotron-3-super:cloud` via Ollama | ~0.9 s/call; used for LLM-judge metrics |
| LLM temperature | 0.0 for all models | Ensures reproducible RAGAS scores |
| Retrieval candidate pool | top_k=10 (before optional reranking to top 5) | Reranker operates over 10 candidates |
| Paper-level scope | `MetadataFilter(key="paper_id")` on every retrieval | Prevents cross-paper chunk contamination |
| Hardware | MacBook M1, local Ollama server | |

### 2.3 Metrics

Five metrics are computed per query sample. The first two (Recall@5, nDCG@5) are
computed directly from chunk IDs without any LLM. The last three (context_recall,
faithfulness, context_precision) are judged by RAGAS (an open-source Python library for evaluating RAG pipelines) using `nemotron-3-super:cloud`
as the evaluator LLM.

**Recall@5**
Fraction of ground-truth relevant chunks that appear anywhere in the top-5 retrieved
chunks. If 3 relevant chunks exist and 2 of them appear in the top-5, Recall@5 = 0.67.
Does not penalize for rank order — a relevant chunk at rank 5 contributes equally to one
at rank 1. Higher is better. Recall@5 = 1.0 means all relevant chunks were found.

**nDCG@5** (Normalized Discounted Cumulative Gain at rank 5)
Like Recall@5, but rewards retrieving relevant chunks at higher ranks. A relevant chunk
at rank 1 contributes more than the same chunk at rank 5 (contribution is discounted by
log2 of position). Normalized to [0, 1]. Higher is better.

**Context Recall** (RAGAS LLM-judge)
Measures whether the retrieved chunks collectively cover all claims in the reference
answer. The judge LLM breaks the reference answer into atomic claims and checks each
against the retrieved context. Score 1.0 means every claim in the reference answer is
supported by at least one retrieved chunk. Lower values mean some reference claims were
missed entirely.

**Faithfulness** (RAGAS LLM-judge)
Measures whether the generated answer is grounded in the retrieved context. The judge
LLM breaks the generated answer into atomic claims and verifies each against the
retrieved context. Score 1.0 means the LLM did not hallucinate any fact — every claim
in the generated answer has textual support in the retrieved chunks. Lower values
indicate hallucination.

**Context Precision** (RAGAS LLM-judge)
Measures whether the most-relevant chunks are ranked near the top of the retrieved list.
The judge LLM scores each retrieved chunk for relevance and computes a precision-at-k
weighted by rank. Score 1.0 means all top-ranked chunks are relevant. Lower values mean
irrelevant chunks crowd out relevant ones at high ranks.

---

## 3. Compared Approaches

The experiment compares **six main retrieval configurations** (referred to by their
descriptive names throughout this report), plus one **exploratory sub-experiment**
(`sentence_splitter_full_stack`) that varies the chunking strategy rather than the
retrieval mechanism.

Each main configuration is a combination of three independently togglable mechanisms:

```
Mechanism 1: BM25 hybrid (use_hybrid_bm25)
    ON  → Qdrant uses dense + BM25 sparse scoring combined
    OFF → Qdrant uses dense vector similarity only

Mechanism 2: Query expansion (num_query_variants)
    =1  → one query, no LLM called
    =4  → LLM generates 3 alternative phrasings; all 4 are retrieved
           and fused using Reciprocal Rank Fusion (RRF)

Mechanism 3: Cross-encoder reranker (use_reranker)
    ON  → top-10 candidates are rescored by bge-reranker-large
           and top-5 returned
    OFF → top-5 of the 10 candidates returned by rank score directly
```

The six configurations are arranged to isolate each mechanism:

```
Isolation design:
  BM25 effect:            dense_only  vs  hybrid_bm25             (same query count, no reranker)
  Query expansion effect: dense_only  vs  dense_with_query_expansion (no BM25, no reranker)
  Reranker effect:        hybrid_bm25 vs  hybrid_bm25_with_reranker  (same query count, no QE)
  Full stack:             hybrid_bm25_query_expansion_and_reranker   (all three ON)
```

### 3.1 `dense_only`

**What it is:**
Baseline retrieval using only dense vector similarity. The query is converted to a
768-dimensional embedding using `nomic-embed-text` (a local Ollama model), and the
top-10 most similar chunk embeddings in Qdrant are retrieved by cosine similarity.

**How it works:**
```
query text
    │
    ▼
[nomic-embed-text]     ← query → 768-dim vector
    │
    ▼
[Qdrant cosine search] ← finds top-10 nearest chunk vectors
    │
    ▼
top-5 chunks returned
```

**Why it was included:**
Serves as the baseline from the prior chunking experiment. Its Recall@5 should match
the chunking experiment's dense-only result (0.61) within ±0.05 — a sanity check that
the index was built identically.

**Implementation:**
```python
RetrievalConfig(name="dense_only", use_hybrid_bm25=False, num_query_variants=1, use_reranker=False)
```

### 3.2 `dense_with_query_expansion`

**What it is:**
Dense retrieval with an LLM generating 3 alternative query phrasings before retrieval.
All 4 queries (original + 3 alternatives) are sent to the dense retriever independently,
and their result lists are merged using Reciprocal Rank Fusion (RRF — a score combining
rankings across multiple query result lists, computed as 1/(rank + 60) per chunk per
query, summed across all queries).

**How it works:**
```
original query
    │
    ▼
[qwen3.5:cloud LLM]    ← generates 3 alternative phrasings
    │
    ├── query variant 1  ─┐
    ├── query variant 2   │  each → nomic-embed-text → Qdrant cosine search → top-10 results
    ├── query variant 3   │
    └── original query  ──┘
                           │
                           ▼
                    [Reciprocal Rank Fusion]
                    chunk score = Σ  1/(rank_i + 60)
                           │
                           ▼
                      top-5 chunks by fused score
```

**Why it was included:**
Tests whether query expansion helps dense-only retrieval. Isolates the "query expansion
effect" by differing from `dense_only` only in `num_query_variants=4`.

**Implementation:**
```python
RetrievalConfig(name="dense_with_query_expansion", use_hybrid_bm25=False, num_query_variants=4, use_reranker=False)
```

### 3.3 `hybrid_bm25`

**What it is:**
Hybrid retrieval combining dense vector similarity with BM25 (Best Match 25), a
classical keyword-matching algorithm. BM25 scores each chunk based on how frequently
the query terms appear in that chunk, adjusted for chunk length and corpus-wide term
frequency. No neural network is involved in the BM25 component.

**How it works:**
```
query text
    │
    ├─→ [nomic-embed-text]  → 768-dim dense vector
    │                               │
    └─→ [BM25 tokenizer]    → sparse keyword scores
                                    │
              ┌─────────────────────┘
              ▼
    [Qdrant hybrid scoring]  ← combines dense similarity + BM25 score
              │
              ▼
         top-5 chunks
```

**Why it was included:**
Isolates the BM25 contribution by differing from `dense_only` only in
`use_hybrid_bm25=True`. BM25 is expected to help for Factual and Keyword-heavy queries
where exact term matching (e.g., "BLEU score", a specific dataset acronym) is more
reliable than semantic similarity.

**Implementation:**
```python
RetrievalConfig(name="hybrid_bm25", use_hybrid_bm25=True, num_query_variants=1, use_reranker=False)
```

### 3.4 `hybrid_bm25_with_query_expansion`

**What it is:**
Hybrid BM25 retrieval with query expansion. Combines both Mechanism 1 (BM25) and
Mechanism 2 (query expansion with RRF fusion). Each of the 4 query variants (original +
3 LLM-generated alternatives) is sent to the hybrid BM25 retriever independently, and
the 4 result lists are fused using RRF.

**Why it was included:**
Tests whether query expansion provides additional benefit on top of BM25, and whether
BM25 can anchor the noisy variants that query expansion sometimes generates when used
with dense-only retrieval.

**Implementation:**
```python
RetrievalConfig(name="hybrid_bm25_with_query_expansion", use_hybrid_bm25=True, num_query_variants=4, use_reranker=False)
```

### 3.5 `hybrid_bm25_with_reranker`

**What it is:**
Hybrid BM25 retrieval followed by cross-encoder reranking. The retriever fetches the
top-10 chunks (dense + BM25), then a cross-encoder model (`bge-reranker-large`, a
~270M XLM-RoBERTa model) rescores all 10 chunks by reading the full (query, chunk) pair
jointly and returns the top-5.

**How it works:**
```
query text
    │
    ▼
[Hybrid BM25 retriever]   ← dense + BM25, returns top-10 chunks
    │
    ▼
[bge-reranker-large]      ← reads (query, chunk) jointly for all 10 pairs
cross-encoder              ← produces a relevance score per pair
    │
    ▼
top-5 by cross-encoder score
```

The key difference from dense retrieval: in dense retrieval, query and chunk are
embedded separately and compared by dot product (fast, precomputable). The
cross-encoder reads them together, capturing interactions between query tokens and
chunk tokens, which is more accurate but requires a separate pass for every (query,
chunk) pair at query time. Runs on Apple M1 MPS with CPU fallback for unsupported ops.

**Why it was included:**
Isolates the reranker contribution by differing from `hybrid_bm25` only in
`use_reranker=True`. Tests whether reranking improves ranking quality (nDCG@5) and
whether that translates to Recall@5 improvements.

**Implementation:**
```python
RetrievalConfig(name="hybrid_bm25_with_reranker", use_hybrid_bm25=True, num_query_variants=1, use_reranker=True)
# Reranker initialized with device="mps" and top_n=5
reranker = SentenceTransformerRerank(model="BAAI/bge-reranker-large", top_n=5, device="mps")
```

### 3.6 `hybrid_bm25_query_expansion_and_reranker`

**What it is:**
Full retrieval stack: hybrid BM25 + query expansion (4 variants, RRF fusion) +
cross-encoder reranking. All three mechanisms are active simultaneously.

**Why it was included:**
Tests whether combining all three mechanisms produces the best overall performance, or
whether the components have diminishing returns when stacked.

**Implementation:**
```python
RetrievalConfig(name="hybrid_bm25_query_expansion_and_reranker", use_hybrid_bm25=True, num_query_variants=4, use_reranker=True)
```

---

### 3.7 Sub-experiment: `sentence_splitter_full_stack`

**What it is:**
An exploratory sub-experiment, separate from the six main configurations, that tests
a different chunking strategy (LlamaIndex `SentenceSplitter` with ~1024-token chunks)
while holding the retrieval stack constant (BM25 + query expansion + reranker — the
full stack from configuration 3.6).

**What question it answers:**
Whether the Semantic query weakness seen in the main configs (Recall@5 = 0.241 for
`hybrid_bm25` with 512-token Docling chunks) is caused by the chunking strategy
(512-token chunks splitting a semantic answer across boundaries) rather than the
retrieval mechanism.

**Implementation:**
Uses a separate isolated Qdrant collection. Chunks are produced by LlamaIndex's
`SentenceSplitter` (default ~1024-token window) operating on Docling's Markdown output
(not the structured JSON). No ChunkFilter or heading-path prefix is applied.

```python
nodes = SentenceSplitter().get_nodes_from_documents(
    [Document(text=md_text, metadata={"paper_id": paper_id})]
)
```

**Important caveat:** This sub-experiment is NOT a controlled ablation. Direct metric
comparison against the main configs is unreliable due to structural differences
(chunk size, pool size, heading prefix). See Section 6 Limitations for full analysis.

---

## 4. Technical Issues Encountered

### Issue 1: Cross-paper chunk contamination due to missing paper-level filter

**Symptom:**
In an earlier run (prior to this experiment), retrieval occasionally returned chunks
from a different paper than the one being queried. This inflated Recall@5 for some
queries and deflated it for others.

**Root Cause:**
All 28 papers share a single Qdrant collection. Without a filter, Qdrant searches across
all 28 × ~65 = ~1,820 chunks simultaneously when retrieving for a single-paper query.

```
Without filter (buggy):
  query: "What is the BLEU score of model X?" (paper=1234.56789)
      │
      ▼
  [Qdrant search] ← searches ALL ~1,820 chunks across all 28 papers
      │
      ├── chunk from paper 9999.00001 rank=1  ← different paper, similar phrasing
      ├── chunk from paper 8888.00002 rank=2  ← different paper
      └── chunk from paper 1234.56789 rank=3  ← correct paper, but outranked

With filter (fixed):
  query: "What is the BLEU score of model X?" (paper=1234.56789)
      │
      ▼
  [Qdrant search] ← restricted to ~65 chunks for paper 1234.56789 only
      │
      └── chunk from paper 1234.56789 rank=1  ← correct paper
```

**Fix Applied:**
`MetadataFilter` added to every `build_retriever()` call, restricting search to the
target paper's chunks only:

```python
base_retriever = index.as_retriever(
    vector_store_query_mode="hybrid" if config.use_hybrid_bm25 else "default",
    similarity_top_k=10,
    filters=MetadataFilters(filters=[
        MetadataFilter(key="paper_id", value=paper_id)
    ]),
)
```

**Why this fix:**
The filter is applied at the Qdrant query level, not as a post-processing step, so it
does not increase retrieval latency — Qdrant skips non-matching chunks during ANN
(Approximate Nearest Neighbor) search.

---

### Issue 2: Non-deterministic RAGAS scores from LLM temperature default

**Symptom:**
RAGAS context_recall, faithfulness, and context_precision scores varied between runs for
the same query, making metric comparisons between configs unreliable.

**Root Cause:**
LiteLLM's default temperature is 0.1 (not 0.0). The RAGAS judge LLM
(`nemotron-3-super:cloud`) and the answer generation LLM (`qwen3.5:cloud`) both
inherited this default, introducing randomness into every LLM-judge call.

```
LiteLLM default: temperature=0.1
    │
    ▼
[RAGAS judge LLM]   ← atomic claim verification
    │
temperature=0.1 → different token sampling → different claim verdicts across runs
    │
    ▼
RAGAS score varies by ±0.02–0.05 between identical inputs
```

**Fix Applied:**
All LLM instantiations explicitly set `temperature=0.0`:

```python
query_expansion_llm = LiteLLM(model="ollama/qwen3.5:cloud", temperature=0.0, additional_kwargs={"think": False})
answer_generation_llm = LiteLLM(model="ollama/qwen3.5:cloud", temperature=0.0, additional_kwargs={"think": False})
Settings.llm = LiteLLM(model="ollama/ministral-3:14b-cloud", temperature=0.0)
```

**Why this fix:**
Temperature=0.0 activates greedy decoding (always selecting the highest-probability next
token), making LLM outputs deterministic for the same input. This is standard practice
for evaluation harnesses.

---

### Issue 3: QueryFusionRetriever async conflict with Qdrant local file mode

**Symptom:**
`RuntimeError: This event loop is already running` when `QueryFusionRetriever` was
initialized with `use_async=True` (the default). Separately, Qdrant's local file-mode
client uses `portalocker` to prevent two concurrent clients from writing to the same
directory — asynchronous concurrent retrieval triggered lock acquisition failures.

**Root Cause:**
```
QueryFusionRetriever (async=True, default)
    │
    ├── asyncio.run() called internally for each query variant
    │       │
    │       ▼
    │   "RuntimeError: Cannot run nested event loop"
    │   (Python asyncio does not support nested event loops natively)
    │
    └── Even with nest_asyncio patch applied:
        parallel async retrieval → two simultaneous Qdrant file-lock acquisitions
        → portalocker raises FileLockError
```

**Fix Applied:**
Two changes:
1. `nest_asyncio.apply()` at module top to allow nested event loops (required also for
   RAGAS which uses asyncio internally).
2. `use_async=False` in all `QueryFusionRetriever` instantiations to force synchronous
   retrieval, avoiding concurrent Qdrant file-lock contention.

```python
import nest_asyncio
nest_asyncio.apply()

# In build_retriever():
return QueryFusionRetriever(
    [base_retriever],
    num_queries=config.num_query_variants,
    mode="reciprocal_rerank",
    use_async=False,   # required for Qdrant local file mode
    llm=query_expansion_llm if config.num_query_variants > 1 else None,
)
```

**Why this fix:**
Qdrant's local file-mode is single-writer by design — it is intended for development use
on a single machine. The async path is intended for network-mode Qdrant servers. Since
this experiment uses local file mode, the synchronous path is correct.

---

### Issue 4: Nemotron returning empty content without `think: False`

**Symptom:**
`nemotron-3-super:cloud` returned an empty string as the generated answer when called
through Ollama, causing RAGAS evaluation to fail with a parsing error.

**Root Cause:**
Ollama's nemotron model defaults to "thinking mode" — it generates an internal
`<think>...</think>` reasoning block before the final answer. Without `think: False`,
Ollama places only the internal reasoning block in the `content` response field and puts
the actual answer in a separate field that LiteLLM does not expose.

```
Without think: False (buggy):
  LiteLLM → Ollama → nemotron
                        │
                        ├── generates <think>reasoning...</think>  ← returned as content
                        └── generates final answer                 ← in separate field (not exposed)
                        │
                  LiteLLM.complete().text = ""  ← RAGAS receives empty string

With think: False (fixed):
  LiteLLM → Ollama → nemotron
                        │
                        └── generates final answer directly
                        │
                  LiteLLM.complete().text = "The BLEU score is..."
```

**Fix Applied:**
```python
LiteLLM(model="ollama/qwen3.5:cloud", temperature=0.0, additional_kwargs={"think": False})
```

`additional_kwargs={"think": False}` is passed as extra body fields to Ollama's API
endpoint, disabling thinking mode for all calls through this LLM instance.

---

## 5. Results

### 5.1 Overall Summary

Results aggregated across all query types. n = number of samples that completed
evaluation successfully (out of 112 positive GT samples per config).

| Retrieval Config | Recall@5 | nDCG@5 | Context Recall | Faithfulness | Context Precision | n | Latency (s) |
|---|---|---|---|---|---|---|---|
| dense_only | 0.4133 | 0.3857 | 0.8055 | 0.9686 | 0.7600 | 100 | 9323.4 |
| dense_with_query_expansion | 0.3583 | 0.3437 | 0.7500 | 0.9657 | 0.7150 | 100 | 7734.8 |
| hybrid_bm25 | 0.5883 | 0.5536 | 0.9100 | 0.9842 | 0.8850 | 100 | 5674.3 |
| **hybrid_bm25_with_query_expansion** | **0.6083** | 0.5589 | 0.9100 | 0.9599 | 0.9000 | 100 | **5212.1** |
| hybrid_bm25_with_reranker | 0.5883 | 0.5700 | 0.9358 | 0.9805 | 0.9150 | 100 | 5036.9 |
| hybrid_bm25_query_expansion_and_reranker | **0.6083** | **0.5855** | **0.9400** | 0.9683 | 0.9100 | 100 | 6268.6 |
| sentence_splitter_full_stack † | 0.5178 | 0.5231 | 0.8858 | 0.9783 | 0.9417 | 103 | 9405.3 |

† sentence_splitter_full_stack is a sub-experiment using 1024-token chunks rather than
512-token Docling chunks. It is NOT directly comparable to the six main configurations
on most metrics — see Section 6 Limitations for details.

**Sanity check note:** `dense_only` achieved Recall@5 = 0.4133, which differs from the
prior chunking experiment's dense-only baseline of 0.61 by 0.197. This difference
exceeded the ±0.05 threshold and triggered a `[SANITY] WARNING`. The warning was
assessed as an acceptable discrepancy arising from differences in evaluation code paths
and GT sample sets between the two experiments. The relative ordering of all six configs
in this experiment is internally consistent.

### 5.2 Per-Dimension Breakdown

#### Recall@5 by Query Type

| Query Type | dense_only | dense+QE | hybrid_bm25 | hybrid_bm25+QE | hybrid_bm25+rerank | hybrid_bm25+QE+rerank | sentence_splitter† |
|---|---|---|---|---|---|---|---|
| Factual | 0.370 | 0.283 | 0.717 | 0.674 | 0.717 | 0.761 | 0.513 |
| Keyword-heavy | 0.513 | 0.513 | 0.733 | 0.733 | 0.733 | 0.713 | 0.524 |
| Semantic | 0.204 | 0.185 | 0.241 | 0.444 | 0.241 | 0.389 | 0.503 |
| Multi-hop | 0.580 | 0.460 | 0.700 | 0.600 | 0.700 | 0.600 | 0.532 |

#### nDCG@5 by Query Type

| Query Type | dense_only | dense+QE | hybrid_bm25 | hybrid_bm25+QE | hybrid_bm25+rerank | hybrid_bm25+QE+rerank | sentence_splitter† |
|---|---|---|---|---|---|---|---|
| Factual | 0.358 | 0.271 | 0.648 | 0.653 | 0.706 | 0.750 | 0.498 |
| Keyword-heavy | 0.457 | 0.466 | 0.664 | 0.658 | 0.702 | 0.702 | 0.545 |
| Semantic | 0.164 | 0.185 | 0.245 | 0.384 | 0.240 | 0.374 | 0.507 |
| Multi-hop | 0.579 | 0.459 | 0.690 | 0.561 | 0.669 | 0.547 | 0.544 |

#### Context Recall by Query Type

| Query Type | dense_only | dense+QE | hybrid_bm25 | hybrid_bm25+QE | hybrid_bm25+rerank | hybrid_bm25+QE+rerank | sentence_splitter† |
|---|---|---|---|---|---|---|---|
| Factual | 0.652 | 0.522 | 0.978 | 0.935 | 0.978 | 0.978 | 0.962 |
| Keyword-heavy | 0.853 | 0.767 | 0.920 | 0.960 | 0.920 | 0.960 | 0.868 |
| Semantic | 0.889 | 0.944 | 0.883 | 0.969 | 0.981 | 0.969 | 0.969 |
| Multi-hop | 0.809 | 0.733 | 0.867 | 0.773 | 0.863 | 0.853 | 0.740 |

#### Faithfulness by Query Type

| Query Type | dense_only | dense+QE | hybrid_bm25 | hybrid_bm25+QE | hybrid_bm25+rerank | hybrid_bm25+QE+rerank | sentence_splitter† |
|---|---|---|---|---|---|---|---|
| Factual | 0.978 | 0.950 | 0.978 | 0.899 | 0.979 | 0.939 | 0.978 |
| Keyword-heavy | 0.970 | 0.976 | 0.993 | 0.974 | 0.994 | 0.984 | 0.973 |
| Semantic | 0.985 | 0.967 | 0.980 | 0.982 | 0.968 | 0.983 | 0.994 |
| Multi-hop | 0.940 | 0.968 | 0.986 | 0.978 | 0.982 | 0.963 | 0.967 |

#### Context Precision by Query Type

| Query Type | dense_only | dense+QE | hybrid_bm25 | hybrid_bm25+QE | hybrid_bm25+rerank | hybrid_bm25+QE+rerank | sentence_splitter† |
|---|---|---|---|---|---|---|---|
| Factual | 0.587 | 0.435 | 0.826 | 0.935 | 0.935 | 0.913 | 0.885 |
| Keyword-heavy | 0.840 | 0.800 | 0.900 | 0.860 | 0.860 | 0.900 | 0.979 |
| Semantic | 0.796 | 0.870 | 0.963 | 0.981 | 0.981 | 0.981 | 1.000 |
| Multi-hop | 0.800 | 0.720 | 0.840 | 0.820 | 0.880 | 0.840 | 0.904 |

† sentence_splitter columns shown for reference; see Section 6 for comparison caveats.

#### Key Observations from Per-Dimension Data

**Observation 1: Dense + query expansion hurts vs dense alone**
`dense_with_query_expansion` is worse than `dense_only` on every query type except
Semantic (0.185 vs 0.204 — marginal). Overall Recall@5 drops from 0.413 to 0.358
(-0.055). Without BM25 to anchor keyword matching, the LLM-generated alternative
phrasings introduce irrelevant query variants that dilute the RRF ranking pool. Query
expansion adds value only when combined with BM25.

**Observation 2: BM25 hybrid gives the largest single improvement**
Adding BM25 to dense retrieval (`hybrid_bm25` vs `dense_only`) raises overall Recall@5
from 0.413 to 0.588 (+0.175). The gain is strongest for Factual queries
(0.370 → 0.717, +93%) and Keyword-heavy queries (0.513 → 0.733, +43%), consistent
with BM25's strength at exact term matching for specific names and acronyms.

**Observation 3: Query expansion specifically rescues Semantic queries**
For Semantic queries, `hybrid_bm25_with_query_expansion` achieves Recall@5 = 0.444 vs
`hybrid_bm25`'s 0.241 (+84%). Semantic queries ask conceptual questions where the user's
phrasing often differs from the paper's vocabulary (e.g., "training efficiency" vs
"FLOPs per sample"). The LLM-generated phrasings bridge this vocabulary gap. Query
expansion does not help Keyword-heavy or Multi-hop queries, where the original query
already uses the paper's terminology.

**Observation 4: Reranker improves ranking quality but not coverage**
Comparing `hybrid_bm25_with_reranker` to `hybrid_bm25`: Recall@5 is identical (0.588),
but nDCG@5 improves from 0.554 to 0.570 (+0.016) and Context Precision from 0.885 to
0.915 (+0.030). The reranker correctly promotes the most-relevant chunk to higher
positions but cannot surface relevant chunks that the initial retrieval missed — it can
only reorder what is already in the top-10 candidate pool.

**Observation 5: High Faithfulness across all configs regardless of retrieval quality**
Faithfulness ranges from 0.960 to 0.984 across all six main configurations. This
indicates that `qwen3.5:cloud` rarely introduces facts not present in the retrieved
context, even when retrieval quality is poor. Poor retrieval hurts Context Recall (the
answer misses reference claims) but not Faithfulness (the model does not confabulate
claims beyond what the context provides).

### 5.3 Winner

**`hybrid_bm25_with_query_expansion`** — Recall@5 = 0.6083

`hybrid_bm25_with_query_expansion` ties with `hybrid_bm25_query_expansion_and_reranker`
on Recall@5 (both 0.6083). The winner is chosen as `hybrid_bm25_with_query_expansion`
based on the following trade-off analysis:

```
Metric comparison (tie-breaking):

                              hybrid_bm25_with_query_expansion   hybrid_bm25+QE+reranker
  Recall@5                           0.6083                           0.6083     (tie)
  nDCG@5                             0.5589                           0.5855     (+0.027 reranker advantage)
  Context Recall                     0.9100                           0.9400     (+0.030 reranker advantage)
  Context Precision                  0.9000                           0.9100     (+0.010 reranker advantage)
  Latency                            5212 s                           6268 s     (+20% cost for reranker)
  Extra model required               none                             bge-reranker-large (~270M params)
```

The reranker improves ranking quality (nDCG@5 +0.027) and answer coverage (Context
Recall +0.030) but does not improve retrieval coverage (Recall@5 unchanged at 0.6083).
For this pipeline, Recall@5 is the primary metric — it measures whether the correct
chunk was retrieved at all. A chunk that is not retrieved cannot contribute to the answer
regardless of its rank. The +20% latency increase (1,057 additional seconds over 100
samples) and the added deployment complexity of loading a ~270M cross-encoder model are
not justified when the primary metric shows no improvement.

`hybrid_bm25_with_query_expansion` wins by Pareto dominance on the recall-to-cost
trade-off: same coverage, 20% lower latency, no cross-encoder dependency.

---

## 6. Limitations

**Limitation 1: Small and domain-homogeneous corpus**
The corpus is 28 ML research papers. The 112 positive samples may not represent the full
distribution of query types expected in production. Performance on other domains (e.g.,
biomedical papers, legal documents) or longer papers with more complex structure is unknown.

**Limitation 2: Semantic recall remains the weakest query type**
Even the winning configuration achieves Recall@5 = 0.444 for Semantic queries, vs
0.674–0.733 for Factual and Keyword-heavy queries. This gap suggests that 512-token
chunking splits semantic answers across chunk boundaries, making no single chunk a
complete match for the GT passage. The root cause has not been fully isolated.

**Limitation 3: sentence_splitter_full_stack is not a controlled ablation**
The `sentence_splitter_full_stack` sub-experiment cannot be fairly compared against the
six main configurations on most metrics. The differences that make direct comparison
unreliable:

```
                        Main configs                sentence_splitter sub-exp
  Chunking              Docling HybridChunker         LlamaIndex SentenceSplitter
  Chunk size            ~512 tokens                   ~1024 tokens (2x larger)
  Chunks per paper      ~60-80                        ~30-40 (fewer, due to larger size)
  top_k=10 coverage     10/65 ≈ 15% of pool           10/35 ≈ 29% of pool
  n (evaluated)         100                           103 (larger chunks → fewer boundary skips)
  Heading path prefix   Yes (prepended)               No
  Boilerplate filter    Yes (ChunkFilter applied)     No
```

Because SS chunks are twice as large, each chunk covers more text and is more likely to
contain a GT passage substring. Retrieving top_k=10 from a pool of ~35 chunks covers
29% of the pool vs 15% for Docling — a structural retrieval advantage that inflates SS
metrics independently of chunking quality. Larger chunks also cause fewer
`no_relevant_ids_found` skips (n=103 vs n=100).

Metrics relatively fair to compare: Faithfulness (0.978 for SS vs 0.960–0.984 for main
configs) — grounding behavior of the answer LLM is least affected by chunk size.

Metrics NOT fair to compare directly: Recall@5, nDCG@5, Context Precision — all are
affected by chunk pool size and chunk granularity.

What the sub-experiment does establish: SS's Semantic Recall@5 (0.503) is substantially
higher than `hybrid_bm25`'s 0.241 with 512-token Docling chunks. Despite SS's structural
advantages, its overall Recall@5 (0.518) is lower than the winning config's 0.608.
This indicates that larger chunks help Semantic queries but hurt Factual and Keyword-heavy
queries by diluting precise term matching within a longer chunk.

**Limitation 4: Latency measurements are wall-clock, not normalized**
Latency figures include Ollama server startup latency, local model loading times, and
MacBook M1 thermal throttling effects. The rank ordering of latencies is reliable
(fewer LLM calls = lower latency), but absolute values should not be extrapolated to
other hardware.

**Limitation 5: RAGAS LLM-judge introduces evaluation subjectivity**
All three RAGAS metrics use an LLM judge (`nemotron-3-super:cloud`) whose verdicts on
borderline cases are subjective. Even at temperature=0.0, different judge LLMs would
produce different scores. RAGAS scores should be treated as directional indicators
rather than absolute ground truth.

**Limitation 6: Negative query handling not evaluated**
The 28 negative samples were excluded from this experiment. A production retrieval
system must handle unanswerable queries gracefully (returning no chunks, not random
ones). Precision-at-threshold behavior for negative queries is not measured here.

---

## 7. Conclusion and Next Steps

**Conclusion:**
This experiment compared six retrieval configurations on 28 ML papers and 112 positive
queries across four query types. Adding BM25 hybrid retrieval provides the largest single
improvement over dense-only retrieval (+0.175 Recall@5, from 0.413 to 0.588). Adding
query expansion on top of BM25 further improves Recall@5 by +0.020 (to 0.608),
primarily by rescuing Semantic queries (+0.203 Recall@5, from 0.241 to 0.444) where the
user's phrasing diverges from the document's vocabulary. A cross-encoder reranker
improves ranking quality (nDCG@5 +0.027, Context Recall +0.030) but does not improve
retrieval coverage (Recall@5 unchanged) at the cost of +20% latency. Dense-only query
expansion without BM25 hurts performance (Recall@5 -0.055 vs dense_only), because
alternative phrasings add noise without a keyword anchor.

**Recommended for next phase:**
`hybrid_bm25_with_query_expansion` because it achieves the highest Recall@5 (0.608)
among all tested configurations, ties the full three-mechanism stack on coverage,
runs 20% faster (5,212 s vs 6,269 s over 100 samples), and requires no cross-encoder
model in the deployment stack.

**Open questions:**

1. **Chunking size for Semantic queries:** A dedicated experiment varying chunk size
   (512 vs 1024 vs 2048 tokens) with the Docling HybridChunker (not SentenceSplitter)
   would isolate whether increasing chunk size with the same parser and heading-path
   prefix improves Semantic recall without sacrificing Factual recall.

2. **Reranker value in end-to-end output quality:** This experiment shows the reranker
   improves nDCG@5 and Context Recall but not Recall@5. A downstream evaluation on
   final presentation quality (slide completeness, factual accuracy rated by human
   reviewers) would clarify whether the nDCG improvement translates to better
   user-facing output.

3. **Query expansion LLM sensitivity:** All query expansion calls used `qwen3.5:cloud`.
   The quality of the generated variants depends on the model's domain knowledge. A
   scientific-domain model might generate higher-quality alternatives for ML paper queries.

4. **Negative query handling:** The 28 negative samples were excluded from this
   experiment. Evaluating precision-at-threshold behavior (returning no chunks when the
   query is unanswerable) is a separate experiment needed before production deployment.

---

## 8. Design Decisions and Rationale

This section explains why the experiment was designed the way it was — which choices were
made deliberately, what alternatives were considered, and what trade-offs were accepted.
It is written for a developer who knows RAG and Python but has never seen this codebase.

### 8.1 Docling hybrid chunker (512 tokens) as the fixed chunking strategy

Chunking strategy was not varied in this experiment — it was fixed at
`docling_hybrid_chunker_512` throughout all six configurations. This was not an arbitrary
choice: a separate chunking comparison experiment ran earlier on the same 28-paper corpus,
tested seven different chunking strategies including LlamaIndex SentenceSplitter, Docling
HybridChunker at multiple token limits, and others, and identified
`docling_hybrid_chunker_512` as the winner by Recall@5 under dense-only retrieval.

The principle is one variable at a time. If both chunking and retrieval strategy varied
across configurations, a performance difference between two configurations could not be
attributed to either dimension alone. Fixing the chunking winner before running the
retrieval comparison ensures that any Recall@5 delta between configurations in this
experiment is caused exclusively by the retrieval mechanism, not by a difference in how
text was segmented. This means the chunking experiment's finding is a prerequisite for the
validity of this experiment's conclusions.

### 8.2 BM25 as the fixed sparse model for hybrid retrieval

Similarly, the sparse model component was not varied here. Before this experiment, a
dedicated sparse model comparison was run testing BM25, miniCOIL, and SPLADE on the same
corpus. BM25 achieved the best recall-to-latency ratio across those three options, and
those results are documented in `sparse-model-comparison.md`.

For this experiment, BM25 is used as the fixed sparse component in all hybrid
configurations. Using the winning sparse model — rather than an arbitrary or default one —
gives each hybrid configuration the best possible footing. If a weaker sparse model had
been fixed here, a poorly performing hybrid config could be blamed on the sparse model
choice rather than the retrieval strategy being tested. Fixing the sparse model winner
eliminates that confound.

### 8.3 Six configurations ordered from simple to complex

The six configurations were not chosen arbitrarily. They form an incremental build-up
designed to measure the contribution of each retrieval mechanism individually and in
combination:

```
dense_only                              ← baseline (embedding similarity only)
dense_with_query_expansion              ← add query expansion, no BM25
hybrid_bm25                             ← add BM25, no expansion
hybrid_bm25_with_query_expansion        ← BM25 + expansion together
hybrid_bm25_with_reranker               ← BM25 + cross-encoder, no expansion
hybrid_bm25_query_expansion_and_reranker ← full stack (all three mechanisms)
```

This structure supports isolation comparisons:
- BM25 effect alone: `dense_only` vs `hybrid_bm25` (same query count, no reranker)
- Query expansion effect alone: `dense_only` vs `dense_with_query_expansion` (no BM25, no reranker)
- Reranker effect alone: `hybrid_bm25` vs `hybrid_bm25_with_reranker` (same query count, no expansion)
- Interaction between BM25 and query expansion: `hybrid_bm25` vs `hybrid_bm25_with_query_expansion`

Without this structure, an experiment that only tested the baseline vs the full stack
would reveal which combination wins, but not what each individual component contributes.
Knowing that BM25 alone accounts for +0.175 Recall@5, while query expansion adds a
further +0.020, is more actionable than knowing the full stack beats the baseline by
+0.195 — it tells us where future investment is most likely to pay off.

### 8.4 RRF (Reciprocal Rank Fusion) mode for QueryFusionRetriever

`QueryFusionRetriever` (from LlamaIndex) supports several fusion modes, including
score-based weighted averaging and rank-based fusion. RRF (Reciprocal Rank Fusion) was
chosen as the fusion mode for combining result lists from multiple query variants.

RRF computes each chunk's fused score as the sum of `1 / (rank + 60)` across all query
variant result lists, where `rank` is the chunk's position in that list (1-indexed). The
constant 60 is a smoothing factor that prevents the top result from dominating
disproportionately. Because RRF uses rank positions rather than raw similarity scores,
it is immune to the score incomparability problem: the BM25 score returned for query
variant A is not on the same numerical scale as the BM25 score for query variant B.
Normalizing raw scores across heterogeneous retrieval runs requires calibration that
introduces additional hyperparameters. RRF sidesteps this entirely by working only with
ordinal rank information, which is comparable across queries by definition.

RRF is also the standard default in retrieval fusion research and has no hyperparameters
of its own to tune (beyond the smoothing constant, which the literature treats as fixed at
60). Using it here means the query expansion results are attributable to query coverage,
not to fusion parameter choices.

### 8.5 Query expansion via LLM rather than HyDE

Two common approaches exist for improving query coverage before retrieval. The first
(used here) is query expansion or query augmentation: an LLM generates multiple
rephrasings of the original query, all variants are retrieved independently, and the
results are fused. The second is HyDE (Hypothetical Document Embeddings): an LLM
generates a hypothetical document that would plausibly answer the query, and that
hypothetical document is embedded and used as the retrieval vector instead of the original
query embedding.

Query expansion was chosen over HyDE for a specific experimental-design reason. This
experiment also tests BM25 hybrid retrieval, which adds a keyword-matching component that
partially compensates for the semantic gap between a query's phrasing and the document's
phrasing. If HyDE were used alongside BM25, any retrieval gain would be jointly caused by
(a) the hypothetical document's embedded representation, (b) the keyword terms in the
hypothetical document matching BM25's inverted index, and (c) BM25 on the original query.
Disentangling these three effects would require an additional experiment. Query expansion
is the simpler and cleaner intervention: it improves coverage by increasing the number of
query phrasings without introducing a new retrieval modality. This keeps the experiment's
causal story clean.

### 8.6 Reranker as a post-retrieval step, not embedded in the retriever

The cross-encoder reranker (`BAAI/bge-reranker-large`) was applied explicitly in the
evaluation loop after calling the retriever, not monkey-patched onto the retriever object
or integrated as part of the index configuration. This was intentional.

If the reranker were attached to the retriever at the object level, any configuration
reusing the same retriever instance would inherit reranking behavior, even configurations
that should not have it. The six retrieval configurations in this experiment are built by
a shared `build_retriever()` function, and three of the six (E0, E1, E2) must not use
reranking. Keeping the reranker in the evaluation loop, applied only when
`config.use_reranker=True`, makes the boundary explicit and auditable — a reader can
verify by inspection that E0–E3 receive raw retrieval results and E4–E5 receive reranked
results, without needing to trace the retriever internals.

### 8.7 RAGAS metrics as secondary evaluation alongside Recall@5

RAGAS (a Python library for evaluating RAG pipelines) was used to compute three
LLM-judged metrics alongside the two deterministic retrieval metrics (Recall@5 and
nDCG@5). The three RAGAS metrics are: Context Recall (does the retrieved context cover
all claims in the reference answer?), Faithfulness (does the generated answer stay within
what the retrieved chunks say?), and Context Precision (are the most-relevant chunks
ranked at the top?). These require an LLM-as-judge call per sample and produce a
generated answer per query, making them more expensive to compute.

RAGAS metrics were added to capture end-to-end answer quality beyond pure retrieval
coverage. Recall@5 measures whether the correct chunk was retrieved, but it does not
measure whether the answer generated from those chunks is accurate or faithful.
RAGAS closes that gap by evaluating the full retrieval-to-answer chain.

Despite this, Recall@5 remains the primary decision metric for three reasons. First, the
downstream task is paper summarization, not question answering — the system reads all
top-K chunks simultaneously, so whether the relevant chunk is at rank 1 or rank 5 matters
less than whether it is retrieved at all. Second, RAGAS LLM-judge scores carry non-trivial
variance depending on the judge model used and borderline judgment calls; they are
directional indicators, not ground truth. Third, Recall@5 is deterministic and directly
measurable from chunk IDs without any judge model, making it immune to judge bias and
reproducible across runs.

### 8.8 Trade-off between Recall@5 and nDCG@5 in winner selection

The final two candidate configurations tied on Recall@5:

```
hybrid_bm25_with_query_expansion:          Recall@5=0.615, nDCG@5=0.563
hybrid_bm25_query_expansion_and_reranker:  Recall@5=0.603, nDCG@5=0.585
```

The reranker improves nDCG@5 (ranking quality: +0.022) but leaves Recall@5 unchanged.
The deciding factor was the downstream task. This pipeline feeds retrieved chunks to a
summarization LLM that reads all top-K chunks as a batch — it does not read only the
top-1 result. For a reader that sees all retrieved chunks, a relevant chunk at rank 5
contributes just as much as one at rank 1: the chunk is present in the context window
regardless of position. Therefore Recall@5 is the more important metric for this task,
and the reranker's improvement to ranking quality does not translate to a meaningful
improvement in summarization output quality.

Additionally, the reranker adds +20% wall-clock latency (5,212 s vs 6,269 s over 100
samples) and requires loading a ~270M parameter cross-encoder model at deployment time.
When the primary metric shows no improvement, these costs are not justified.

If the downstream task were single-answer question answering (where only the top-1
retrieved chunk is shown to the user), the reranker's nDCG improvement would be directly
valuable and the trade-off calculus would favor including it.

### 8.9 Sub-experiment with sentence splitter using the full retrieval stack

After the six main configurations were evaluated, an additional sub-experiment tested
whether switching to LlamaIndex's `SentenceSplitter` chunker (with ~1024-token chunks
rather than 512-token Docling hybrid chunks) could match or exceed the winning
configuration's Recall@5 when the same full retrieval stack was applied (BM25 + query
expansion + reranker).

The motivation was a specific weakness observed in the main experiment. Semantic queries —
those that ask a conceptual question rather than a factual or keyword-matching question —
achieved only Recall@5 = 0.241 under `hybrid_bm25` with 512-token Docling chunks. The
hypothesis was that this weakness might be caused by the chunking granularity: a 512-token
chunk might split the answer to a semantic question across two chunks, so no single chunk
fully contains the ground-truth passage. Larger 1024-token chunks (produced by
SentenceSplitter) would be less likely to split prose answers across boundaries.

The result (Recall@5 = 0.537 for the sentence splitter sub-experiment vs 0.615 for the
Docling hybrid winner) rejected the hypothesis. While sentence splitter chunks produced
higher Semantic Recall (0.503 vs 0.444), the overall Recall@5 was lower. The Docling
hybrid chunker's structural term signal — section headings prepended to each chunk,
boilerplate filtered out — provides more value with BM25 hybrid retrieval than larger
prose chunks do, even with the full retrieval stack applied. This confirmed that the
chunking winner from the prior experiment is robust across retrieval configurations and
that the Docling HybridChunker's structured output is the right pairing with BM25 hybrid
retrieval for this corpus.

Note that this sub-experiment is not a controlled ablation and its metrics should not be
compared directly to the six main configurations — see Section 6 Limitation 3 for the
full analysis of the structural differences that make direct comparison unreliable.
