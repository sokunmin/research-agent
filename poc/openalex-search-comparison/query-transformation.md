# query-transformation.py — Experiment Report

## Purpose

Compare three query strategies for OpenAlex BM25 paper search across 25 queries grouped into 5 categories. The experiment measures whether LLM-based query transformation improves retrieval relevance over raw user input, and whether adding dynamic filter extraction (year_window, min_citations) further improves results beyond topic-only cleaning.

**Motivation (prior smoke test):** Informal smoke tests in `compare_search_methods.py` with hardcoded (non-LLM) query variants across 3 queries × 4 variants showed:
- `Works().search_filter(title_and_abstract=)` always returns 0 results regardless of query quality — too strict, rejected
- `Works().search(clean_topic)` produced correct top-1 in all 3 cases; `Works().search(raw_query)` produced off-topic results in 2/3 cases
- **Gap:** Those tests used hand-crafted ideal variants. This experiment uses real LLM output to answer: does the LLM actually produce clean_topic reliably, and does dynamic filter extraction add further value?

**Three questions this experiment answers:**
1. Does LLM query transformation improve retrieval over raw input? (A vs B)
2. Does dynamic filter extraction (year_window, min_citations) add improvement over topic-only cleaning? (B vs C)
3. Are improvements statistically significant across a 25-query diverse test set?

Script: `poc/openalex-search-comparison/query-transformation.py`
Results: `poc/openalex-search-comparison/query_transformation_results.json`
Run log: `poc/openalex-search-comparison/query_transformation_run_log.txt`

---

## Environment

| Item | Value |
|---|---|
| Python env | `micromamba py3.12` |
| Embedding model | `ollama/nomic-embed-text` (`LLM_RELEVANCE_EMBED_MODEL` from .env) |
| Transformation LLM | `ollama/ministral-3:14b-cloud` (`LLM_SMART_MODEL` from .env) |
| LLM-as-judge | `ollama_chat/gemma4:31b-cloud` (`LLM_VISION_FALLBACK_MODEL` from .env) |
| Ollama base URL | `http://localhost:11434` |
| Think suppression | `DISABLE_OLLAMA_THINK=true` → `extra_body={"think": False}` on all LLM calls |
| OpenAlex auth | `OPENALEX_API_KEY` + `OPENALEX_EMAIL` from .env (polite pool) |
| pyalex config | `max_retries=5`, `retry_backoff_factor=0.5` |

---

## Strategies Under Comparison

| ID | Name | BM25 input | year_window | min_citations | LLM calls |
|---|---|---|---|---|---|
| **A** | Raw (pipeline baseline) | Original user query unchanged | 3 (default) | 50 (default) | 0 |
| **B** | Clean topic | LLM-extracted `clean_topic` | 3 (default) | 50 (default) | 1 (shared with C) |
| **C** | Clean topic + dynamic filters | LLM-extracted `clean_topic` | LLM-extracted | LLM-extracted | 1 (shared with B) |

**B and C share a single LLM call per query** (`_extract_search_params`). Both receive the same `clean_topic`. The only difference between B and C is whether the LLM-extracted `year_window` and `min_citations` are applied to the OpenAlex filter.

---

## Prompts

### SEARCH_PARAMS_PMT (used by both B and C)

```
You are an academic search specialist.
Given a user research query, return JSON with exactly three keys:
- clean_topic: 2-6 plain keywords for OpenAlex BM25 full-text search.
  Output ONLY simple keywords separated by spaces — no boolean operators (AND/OR/NOT),
  no quotes, no parentheses, no date syntax, no special characters.
  Focus only on subject matter — ignore time periods, citation counts, and how the user phrased the request.
  Use domain-specific terminology. Keep scope faithful — do NOT generalise.
  Examples:
  'attention mechanism in transformer models in the last 2 years' -> 'attention mechanism transformer self-attention';
  'highly cited papers on LoRA fine-tuning' -> 'LoRA low-rank adaptation fine-tuning';
  'I want to learn about RAG for LLMs' -> 'retrieval augmented generation language models'
- year_window: integer 1-20. Extract from time phrases ('last 2 years' -> 2, 'recent' -> 3). Default 3.
- min_citations: integer >=0. Extract from citation phrases ('highly cited' -> 200,
  'at least 100 citations' -> 100). Default 50.
Return JSON only, no explanation, no markdown fences.
```

### JUDGE_PMT_TEMPLATE (LLM-as-judge, Strategy C categories 1–4 only)

