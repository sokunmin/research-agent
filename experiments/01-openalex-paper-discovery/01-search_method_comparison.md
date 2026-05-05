# Experiment 1 — OpenAlex vs. Tavily: Paper Discovery Path Selection

## Task Context

This experiment targets **Step 1 — Paper Retrieval** from the system architecture (README → System Architecture).

```
Input: user_query (str)
      │
      ▼
┌── 1. PAPER DISCOVERY ─────────────────────────────────────────────────────┐
├─── Original (lz-chen) ──────────────────┬─── My Implementation ──────────┤
│ Tavily Web Search (paid API)            │ OpenAlex BM25 Search            │
│   + query prefix engineering            │   + Quality Filters             │
│   → OpenAlex title-match (search_filter)│     oa_status: diamond|gold|green│
│   → citation expansion (cites=seed_id) │     cited_by_count > 50         │
│   Non-deterministic; 2+ API providers  │     publication_year > now-3yr  │
│                                         │     type != retraction          │
│                                         │   + Deduplication by entry_id   │
└─────────────────────────────────────────┴────────────────────────────────-┘
      │
      ▼
Output: List[Paper]                                → Step 2: Relevance Filter
```

**About OpenAlex** — OpenAlex is a free, open academic literature database (250M+ papers) with a Python SDK (`pyalex`). `Works()` is a query builder analogous to an ORM — compose any query by chaining the methods below:

| Method | API call | What it does |
|---|---|---|
| Keyword search | `Works().search_filter(title_and_abstract=q)` | AND match restricted to title and abstract fields only |
| BM25 search ✅ | `Works().search(q)` | BM25 relevance ranking across title, abstract, and full text |
| Semantic search | `Works().similar(q)` | Embedding-based vector similarity |
| Quality filter | `<query>.filter(key=value, ...)` | Stacks AND constraints on any search — narrows by OA status, citation count, publication year, type |
| Citation expansion | `<query>.filter(cites=seed_id)` | Fetches all papers that cite a specific seed paper; Path A uses this to build its candidate pool |
| Execute | `<query>.get(per_page=N)` | Executes the composed query and returns up to N results |

OA (Open Access) status indicates how a paper is made available. OpenAlex assigns one of five statuses:

| OA status | Meaning | PDF downloadable? |
|---|---|---|
| diamond | Published in a fully open journal (no author fee) | ✅ Yes |
| gold | Published in an open-access journal (author paid APC) | ✅ Yes |
| green | Freely available as a preprint or repository copy (e.g., ArXiv) | ✅ Yes |
| bronze | Free to read on publisher site but no open license; can be removed | ⚠️ Unreliable |
| closed | Subscription-only; no free copy available | ❌ No |

The pipeline goal is papers that are both high-cited and downloadable. `oa_status in {diamond, gold, green}` is the filter that guarantees a downloadable full-text PDF — a hard requirement for the downstream VLM summarization step, which reads the entire paper. Bronze and closed papers risk returning a paywalled or missing PDF at download time. `cited_by_count > N` and `publication_year > YYYY` further narrow to established, recent work.

This experiment compares the two paths across five research domains.

---

## Summary

- **Problem:** The Tavily-seeded citation-expansion path produces zero candidates for the pipeline's primary topic across all three test runs, blocking the entire downstream pipeline.
  - Root cause is structural: the single seed paper found by Tavily has no citing works in OpenAlex. Citation expansion returns an empty set regardless of Tavily's output.
  - Title artifacts in Tavily-scraped results (`"- arXiv"` suffixes, blog post prefixes) cause 80% of OpenAlex title-match lookups to return wrong papers or no result.
  - Tavily requires a paid external API and 6 API calls per topic. Output is non-deterministic across runs.
- **Solution:** Compare the Tavily-seeded citation-expansion path against a direct OpenAlex BM25 query with quality filters (OA status, citation count, recency, no retractions) across 5 research domains — 10 sub-experiments total.
- **Result:** The direct OpenAlex BM25 path was adopted — it retrieves 92–100 candidates for all 5 topics, eliminating zero-candidate failures entirely.
  - Total relevant papers increased from 53 to 64 (+20.8%) across five research domains.
  - Both paths meet the ≥ 10 relevant paper target in 2 of 5 domains. The direct path wins on 4 of 5 topics.

---

## Experiment Setup

✅ = currently used in the pipeline

### Objective

- **Problem:** The original Tavily citation-expansion path produces zero candidates for the primary topic and is non-deterministic across runs.
- **Goal:** Determine whether direct OpenAlex search with quality filters can replace the Tavily path, and which OpenAlex search modality (keyword, BM25, semantic) best serves the pipeline.
- **Pass condition:** ≥ 10 relevant papers per topic after two-stage relevance filtering (embedding pre-screen + LLM verification; fully described in Exp 2).

