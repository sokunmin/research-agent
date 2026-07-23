# Experiment 5 — Query Transformation: Structured Extraction

## Task Context

This experiment targets **Step 1 — Paper Discovery** (`discover_candidate_papers`) in `SummaryGenerationWorkflow` (README → System Architecture).

```
Input: user_query (str)                        ← user input
      │
      ▼
┌── 1. PAPER DISCOVERY ────────────────────────────────────────────────────────┐
├─── Original (lz-chen) ──────────────────────┬─── My Implementation ──────────┤
│ Tavily web search                           │ OpenAlex BM25 with             │
│   → Semantic Scholar API                    │   query transformation         │
│   (title match + citation expansion)        │   + quality filters            │
│   Non-deterministic; paid API               │   (oa_status, citations, year) │
└─────────────────────────────────────────────┴────────────────────────────────┘
      │
      ▼
Output: List[Paper]                                    → Step 2: Relevance Filter
```

The experiment targets the search-parameter extraction sub-step inside `discover_candidate_papers`. This sub-step converts the raw user query into a topic keyword string plus a recency and citation filter, before any BM25 call is made.

```
Step 1 — discover_candidate_papers (detail)
──────────────────────────────────────────────────────────────────────────
 Input: raw user_query
       │
       ▼
 ┌─── EXPERIMENT TARGET: Search Parameter Extraction ─────────────────────────────┐
 │                                                                                │
 │  ┌── Single-Call Design ✅ ──────┐    ┌── Split-Call Design ─────────────────┐ │
 │  │ 1 LLM call                    │    │ 2 independent LLM calls              │ │
 │  │ asks all 7 questions together │    │ Call 1 — topic questions (3 fields)  │ │
 │  │                               │    │ Call 2 — filter questions (4 fields) │ │
 │  └───────────────────────────────┘    └──────────────────────────────────────┘ │
 │                                                                                │
 └────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
 Output: clean_topic (str), year_window (int), min_citations (int),
         has_identifiable_topic (bool), topic_missing_reason (str)
       │
       ▼
 OpenAlex BM25 full-text search using clean_topic
   + filter(publication_year, cited_by_count)
       │
       ▼
 List[Paper]                → Step 2: Relevance Filter
```

---

## Summary

- **Problem:** lz-chen's paper-discovery step cannot filter candidate papers by recency or citation count, and has no LLM step of any kind to interpret those preferences from the user's query.
- **Solution:** This fork closes that gap with a single LLM call that extracts the topic while detecting those preferences — this experiment tests that call against a split-call alternative across 40 hand-authored queries with identical prompt wording.
  - One call answers every question together.
  - Two independent calls split topic questions from year/citation questions.
- **Result:** Both call structures close the original gap with identical accuracy, but the single-call design produces meaningfully cleaner topic keywords than the split-call design — 2.92 versus 2.65 out of 3.

---

## Experiment Setup

✅ = currently used in the pipeline

### Two Extraction Strategies Compared

| Strategy | LLM calls | Question style | Few-shot examples | Wording vs. other strategy |
|---|---|---|---|---|
| Single-Call Design ✅ | 1 | Direct question per field | None | Identical for every shared question |
| Split-Call Design | 2 (independent) | Direct question per field | None | Identical for every shared question |

### Extracted Fields

| Field | Type | Meaning |
|---|---|---|
| `has_identifiable_topic` | boolean | Whether the query names a research topic |
| `topic_missing_reason` | string, nullable | One-sentence reason when no topic is found |
| `year_window` | integer | How many years back to search |
| `min_citations` | integer | Minimum citation count to require |
| `clean_topic` | string | The query's topic, with time/citation phrasing and conversational wording removed |

### Prompts

<details>
<summary><b>Single-Call Design — <code>SEARCH_PARAMS_STAGED_PMT</code></b></summary>

```text
You are an academic search specialist. Today's year is {current_year}.
Answer the following about this research query, and return JSON with exactly seven keys in this order:

1. Does the query actually request academic literature on some subject, however broad — not merely mention a subject-related term while asking for something unrelated to literature search? -> has_identifiable_topic (true/false)
2. If not, why not, in one short sentence? -> topic_missing_reason (string, null if question 1 is true)
3. Does the query express a preference for how recent the papers should be? -> has_year_constraint (true/false)
4. If yes, how many years back does that imply — use the exact number if given, otherwise your best judgment? -> year_window (integer 1-20; 3 if question 3 is false)
5. Does the query express a preference for how impactful or well-cited the papers should be? -> has_citation_constraint (true/false)
6. If yes, what citation count does that imply — use the exact number if given, otherwise your best judgment? -> min_citations (integer >=0; 50 if question 5 is false)
7. What is the research subject, as 2-6 plain keywords? No boolean operators, quotes, or special characters. Ignore how recent or well-cited the user wants the papers to be, and ignore how the user phrased the request. Keep specialized terms, named entities, and abbreviations exactly as written. -> clean_topic (string, empty if question 1 is false)

Return JSON only, no explanation, no markdown fences.

User research query: {user_query}
```
</details>

<details>
<summary><b>Split-Call Design — <code>TOPIC_EXTRACTION_PMT</code> + <code>SEARCH_FILTERS_EXTRACTION_PMT</code></b></summary>