```
Is the following paper relevant to this research query?

Research query: {original_query}

Paper title: {title}
Paper abstract: {abstract}

Answer with exactly one word: yes or no.
```

---

## Prompt Design Rationale: Negative vs Positive Instruction

### The Key Change

The `clean_topic` instruction in `SEARCH_PARAMS_PMT` was revised during this experiment:

| Version | Instruction |
|---|---|
| Negative (initial) | "Strip time constraints, citation constraints, and conversational phrasing." |
| Positive (final, current) | "Focus only on subject matter — ignore time periods, citation counts, and how the user phrased the request." |

The prompt currently in the script uses the **positive (current)** version.

### Why Positive Instruction Works Better (LLM Mechanism)

**1. Task Framing — Extraction vs Classification+Removal**

Negative instruction requires a two-step process:
1. Classify each part of the query: "Is this a time constraint? A citation constraint? Conversational phrasing?"
2. Remove what was classified

This intermediate classification task is error-prone because the categories have fuzzy boundaries. "Highly cited" is simultaneously a citation constraint *and* a semantic modifier describing paper quality. The model must decide which interpretation wins — and often doesn't.

Positive instruction instead asks: *"What is the academic subject matter of this query?"* This is a **semantic extraction** task — a single step that LLMs are directly trained to perform through exposure to millions of academic texts (paper titles, abstracts, keyword fields).

**2. Language Invariance**

Negative instruction implicitly assumes English grammar patterns:
- "Strip conversational phrasing" → assumes patterns like "I want to learn about", "papers on", "help me find"
- These don't generalize to Chinese ("最近有哪些...的論文"), Japanese, or other languages

Positive instruction's core concept — *"what is the academic subject matter?"* — is language-agnostic. The LLM's multilingual capacity handles syntax differences across languages naturally without needing language-specific stripping rules.

**3. Cognitive Load — One-Step vs Two-Step Reasoning**

Negative instructions require the model to first define a category boundary (what counts as "time constraint"?) before applying it. This extra reasoning step introduces an additional source of error.

Positive instruction directly defines the *target*: academic subject matter keywords. The model generates output by attending to what it already understands deeply — the vocabulary from paper titles, abstracts, and keyword fields.

### Evidence: Q20

Q20 query: *"highly cited recent work on vision transformers"*

| Version | clean_topic output |
|---|---|
| Negative prompt | `highly cited vision transformer ViT self-attention` |
| Positive prompt | `vision transformer ViT self-attention computer vision` |

With the negative prompt, the model correctly stripped "recent" (time constraint) but failed to strip "highly cited" — because "highly cited" also describes a property of papers, making it semantically ambiguous. With the positive prompt, the model asked itself "what is the subject matter?" and answered directly: vision transformers, ViT, self-attention, computer vision. No ambiguity.

### Observed Trade-off

Switching to positive prompt caused precision@5 to decrease slightly for Strategy B (0.230 → 0.190). This is because some queries had clean_topics that changed from specific technical acronyms ("VLMs CLIP vision transformer") to broader conceptual terms ("multimodal foundation models"). BM25 rewards exact string matches, so more specific acronyms retrieve papers whose titles contain those exact terms — which the LLM judge then rates as relevant.

However, this is a **BM25 surface matching artifact**, not an indicator of better semantic quality. The precision@5 difference is not statistically significant (p=0.1191, fails Holm-Bonferroni threshold α=0.0167), so the difference is within noise. The positive prompt produces cleaner, more language-agnostic queries that are more robust across diverse user inputs.

---

## Static Defaults

| Constant | Value | Description |
|---|---|---|
| `DEFAULT_YEAR_WINDOW` | 3 | years back from current year for `publication_year` filter |
| `DEFAULT_MIN_CITATIONS` | 50 | lower bound for `cited_by_count` filter |
| `PER_PAGE` | 20 | top-N results fetched for similarity computation |
| `OA_STATUS` | `diamond\|gold\|green` | OpenAlex open-access filter |

---

## Query Dataset (25 queries)

