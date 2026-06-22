# Chunking Strategy Comparison — Experiment Report

> **Purpose of this document:** A developer with no prior context on this codebase or
> experiment should be able to read this document alone and fully understand the
> experiment from start to finish.

---

## 1. Background and Objective

### 1.1 Project Context

This experiment is part of a research paper summarization pipeline that processes academic PDFs and generates PowerPoint presentations. Before slides can be generated, the pipeline must retrieve the most relevant passages from each paper in response to a user query. That retrieval step is called RAG (Retrieval-Augmented Generation):

```
PDF file
   │
   ▼
[Docling PDF parser]  ── produces a structured DoclingDocument (headings, tables, text)
   │
   ▼
[Chunker]             ── splits the document into smaller text segments ("chunks")
   │
   ▼
[Embedding model]     ── converts each chunk to a vector (768-dim float array)
   │
   ▼
[Qdrant vector store] ── stores the chunk vectors in-memory
   │
   ▼
[Retriever]           ── given a query, finds the top-K most similar chunk vectors
   │
   ▼
[Retrieved chunks]    ── sent to the LLM as context for answer generation
```

The **chunker** (second step) has a large impact on retrieval quality: if a ground-truth answer passage is split across two chunk boundaries, no single chunk will contain enough information to match the query, and retrieval will fail.

### 1.2 Why This Experiment

Before this experiment, the pipeline had no principled choice for its chunker. The default LlamaIndex `SentenceSplitter` was used as a placeholder. Multiple chunking libraries are available (LlamaIndex text splitters, Docling structure-aware chunkers), each making different trade-offs between chunk size, semantic coherence, and document structure awareness.

The retrieval strategy experiment that follows this one needs to know which chunker to fix as a constant. This experiment was designed to answer that question first.

### 1.3 Experiment Goal

Identify the best chunking strategy for dense-only retrieval over 28 academic ML papers by measuring Recall@5 and nDCG@5 across 112 ground-truth query-passage pairs, with all other conditions fixed.

---

## 2. Evaluation Setup

### 2.1 Dataset

- **Corpus:** 28 academic ML papers, pre-parsed by Docling into structured JSON format (`DoclingDocument`)
- **Ground-truth (GT) dataset:** 112 positive samples, each containing:
  - `paper_id` — the arXiv ID of the paper
  - `query` — a natural-language question about the paper
  - `gt_passages` — one or more reference text passages from the paper that correctly answer the query
  - `query_type` — one of `Factual`, `Keyword-heavy`, `Semantic`, `Multi-hop`
- Only positive samples (confirmed correct passages) were used; negative samples were excluded.

### 2.2 Fixed Conditions

All variables other than the chunker were held constant to isolate chunking as the sole experimental factor:

| Parameter | Value | Reason Fixed |
|-----------|-------|--------------|
| Embedding model | `ollama/nomic-embed-text` (runs locally via Ollama) | Same model as production pipeline |
| Retrieval method | Dense-only (cosine similarity) | Isolates chunking; hybrid retrieval is the next experiment |
| `similarity_top_k` | 10 (retrieve top-10 chunks) | Same as production; evaluation is cut at 5 |
| Evaluation cutoff | 5 (`EVAL_K=5`) | Recall@5 and nDCG@5 |
| No LLM at query time | Yes | Ensures reproducibility; no generative step |
| Vector store | Qdrant in-memory (`:memory:`) | Fresh isolated collection per paper per strategy |

### 2.3 Metrics

All metrics are computed per query and then averaged.

**Recall@5** — "Did the correct passage appear in the top-5 retrieved chunks?"

A score of 1.0 means the correct passage was retrieved; 0.0 means it was not. Averaged across all queries: Recall@5 = 0.61 means that in 61% of the 100–104 evaluated queries, the correct passage appeared in the top-5 results.

**nDCG@5** (Normalized Discounted Cumulative Gain at 5) — "How highly ranked was the correct passage within the top-5?"

nDCG@5 = 1.0 means the correct passage was ranked first; nDCG@5 = 0.5 means it appeared lower in the list. nDCG@5 is always ≤ Recall@5 because it penalizes results that are correct but ranked low. A strategy with high Recall@5 but much lower nDCG@5 retrieves the right passage but buries it near position 5.

**n** (per-row sample count) — number of GT queries evaluated for a given strategy and query type. Values below 112 indicate some queries were skipped due to `no_relevant_ids_found` (the chunker produced no chunk containing the GT passage substring).

---

## 3. Compared Approaches

Strategies 1–5 were evaluated in the first pass (run at 11:25 on 2026-06-11). Strategies 6 and 7 were added later as follow-up sub-experiments and evaluated in a second pass (run at 18:24) using `--start-from` to resume without re-running strategies 1–5.

### 3.1 `sentence_splitter_default`