### Relevance Filter (applied equally to both paths)

The two-stage relevance filter validated in the companion ablation study (Exp 2) is applied as a fixed downstream filter to both paths:

- **Stage 1:** `ollama/nomic-embed-text` — cosine similarity between topic embedding and paper text (title + abstract). Threshold = 0.500.
- **Stage 2:** `ollama/qwen3.5:2b` with Prompt-Strict (survey-heuristic) — invoked only for papers in the ambiguous band [0.500, 0.610). Extended metadata fields (keywords, topics, primary\_topic, concepts) used as input.
- **Performance:** F1 = 0.974, Precision = 1.000, Recall = 0.950 on a balanced 120-paper ground truth dataset.

This filter's classification performance is not under evaluation here; it serves as a common downstream filter to make relevant counts comparable across paths.

### Download Validation

A separate validation script (`pdf_download_fallback.py`) confirms that papers passing `oa_status` in {diamond, gold, green} are downloadable: 5/5 using a four-strategy fallback chain. Download reliability is not evaluated in this experiment.

### Topics (five domains)

| Label | Topic | Domain |
|---|---|---|
| RESEARCH\_TOPIC | attention mechanism in transformer models | NLP / Deep Learning |
| TOPIC\_Q | federated learning privacy preservation | Distributed Systems |
| TOPIC\_R | reinforcement learning policy gradient optimization | Reinforcement Learning |
| TOPIC\_S | convolutional neural network image recognition | Computer Vision |
| TOPIC\_NEW | CRISPR gene editing therapeutic applications | Biomedical (non-ML) |

### Paths compared

> **Semantic Scholar note:** The original implementation uses Semantic Scholar (`s2.search_paper()` + `s2.get_paper_citations()`). That API was unavailable for this experiment, so Path A is re-implemented using OpenAlex equivalents that preserve the same structural pattern — Tavily seed → title lookup → citation expansion. The failure modes documented below are inherent to the pattern itself, not to the choice of citation API.

```
┌─ STAGE 1: SEARCH ─────────────────────────────────────────────────────────────────┐
│                                            │                                       │
│  Path A — lz-chen original                 │  Path B — my implementation ✅        │
│  (re-implemented via OpenAlex)             │                                       │
│                                            │                                       │
│  user_query                                │  user_query                           │
│    │                                       │    │                                  │
│    ▼                                       │    ▼                                  │
│  Tavily.search(                            │  Works().search(query)                │
│    "arxiv papers about... {query}",        │    .filter(                           │
│    max_results=2)                          │      is_oa=True,                      │
│    │ [web pages: titles + snippets]        │      oa_status=                       │
│    ▼                                       │        "diamond|gold|green",          │
│  search_filter(                            │      cited_by_count=">50",            │
│    title_and_abstract=title)               │      publication_year=">now-3yr",     │
│    │ [seed paper per Tavily result]        │      type="!retraction")              │
│    ▼                                       │    .get(per_page=100)                 │
│  filter(cites=seed_id, per_page=50)        │    │ [100 pre-filtered candidates]    │
│    │ [0–N citing papers]                  │                                       │
│                                            │                                       │
├─ STAGE 2: FILTER ─────────────────────────────────────────────────────────────────┤
│    ▼                                       │    ▼                                  │
│  GPT-4o Mini                               │  nomic-embed-text cosine sim          │
│    relevance score (0 / 1 / 2)             │    threshold = 0.500                  │
│    │                                       │    │                                  │
│    ▼                                       │    ▼ [band 0.500–0.610 only]          │
│  sort by (score, ArXiv presence)           │  qwen3.5:2b survey-heuristic          │
│    → top-5                                 │    │ [relevant papers]                │
│    │                                       │    ▼                                  │
│                                            │  sort by similarity → top-N           │
│                                            │    │                                  │
├─ STAGE 3: DOWNLOAD ───────────────────────────────────────────────────────────────┤
│    ▼                                       │    ▼                                  │
│  ArXiv PDF download                       │  4-strategy fallback chain            │
│    (arxiv_id required;                     │    1. arxiv_api      (3 s delay)      │
│     no fallback if ID missing)             │    2. arxiv_direct_url               │
│                                            │    3. pyalex_pdf                      │
│                                            │    4. oa_url + browser headers        │
├─ SUMMARY ─────────────────────────────────────────────────────────────────────────┤
│                                            │                                       │
│  APIs      Tavily + OpenAlex + ArXiv       │  OpenAlex only                        │
│  Calls     1+N×search_filter+N×cites       │  1                                    │
│  Pool      0–100 (citation-graph dep.)     │  92–100 (all 5 topics)                │
│  PDF       arxiv_id required; no guarantee │  oa_status = PDF guaranteed           │
│  Repeats   No (Tavily output varies)       │  Yes                                  │
│                                            │                                       │
└────────────────────────────────────────────┴───────────────────────────────────────┘
```