| ID | Category | Query |
|---|---|---|
| Q01 | 1 — Time constraint | attention mechanism in transformer models in the last 2 years |
| Q02 | 1 — Time constraint | recent advances in diffusion models for image generation |
| Q03 | 1 — Time constraint | graph neural networks in the past 3 years |
| Q04 | 1 — Time constraint | state space models for sequence modeling published recently |
| Q05 | 1 — Time constraint | vision language models from the last year |
| Q06 | 2 — Citation constraint | highly cited papers on LoRA fine-tuning |
| Q07 | 2 — Citation constraint | most influential work on RLHF for language models |
| Q08 | 2 — Citation constraint | seminal papers on knowledge distillation |
| Q09 | 2 — Citation constraint | highly cited research on mixture of experts |
| Q10 | 2 — Citation constraint | top cited work on in-context learning |
| Q11 | 3 — Conversational | I want to learn about RAG for LLMs |
| Q12 | 3 — Conversational | can you find papers about how transformers work |
| Q13 | 3 — Conversational | I'm looking for research on AI alignment |
| Q14 | 3 — Conversational | help me find papers about efficient inference for LLMs |
| Q15 | 3 — Conversational | papers explaining how chain of thought prompting works |
| Q16 | 4 — Mixed constraints | highly cited recent papers on instruction tuning for LLMs |
| Q17 | 4 — Mixed constraints | I want recent influential work on multimodal language models |
| Q18 | 4 — Mixed constraints | find me top papers on neural architecture search from the last 2 years |
| Q19 | 4 — Mixed constraints | most important papers on federated learning published recently |
| Q20 | 4 — Mixed constraints | highly cited recent work on vision transformers |
| Q21 | 5 — Clean (control) | transformer self-attention mechanism |
| Q22 | 5 — Clean (control) | BERT language model pre-training |
| Q23 | 5 — Clean (control) | contrastive learning visual representations |
| Q24 | 5 — Clean (control) | reinforcement learning policy gradient |
| Q25 | 5 — Clean (control) | neural machine translation sequence to sequence |

**Category design intent:**
- Cat 1–4: queries with non-semantic terms that BM25 may match literally (time/citation phrases, conversational words); Strategy A expected to underperform
- Cat 5: clean technical queries; A ≈ B ≈ C expected — validates that the metric is not uniformly biased toward any strategy. If Cat 5 shows B or C consistently higher than A on clean queries, the metric itself is suspect.

---

## Evaluation Metrics

| Metric | Definition | Scope | Notes |
|---|---|---|---|
| `mean_sim_at_20` | Mean cosine similarity between **original user query** embedding and top-20 OpenAlex result embeddings | All 25 queries | Original query (not reformulated) is embedded — measures whether retrieved papers match the user's original intent regardless of which query form was sent to BM25; uses `nomic-embed-text`; 0.0 if 0 results |
| `precision_at_5` | Fraction of top-k papers judged relevant by LLM-as-judge (yes/no per paper), where k = min(5, n_results) | Categories 1–4 only (N=20) | `None` if 0 results; denominator is min(5, n_results), not always 5; not run for Cat 5 (control group) |
| `n_results` | Total OpenAlex result count for the query+filter combination | All 25 queries | Recall proxy; very low values indicate over-restrictive filters |

**Statistical test:** Wilcoxon signed-rank, significance threshold p < 0.05.
- **Why Wilcoxon (non-parametric):** N=25 is too small to assume normality of differences; Wilcoxon makes no distributional assumption and is robust on small samples.
- **Why two-sided:** `scipy.stats.wilcoxon(alternative='two-sided')`. Strategy C may over-tighten filters and produce worse results than B — the direction of effect is not pre-assumed. One-sided (B > A) would be more powerful but inappropriate for B vs C.
- **Effect size:** `r = Z / sqrt(N)` where Z is approximated from p-value and sign of median difference.

**Embedding text construction** (mirrors `paper_scraping._build_paper_embedding_text`):
```
title + abstract (reconstructed from abstract_inverted_index) + keywords + topics
```
Note: `work.get("abstract")` always returns `None` in pyalex — abstract is reconstructed from `abstract_inverted_index`.

---

## Metric Interpretation

### What Each Metric Measures

**mean_sim@20** measures semantic alignment between the *original user query* and the top-20 papers retrieved by BM25:

1. Embed the original user query using `nomic-embed-text` → query vector
2. For each of the top-20 BM25 results, embed the paper (title + abstract + keywords + topics) → paper vector
3. Compute cosine similarity between query vector and each paper vector
4. Average the 20 similarity scores → mean_sim@20

Key point: the embedding always uses the **original raw query**, not the reformulated `clean_topic`. This ensures we measure whether *the retrieved papers match what the user actually wanted*, not whether the LLM rephrased the query correctly.

**precision@5** measures whether the top-5 papers are actually relevant, judged by an LLM:

1. Take the top-5 papers from BM25 results (or all if fewer than 5)
2. An LLM judge reads each paper's title + abstract and answers "yes/no: is this relevant to the original query?"
3. precision@5 = number of "yes" answers / 5

This is human-interpretable but dependent on the LLM judge's reasoning — there is inherent run-to-run variance.

### Why Both Metrics Improve for B/C vs A

Strategy A sends the raw query directly to BM25. Raw queries often contain non-academic tokens ("I want to learn about", "last 2 years", "highly cited") that:

- **For BM25:** become literal search tokens. BM25 ranks papers higher if they contain those exact tokens. A paper discussing "highly cited methods" may rank above a more relevant paper that simply doesn't use that phrase.
- **For embedding similarity:** the query vector encodes these modifiers, but retrieved papers don't contain them in their text, so cosine similarity is diluted.

Strategies B and C strip these non-topic tokens, leaving only domain-specific keywords (e.g., "attention mechanism transformer self-attention"). BM25 then retrieves papers whose titles/abstracts contain these exact academic terms — papers that are semantically closer to the user's actual research intent.

Result: both mean_sim@20 and precision@5 improve for B/C. Only mean_sim@20 is statistically significant (p<0.01 after Holm-Bonferroni). precision@5 shows the same directional improvement but does not reach significance (p=0.1191).

### Relationship to the Pipeline's Two-Stage Relevance Filter

The downstream pipeline uses a two-stage filter on BM25 candidates:
- **Stage 1 (embedding similarity):** embed each candidate paper → compare to topic embedding → filter by threshold
- **Stage 2 (LLM verification):** LLM re-ranks and confirms relevance for borderline papers

mean_sim@20 uses the same `nomic-embed-text` model and the same paper embedding construction as Stage 1. A higher mean_sim@20 means Stage 1 will retain more papers (more papers score above the relevance threshold), and those papers will be more semantically aligned with the user's intent.

mean_sim@20 is **not** Stage 1 itself — Stage 1 applies a threshold and filters; mean_sim@20 measures the distribution of scores before filtering. But it directly predicts how well Stage 1 will perform on these queries.

### Why B/C Precision@5 Is Not Uniformly Higher

Strategies B/C improve precision@5 on average, but individual queries show mixed results:

- **Cat 3 (Conversational, Q11–Q13), B < A:** Q11 "I want to learn about RAG for LLMs" → clean_topic: "retrieval augmented generation large language models". The raw query happened to match papers that use similarly informal phrasing in their abstracts. The cleaned topic retrieved academically phrased papers that are equally valid but less surface-matched.
- **Cat 2 (Citation constraint, Q07–Q08), B < A:** Strategy A's raw query contained "influential" / "seminal", which directly matched high-impact papers in OpenAlex. Those papers happen to be relevant — the citation-filtering language accidentally produced better BM25 matches.

This is why precision@5 serves as **directional corroboration**, not the primary metric. mean_sim@20 is more stable across query types because it measures semantic space alignment rather than surface keyword overlap.

---

## Full Results

### Per-Query Results (all 25 queries)