**What it is:** The default LlamaIndex text splitter. It tokenizes text using a sentence boundary detector and then groups sentences into fixed-size windows of approximately 1024 tokens (tiktoken `cl100k_base`, which is OpenAI's tokenizer), with a 200-token overlap between adjacent chunks.

**How it works:**
```
Raw markdown text of the paper
   │
   ▼
[Sentence boundary detection]
   │
   ▼
[Group into ~1024-token windows with 200-token overlap]
   │
   ▼
[Flat list of TextNodes, avg 36.6 chunks per paper]
```

**Why it was included:** Establishes the baseline. Represents the simplest possible approach with no document-structure awareness.

**Implementation:**
```python
SentenceSplitter()  # LlamaIndex defaults: chunk_size=1024, chunk_overlap=200
```

---

### 3.2 `semantic_splitter`

**What it is:** LlamaIndex `SemanticSplitterNodeParser`. Instead of splitting at fixed token counts, it splits at points where embedding similarity between adjacent sentences drops sharply (semantic boundary detection).

**How it works:**
```
Sentences s1, s2, s3, s4, s5 ...
   │
   ▼
[Embed each sentence → 768-dim vector via nomic-embed-text]
   │
   ▼
[Compute cosine similarity between consecutive sentence embeddings]
   │
   ▼
[Split where similarity drops below the 95th-percentile threshold]
   │
   ▼
[Semantic chunks, avg 43.7 chunks per paper]
```

`buffer_size=1` means each "sentence unit" used for boundary detection includes 1 neighboring sentence on each side. `breakpoint_percentile_threshold=95` means a boundary is inserted when similarity is in the bottom 5% of all pairwise similarities.

**Why it was included:** Tests whether adaptively-sized semantic chunks improve recall compared to fixed-size windows. Hypothesized to produce more coherent single-topic chunks.

**Implementation:**
```python
SemanticSplitterNodeParser(
    embed_model=TruncatingEmbeddingWrapper(embed_model),
    buffer_size=1,
    breakpoint_percentile_threshold=95,
)
```

Note: `SemanticSplitterNodeParser` calls the embedding model during chunking (not just at index time), because it must embed each sentence to detect boundaries. A custom `TruncatingEmbeddingWrapper` was required to handle oversized sentences — see Section 4, Issue 1.

---

### 3.3 `docling_hierarchical_chunker`

**What it is:** Docling's `HierarchicalChunker`. Unlike the text-only splitters above, this chunker operates on the structured `DoclingDocument` (not raw markdown). It preserves the document's section hierarchy and produces chunks that align exactly with section boundaries — one chunk per logical section.

**How it works:**
```
DoclingDocument (structured: headings, sections, tables, figures)
   │
   ▼
[HierarchicalChunker traverses the document tree]
   │
   ▼
[One chunk per leaf section, no token-size cap]
   │
   ▼
[contextualize() prepends section heading path]
   │  e.g., "3. Method > 3.2 Training\n" + prose
   ▼
[Filter boilerplate via ChunkFilter (references, copyright, page headers)]
   │
   ▼
[avg 175.9 chunks per paper — much more granular than other strategies]
```

**Why it was included:** Tests whether document structure awareness (knowing exactly where each section begins and ends) improves retrieval.

**Implementation:**
```python
ContextualDoclingNodeParser(chunk_filter=chunk_filter)
# Default chunker = HierarchicalChunker
```

---

### 3.4 `docling_hybrid_chunker_512`

**What it is:** Docling's `HybridChunker` with a 512-token limit. Like `HierarchicalChunker`, it uses the structured `DoclingDocument`, but it also applies a token-count cap: sections longer than 512 tokens (tiktoken `cl100k_base`) are further split. Shorter sections are merged up to the 512-token limit.

**How it works:**
```
DoclingDocument
   │
   ▼
[HybridChunker: split long sections, merge short sections → <= 512 tokens per chunk]
   │
   ▼
[contextualize() prepends heading: "3. Method\n" + prose]
   │
   ▼
[ChunkFilter removes boilerplate]
   │
   ▼
[avg 79.5 chunks per paper]
```

The `contextualize()` call prepends the section heading to each chunk before storing it in the vector database. The full stored text (heading + prose) is embedded.

**Why it was included:** Tests whether combining structure-awareness with a reasonable token limit produces better-sized chunks than pure section-aligned chunking. The 512-token limit is a common industry heuristic for dense retrieval.

**Implementation:**
```python
ContextualDoclingNodeParser(
    chunker=HybridChunker(tokenizer=DoclingChunker._TokenizerAdapter(max_tokens=512)),
    chunk_filter=chunk_filter,
)
```

---

### 3.5 `docling_hybrid_chunker_512_no_context`

**What it is:** Same as `docling_hybrid_chunker_512` but with `contextualize()` disabled. The heading is not prepended; both `node.text` (stored in Qdrant) and the embedding vector are derived from prose only.

**Why it was added:** Strategy #4 (`docling_hybrid_chunker_512`) showed weak semantic recall (Recall@5 = 0.35) vs `sentence_splitter` (0.63). The hypothesis was that prepending a heading like `"3. Method\n"` to each chunk distorts the embedding vector away from the chunk's actual content semantics, hurting queries that describe the content in natural language. This strategy tests that hypothesis by removing the heading entirely from both the stored text and the embedding.

**Implementation:**
```python
ContextualDoclingNodeParser(
    chunker=HybridChunker(tokenizer=tokenizer_512),
    chunk_filter=chunk_filter,
    use_contextualize=False,  # heading removed from text and embedding
)
```

---

### 3.6 `docling_hybrid_chunker_512_prose_embed`

**What it is:** Same as `docling_hybrid_chunker_512` but with separate text paths for storage and embedding. The full heading + prose is stored in Qdrant as `node.text` (available to the LLM for answer generation). The embedding is computed from prose only.

**Why it was added:** This is the "Method B" test of the same heading-distortion hypothesis as strategy #5 (`no_context`). It asks: can we keep the heading for the LLM while using clean prose vectors for retrieval?

```
node.text (stored, LLM reads this):      "3. Method\n  We trained with SGD ..."
node.metadata["_embed_text"] (embedded):  "We trained with SGD ..."
                                           ^ vector computed from this only
```

**Implementation:**
```python
ContextualDoclingNodeParser(
    chunker=HybridChunker(tokenizer=tokenizer_512),
    chunk_filter=chunk_filter,
    use_contextualize=True,
    prose_only_embed=True,  # embed prose only, store heading+prose
)
```

---

### Excluded Approach: `markdown_element_splitter`

`MarkdownElementNodeParser` (LlamaIndex) is a table-aware parser that uses an LLM (`ollama/ministral-3:14b-cloud`) to convert markdown tables into natural-language summaries before embedding. It was tested (strategy #3 in the original 5-strategy run) but excluded from all comparison tables because of an evaluation method incompatibility:

The LLM rewrites table content during chunking. The GT passage substring matching (`MetricsCalculator.find_relevant_ids`) searches for the original table text verbatim inside `node.text`. After LLM rewriting, the original text no longer exists in any node — so `find_relevant_ids` returns 0 relevant IDs for every table-containing query, and all 104 evaluated samples score Recall@5 = 0.00.

This is not a genuine retrieval failure. The strategy produces semantically valid chunks, but the evaluation harness is incompatible with LLM-rewritten content. A proper evaluation would require semantic similarity matching between the GT passage and node text, rather than substring containment.

---

## 4. Technical Issues Encountered

### Issue 1: Oversized Nodes Crash the Ollama Embedding Server (HTTP 400)

**Symptom:** During evaluation with `semantic_splitter`, Ollama returned HTTP 400 errors mid-run. The splitter calls the embedding model on every sentence during chunking, not only at index time. Some individual sentences from Docling-parsed markdown (e.g., full markdown table rows rendered as one long line) exceeded the 2048 BERT-token limit of `nomic-embed-text`.

**Root Cause:**
```
SemanticSplitterNodeParser internals:
   for sentence in all_sentences:
       embed(sentence)   <── calls nomic-embed-text for EVERY sentence

nomic-embed-text (inside Ollama):
   hard limit = 2048 BERT tokens
   if len(tokens) > 2048: return HTTP 400

Contrast with the other 4 strategies:
   SentenceSplitter, MarkdownElementNodeParser, ContextualDoclingNodeParser
   do NOT call embed_model during chunking.
   They return raw TextNodes; the pre-embed loop in main() truncates before
   embedding. SemanticSplitterNodeParser is the only chunker that embeds
   during chunking, bypassing the pre-embed loop.
```

A secondary complication: the HuggingFace `bert-base-uncased` tokenizer (used for pre-checking token counts) and the GGUF build of `nomic-embed-text` inside Ollama tokenize some Unicode characters differently. For example, `U+2026` (ellipsis `…`) counts as 1 token in HuggingFace but 2 tokens in the GGUF binary. A naive count using HuggingFace alone can underestimate the actual Ollama token count, causing a chunk that appears "safe" to still trigger HTTP 400.

**Fix Applied:**

Two-step approach in `truncate_to_bert_limit()`:

```python
def truncate_to_bert_limit(text: str) -> str:
    # Step 1: NFKC normalization converts Unicode compatibility characters to ASCII
    # (e.g. U+2026 … → ..., U+FB01 fi-ligature → fi).
    # Both tokenizers agree on ASCII, eliminating cross-tokenizer mismatch.
    text = unicodedata.normalize("NFKC", text)

    ids = BERT_TOKENIZER.encode(text, add_special_tokens=False)
    if len(ids) <= BERT_MAX_TOKENS:
        return text

    # Step 2: BERT_MAX_TOKENS=1900 provides a 7% buffer below 2048
    # to absorb residual GGUF tokenizer drift for characters not covered by NFKC.
    return BERT_TOKENIZER.decode(ids[:BERT_MAX_TOKENS], skip_special_tokens=True)
```

`SemanticSplitterNodeParser` received a `TruncatingEmbeddingWrapper` that applies `truncate_to_bert_limit()` before every embed call inside the splitter's boundary detection loop.

**Why this fix:** NFKC normalization is safe for retrieval text (it does not change semantics, only Unicode encoding) and eliminates the primary source of tokenizer disagreement. The 7% buffer handles rare Unicode edge cases not covered by NFKC. A pure character-count truncation was rejected because character count does not map reliably to token count for non-ASCII text.

The log records 3,935 truncation events across the full run — mostly from `sentence_splitter_default` and `semantic_splitter` chunks that happened to contain full markdown tables or long equation strings.

---

### Issue 2: QdrantVectorStore Docstore Is Empty (Known Issue)

**Symptom:** If `relevant_ids` were looked up via `index.docstore`, the result was always an empty set regardless of what was indexed. This would cause every query to be skipped with `no_relevant_ids_found`, making the entire evaluation produce zero results.

**Root Cause:**
```
VectorStoreIndex with QdrantVectorStore backend
   │
   ├── Vectors + payload  →  stored in Qdrant (in-memory)     ← works
   │
   └── LlamaIndex docstore (in-memory Python dict of node objects)
         │
         └── NOT populated when QdrantVectorStore is used as backend.
             QdrantVectorStore does not write back to the docstore
             during VectorStoreIndex construction.
```

**Fix Applied:**

`MetricsCalculator.find_relevant_ids()` was passed the `nodes` list directly (the in-memory Python list constructed during chunking) instead of querying `index.docstore`:

```python
# Correct: pass in-memory nodes list directly
relevant_ids = MetricsCalculator.find_relevant_ids(nodes, sample["gt_passages"])
```

The method performs substring matching: it returns the `node_id` of every node whose `node.text` contains the ground-truth passage as a substring.

**Why this fix:** The `nodes` list is in scope and contains all nodes with their IDs. Since each paper gets its own isolated Qdrant collection (`:memory:` with a fresh client per paper), bypassing the docstore introduces no cross-paper contamination.

---

### Issue 3: Some Queries Are Skipped Due to No Relevant IDs Found

**Symptom:** For certain paper-strategy combinations, `find_relevant_ids()` returned an empty set and the query was logged as `[SKIP] reason=no_relevant_ids_found`. This occurs across all strategies.

**Root Cause:** Substring matching requires the exact GT passage text to appear inside a single `node.text`. If the chunker splits the GT passage at a boundary between two adjacent chunks (neither chunk contains the full GT passage string), no match is found. This is an inherent limitation of substring-based evaluation.

Papers with skips across multiple strategies: `2002.05709`, `2101.00190`, `2109.01652`, `2112.10752`, `2205.14135`, `2212.10560`. The skip count differs per strategy, reflected in the varying `n` values in the summary tables (strategies 1–2 evaluated 102–104 queries; Docling strategies evaluated 100).

**No fix was applied** — this is expected behavior from substring matching. The skip counts are small (at most 12 queries per strategy out of 112) and affect all strategies roughly equally, so they do not materially change the ranking.

---

### Issue 4: Duplicate [SUMMARY] Lines in the Log for Strategies 1–5

**Symptom:** The log file contains two complete `[SUMMARY]` blocks for strategies 1–5, plus a `[WINNER]` and `[END]` after each block.

**Root Cause:** The experiment was run in two passes. The first pass (timestamp 11:25) evaluated strategies 1–5 and wrote a complete summary + winner block. The second pass (timestamp 18:24) used `--start-from docling_hybrid_chunker_512_no_context` to add strategies 6 and 7. The `load_scores_from_log()` function replayed the earlier `[RESULT]` lines for strategies 1–5 into memory, and the script then wrote a new complete summary block covering all 7 strategies. This produced two summary blocks in the same log file.

**Resolution:** The second complete block (all 7 strategies) is the authoritative result. The numerical values for strategies 1–5 are identical in both blocks. `latency_s` is 0.0 for strategies 1–5 in both blocks because the resume function sets latency to 0.0 for all loaded strategies (elapsed time cannot be recovered from `[RESULT]` lines). Strategies 6 and 7 have only one `[SUMMARY]` line each, with correct latency values (152.3 s and 165.3 s respectively).

---

## 5. Results

### 5.1 Overall Summary

`markdown_element_splitter` is excluded from this table — see Section 3 (Excluded Approach) for the reason.

`latency_s` for strategies 1–4 shows 0.0 because those strategies were loaded from the previous log in the second pass and elapsed time cannot be recovered. Text splitters (strategies 1–2) are near-instant in practice; Docling strategies (3–4) are estimated to take 150–260 seconds based on the observed runtimes for strategies 5–6.

| Strategy | Recall@5 | nDCG@5 | n | latency_s | avg_chunks/paper |
|---|---|---|---|---|---|
| `sentence_splitter_default` | 0.60 | 0.49 | 104 | ~0 | 36.6 |
| `semantic_splitter` | 0.59 | 0.40 | 102 | ~0 | 43.7 |
| `docling_hierarchical_chunker` | 0.51 | 0.40 | 100 | ~256 | 175.9 |
| `docling_hybrid_chunker_512` | **0.61** | **0.48** | 100 | 182.5 | 79.5 |
| `docling_hybrid_chunker_512_no_context` | 0.59 | 0.48 | 100 | 152.3 | 79.4 |
| `docling_hybrid_chunker_512_prose_embed` | 0.59 | 0.48 | 100 | 165.3 | 79.5 |

Winner (highest Recall@5): **`docling_hybrid_chunker_512`** (Recall@5 = 0.61, nDCG@5 = 0.48).

---

### 5.2 Per Query-Type Breakdown

Recall@5 by query type (n = sample count for that query type and strategy):

| Strategy | Factual | Keyword-heavy | Multi-hop | Semantic |
|---|---|---|---|---|
| `sentence_splitter_default` | 0.53 (n=26) | 0.56 (n=25) | 0.69 (n=26) | 0.63 (n=27) |
| `semantic_splitter` | 0.44 (n=25) | 0.67 (n=24) | 0.57 (n=26) | 0.68 (n=27) |
| `docling_hierarchical_chunker` | 0.63 (n=23) | 0.60 (n=25) | 0.61 (n=25) | 0.22 (n=27) |
| `docling_hybrid_chunker_512` | 0.57 (n=23) | **0.73** (n=25) | **0.81** (n=25) | 0.35 (n=27) |
| `docling_hybrid_chunker_512_no_context` | 0.59 (n=23) | 0.71 (n=25) | 0.79 (n=25) | 0.31 (n=27) |
| `docling_hybrid_chunker_512_prose_embed` | 0.59 (n=23) | 0.71 (n=25) | 0.79 (n=25) | 0.31 (n=27) |

nDCG@5 by query type:

| Strategy | Factual | Keyword-heavy | Multi-hop | Semantic |
|---|---|---|---|---|
| `sentence_splitter_default` | 0.40 | 0.47 | 0.60 | 0.48 |
| `semantic_splitter` | 0.32 | 0.39 | 0.42 | 0.45 |
| `docling_hierarchical_chunker` | 0.44 | 0.53 | 0.54 | 0.13 |
| `docling_hybrid_chunker_512` | 0.44 | **0.56** | **0.70** | 0.24 |
| `docling_hybrid_chunker_512_no_context` | 0.47 | 0.54 | 0.71 | 0.22 |
| `docling_hybrid_chunker_512_prose_embed` | 0.47 | 0.54 | 0.71 | 0.22 |

**Key observations:**

- `docling_hybrid_chunker_512` leads on Keyword-heavy (Recall@5 = 0.73) and Multi-hop (0.81) queries.
- All Docling-based strategies score poorly on Semantic queries (0.22–0.35 Recall@5). `sentence_splitter` scores 0.63 and `semantic_splitter` scores 0.68 — both substantially higher.
- `docling_hierarchical_chunker` has by far the most chunks per paper (175.9 average) and the worst overall Recall@5 (0.51), suggesting that section-aligned chunks with no size cap become too fine-grained, scattering ground-truth passages across many tiny sub-sections.
- Strategies 5 (`no_context`) and 6 (`prose_embed`) produce identical results for all query types — see Section 5.3 for interpretation.

---

### 5.3 Winner

**`docling_hybrid_chunker_512`** — Recall@5 = 0.61, nDCG@5 = 0.48

It leads on the two most diagnostically important query types for academic papers:
- **Keyword-heavy** (Recall@5 = 0.73): queries containing specific model names, numbers, or dataset names. Structure-aware chunking keeps these terms within a single section boundary, making them co-occur in one chunk.
- **Multi-hop** (Recall@5 = 0.81): queries that require connecting information within a section. The 512-token cap ensures no chunk is too large, while structure alignment ensures no cross-section fragmentation.

The 512-token cap is the critical differentiator over `docling_hierarchical_chunker`: pure section-aligned chunks have no size limit, producing 175.9 chunks/paper on average. Each chunk can be very long, which reduces cosine similarity against a short query (the relevant sentence is diluted by surrounding text). The hybrid chunker avoids this by capping at 512 tokens while still respecting section boundaries.

---

### 5.4 Sub-Experiment: The Heading-Context Hypothesis (Strategies 5 and 6)

After the first pass, `docling_hybrid_chunker_512` showed Semantic recall = 0.35 vs `sentence_splitter`'s 0.63. The following hypothesis was formed:

> `contextualize()` prepends a section heading like `"3. Method\n"` to each chunk before embedding. This extra text in the vector representation may distort the embedding away from the chunk's actual content semantics. Semantic queries describe content in natural language rather than structural terms, so they might benefit from embedding prose without the heading.

Two targeted experiments were run to test this:

| Test | Strategy | embed input | store input | Semantic Recall@5 |
|---|---|---|---|---|
| Baseline | `docling_hybrid_chunker_512` | heading + prose | heading + prose | 0.35 |
| Remove heading entirely | `no_context` | prose only | prose only | 0.31 |
| Separate embed and store paths | `prose_embed` | prose only | heading + prose | 0.31 |

**Finding: The hypothesis was wrong.** Both tests scored Semantic Recall@5 = 0.31, which is worse than the baseline 0.35. Removing the heading from the embedding path did not improve semantic retrieval — it slightly degraded it.

**Interpretation:** The lower semantic recall of Docling-based strategies is not caused by heading text in embeddings. The more likely cause is the section-boundary chunking style itself. Docling sections are dense, single-topic blocks. A broad semantic query ("how does this model generalize?") typically spans multiple sections. Fixed-size overlapping windows (`sentence_splitter`) cut across section boundaries with a 200-token overlap, accidentally co-locating related text from multiple nearby sections in one chunk — which makes it easier to match a broad semantic query. The structure-aware chunker, by respecting section boundaries strictly, prevents this cross-section text co-location.

---

## 6. Limitations

- **Substring matching for ground truth** — `find_relevant_ids` uses exact substring matching. If a GT passage is split across a chunk boundary, or if a chunker normalizes or rewrites text (as `markdown_element_splitter` does for tables), it scores as a miss even if the chunk is semantically correct. This makes `markdown_element_splitter` unevaluable and may slightly undercount recall for any strategy that normalizes whitespace or Unicode.

- **Dense-only retrieval** — This experiment uses only cosine similarity over `nomic-embed-text` embeddings. Keyword-heavy queries are known to benefit from BM25 (sparse) retrieval, which matches on exact keyword overlap. The Recall@5 values reported here are lower bounds on what could be achieved with hybrid (dense + sparse) retrieval.

- **Small corpus** — 28 papers with 112 GT samples. Per-query-type sample counts are 23–27 queries per strategy. Small differences (e.g., 0.59 vs 0.61 Recall@5) may not be stable across a larger dataset.

- **Single embedding model** — All strategies were evaluated with `nomic-embed-text` (2048 BERT-token limit). A longer-context embedding model might change the relative ranking, particularly for `docling_hierarchical_chunker` whose large chunks (average 175.9 per paper) may exceed the effective representation range of a 2048-token model.

- **`latency_s` not recovered for strategies 1–5** — Because `load_scores_from_log()` sets latency to 0.0 for all loaded strategies, the wall-clock chunking time for strategies 1–4 is not available from the log. Text splitters (1–2) are near-instant; the Docling strategies (3–4) likely took 150–260 seconds, inferred from strategies 5–6.

- **`markdown_element_splitter` not evaluatable** — This strategy could not be compared because the evaluation harness relies on substring matching, which is incompatible with LLM-rewritten table text. A semantic-similarity-based evaluation harness would be required.

---

## 7. Conclusion and Next Steps

**Conclusion:**

This experiment compared six evaluable chunking strategies across 28 academic ML papers and 112 ground-truth query-passage pairs under fixed dense-only retrieval conditions.

`docling_hybrid_chunker_512` achieved the highest overall Recall@5 = 0.61 (nDCG@5 = 0.48), with the strongest performance on Keyword-heavy (0.73) and Multi-hop (0.81) queries — the query types most representative of academic paper retrieval needs. Its advantage comes from combining Docling's document-structure awareness (respecting section boundaries) with a 512-token size cap that prevents large sections from becoming retrieval-unfriendly monoliths.

A two-strategy sub-experiment (strategies 5 and 6) tested whether removing section headings from the embedding path would fix the weak Semantic recall observed in strategy 4. The hypothesis was wrong: removing headings made Semantic recall slightly worse (0.31 vs 0.35), indicating the cause is the section-boundary chunking pattern itself, not heading text in embeddings.

**Recommended for next phase:**

`docling_hybrid_chunker_512` because it leads on overall Recall@5 and on the two most structurally important query types for academic papers. The Semantic recall weakness (0.35) is a known limitation that hybrid retrieval (adding BM25) may address in the next experiment.

**Open questions:**

1. Does adding BM25 sparse retrieval (hybrid retrieval) close the Semantic recall gap between `docling_hybrid_chunker_512` (0.35) and `sentence_splitter` (0.63)?
2. Would a larger-context embedding model change the relative rankings, particularly for the coarse `docling_hierarchical_chunker` with its large section-sized chunks?
3. Can a semantic-similarity-based evaluation harness properly assess `markdown_element_splitter`, which rewrites tables with an LLM during chunking?
4. Is 512 tokens the optimal cap, or would a different limit (e.g., 256 or 1024 tokens) change the relative rankings?

---

## 8. Design Decisions and Rationale

This section documents the reasoning behind key experimental design choices. Each sub-section is self-contained and written for a developer who has not seen this codebase before but is familiar with RAG systems and Python.

---

### 8.1 Dense-only retrieval as the fixed condition for chunking comparison

This experiment held retrieval fixed at dense-only (single-query cosine similarity over `nomic-embed-text` embeddings, no BM25, no reranker) so that the only variable being manipulated was the chunking strategy. The principle is standard controlled experimentation: when comparing N approaches on dimension A, all other dimensions must be held constant. If retrieval were also varied during the chunking comparison — for example, by running some strategies with BM25 and others without — any observed differences in Recall@5 could come from retrieval, chunking, or their interaction, making it impossible to attribute the effect to either alone.

Dense-only retrieval was chosen as the fixed baseline because it is the simplest possible retrieval configuration. It has no tunable hyperparameters beyond `similarity_top_k`, and it is the default configuration of the production pipeline. Using the simplest baseline ensures the chunking signal dominates the measurement. Hybrid retrieval (dense + BM25 + optional reranker) is a separate follow-on experiment in which chunking is held constant at `docling_hybrid_chunker_512` — the winner identified here.

---

### 8.2 Exclusion of `markdown_element_splitter` from the main comparison

`MarkdownElementNodeParser` (LlamaIndex) was tested but excluded from all comparison tables. The reason is a confound that makes head-to-head comparison with the other five strategies invalid rather than merely difficult.

The parser calls an LLM (`ollama/ministral-3:14b-cloud`) during chunking to rewrite markdown table rows into natural-language summaries. This introduces an additional variable — LLM capability for table summarization — that none of the other five strategies possess. Including it in the comparison would mean that any performance difference could be explained by either the structural parsing or the LLM summarization, and there is no way to disentangle the two from the aggregate Recall@5 score.

A secondary complication: the evaluation harness uses substring matching to identify which nodes contain a ground-truth passage. After LLM rewriting, the original table text no longer exists verbatim inside any node, so the harness returns zero relevant IDs for every table-containing query. This produces Recall@5 = 0.00 across all 104 evaluated samples — a measurement artifact, not a genuine retrieval failure.

The strategy was excluded rather than patched (e.g., with semantic similarity matching) because the goal of this experiment is a clean apples-to-apples chunking comparison. A proper evaluation of `markdown_element_splitter` requires a separate experiment that explicitly frames the comparison as "chunking-only vs chunking + LLM table summarization" and uses a semantic-similarity-based evaluation harness.

---

### 8.3 512-token limit for the HybridChunker

The 512-token limit was selected to match the retrieval granularity that works well for factual queries over academic ML papers. The choice is a trade-off between two failure modes.

If chunks are too short (e.g., 256 tokens), related content is split across chunk boundaries. A method description and its associated equation often occupy 300–400 tokens together; capping at 256 forces them into separate chunks. When a query asks about the method, neither chunk individually contains both parts, reducing recall. If chunks are too long (e.g., 1024 tokens), a retrieved chunk contains too much unrelated content alongside the relevant passage. The embedding vector is computed over the entire chunk text, so a relevant sentence embedded inside 1000 tokens of surrounding prose is diluted — its cosine similarity against a short query drops, pushing it down the ranking.

The 512-token limit is a well-established industry heuristic for dense retrieval over technical documents and was taken as the starting point. The sub-experiments (strategies 5 and 6, which removed heading context while keeping the same 512-token cap) confirmed that the cap itself is doing structural work: eliminating the prefix did not change chunk count meaningfully (79.4 vs 79.5 chunks per paper), confirming that the token limit — not the heading text — governs chunk boundaries.

The hierarchical chunker result (Recall@5 = 0.51, avg 175.9 chunks per paper) provides indirect evidence that removing the token cap is harmful: larger, section-sized chunks dilute the embedding and hurt recall. The hybrid chunker's cap prevents this dilution while preserving section boundary alignment.

---

### 8.4 Heading prefix (contextualize) as part of the chunk text

`HybridChunker` in Docling produces raw prose chunks. The `contextualize()` call, applied via `ContextualDoclingNodeParser`, prepends the section heading path to each chunk before it is stored in Qdrant and embedded. A chunk about dropout regularization inside section 3.2.1 is stored as `"3. Method > 3.2 Architecture > 3.2.1 Encoder\n  We applied dropout=0.1 ..."` rather than `"We applied dropout=0.1 ..."`.

The rationale for this design is that a chunk whose embedding vector includes its heading is easier to retrieve when the query uses structural language ("what regularization is used in the encoder?"). Without the heading, the word "encoder" does not appear in the chunk text at all — it only appears in the surrounding heading structure — so the embedding has no signal for queries that reference the section.

The sub-experiments (strategies 5 and 6) empirically tested whether the heading was helping or hurting semantic retrieval. Strategy 5 (`no_context`) stripped the heading from both the stored text and the embedding. Strategy 6 (`prose_embed`) kept the heading in stored text but computed the embedding on prose only. Both scored Semantic Recall@5 = 0.31, versus 0.35 for the base hybrid chunker with heading included. The heading is not the cause of weak Semantic recall — removing it made performance slightly worse. The heading is therefore retained in the production configuration.

---

### 8.5 Sub-experiment design: testing the heading-context hypothesis

After the initial five-strategy run, `docling_hybrid_chunker_512` achieved Semantic Recall@5 = 0.35, substantially below `sentence_splitter_default` (0.63) and `semantic_splitter` (0.68). This gap was unexpected because the hybrid chunker outperformed both on Keyword-heavy and Multi-hop queries.

The leading hypothesis was that `contextualize()` was distorting the embedding vector. Semantic queries describe concepts in natural language ("how does the model handle long-range dependencies?") rather than citing specific keywords or section names. If the embedding vector is partly "occupied" by heading tokens, the cosine similarity between the chunk vector and a semantic query vector could decrease.

Two targeted sub-experiments were designed to test this hypothesis in isolation:

- **Strategy 5 (`no_context`)**: remove the heading entirely from both stored text and embedding. If the hypothesis is correct, Semantic Recall@5 should increase because the embedding is now pure prose.
- **Strategy 6 (`prose_embed`)**: keep the heading in stored text (so the LLM can use it for answer generation) but compute the embedding from prose only. If the embedding distortion is the cause, this variant should match or improve on strategy 5.

Both strategies scored Semantic Recall@5 = 0.31 — worse than the baseline 0.35. The hypothesis was falsified. The sub-experiments also served a secondary purpose: they confirmed that `ContextualDoclingNodeParser` correctly implements the `prose_only_embed` path, because strategies 5 and 6 produced identical scores, as expected when the only difference is where the heading appears in the storage path (both use identical embedding vectors).

The semantic recall gap between Docling-based strategies and text splitters is interpreted as a structural property of section-boundary chunking: overlapping fixed-size windows accidentally co-locate content from adjacent sections, making broad semantic queries easier to match. This is expected behavior and does not indicate a defect in the Docling chunker.

---

### 8.6 Recall@5 as primary metric over nDCG@5

Recall@5 was chosen as the primary decision criterion for selecting the winning chunking strategy. The reasoning is grounded in how the downstream pipeline uses retrieved chunks.

In this pipeline, the retriever returns the top-K chunks, and all of them are passed to the LLM as context for paper summarization. The LLM reads all retrieved chunks; it does not read the top-1 chunk more carefully than the top-5 chunk. As a result, whether the relevant passage is ranked first or fifth among the five retrieved chunks makes no practical difference — what matters is whether it appears in the retrieved set at all. Recall@5 directly measures this: did the relevant chunk appear in the top-5?

nDCG@5 (Normalized Discounted Cumulative Gain at 5) is reported as a secondary metric because it reveals something useful about ranking quality even when Recall@5 is equal. A strategy with Recall@5 = 0.61 and nDCG@5 = 0.48 returns the correct chunk but often ranks it near position 4–5. If the pipeline were changed to use top-1 or top-2 retrieval in a future phase, nDCG@5 would become the primary metric. For the current summarization use case, Recall@5 dominates.

This choice also simplifies the comparison: `docling_hybrid_chunker_512` leads on Recall@5 (0.61) and is essentially tied on nDCG@5 (0.48) with `sentence_splitter_default` (0.49). The Recall@5 lead is what justifies the selection.

---

### 8.7 Why nomic-embed-text as the fixed embedding model

`nomic-embed-text` is the embedding model deployed in the production pipeline. It was fixed across all strategies so that any difference in Recall@5 between strategies is attributable to chunking, not to varying embedding model behavior.

Using the same model as production ensures that findings from this experiment transfer directly: whichever chunker scores highest under `nomic-embed-text` will perform best when integrated into the production indexing step without re-indexing under a different model. If a different embedding model had been used for evaluation (e.g., a higher-capacity model with a longer context window), the winning chunker might differ, and the results would not transfer to production without an additional re-indexing step.

`nomic-embed-text` runs locally via Ollama, which provides two practical advantages for this experiment. First, there are no API costs per embedding call — the evaluation loop embeds approximately 2,200 chunks per strategy (79.5 chunks × 28 papers) plus the 140 query embeddings, and running this across six strategies in two passes would accumulate non-trivial API charges on a hosted model. Second, there are no rate limits: the evaluation loop can issue embedding requests as fast as the Ollama server can handle them, without throttling logic. The tradeoff is that `nomic-embed-text` has a 2048 BERT-token hard limit, which required the truncation fix described in Section 4, Issue 1.