```text
# Call 1 — TOPIC_EXTRACTION_PMT
You are an academic search specialist. Answer about this research query, and return JSON with exactly three keys:

1. Does the query actually request academic literature on some subject, however broad — not merely mention a subject-related term while asking for something unrelated to literature search? -> has_identifiable_topic (true/false)
2. If not, why not, in one short sentence? -> topic_missing_reason (string, null if question 1 is true)
3. What is the research subject, as 2-6 plain keywords for search? No boolean operators, quotes, or special characters. Ignore how recent or well-cited the user wants the papers to be, and ignore how the user phrased the request. Keep specialized terms, named entities, and abbreviations exactly as written. -> clean_topic (string, empty if question 1 is false)

Return JSON only, no explanation, no markdown fences.

User research query: {user_query}

# Call 2 — SEARCH_FILTERS_EXTRACTION_PMT
You are an academic search specialist. Today's year is {current_year}. Answer about this research query, and return JSON with exactly four keys:

1. Does the query express a preference for how recent the papers should be? -> has_year_constraint (true/false)
2. If yes, how many years back does that imply — use the exact number if given, otherwise your best judgment? -> year_window (integer 1-20; 3 if question 1 is false)
3. Does the query express a preference for how impactful or well-cited the papers should be? -> has_citation_constraint (true/false)
4. If yes, what citation count does that imply — use the exact number if given, otherwise your best judgment? -> min_citations (integer >=0; 50 if question 3 is false)

Return JSON only, no explanation, no markdown fences.

User research query: {user_query}
```
</details>

### Ground Truth Dataset

| Property | Value | Description |
|---|---|---|
| Total queries | 40 | The full test set |
| Categories | 13 | Query types covered — time limits, citation limits, cross-domain topics, and more |
| Topic-present queries | 37 | Queries with a real topic to extract |
| Topic-absent queries | 3 | Queries with no topic at all, to catch false positives |
| Constraint combinations | 8 | Every mix of topic, year, and citation constraints being present or absent |

| Field | How it's graded |
|---|---|
| `has_topic` | Exact match against ground truth |
| `year_window` | Exact match if explicit; range check if vague; default value if absent |
| `min_citations` | Exact match if explicit or absent; floor check (`actual >= floor`) if vague |
| `clean_topic` | Claude judge scores 1–3 against a reference answer and required-term list |

### Metrics & Model

| Metric | Scope |
|---|---|
| Deterministic field accuracy (`has_topic`, `year_window`, `min_citations`) | All 40 queries |
| `preserves_key_terms` (boolean) | 37 topic-present queries |
| `quality_score` (1–3 Likert) | 37 topic-present queries |

| Role | Model |
|---|---|
| Extraction LLM (both designs) | ollama/ministral-3:14b-cloud |
| `clean_topic` quality judge | Claude (single pass per sample) |

---

## Full Experimental Results

### Analysis 1 — Deterministic Field Accuracy

- **Purpose:** Check whether call structure changes accuracy on the three fields graded by exact, range, or floor rules.
- **Expected:** No difference between designs, since neither field requires excluding information the model extracts elsewhere in the same call.

| Field | Single-Call Design ✅ | Split-Call Design |
|---|---|---|
| `has_topic_correct` | **39/40** | **39/40** |
| `year_window_correct` | **40/40** | **40/40** |
| `min_citations_correct` | **37/40** | **37/40** |

- Topic presence: both designs fail query 21 ("weather forecast") — ground truth expects `true`, both extract `false`.
- Citation threshold: the single-call design fails queries 14, 17, 39; the split-call design fails queries 7, 14, 17 — queries 14 and 17 fail under both designs.

**Conclusion:** Call structure has no effect on any field checked by fixed rules — the entire measurable difference between the two designs is isolated to the open-text topic extraction covered in Analysis 2.

### Analysis 2 — Topic Extraction Quality (37 Topic-Present Queries)

- **Purpose:** Check whether call structure changes the quality of the extracted topic keywords.
- **Expected:** The split-call design scores higher, since separating topic extraction from constraint detection removes the need to detect and exclude constraint language within the same call.

| Metric | Single-Call Design ✅ | Split-Call Design |
|---|---|---|
| `preserves_key_terms = true` | **36/37** | **36/37** |
| Mean `quality_score` (1–3) | **2.92** | 2.65 |

| Quality Score | Single-Call Design ✅ | Split-Call Design |
|---|---|---|
| 3 — faithful, no meaningful loss | **35** | 25 |
| 2 — loses specificity or over-broadens | 1 | **11** |
| 1 — misses the subject or drops a required term | 1 | 1 |
| Total queries | 37 | 37 |
| Weighted sum (score × count) | 108 | 98 |
| Mean score (sum ÷ total) | **2.92** | 2.65 |

Query 21 ("weather forecast") produced an empty topic string under both designs — both misjudged it as topic-less (Analysis 1).

**Conclusion:** Splitting the calls backfires — the two jobs still interfere, just in reverse of what the split was meant to fix.

---

## Observations

### Why does the split-call design leak constraint words into the topic keywords more often than the single-call design?

The split-call design produces 12 of the 14 lower-scoring extractions across the dataset, driven mainly by leaked citation- and year-related words in the extracted topic — despite both prompts giving an identical instruction to exclude such words.

- The split-call design's mean topic-quality score is 0.27 points lower than the single-call design's (2.65 vs. 2.92, out of 3).

---

## Decision

### Which call structure should the pipeline use?

The single-call design is selected — it wins on topic-keyword quality (Analysis 2) and needs just 1 LLM call per query, versus 2 for the split-call design, which adds latency with no accuracy gain on structured fields (Analysis 1).

---

## Pipeline Integration Status ✅ INTEGRATED

The single-call design's exact prompt wording replaced the pipeline's previous declarative, few-shot extraction prompt in `backend/prompts/prompts.py`'s `SEARCH_PARAMS_EXTRACTION_PMT`, called once per query from `summary_gen.py`'s `supervisor_search` step.