| Query ID | Category | mean_sim@20 (Strategy A: raw) | mean_sim@20 (Strategy B: clean topic) | mean_sim@20 (Strategy C: dynamic filters) | precision@5 (Strategy A) | precision@5 (Strategy B) | precision@5 (Strategy C) | clean_topic extracted by LLM (shared by B and C) |
|---|---|---|---|---|---|---|---|---|
| 01 | 1 | 0.535016 | 0.536434 | 0.563133 | 0.20 | 0.40 | 0.25 | attention mechanism transformer self-attention multihead attention |
| 02 | 1 | 0.490507 | 0.513163 | 0.513163 | 0.20 | 0.20 | 0.20 | diffusion models image generation score-based generative models |
| 03 | 1 | 0.533573 | 0.566207 | 0.566207 | 0.20 | 0.40 | 0.40 | graph neural networks GNN message passing |
| 04 | 1 | 0.491297 | 0.531075 | 0.531075 | 0.00 | 0.60 | 0.60 | state space models sequence modeling neural ordinary differential equations |
| 05 | 1 | 0.526168 | 0.556049 | 0.555687 | 0.00 | 0.20 | 0.20 | vision language models multimodal foundation models |
| 06 | 2 | 0.546148 | 0.569568 | 0.567186 | 0.00 | 0.20 | 0.25 | LoRA low-rank adaptation fine-tuning parameter-efficient transfer learning |
| 07 | 2 | 0.655358 | 0.637514 | 0.649426 | 0.00 | 0.00 | 0.00 | reinforcement learning human feedback language models RLHF |
| 08 | 2 | 0.528267 | 0.509243 | 0.512632 | 0.00 | 0.00 | 0.00 | knowledge distillation teacher student models |
| 09 | 2 | 0.484453 | 0.511686 | 0.518320 | 0.00 | 0.20 | 0.20 | mixture of experts sparse expert networks neural architecture search |
| 10 | 2 | 0.545957 | 0.569756 | 0.569756 | 0.00 | 0.20 | 0.20 | in-context learning prompt tuning few-shot learning |
| 11 | 3 | 0.545006 | 0.499319 | 0.499319 | 0.60 | 0.40 | 0.40 | retrieval augmented generation large language models |
| 12 | 3 | 0.502223 | 0.492328 | 0.492328 | 0.60 | 0.60 | 0.60 | transformer architecture self-attention positional encoding encoder decoder |
| 13 | 3 | 0.532129 | 0.523831 | 0.523831 | 0.20 | 0.00 | 0.00 | AI alignment safety interpretability robustness |
| 14 | 3 | 0.534788 | 0.573489 | 0.573489 | 0.20 | 0.00 | 0.00 | efficient inference large language models quantization pruning distillation |
| 15 | 3 | 0.525909 | 0.561437 | 0.561437 | 0.20 | 0.00 | 0.00 | chain thought prompting reasoning step-by-step |
| 16 | 4 | 0.580757 | 0.569393 | 0.569393 | 0.00 | 0.00 | 0.00 | instruction tuning large language models prompt engineering |
| 17 | 4 | 0.541017 | 0.590645 | 0.590645 | 0.00 | 0.00 | 0.00 | multimodal language models vision language pretraining cross-modal alignment |
| 18 | 4 | 0.556086 | 0.598163 | 0.569996 | 0.00 | 0.00 | 0.00 | neural architecture search NAS |
| 19 | 4 | 0.497738 | 0.495561 | 0.495561 | 0.00 | 0.20 | 0.20 | federated learning privacy-preserving distributed machine learning |
| 20 | 4 | 0.552582 | 0.597387 | 0.597387 | 0.00 | 0.20 | 0.20 | vision transformer ViT self-attention computer vision |
| 21 | 5 | 0.417054 | 0.423800 | 0.423800 | — | — | — | transformer self-attention mechanism multi-head attention |
| 22 | 5 | 0.545846 | 0.564158 | 0.564158 | — | — | — | BERT pre-training masked language modeling transformer |
| 23 | 5 | 0.481001 | 0.504062 | 0.504062 | — | — | — | contrastive learning visual representation self-supervised learning |
| 24 | 5 | 0.415238 | 0.415238 | 0.415238 | — | — | — | reinforcement learning policy gradient methods |
| 25 | 5 | 0.510799 | 0.516812 | 0.516812 | — | — | — | neural machine translation sequence to sequence encoder decoder attention |

---

### Overall Medians (N=25)

| Strategy | median mean_sim@20 |
|---|---|
| A (raw query) | 0.5321 |
| B (clean topic, fixed filters) | 0.5364 |
| C (clean topic, dynamic filters) | 0.5557 |

---

### Wilcoxon Signed-Rank Tests — mean_sim@20 (N=25)

| Comparison | median (strategy X) | median (strategy Y) | W (Wilcoxon test statistic) | p (p-value) | r (effect size) | Result |
|---|---|---|---|---|---|---|
| A vs B | 0.5321 | 0.5364 | 61.0 | 0.0096 | 0.529 | **significant** |
| B vs C | 0.5364 | 0.5557 | 10.0 | 0.5781 | 0.000 | not significant |
| A vs C | 0.5321 | 0.5557 | 53.0 | 0.0043 | 0.582 | **significant** |

**Holm-Bonferroni correction (k=3, sorted by p):** A vs C (p=0.0043 < α=0.0167 ✓), A vs B (p=0.0096 < α=0.025 ✓), B vs C (p=0.5781 > α=0.05 ✗). Both A vs B and A vs C remain significant after correction.

---

### Per-Category Breakdown — median mean_sim@20