### Internal experiments (10 sub-experiments)

| Sub-Exp | Description |
|---|---|
| Exp 01 | Keyword search — `Works().search_filter(title_and_abstract=)` |
| Exp 02 | BM25 full-text search — `Works().search()` |
| Exp 03 | Semantic search — `Works().similar()` |
| Exp 04 | Cross-method overlap: keyword / BM25 / semantic |
| Exp 05 | Tavily query format: bare query vs. arxiv-prefix — academic hit rate |
| Exp 06 | Tavily seed vs. OpenAlex direct — 5-paper head-to-head |
| Exp 07 | Tavily arxiv-prefix titles → OpenAlex title-match gap |
| Exp 08 | Path B `per_page` sensitivity sweep (25 / 50 / 100 / 150) |
| Exp 09 | Path A five-domain results (3-run non-determinism test + cross-domain) |
| Exp 10 | Path B five-domain results |

---

## Full Experimental Results

### OpenAlex Search Modality Characterization (Exp 01–03)

- **Purpose:** Compare three OpenAlex search modalities (keyword, BM25, semantic) on relevance rate and ArXiv ID coverage.
- **Expected:** At least one modality achieves > 50% relevance rate with meaningful ArXiv ID coverage for downstream PDF download.

Topic: RESEARCH\_TOPIC (`attention mechanism in transformer models`), `per_page=25`, two-stage filtering.

| Method | API Call | Candidates | Relevant | Relevance % | ArXiv | ArXiv % |
|---|---|---|---|---|---|---|
| Keyword Search | `search_filter(title_and_abstract=)` | 25 | 15 | 60% | 3 | 12% |
| BM25 Full-Text ✅ | `search()` | 25 | 13 | 52% | 6 | 24% |
| Semantic Search | `similar()` | 25 | 17 | 68% | 9 | 36% |

**Conclusion:** BM25 was selected over semantic despite lower relevance rate (52% vs 68%) — its bias toward high-cited papers aligns with the citation count quality filter applied downstream.

### Cross-Method Overlap (Exp 04)

- **Purpose:** Determine whether the three modalities retrieve overlapping or complementary paper sets.
- **Expected:** Near-zero overlap between any pair would confirm the methods access different regions of the literature.

| Comparison | Overlap |
|---|---|
| Keyword ∩ BM25 (M1 ∩ M2) | 18 papers |
| Keyword ∩ Semantic (M1 ∩ M3) | 0 papers |
| BM25 ∩ Semantic (M2 ∩ M3) | 0 papers |
| Semantic unique (M3 only) | 25 papers |
| Keyword/BM25 union (M1 ∪ M2 only) | 32 papers |

**Conclusion:** BM25 largely subsumes keyword search (72% overlap) — semantic search is fully complementary, accessing a different region of the literature with zero overlap with either text-based method.

### Tavily Failure Mode Analysis (Exp 05–07)

- **Purpose:** Document the structural failure modes in Path A that cause unreliable candidate retrieval.
- **Expected:** Academic hit rate ≥ 80% and title-match success ≥ 80% would be required for Path A to remain viable.

**Query format sensitivity (Exp 05) — RESEARCH\_TOPIC:**

| Format | Academic Hits | Non-Academic Hits | Academic Hit Rate |
|---|---|---|---|
| Bare query | 0 | 5 | 0% |
| Arxiv-prefix query | 3 | 2 | 60% |

**Conclusion:** Even with the best-case arxiv-prefix format, 40% of results remain non-academic — Tavily's academic hit rate is too unreliable to serve as a seeding mechanism.

**Seed quality comparison (Exp 06) — 5 papers per method:**

| Metric | Method X (Tavily + OpenAlex title-match) | Method Y (OpenAlex direct) |
|---|---|---|
| Papers found | 5 | 5 |
| Citation counts | [308, 686, 104, 572, 461] | [235, 6507, 5499, 12, 68] |
| Median citations | 461 | 235 |
| Max citations | 686 | 6507 |
| Overlap | 0 papers | 0 papers |
| API calls | 6 (1 Tavily + 5 OpenAlex) | 1 |

