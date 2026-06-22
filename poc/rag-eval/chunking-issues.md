# Chunking Strategy Comparison — Known Issues

Issues discovered during Phase 1 execution. Each entry explains the root cause, impact, and fix applied so any developer can understand and reproduce the fix.

---

## Issue 1: SentenceSplitter produces empty nodes → Ollama HTTP 400

**Discovered:** 2026-06-10
**Affects:** `sentence_splitter_default`, `semantic_splitter`, `markdown_element_splitter`
**Status:** Fixed

### Symptom
```
litellm.APIConnectionError: OllamaException - Client error '400 Bad Request'
for url 'http://localhost:11434/api/embed'
```

### Root Cause
`SentenceSplitter` (and other plain-text parsers) can produce nodes with empty or whitespace-only `text` when the input markdown contains section headers with no body text, or whitespace-only paragraphs between sections. When `node.text = ""` is passed to `embed_model.get_text_embedding()`, Ollama rejects it with HTTP 400.

### Fix Applied
Filter out empty nodes immediately after chunking, before the embedding loop:
```python
nodes = [n for n in node_parser.get_nodes_from_documents([li_doc]) if n.text.strip()]
```

---

## Issue 2: tiktoken vs BERT WordPiece mismatch + GGUF tokenizer drift → Ollama HTTP 400

**Discovered:** 2026-06-10
**Affects:** All 5 strategies (any node containing markdown tables or Unicode typographic characters)
**Status:** Fixed (Option B — NFKC normalization + 1900-token buffer)

### What is a Token?

Before an AI embedding model can process text, the text is split into small units called "tokens". Different tools use different splitting algorithms and produce different counts for the same text:

```
"unhappiness"

tiktoken (OpenAI BPE):       "unhappiness"        → 1 token
BERT WordPiece (Google):     "un" + "##happiness" → 2 tokens
```

This matters because every embedding model has a maximum number of tokens it can accept at once.

### What are [CLS] and [SEP]?

BERT architecture (which nomic-embed-text is based on) requires every input to be wrapped with two special system tokens that BERT adds automatically:

```
Your text: "The model achieved 84% accuracy"

What BERT actually receives:
  [CLS]  The model achieved 84% accuracy  [SEP]
    ↑                                        ↑
  added automatically by Ollama          added automatically by Ollama
  1 token                                1 token

Total tokens consumed: 1 + 5 (words) + 1 = 7 tokens
```

nomic-embed-text's hard limit is 2048 tokens. Since [CLS] and [SEP] always consume 2 slots, only 2046 tokens are available for actual content.

### Root Cause — Two Layers

**Layer 1: tiktoken vs BERT WordPiece**

`SentenceSplitter(chunk_size=1024)` uses tiktoken to decide where to cut chunks. But nomic-embed-text inside Ollama uses BERT WordPiece. The same text gets very different token counts:

```
Markdown table separator line:
"|---------|---------|---------|"

tiktoken (BPE, merges repeated chars):  ≈  8 tokens
BERT WordPiece (each char separately):  ≈ 90 tokens  (10× more)
```

Measured on paper 2109.07958 (BIG-Bench), node 17:

| Metric | Value |
|---|---|
| Character length | 5834 |
| tiktoken count | 990 — SentenceSplitter thought this was safe |
| BERT token count (actual) | 2422 — exceeds 2048 limit |
| Tokens from `\|` and `-` alone | 1591 (65.7%) — formatting noise |

**Layer 2: HuggingFace BERT tokenizer vs Ollama GGUF tokenizer drift**

We added a HuggingFace BERT tokenizer pre-check (truncate to 2046 BERT tokens before sending to Ollama). The truncation fired correctly — but Ollama still returned 400.

Why: HuggingFace `bert-base-uncased` and Ollama's GGUF build of nomic-embed-text tokenize certain Unicode characters differently:

```
"…" (U+2026 HORIZONTAL ELLIPSIS — one character, common in academic PDFs)

HuggingFace bert-base-uncased:  "…" → 1 token
Ollama GGUF (llama.cpp):        "…" → 2 tokens

node[17] has 2 occurrences of "…"

Our HuggingFace pre-check said:
  [CLS] + 2046 content tokens + [SEP] = 2048 → looks safe ✓

Ollama GGUF actually counted:
  [CLS] + 2046 + 2 extra (one extra per "…") + [SEP] = 2050 → exceeds 2048 → 400 ✗
```

### Is Updating Ollama a Fix?

llama.cpp issue #5496 (BERT tokenizer Unicode discrepancy) was closed 2024-02-29, fixed by PR #5740. The fix addressed NFD accent normalization for characters like ō → o, ü → u.

U+2026 HORIZONTAL ELLIPSIS is **not** affected by NFD normalization (`NFD("…") = "…"` — it has no decomposition). PR #5740 does not fix the U+2026 discrepancy. Current Ollama v0.30.7 (llama.cpp b9509) includes the PR #5740 fix but the U+2026 problem remains. Updating Ollama is not a reliable solution.