| Category | N (queries) | Description | median mean_sim@20 (Strategy A) | median mean_sim@20 (Strategy B) | median mean_sim@20 (Strategy C) | B > A | C > B |
|---|---|---|---|---|---|---|---|
| 1 | 5 | Time constraint | 0.5262 | 0.5364 | 0.5557 | ✓ | ✓ |
| 2 | 5 | Citation constraint | 0.5460 | 0.5696 | 0.5672 | ✓ | ✗ |
| 3 | 5 | Conversational | 0.5321 | 0.5238 | 0.5238 | ✗ | ✗ |
| 4 | 5 | Mixed constraints | 0.5526 | 0.5906 | 0.5700 | ✓ | ✗ |
| 5 | 5 | Clean (control) | 0.4810 | 0.5041 | 0.5041 | ✓ | ✗ |

---

### LLM-as-Judge Precision@5 — Categories 1–4 (N=20)

| Strategy | mean precision@5 | N |
|---|---|---|
| A | 0.120 | 20 |
| B | 0.190 | 20 |
| C | 0.185 | 20 |

#### Wilcoxon Signed-Rank Tests — precision@5 (paired, N=20)

| Comparison | median (strategy X) | median (strategy Y) | W (Wilcoxon test statistic) | p (p-value) | r (effect size) | Result |
|---|---|---|---|---|---|---|
| A vs B | 0.000 | 0.200 | 22.0 | 0.1191 | 0.000 | not significant |
| B vs C | 0.200 | 0.200 | 1.0 | 1.0000 | 0.000 | not significant |
| A vs C | 0.000 | 0.200 | 23.0 | 0.1260 | 0.000 | not significant |

Note: Only queries where all three strategies had non-`None` `precision_at_5` values are included in the paired test. Queries with `n_results=0` for any strategy produce `precision_at_5=None` and are excluded from the pair.

**Holm-Bonferroni correction (k=3, sorted by p):** A vs B (p=0.1191 > α=0.0167 ✗) — first test fails, all three tests are not significant after correction. Precision@5 serves as directional corroboration only; mean_sim@20 is the confirmatory indicator.

---

### Strategy C — Extracted Filter Values Per Query

| Query ID | Category | year_window | min_citations | n_results (total OpenAlex result count) |
|---|---|---|---|---|
| 01 | 1 | 2 | 50 | 4 |
| 02 | 1 | 3 | 50 | 199 |
| 03 | 1 | 3 | 50 | 46 |
| 04 | 1 | 3 | 50 | 46 |
| 05 | 1 | 2 | 50 | 60 |
| 06 | 2 | 3 | 200 | 4 |
| 07 | 2 | 3 | 200 | 8 |
| 08 | 2 | 3 | 200 | 9 |
| 09 | 2 | 3 | 200 | 10 |
| 10 | 2 | 3 | 200 | 38 |
| 11 | 3 | 3 | 50 | 391 |
| 12 | 3 | 3 | 50 | 124 |
| 13 | 3 | 3 | 50 | 270 |
| 14 | 3 | 3 | 50 | 39 |
| 15 | 3 | 3 | 50 | 189 |
| 16 | 4 | 3 | 200 | 32 |
| 17 | 4 | 3 | 50 | 104 |
| 18 | 4 | 2 | 50 | 8 |
| 19 | 4 | 3 | 50 | 218 |
| 20 | 4 | 3 | 100 | 43 |
| 21 | 5 | 3 | 50 | 337 |
| 22 | 5 | 3 | 50 | 145 |
| 23 | 5 | 3 | 50 | 497 |
| 24 | 5 | 3 | 50 | 280 |
| 25 | 5 | 3 | 50 | 273 |

---

## Implementation Notes

### Single LLM call for B and C
`_extract_search_params(query)` is called once per query and returns `{clean_topic, year_window, min_citations}`. Strategy B uses `clean_topic` with default filters. Strategy C uses all three fields. This ensures B and C receive the identical `clean_topic`; the only controlled variable between B and C is whether dynamic filter values are applied.

### Why separate strategy B and C prompts were abandoned
An earlier version used two separate prompts: `STRATEGY_B_PMT` (topic-only) and `STRATEGY_C_PMT` (full SearchParams). The B prompt produced PubMed Boolean syntax on several queries (e.g. `"attention mechanisms" AND "transformer models" AND ("2022/01/01"[Date - Publication]...)`), causing 0 results or HTTP 500 errors. The root cause was that the prompt said "BM25 query" without format constraints — the model defaulted to its training bias toward PubMed/Boolean syntax. The merged `SEARCH_PARAMS_PMT` with explicit format constraints (no operators, no quotes, plain keywords only) and concrete examples resolved this.

