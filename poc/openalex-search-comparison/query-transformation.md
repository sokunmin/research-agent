# query-transformation.py — Experiment Report

## Purpose

Compare two LLM prompt designs for extracting structured search parameters from a natural-language research query: whether the query names a research topic, whether it expresses a year or citation-count preference, and what the core topic keywords are. This experiment does not call OpenAlex and does not evaluate retrieval quality — it only checks whether each prompt design extracts these fields correctly against a hand-authored ground truth.

Script: `poc/openalex-search-comparison/query-transformation.py`
Ground truth: `poc/openalex-search-comparison/query_transformation_v2_gt.json` (40 queries)
Results: `poc/openalex-search-comparison/query_transformation_v2_results/plan_comparison.json`

---

## Background: Why This Experiment Was Redone

An earlier version of this script compared three strategies (raw query, LLM-cleaned topic, LLM-cleaned topic with dynamic filters) by sending each to OpenAlex and measuring retrieval quality (`mean_sim@20`, `precision@5`) across 25 queries. That comparison is documented separately and is not repeated here.

Since that earlier comparison ran, the production pipeline's extraction prompt (`SEARCH_PARAMS_EXTRACTION_PMT` in `backend/prompts/prompts.py`) changed in ways the earlier experiment never tested:

- Two new fields were added: `has_identifiable_topic` (a boolean guard for queries with no research subject) and `topic_missing_reason` (a one-sentence explanation shown back to the user when no topic is found).
- The `year_window` instruction was expanded with explicit filter-math examples and a `{current_year}` template variable (needed because the extraction model's training-data cutoff does not match the actual current date).
- A rule was added instructing the model not to expand or "correct" proper nouns, model names, or abbreviations (e.g. BERT, GPT, LoRA) when extracting the topic.
- The production prompt's few-shot examples are all drawn from the ML/AI domain (attention mechanisms, LoRA, RAG).

This experiment tests these newer behaviors directly, using a redesigned test set and a redesigned evaluation method (ground-truth comparison instead of retrieval-based similarity scoring).

---

## Design Decisions

### Question-Form Prompting Instead of Declarative Field Descriptions

The production prompt and the earlier experiment's prompt both describe each field declaratively, e.g. `"has_identifiable_topic: boolean. True if the query names a concrete academic concept..."`. This experiment's prompts instead phrase every field as a direct question, e.g. `"Does the query actually request academic literature on some subject...? -> has_identifiable_topic (true/false)"`, with `->` mapping each question to its output field.

Rationale: question-answering is a heavily represented format in LLM training and instruction-tuning data, compared to schema-field description. A direct question may align more closely with how the model is trained to reason about presence/absence of information, requiring less indirection than translating an abstract field description into an implicit judgment. This is a hypothesis motivating the design choice, not a claim independently verified by this experiment — this experiment did not run a controlled question-form-vs-declarative-form comparison; both prompt variants tested here use question form.

### No Few-Shot Examples

Neither prompt variant includes worked examples (the production prompt has four ML-domain examples for `clean_topic` extraction). This repository has two prior findings, from separate experiments, relevant to this decision:

- `experiments/02-agent-behavior/09-react_agent_task_prompt_eval.md`: a code example with no null-guard caused a tested model to omit null guards in its own output, even when the text instruction said to include them — described there as "a model mimics the style of provided code examples — including what they omit."
- `experiments/02-agent-behavior/10-react_agent_tool_dispatch_eval.md`: a few-shot JSON key name created a pattern that overrode the actual required key name in the model's output.
- `experiments/02-agent-behavior/06-structured_output_method_comparison.md`: few-shot prompting added measured latency with no accuracy gain over field descriptions alone, on the same model family tested here.

Based on these findings, this experiment's prompts rely only on field descriptions and conceptual instructions, with no example query-to-output pairs, and no domain-specific vocabulary in the instructions themselves.

### Two Extraction Strategies Compared

| Strategy | LLM calls | Class |
|---|---|---|
| `single_call_staged` | 1 | `SingleCallStagedExtractor` |
| `split_topic_filter` | 2 (topic call + filter call) | `SplitTopicFilterExtractor` |

`single_call_staged` asks all seven fields (topic validity, topic-missing reason, year constraint flag, year window, citation constraint flag, min citations, clean topic) in one LLM call, with the seven questions ordered so the model judges topic validity and constraints before extracting the topic keywords last.

`split_topic_filter` asks the three topic-related fields in one call and the four year/citation fields in a second, independent call. The two calls do not depend on each other's output. The implementation issues them sequentially; they were not parallelized in this run.

The two strategies test whether combining all extraction into one call causes cross-task interference — specifically, whether an instruction to *ignore* year/citation phrasing when building the topic keywords (needed for the `clean_topic` field) interferes with, or is interfered with by, the requirement to *detect* that same phrasing (needed for the `has_year_constraint`/`has_citation_constraint` fields) when both instructions are present in the same prompt.

### Identical Wording Across Both Strategies

Both prompts use word-for-word identical phrasing for every corresponding question (e.g. both ask "however broad?" when judging topic validity; both include "use the exact number if given, otherwise your best judgment" when extracting year/citation values; both include the same "no boolean operators... ignore how recent or well-cited..." instruction when extracting the topic). This was corrected during prompt design after an initial draft had these phrases present in one strategy's prompt but not the other's, which would have made the strategy comparison confounded with a wording-completeness comparison rather than a pure call-structure comparison.

### No OpenAlex Calls

This experiment stops after the LLM extraction step. Extracted parameters are not sent to OpenAlex, and no retrieval-based metric is computed. Including OpenAlex would introduce additional variables (database content, ranking behavior) unrelated to the prompt design being compared, making it impossible to attribute a result to the extraction prompt versus the search engine's own behavior.

---

## Ground Truth Design

Ground truth for all 40 queries is stored in `query_transformation_v2_gt.json`, authored by an LLM (Claude) and spot-checked by hand for the boundary/ambiguous categories before being used. It was not independently re-verified by a second reviewer.

### `has_topic`

A boolean expected value. Checked by exact match against the model's `has_identifiable_topic` output.

### `year_window`

One of three types:
- `explicit`: the query gives an exact number (e.g. "last 2 years" -> 2). Checked by exact match.
- `vague`: the query implies a preference without an exact number (e.g. "recent"). Ground truth specifies an `acceptable_range` (e.g. `[2, 4]`); checked by range membership, not exact match, since no single number is uniquely correct for a vague phrase.
- `absent`: the query does not mention time. Checked by exact match against the system default (3).

### `min_citations`

Uses `explicit` and `absent` the same way as `year_window` (exact match). For `vague` cases, ground truth specifies a `floor` value instead of a range, and the check is `actual >= floor`, not a bounded range. This differs from `year_window`'s vague handling: a citation count above the floor is still consistent with the query's intent (a value of 500 for "highly cited" is not wrong, only stricter than a lower estimate would be), whereas a `year_window` that is too large defeats the purpose of a "recent" constraint. The two fields were given different comparison rules for this reason.

### `clean_topic`

Not compared by exact string match. Ground truth provides a `clean_topic_reference_answer` (an example of an acceptable answer, not the only correct one) and a `clean_topic_must_preserve` list (specific terms, e.g. proper nouns or acronyms, that the extracted topic should recognizably retain — some entries list acceptable alternatives, e.g. `"RAG"` or `"retrieval augmented generation"`). Evaluation of this field is described under Evaluation Architecture below.

---

## Test Dataset (40 Queries)

### Category Breakdown

| Category | N | Purpose |
|---|---|---|
| `time_constraint` | 4 | Year constraint only, mix of explicit and vague phrasing |
| `citation_constraint` | 4 | Citation constraint only, vague phrasing (e.g. "highly cited") |
| `conversational` | 2 | Informal phrasing, no year/citation constraint |
| `clean_technical` | 2 | Formal technical phrasing, no year/citation constraint |
| `mixed_constraints` | 5 | Year and citation constraints both present, including one query with both given as explicit numbers |
| `no_topic_boundary` | 2 | Queries expressing search intent with no actual subject matter (e.g. "help me find good research to read") |
| `no_topic_clear` | 1 | A query unrelated to literature search despite containing a domain-adjacent word ("what's the weather today") |
| `topic_boundary_bare` | 1 | A bare topic-like noun phrase with no additional context ("weather forecast") |
| `topic_with_context` | 1 | The same subject area with explicit research framing ("regression models for weather forecasting") |
| `citation_explicit` | 5 | Citation constraint given as an explicit number, including combinations with explicit or vague year constraints |
| `cross_domain_broad` | 4 | Single-word or short broad topics outside ML/AI (medicine, physics, environmental science, biology) |
| `cross_domain_specific` | 4 | Specific technical terms/acronyms outside ML/AI (CRISPR, dark matter, renewable energy, mRNA) |
| `retained_original` | 5 | Queries carried over unchanged from the earlier 25-query experiment, for reference |

Total: 40.

### Combinatorial Coverage Rationale

The three boolean/near-boolean dimensions (topic present, year constraint present, citation constraint present) define 8 possible combinations. The retained/mixed/time/citation categories cover the four combinations where a topic is present; the `no_topic_*` and `topic_boundary_*` categories were added specifically because the earlier 25-query experiment (predating the `has_identifiable_topic` field) had zero coverage of the four combinations where no topic is present.

### The "weather forecast" Minimal Pair

Three queries share the word "weather" but differ in grammatical structure and intended answer:

| Query | Expected `has_topic` | Reasoning |
|---|---|---|
| "what's the weather today" | `false` | Phrased as a direct question requesting a specific real-time fact, not a request for literature |
| "weather forecast" | `true` | A bare noun phrase; in the context of a paper-search system, defaults to being read as a topic description |
| "regression models for weather forecasting" | `true` | Explicit research framing, unambiguous |

This set tests whether the model distinguishes "a query structured as a topic description" from "a query structured as a direct question that happens to mention a domain-adjacent word," rather than keying off the presence of any single word.

---

## Evaluation Architecture

### Deterministic Checks (Python)

`GroundTruthChecker` in `query-transformation.py` implements the exact/range/floor comparison rules described above for `has_topic`, `year_window`, and `min_citations`. These checks require no LLM call and produce the same result on every run for the same extracted output.

### LLM-as-Judge for `clean_topic` Quality (Claude, Single-Pass)

`clean_topic` is free text, so paraphrases and reordering should not be penalized by exact string matching (e.g. "neural networks for graphs" should not be marked wrong for failing to match "graph neural networks" character-for-character). This field was judged by Claude, reading each extracted `clean_topic` against that query's `clean_topic_reference_answer` and `clean_topic_must_preserve` list, producing:

- `preserves_key_terms` (boolean): whether every required term is recognizably present (word-level matching; alternatives listed with "or" both count).
- `quality_score` (1-3): 3 = faithfully captures the subject with no meaningful loss; 2 = captures the general direction but loses specificity or over-broadens a term; 1 = misses the subject, drops a required term, or corrupts a term into something unrelated.
- `reason`: one sentence justifying the score, logged so any individual judgment can be manually reviewed afterward.

Each sample was judged once, not via repeated sampling with majority voting. This is an explicit cost/reliability trade-off, discussed below.

---

## Trade-offs

- **No statistical significance testing.** With 37-40 topic-present queries split across 13 categories (2-5 queries per category), most categories do not have enough samples for a paired significance test (e.g. McNemar's test) to reach conventional power. Results below are reported as raw counts and scores, not p-values.
- **Single-pass LLM judging, not multi-sample consensus.** Asking the same judge model the same question multiple times and taking a majority vote reduces the effect of any single judgment's variance, at the cost of additional LLM calls. This experiment used one judgment per sample due to a stated cost constraint. Judgments include a logged reason specifically so they remain manually spot-checkable after the fact, partially offsetting the lack of repeated sampling.
- **Ground truth was LLM-authored, not independently re-verified for every entry.** The boundary/ambiguous categories were spot-checked by hand; the remaining entries were not.
- **The extraction model (`ministral-3:14b-cloud`) is the only model tested.** Results describe this model's behavior under both prompt designs; they do not describe how a different extraction model would behave under the same two designs.

---

## Full Results

### Deterministic Field Accuracy (out of 40)

| Field | `single_call_staged` | `split_topic_filter` |
|---|---|---|
| `has_topic_correct` | 39/40 | 39/40 |
| `year_window_correct` | 40/40 | 40/40 |
| `min_citations_correct` | 37/40 | 37/40 |

Both strategies produced identical totals on all three fields. Individual queries were not always identical between the two strategies: for `min_citations`, `single_call_staged` failed on query ids 14, 17, 39; `split_topic_filter` failed on query ids 7, 14, 17. Ids 14 and 17 failed under both strategies (a shared failure, not distinguishing between them); ids 7 and 39 each failed under only one strategy (one discordant pair each direction).

`has_topic_correct` failed identically for both strategies on query id 21 ("weather forecast" — ground truth expects `true`; both strategies extracted `false`). Both strategies produced an empty `clean_topic` for this query, consistent with the extraction prompts' own instruction to leave `clean_topic` empty when no topic is judged present.

### `clean_topic` Quality Scores (out of 37 topic-present queries)

| Metric | `single_call_staged` | `split_topic_filter` |
|---|---|---|
| `preserves_key_terms = true` | 36/37 | 36/37 |
| Mean `quality_score` (1-3) | 2.92 | 2.65 |
| Score distribution (3 / 2 / 1) | 35 / 1 / 1 | 25 / 11 / 1 |

### Samples Scoring ≤2 or Failing Term Preservation

| Query ID | Strategy | Extracted `clean_topic` | Reason |
|---|---|---|---|
| 5 | `split_topic_filter` | "LoRA fine-tuning highly cited papers" | Leaks the citation-constraint phrase "highly cited papers" into the topic string |
| 7 | `single_call_staged` | "knowledge distillation seminal papers" | Leaks "seminal papers" qualifier |
| 7 | `split_topic_filter` | "knowledge distillation seminal papers machine learning deep learning neural networks" | Leaks citation phrase and adds generic, non-specific terms |
| 8 | `split_topic_filter` | "in-context learning top cited work" | Leaks "top cited work" qualifier |
| 10 | `split_topic_filter` | "transformers architecture neural networks attention mechanisms deep learning" | Diluted with generic terms not specific to the query |
| 15 | `split_topic_filter` | "vision transformers highly cited recent work" | Leaks citation/recency qualifier |
| 16 | `split_topic_filter` | "federated learning citations" | Leaks the word "citations" |
| 21 | `single_call_staged` | "" (empty) | `has_identifiable_topic` was incorrectly `false` for this query (see above); the extraction prompt leaves `clean_topic` empty in that case |
| 21 | `split_topic_filter` | "" (empty) | Same as above |
| 23 | `split_topic_filter` | "LoRA fine-tuning citations" | Leaks the word "citations" |
| 24 | `split_topic_filter` | "knowledge distillation machine learning" | Broadened with a generic, non-specific term |
| 25 | `split_topic_filter` | "RAG retrieval augmented generation citations" | Leaks the word "citations" |
| 26 | `split_topic_filter` | "vision transformers citations" | Leaks the word "citations" |
| 27 | `split_topic_filter` | "mixture of experts MoE deep learning neural networks" | Diluted with generic terms not specific to the query |

12 of these 14 cases are `split_topic_filter`; 11 of the 12 involve a year- or citation-related word appearing in `clean_topic` despite the prompt's explicit instruction to exclude such words.

### An Observed Pattern in the Failure Cases

In `single_call_staged`, the four questions asking the model to identify and extract year/citation constraints (questions 3-6) come immediately before the question asking it to extract the topic while ignoring those same constraints (question 7), within the same LLM call. In `split_topic_filter`, the topic-extraction call never asks about year/citation constraints at all — the instruction to ignore them appears without the model having first been asked to identify them in that call.

The majority of `split_topic_filter`'s lower-scoring `clean_topic` extractions involve exactly the words (citation counts, "highly cited," "seminal," "top cited") that the same model's `has_citation_constraint`/`min_citations` questions (asked in a separate call) correctly identified as constraint-related. This experiment did not run a further controlled test isolating why this pattern occurs — it is reported as an observed association between the two calls' outputs for `split_topic_filter`, not a mechanism confirmed by additional experimentation.

---

## Implementation

### Prompts

Full text of `SEARCH_PARAMS_STAGED_PMT`, `TOPIC_EXTRACTION_PMT`, and `SEARCH_FILTERS_EXTRACTION_PMT` is in `query-transformation.py`.

### Reused Components from `poc_base.py`

- `ConfigResultTracker`: per-sample JSON persistence with atomic writes and resume support, reused unmodified for storing the 80 (query, strategy) samples.
- `ExperimentLogger`: structured `[TAG] key=value` console logging, reused unmodified.

`SearchParamsExtractionStrategy` (abstract base class), `SingleCallStagedExtractor`, `SplitTopicFilterExtractor`, and `GroundTruthChecker` are defined in `query-transformation.py` itself, not in `poc_base.py`, since they are specific to this experiment's domain (query parameter extraction) rather than general-purpose utilities reusable across other PoC scripts.

---

## Known Limitations

1. **Single extraction model tested.** All results describe `ministral-3:14b-cloud`'s behavior; a different model may not reproduce the same pattern between the two strategies.
2. **`clean_topic` quality judged by a single LLM pass per sample**, not a multi-sample or multi-model consensus (see Trade-offs).
3. **Small per-category sample sizes** (2-8 queries per category) support pattern observation, not statistically powered comparison.
4. **Ground truth was not independently re-verified for every entry** beyond the spot-checked boundary/ambiguous categories.
5. **`split_topic_filter`'s two calls were run sequentially**, not in parallel, in this implementation, though they are independent and could be parallelized.
6. **This experiment does not evaluate downstream retrieval quality.** It measures extraction accuracy against ground truth only; it does not measure what OpenAlex would return if the extracted parameters were used to search.