### What is NFKC Normalization?

Unicode defines multiple ways to encode characters that look the same. NFKC is a standard that converts them all to their simplest ASCII-compatible form:

```
"…" (U+2026, 1 char, HORIZONTAL ELLIPSIS) → "..." (3 ASCII periods)
"ﬁ" (U+FB01, 1 char, fi ligature)         → "fi"  (2 ASCII chars)
"²" (U+00B2, 1 char, superscript 2)       → "2"   (1 ASCII char)
"ａ" (U+FF41, 1 char, fullwidth a)         → "a"   (1 ASCII char)
```

After NFKC normalization, HuggingFace and Ollama GGUF produce identical token counts for these characters — the source of drift is eliminated.

### Three Solution Options Considered

**Option A — Reduce buffer only:**
```
Change: BERT_MAX_TOKENS = 2046 → 1900
7% headroom absorbs known drift.
Downside: does not eliminate the drift source.
Other Unicode characters could cause the same crash in the future.
```

**Option B — NFKC normalization + reduced buffer (chosen):**
```
Step 1: normalize("NFKC", text)
  Converts "…" → "..." and similar characters.
  Both HuggingFace and Ollama agree on token counts after this.

Step 2: truncate to 1900 BERT tokens
  7% buffer catches any residual drift from other Unicode chars.
  decode with skip_special_tokens=True (no BERT artifacts in output).

Two-layer protection. Industry-recommended for PDF ingestion pipelines.
LangChain and Sentence Transformers apply NFKC internally by default.
```

**Option C — Update Ollama:**
```
Fixes NFD accent bugs from issue #5496 but NOT the U+2026 problem.
Not reliable. Not chosen.
```

### Fix Applied (Option B)

```python
import unicodedata
from transformers import AutoTokenizer

BERT_TOKENIZER = AutoTokenizer.from_pretrained("bert-base-uncased")
BERT_MAX_TOKENS = 1900  # 2048 × 93% — 7% buffer for GGUF tokenizer drift

def prepare_text_for_embedding(text: str) -> str:
    # Step 1: NFKC normalization
    # Converts typographic Unicode to ASCII equivalents.
    # "…" (U+2026) → "..." removes the HF vs GGUF token-count divergence.
    # Safe for academic/scientific text — does not change meaning.
    text = unicodedata.normalize("NFKC", text)

    # Step 2: Truncate to 1900 BERT tokens
    # add_special_tokens=False: count content only, leave 2 slots for [CLS]/[SEP]
    # skip_special_tokens=True: no BERT artifact tokens in decoded output
    ids = BERT_TOKENIZER.encode(text, add_special_tokens=False)
    if len(ids) > BERT_MAX_TOKENS:
        ids = ids[:BERT_MAX_TOKENS]
        text = BERT_TOKENIZER.decode(ids, skip_special_tokens=True)
    return text
```

Applied uniformly across all 5 chunking strategies so recall comparisons remain fair. Truncated nodes are logged with `event=truncated`.

### Why Not try/except?

A try/except that skips failing nodes causes non-deterministic data loss — some strategies might lose more nodes than others depending on which papers they process. This makes recall comparisons between strategies unreliable.

### Deeper Implication

Even with this fix, nodes dominated by markdown table separators have poor embedding quality — 65.7% of BERT tokens are `|` and `-` characters that carry no semantic meaning. This is a known limitation of BERT-based embedding models with markdown-formatted tables.

The three structure-aware strategies in Phase 1 (`markdown_element_splitter`, `docling_hybrid_chunker_512`, `docling_hierarchical_chunker`) separate tables from prose and produce cleaner chunks. Phase 1 measures whether this structural awareness actually improves recall.

**Industry best practices for table-heavy document RAG (2025):**
- LangChain: embed LLM-generated table summaries, store raw markdown table for generation (Multi-Vector Retriever)
- LlamaIndex: `MarkdownElementNodeParser` separates tables into `IndexNode`s — one of the 5 strategies in this experiment
- NeurIPS 2024 TableRAG: cell-level indexing for very large tables (overkill for academic paper RAG)
- Hybrid retrieval (BM25 + dense) + reranker: largest single recall improvement for text+table documents

---

## Notes on `transformers` Package Dependency

`bert-base-uncased` tokenizer requires the `transformers` package:
```bash
micromamba run -n py3.12 pip install transformers
```

Only the tokenizer config files are downloaded (~700 KB total). Model weights (~440 MB) are NOT downloaded. Files are cached at `~/.cache/huggingface/hub/` after first download.

The actual token limit for `nomic-embed-text` via Ollama is 2048 BERT tokens. Although the model card advertises 8192 tokens, Ollama's llama.cpp backend enforces a hard 2048-token ceiling (confirmed Ollama issue #7741).