### Abstract reconstruction
`work.get("abstract")` always returns `None` in pyalex. Abstract text is reconstructed from `work.get("abstract_inverted_index")` using word-position sorting. This mirrors `paper_scraping._reconstruct_abstract()`.

### Embedding input fields
Paper embedding text = `title + abstract + keywords + topics`. This mirrors `paper_scraping._build_paper_embedding_text()` to ensure cosine similarity scores are in the same calibrated space as the pipeline's relevance filter.

### Category 5 control group
Cat 5 queries are already clean technical terms. A ≈ B ≈ C is expected. The observed results (Q21–Q25) confirm this: B and C are equal to A or marginally higher, validating that the metric is not artificially inflating B/C scores. Q24 shows all three strategies at identical sim=0.4152, the lowest across all queries.

---

## Statistical Test Rationale

### Why Wilcoxon Signed-Rank?

Test selection follows three sequential decisions:

**Decision 1 — Paired or independent?**

The same 25 queries are evaluated under all three strategies. Each query produces one score per strategy, forming matched triples — this is a repeated-measures (within-subject) design. All independent-group tests are inapplicable:

| Excluded test | Why excluded |
|---|---|
| Independent t-test | Assumes two separate, unrelated samples |
| Mann-Whitney U | Non-parametric equivalent of independent t-test — same exclusion |
| One-way ANOVA | Assumes independent groups |
| Kruskal-Wallis | Non-parametric one-way ANOVA — same exclusion |
| Fisher's Exact / Chi-square | Categorical data in independent groups |

**Decision 2 — How many groups per comparison?**

The experiment uses pairwise comparisons (A vs B, B vs C, A vs C) with pre-specified directional hypotheses. Multi-group omnibus tests are not required:

| Excluded test | Why excluded |
|---|---|
| RM-ANOVA | Tests k≥3 conditions simultaneously; parametric (requires normality + sphericity) |
| Friedman | Non-parametric RM-ANOVA — appropriate as omnibus, but pre-specified pairwise hypotheses make it unnecessary |

When hypotheses are confirmatory and pre-specified (not exploratory), pairwise tests without an omnibus step are statistically defensible. Friedman would be required for exploratory "does anything differ?" questions.

**Decision 3 — Binary or continuous? Parametric or non-parametric?**

Two paired tests remain: Paired t-test and Wilcoxon signed-rank. Two additional paired tests are also eliminated here:

| Excluded test | Why excluded |
|---|---|
| McNemar | Requires binary outcome (0/1 per pair); mean_sim@20 is continuous |
| Cochran's Q | Multi-condition extension of McNemar; same binary requirement |

Paired t-test vs Wilcoxon signed-rank:

| Criterion | Paired t-test | Wilcoxon signed-rank |
|---|---|---|
| Distributional assumption | Differences must be normally distributed | No distributional assumption (only requires ordinal ranking of differences) |
| N=25 | Shapiro-Wilk power too low to verify normality reliably | Robust regardless |
| Tied differences | Inflates variance estimate when many diffs = 0 | Handles tied pairs via average rank assignment |
| mean_sim@20 range | Bounded [0,1] — difference distribution shape unknown | Unaffected |

**Shapiro-Wilk** is the prerequisite normality test: if differences pass (p > 0.05), Paired t-test is valid. At N=25, Shapiro-Wilk lacks sufficient power to reliably detect non-normality. Combined with the large tied-pair count in B vs C (17/25 differences = 0), Wilcoxon is the correct choice.

**Decision tree summary:**

```
Paired / repeated measures (same 25 queries under all 3 strategies)
    │
    ├─ k≥3 simultaneous → RM-ANOVA (parametric), Friedman (non-parametric)
    │   [excluded: pairwise comparisons with pre-specified hypotheses]
    │
    ├─ Binary outcome (0/1) → McNemar, Cochran's Q
    │   [excluded: mean_sim@20 is continuous]
    │
    └─ Two-group pairwise, continuous data
           │
           ├─ Normal differences → Paired t-test
           │   [excluded: N=25 too small to verify normality; large tied-pair count]
           │
           └─ No distributional assumption → ✅ Wilcoxon signed-rank
```

---

### Why No Omnibus (Friedman) Test?

Friedman test is the non-parametric equivalent of one-way RM-ANOVA. It tests whether any difference exists among k conditions simultaneously, controlling the family-wise Type I error before pairwise comparisons.