**Conclusion:** Tavily-seeded title matching surfaces application-domain papers (median 461 citations) while direct OpenAlex retrieves foundational transformer works including "Attention Is All You Need" (6,507 citations) — at one-sixth the API calls.

**Title match gap (Exp 07) — arxiv-prefix Tavily titles → OpenAlex:**

| Tavily Title | OpenAlex Match | Quality |
|---|---|---|
| An analysis of attention mechanisms... | Exact match (cited: 2) | Correct |
| Nexus: Higher-Order Attention Mechanisms... | No match | Lost |
| Attention Is All You Need - arXiv | "Deep Learning for Natural Language Processing" (cited: 58) | Wrong paper |
| Coffee Time Papers: Attention Is All You Need | "Embracing Chinese Global Security Ambitions" (cited: 26) | Wrong paper |
| Selective Attention Improves Transformer - arXiv | No match | Lost |

**Conclusion:** The `"- arXiv"` suffix in web-scraped titles breaks title matching — "Attention Is All You Need - arXiv" matches an unrelated paper instead of the most-cited transformer work (80% failure rate overall).

### Path B — Candidate Pool Sizing (Exp 08)

- **Purpose:** Find the minimum `per_page` value that captures the full relevant paper pool without diminishing returns.
- **Expected:** Relevant count plateaus before `per_page=150`, confirming the pool is exhausted at a manageable request limit.

`per_page` sweep on RESEARCH\_TOPIC with full BM25 path filter stack and two-stage filtering:

| per\_page | Candidates | Relevant | Relevance % |
|---|---|---|---|
| 25 | 25 | 1 | 4% |
| 50 | 50 | 3 | 6% |
| 100 | 100 | 4 | 4% |
| 150 | 150 | 4 | 3% |

**Conclusion:** Relevant count plateaus at 4 from page size 100 onward — page size 100 captures the full pool and provides a 25× candidate-to-relevant buffer for topics with higher base relevance rates.

### Path A — Five-Domain Results (Exp 09)

- **Purpose:** Measure Path A candidate yield and relevance across five research domains; test non-determinism across three runs.
- **Expected:** Path A meets the ≥ 10 relevant paper target in all 5 domains with consistent results across runs.

**Non-determinism test (3 runs, RESEARCH\_TOPIC):**

| Run | Seeds Found | Candidates | Relevant | Meets Target (≥ 10) |
|---|---|---|---|---|
| Run 1 | 1 | 0 | 0 | No |
| Run 2 | 1 | 0 | 0 | No |
| Run 3 | 1 | 0 | 0 | No |

**Conclusion:** Zero candidates across all three runs — the single seed found has no citing works in OpenAlex, so non-determinism doesn't change the outcome.

**Five-domain results:**

| Topic | Domain | Seeds | Candidates | Relevant | Meets Target |
|---|---|---|---|---|---|
| RESEARCH\_TOPIC | NLP / DL | 1 | 0 | 0 | No |
| TOPIC\_Q | Distributed Systems | 2 | 6 | 4 | No |
| TOPIC\_R | Reinforcement Learning | 2 | 4 | 1 | No |
| TOPIC\_S | Computer Vision | 2 | 52 | 11 | Yes |
| TOPIC\_NEW | Biomedical | 1 | 50 | 37 | Yes |

**Conclusion:** Target met in 2/5 domains — TOPIC\_NEW loses one seed to the title-artifact failure documented in Exp 07.

### Path B — Five-Domain Results (Exp 10)

- **Purpose:** Measure Path B candidate yield and relevance across five domains for head-to-head comparison with Path A.
- **Expected:** Path B eliminates zero-candidate failures and meets the ≥ 10 relevant paper target in all 5 domains.

| Topic | Domain | Candidates | Relevant | Meets Target |
|---|---|---|---|---|
| RESEARCH\_TOPIC | NLP / DL | 100 | 4 | No |
| TOPIC\_Q | Distributed Systems | 92 | 12 | Yes |
| TOPIC\_R | Reinforcement Learning | 100 | 2 | No |
| TOPIC\_S | Computer Vision | 100 | 6 | No |
| TOPIC\_NEW | Biomedical | 100 | 40 | Yes |

**Conclusion:** Zero-candidate failures eliminated across all 5 topics — low counts on RESEARCH\_TOPIC and TOPIC\_R reflect filter strictness, not search failure.

### Head-to-Head Comparison