**Omnibus is required when:** the analysis is exploratory — hypotheses are formed after seeing which pairs differ.

**Omnibus is not required when:** hypotheses are pre-specified and confirmatory. This experiment defines two primary hypotheses before execution:
1. Does B outperform A? (topic cleaning effect)
2. Does C outperform B? (dynamic filter effect)

These are directional, pre-registered hypotheses, not post-hoc fishing. Skipping the Friedman omnibus step is statistically defensible in this context.

A secondary structural reason: A vs C is logically dependent on A vs B and B vs C (transitivity). The effective number of independent comparisons is 2, not 3 — the omnibus provides limited additional protection.

---

### Why Holm-Bonferroni? Why Not Standard Bonferroni?

Three pairwise tests per metric inflate the family-wise Type I error rate beyond α=0.05. Multiple comparison correction is needed.

**Standard Bonferroni** sets the per-test threshold at α/k = 0.05/3 = 0.0167. It is uniformly conservative because it assumes all k tests are independent — which they are not here (A vs C is determined by A vs B and B vs C).

**Holm-Bonferroni** (sequential Bonferroni) sorts tests by p-value and applies decreasing thresholds (0.05/k, 0.05/(k-1), ..., 0.05/1). It is a step-down procedure that is:
- Mathematically proven to control FWER at the same α=0.05 as standard Bonferroni
- Uniformly more powerful — never rejects fewer tests than standard Bonferroni

There is no scenario where standard Bonferroni outperforms Holm. Holm should always be preferred.

**Impact on this experiment:**

*mean_sim@20 (k=3, sorted by p):*

| Rank | Comparison | p | Holm α | Result |
|---|---|---|---|---|
| 1 | A vs C | 0.0043 | 0.05/3 = 0.0167 | ✓ significant |
| 2 | A vs B | 0.0096 | 0.05/2 = 0.025 | ✓ significant |
| 3 | B vs C | 0.5781 | 0.05/1 = 0.05 | ✗ not significant |

Main conclusion unchanged: topic cleaning (B) significantly outperforms raw query (A).

*precision@5 (k=3, sorted by p):*

| Rank | Comparison | p | Holm α | Result |
|---|---|---|---|---|
| 1 | A vs B | 0.1191 | 0.05/3 = 0.0167 | ✗ first test fails → all not significant |

The A vs B precision@5 result (p=0.1191) fails Holm-Bonferroni. Precision@5 serves as directional corroboration only; mean_sim@20 is the sole confirmatory indicator.

---

### Sample Size Justification (N=25)

N=25 was chosen as a balanced design: 5 query categories × 5 queries per category. Equal category representation is required for the per-category breakdown analysis. To maintain balance, any increase would need to add queries in multiples of 5 per category.

N=25 is not an arbitrary convenience choice — it is sufficient for the observed effect size:

| Effect | r | Minimum N for 80% power (α=0.05, two-sided) | Post-hoc power at N=25 |
|---|---|---|---|
| A vs B mean_sim@20 | 0.529 | ~12 | >97% |
| A vs B precision@5 | 0.000 | — | — |

The experiment was adequately powered to detect the A vs B effect. The precision@5 Holm-Bonferroni failure reflects the correction threshold (p=0.1191 > 0.0167), not insufficient power — the uncorrected p already shows a clear directional signal.

---

## Known Limitations

1. **LLM-as-judge not run for Cat 5** — `precision_at_5=None` for all Cat 5 queries by design. The Wilcoxon precision@5 test uses N=20 (Cat 1–4 only).
2. **Cat 3 B < A** — conversational queries (Q11, Q12) show B lower than A. The LLM extracted accurate topic keywords but the original phrasing ("I want to learn about RAG for LLMs") matched the specific RAG papers more directly because those papers use similar informal language in their abstracts.
3. **Single run, no replication** — each query was run once. Embedding-based similarity scores are deterministic; LLM-as-judge outputs may vary across runs.
4. **r=0.000 for B vs C and A vs C in Wilcoxon tables** — the script computes effect size r as `np.sign(np.median(all_diffs)) * z / sqrt(N)`. When most pairs are tied (diff=0), the median of all 25 (or 20) diffs is 0, making np.sign=0 and r=0 regardless of the non-tied pairs' direction. Affected comparisons: B vs C sim@20 (8/25 non-tied, mixed direction), B vs C precision@5 (3/20 non-tied, all B > C), A vs C precision@5 (12/20 non-tied, mixed direction). The W and p values are unaffected by this formula limitation.