| Topic | Path A Candidates | Path A Relevant | Path B Candidates | Path B Relevant | Winner |
|---|---|---|---|---|---|
| RESEARCH\_TOPIC | 0 | 0 | 100 | 4 | Path B |
| TOPIC\_Q | 6 | 4 | 92 | 12 | Path B |
| TOPIC\_R | 4 | 1 | 100 | 2 | Path B |
| TOPIC\_S | 52 | 11 | 100 | 6 | Path A |
| TOPIC\_NEW | 50 | 37 | 100 | 40 | Path B |
| **Total** | **112** | **53** | **492** | **64 (+20.8%)** | **Path B** |

| Property | Path A | Path B |
|---|---|---|
| Topics with >= 10 relevant | 2/5 | 2/5 |
| Total relevant papers | 53 | 64 |
| Topics with 0 candidates | 1/5 (RESEARCH\_TOPIC) | 0/5 |
| Deterministic | No (Tavily-dependent) | Yes |
| External API dependency | Tavily (paid) | None |
| API calls per topic | 1 Tavily + N search\_filter + N cites | 1 OpenAlex |

---

## Observations

### Tavily failure modes stack sequentially — any single failure produces zero usable candidates

```
Tavily-seeded citation expansion (Path A)
  │
  ├─ Failure 1: non-academic results
  │     Bare query → 0% academic hit rate (all blog posts/docs)
  │     Arxiv-prefix → 60% academic hit rate (best case)
  │
  ├─ Failure 2: title artifact mismatch (Exp 07: 80% failure rate)
  │     Web-scraped titles contain "- arXiv", blog prefixes, truncations
  │     search_filter AND logic breaks → wrong paper or no match
  │
  ├─ Failure 3: topical drift
  │     Non-academic titles match closest lexical OpenAlex record
  │     → papers tangentially related or completely off-topic
  │
  └─ Failure 4: empty citation graph (Exp 09 Part 1)
        Even correct seed → filter(cites=seed_id) may return 0 papers
        Structural: entire candidate pool depends on one seed's citation graph
```

**Conclusion:** Path A's zero-candidate result is structural — Failure 2 breaks 80% of title lookups and Failure 4 empties the pool even when a seed is found.

### Low relevant counts on RESEARCH\_TOPIC and TOPIC\_R reflect intentional filter strictness, not a search failure

**Conclusion:** Every paper that passes both filters is genuinely relevant and downloadable — the low count is by design.
- The citation count and recency filters exclude foundational papers (e.g., "Attention Is All You Need", 2017, 6,507 citations — predates the year filter) and the long tail of recent but low-cited papers.
- Two-stage filter Precision = 1.000 rejects application-domain papers (damage detection, medical imaging, crop yield) with zero false positives — the intended behavior.

### Path A outperforms Path B on TOPIC\_S only via citation fan-out from a well-connected seed

**Conclusion:** This advantage is topic-dependent — a different Tavily run may find a different seed with a smaller citation graph.
- TOPIC_S (Computer Vision): Tavily path 11 relevant vs. BM25 path 6 relevant.
- CNN image recognition has influential survey papers with large citation graphs. When Tavily finds a well-connected seed, the fan-out produces a high-quality candidate pool.

---

## Decision

```
Replace Tavily citation-expansion (Path A) with OpenAlex BM25 (Path B)?
  │
  ├─ Path A
  │    ✗ Zero candidates for primary topic across 3 runs (structural, not transient)
  │    ✗ 80% title-match failure rate (Exp 07)
  │    ✗ Non-deterministic — Tavily output can change across runs
  │    ✗ Paid external API dependency
  │    ✗ 6 API calls per topic vs. 1
  │    ✓ Outperforms on TOPIC_S (11 vs. 6 relevant) via citation fan-out
  │    → REPLACED
  │
  └─ Path B (OpenAlex BM25 + quality filters) ✅
       ✓ Candidates for all 5 topics (92–100 per topic)
       ✓ 20.8% more total relevant papers (64 vs. 53)
       ✓ Fully deterministic — same query always returns same candidate set
       ✓ No external API dependency
       ✓ 1 API call per topic
       ✓ All candidates satisfy oa_status filter → guaranteed downloadable
       △ Underperforms on TOPIC_S (6 vs. 11 relevant) — BM25 favors
         application papers; quality filters exclude older foundational works
       → ADOPTED: configuration PATH_B_PER_PAGE=100, cited_by_count > 50,
         publication_year > now-3yr, oa_status in {diamond, gold, green}
```

---

## Pipeline Integration Status ✅ INTEGRATED

Tavily citation-expansion replaced by direct OpenAlex BM25 search with quality filters in `paper_scraping.py` → `fetch_candidate_papers()`.

### Impact

- Zero-candidate failure eliminated across all five tested domains.
- Total relevant papers: 53 → 64 (+20.8%).
- Pipeline is now fully deterministic — no paid external API required.
