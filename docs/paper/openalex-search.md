# OpenAlex & pyalex Crash Course

> Based on experimental results from PoC `poc/openalex-search-comparison/` (Exp 01–20).
> Code: `poc/openalex-search-comparison/main.py`
> Experiment results: `poc/openalex-search-comparison/result.md`

---

## 1. What is OpenAlex?

OpenAlex is an **open, free** academic literature database maintained by the non-profit OurResearch.

```
┌─────────────────────────────────────────────────────────────┐
│                        OpenAlex                             │
│                                                             │
│  Origin: took over from Microsoft Academic Graph (MAG)      │
│  Scale: 250M+ papers, 250M+ authors, 110K+ institutions     │
│  Cost: completely free (API key required)                   │
│  Updates: daily                                             │
│                                                             │
│  vs other databases:                                        │
│  ┌─────────────┬────────┬──────────┬────────────┐          │
│  │             │ Free   │ Full-text│ Python SDK │          │
│  ├─────────────┼────────┼──────────┼────────────┤          │
│  │ OpenAlex    │  ✓     │   ✓      │  pyalex    │          │
│  │ Semantic Sch│  ✓     │   ✓      │  partial   │          │
│  │ Scopus      │  ✗     │   ✓      │  official  │          │
│  │ Web of Sci  │  ✗     │   ✓      │  limited   │          │
│  │ PubMed      │  ✓     │   ✓      │  Entrez    │          │
│  └─────────────┴────────┴──────────┴────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. The Core Object: Work

Every academic paper in OpenAlex is represented as a **Work**. Here is the structure of a Work object:

```
Work
├── id                    "https://openalex.org/W2626778328"
├── display_name          "Attention Is All You Need"
├── publication_year      2017
├── cited_by_count        6504
│
├── open_access
│   ├── is_oa             true
│   ├── oa_status         "gold" | "green" | "diamond" | "hybrid"
│   └── oa_url            "https://arxiv.org/pdf/1706.03762"
│
├── primary_topic
│   ├── id                "https://openalex.org/T10181"
│   └── display_name      "Natural Language Processing Techniques"
│
├── locations[]           ← list of locations where the paper is available
│   └── landing_page_url  "https://arxiv.org/abs/1706.03762"  ← ArXiv ID is here
│
├── doi                   "10.48550/arxiv.1706.03762"
├── referenced_works[]    ["W123", "W456", ...]  ← IDs of papers this work cites
└── abstract_inverted_index  { "Attention": [0], "Is": [1], ... }
                                                ↑ must be reconstructed to read
```

---

## 3. pyalex: Python Wrapper

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   Your Python code                                      │
│        │                                                │
│        │  import pyalex                                 │
│        │  from pyalex import Works                      │
│        │                                                │
│        ▼                                                │
│   ┌─────────────┐    HTTP GET     ┌──────────────────┐  │
│   │   pyalex    │ ─────────────► │  api.openalex.io │  │
│   │  (wrapper)  │ ◄───────────── │    (REST API)    │  │
│   └─────────────┘    JSON resp   └──────────────────┘  │
│        │                                                │
│        ▼                                                │
│   list[dict]  ← each dict is one Work object            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Initialization (required at program start):**

```python
import pyalex
from pyalex import Works

pyalex.config.api_key = "your-key"   # required since 2026-02
pyalex.config.email = "you@mail.com" # optional, enters polite pool
```

**Basic call pattern:**

```python
results = Works()          # create a query object
           .search(...)    # set search conditions (chainable)
           .filter(...)    # set filter conditions
           .sort(...)      # set sort order
           .get(per_page=10)  # execute and retrieve results
#                                  ↑ this triggers the actual HTTP request
```

---

## 4. Four Core Search Methods (validated by Exp 01)

This is the central question of the PoC: OpenAlex offers 4 ways to find papers, each with completely different behavior.

```
Query: "attention mechanism transformer"

METHOD 1: search_filter(title_and_abstract=query)
METHOD 2: search(query)
METHOD 3: filter(cites=<seed_paper_id>)
METHOD 4: similar(query)
```

### Method 1: `search_filter(title_and_abstract=)`

```
┌──────────────────────────────────────────────────────┐
│  search_filter(title_and_abstract="attention         │
│                                    mechanism         │
│                                    transformer")     │
│                                                      │
│  Search scope:  ┌──────┐  ┌──────────┐              │
│                 │TITLE │  │ ABSTRACT │  ← these two only │
│                 └──────┘  └──────────┘              │
│                                                      │
│  Match logic: AND — all three terms must appear      │
│                                                      │
│  Characteristics: precise, conservative, best for   │
│                   exact keyword matching             │
│  Exp 01 relevance: 15/15 = 100%                      │
│  ArXiv coverage:  1/15 = 7% (papers tend to be       │
│                   in journals/conferences)            │
└──────────────────────────────────────────────────────┘
```

### Method 2: `search()`

```
┌──────────────────────────────────────────────────────┐
│  search("attention mechanism transformer")           │
│                                                      │
│  Search scope:                                       │
│  ┌──────┐ ┌──────────┐ ┌────────┐ ┌──────┐          │
│  │TITLE │ │ ABSTRACT │ │FULLTEXT│ │ ...  │ ← broader │
│  └──────┘ └──────────┘ └────────┘ └──────┘          │
│                                                      │
│  Match logic: BM25 relevance ranking (like Google    │
│               Scholar)                               │
│                                                      │
│  Characteristics: more permissive; surfaces          │
│  high-citation papers that search_filter misses      │
│                                                      │
│  Exp 01 relevance: 15/15 = 100%                      │
│  ArXiv coverage:  3/15 = 20% (+2 over search_filter) │
│                                                      │
│  M1 vs M2 overlap: 13/15 = 87%                       │
│  M2 unique: Informer (cited 5469)                    │
│             Attention Is All You Need (cited 6504) ← important │
└──────────────────────────────────────────────────────┘
```

### Method 3: `filter(cites=<id>)`

```
┌──────────────────────────────────────────────────────┐
│  filter(cites="W2626778328")                         │
│                                                      │
│  Concept: citation graph traversal                   │
│                                                      │
│   All papers in database                             │
│       │                                              │
│       ▼  "which papers cite this seed?"              │
│   ┌───────────────────────────────────┐              │
│   │        Seed Paper                 │              │
│   │  "Attention Mechanism, BERT, GPT" │              │
│   │         (cited 76)                │              │
│   └───────────────────────────────────┘              │
│         ▲      ▲      ▲      ▲                       │
│    GPT  UNETR  LLM   ... (papers that cite seed)     │
│   review review surv                                 │
│                                                      │
│  Characteristics: severe topic drift! If the seed   │
│  is a survey paper, citers may be cross-domain       │
│                                                      │
│  Exp 01 relevance: 0% (M3 ∩ M1 = 0, M3 ∩ M2 = 0)   │
│  → all GPT/LLM papers, not original transformer topic│
└──────────────────────────────────────────────────────┘
```

### Method 4: `similar()`

```
┌──────────────────────────────────────────────────────┐
│  similar("attention mechanism transformer")          │
│                                                      │
│  Search approach: AI semantic embedding similarity   │
│                                                      │
│  Query ──embed──► [0.2, 0.8, 0.1, ...]              │
│                         │                            │
│                    vector distance                   │
│                         │                            │
│              ┌──────────┴──────────┐                 │
│         close papers          far papers             │
│                                                      │
│  Characteristics: semantically similar even if       │
│  keywords differ                                     │
│  M4 unique: 4 papers not in M1/M2                    │
│  Exp 01 relevance: 15/15 = 100%                      │
│  Note: API occasionally returns HTTP 500 (unstable)  │
└──────────────────────────────────────────────────────┘
```

### All Four Methods at a Glance

```
                   Topic Precision
                   HIGH ──────────────────────── LOW
                    │                              │
      ──────────────┼──────────────────────────────┤
      Coverage HIGH │  M2 search()    M4 similar() │
                    │                              │
             LOW    │  M1 s_filter()  M3 cites()   │
      ──────────────┴──────────────────────────────┘

      ArXiv Coverage (downloadability): M2 > M1 >> M3 (0%)
```

---

## 5. Advanced Features

### 5-1. `.sort(cited_by_count="desc")`

**Dangerous!** Discovered in Exp 08 / Exp 20:

```
Works().search("attention mechanism in transformer models")
       .sort(cited_by_count="desc")
       .get(per_page=1)

Expected: the most-cited and relevant paper
Actual:   MizAR 60 for Mizar 50 (cited 74,131) ← a math paper!

Why:
┌────────────────────────────────────────────────────┐
│  search() builds a BM25 relevance ranking           │
│       │                                            │
│  sort(cited_by_count) completely replaces BM25      │
│       │                                            │
│  Result = highest-cited paper in the entire DB      │
│           that contains any query token in          │
│           title/abstract                            │
│       ↓                                            │
│  "MizAR" abstract likely contains "transformer"    │
│  (a math term, not ML transformer)                 │
└────────────────────────────────────────────────────┘

Correct approach (Exp 09):
  candidates = Works().search(topic).get(per_page=5)
  seed = max(candidates, key=lambda w: w["cited_by_count"])
  # Let BM25 filter for relevance first, then pick highest-cited in Python
```

### 5-2. `.filter(is_oa=True)`

```
Works().search(topic).filter(is_oa=True).get(per_page=10)

OA = Open Access — paper is freely available

OA status categories (observed in Exp 11):
┌──────────┬────────────────────────────────────────┐
│  gold    │ fully OA journal, permanently free      │
│  green   │ author self-archived (most ArXiv papers)│
│  diamond │ fully OA journal (no APC fee)           │
│  hybrid  │ mixed journal — this specific paper OA  │
└──────────┴────────────────────────────────────────┘

Exp 11 result: relevance still 100%, ArXiv coverage 30% (same as without filter)
→ is_oa=True does NOT mean ArXiv PDF — both green and gold count as OA
```

### 5-3. ArXiv detection: why `is_oa` is not enough

```
is_oa=True includes:
  ┌────────────────────────────────────────────────┐
  │  ArXiv paper  ←──── green (direct PDF download)│
  │  AAAI paper   ←──── gold  (download from AAAI) │
  │  MDPI paper   ←──── gold  (may return 403)      │
  │  DOI paper    ←──── hybrid (may only have HTML) │
  └────────────────────────────────────────────────┘

ArXiv detection in code (via locations):
  for loc in work["locations"]:
      if "arxiv.org" in loc["landing_page_url"]:
          return True

Exp 17 download results for non-ArXiv OA papers:
  4/7 = 57%  → direct PDF download succeeded
  1/7        → returned HTML (via doi.org)
  2/7        → returned 403 (MDPI)
```

### 5-4. `referenced_works` (outgoing citations)

```
filter(cites=seed)         referenced_works
    Direction:                 Direction:

  Paper A ──cites──► seed      seed ──cites──► Paper A
  Paper B ──cites──► seed      seed ──cites──► Paper B
  Paper C ──cites──► seed      seed ──cites──► Paper C
    ↑                                ↑
  Papers that cite seed        Papers that seed cites
  (future papers, possibly     (seed's reference list /
   cross-domain)                prior work)

  Exp 01 M3 filter(cites=): relevance 0% (topic drift)
  Exp 12 referenced_works:  relevance 10% (seed's refs not all relevant)

Neither direction provides high-precision topic coverage.
```

### 5-5. `group_by()`

```
Works().search(topic).group_by("primary_topic.id").get()
→ does not return papers — returns statistical groupings

Exp 15 result (topic: "attention mechanism in transformer models"):

  158,927 papers distributed across:
  ┌──────────────────────────────────────────────┐
  │ #1  Topic Modeling                  14,347   │ 9.0%
  │ #2  NLP Techniques                   6,378   │
  │ #3  Advanced Neural Networks         6,156   │
  │ ...                                          │
  │ #15 Computational Drug Discovery     1,960   │
  └──────────────────────────────────────────────┘
  Top topic covers only 9% — results span many domains

Use case: find a topic ID, then use primary_topic filter to narrow scope (Exp 19)
```

### 5-6. `filter_or(doi=[...])`

```
# Batch query for multiple DOIs
Works().filter_or(doi=["10.xxx", "10.yyy", "10.zzz"]).get()

vs. individual queries:
  ┌─────────────────┬──────────────────────────────┐
  │  5 individual   │  5 HTTP requests             │
  │  filter_or      │  1 HTTP request  ← faster    │
  └─────────────────┴──────────────────────────────┘

Exp 14 result: 5 DOIs → 4 papers returned (80% hit rate)
→ 1 DOI not found in OpenAlex (incomplete data is normal)
```

---

## 6. Seed Paper Strategy (core of Exp 02, 08, 09, 20)

The key design decision in this workflow: use a single "representative paper" as a starting point.

```
┌───────────────────────────────────────────────────────────┐
│                  Seed Paper Selection                      │
│                                                           │
│ Goal: find a highly-cited and topically relevant paper    │
│                                                           │
│ Strategy A: search_filter(per_page=1)                     │
│   → take first result (relevant but not necessarily       │
│     high-citation)                                        │
│   → Exp 02: DenseSPH-YOLOv5 (cited 234) ← too low        │
│                                                           │
│ Strategy B: search().sort(cited_by_count="desc", per_page=1) │
│   → sort overrides relevance ranking                      │
│   → Exp 08: MizAR 60 for Mizar 50 (cited 74131)          │
│             ← math paper, not relevant!                   │
│                                                           │
│ Strategy C: search(per_page=5) + Python max(cited_by_count) │
│   → let BM25 filter 5 papers, then pick highest-cited     │
│   → Exp 09: Attention Is All You Need (cited 6504)        │
│             ← correct!                                    │
│                                                           │
│  A (cited 234) << C (cited 6504) <<< B (cited 74131)     │
│  Relevance:  A=✓  C=✓  B=✗                               │
└───────────────────────────────────────────────────────────┘

Important finding (Exp 09):
  Even with the best seed (Attention Is All You Need),
  filter(cites=seed) still yields 0% relevance!

  Reason: "Attention Is All You Need" is cited across many domains
  → AlphaFold, XAI, GNN, DistilBERT, DL-TSC (all off-topic)

  Conclusion: filter(cites=) topic precision has no positive
  correlation with seed quality
```

---

## 7. Tavily's Role in the Workflow (Historical)

Tavily is a **web search API**, not an academic database.

```
┌─────────────────────────────────────────────────────────┐
│                   Original Design Idea                   │
│                                                         │
│  Tavily search                                          │
│  "attention mechanism..."  ──► [title1, title2]         │
│                                      │                  │
│                              OpenAlex exact lookup      │
│                              search_filter(title=)      │
│                                      │                  │
│                              fetch paper metadata       │
│                              (citations, ArXiv, DOI...) │
│                                                         │
│  Assumption: Tavily can return precise academic titles  │
└─────────────────────────────────────────────────────────┘

Exp 04 / Exp 05 findings:

  Query format has a huge impact:
  ┌──────────────────────────────────────────────────┐
  │  Bare query (Exp 04/05 Query A)                  │
  │  "attention mechanism in transformer models"     │
  │  → Tavily returned: Medium articles, IBM         │
  │    tutorials, YouTube videos                     │
  │  → Academic hit rate: 0/2                        │
  │                                                  │
  │  arxiv prefix (Exp 05 Query B / Exp 07)          │
  │  "arxiv papers about the state of the art of..." │
  │  → Tavily returned: ArXiv paper links            │
  │  → Academic hit rate: 2/2 = 100%                 │
  └──────────────────────────────────────────────────┘

Exp 04 / Exp 07 cross-run variance (Tavily is non-deterministic):

  Same query, different times → different results:
  ┌──────────┬─────────────────────────────────┐
  │          │  Run 1 (3/16)   Run 2 (3/17)    │
  ├──────────┼─────────────────────────────────┤
  │ Exp 04 X │ cited [303,685] cited [103,16]  │
  │ Exp 07   │ cited [0, 2]    cited [1026,6504]│
  └──────────┴─────────────────────────────────┘

  Reason: Tavily is a live web search — results vary by cache and time

Note: the current pipeline no longer uses Tavily. Papers are discovered
directly via OpenAlex BM25 full-text search with LLM query reformulation.
```

---

## 8. End-to-End Workflow View

```
User inputs Topic
     │
     ▼
┌────────────────────────────────────────────────────────┐
│              Path A: Primary Search                    │
│                                                        │
│  Works().search(topic)                                 │
│         .filter(is_oa=True)                            │
│         .get(per_page=15)                              │
│              │                                         │
│              ▼                                         │
│     15 papers (93% relevance)                          │
│         ├── has ArXiv (6–7 papers) → direct PDF        │
│         └── non-ArXiv OA (~8 papers) → try oa_url     │
│                                                        │
└────────────────────────────────────────────────────────┘
     │
     │  pick max(cited_by_count) as seed
     ▼
┌────────────────────────────────────────────────────────┐
│              Path B: Citation Expansion (Exp 03)       │
│                                                        │
│  Works().filter(cites=seed_id).get(per_page=5)        │
│              │                                         │
│              ▼                                         │
│         5 papers (60% relevance, 0% ArXiv)             │
│         → zero overlap with Path A (A∩B=0)             │
│         → provides different perspectives              │
│                                                        │
└────────────────────────────────────────────────────────┘
     │
     │  merge and deduplicate
     ▼
   Hybrid: 15 papers (87% relevance, 20% ArXiv)
```

---

## 9. Key Numbers at a Glance

| Method | Relevance | ArXiv% | Best Use Case |
|--------|-----------|--------|---------------|
| `search()` | 100% | 20–30% | Primary search path |
| `search_filter(title_and_abstract=)` | 100% | 7% | Exact keyword matching |
| `search_filter(title=)` | 100% | 0% | Exact title known |
| `similar()` | 100% | 30% | Semantic supplement |
| `filter(cites=)` | 0–60% | 0–60% | High topic drift risk |
| `referenced_works` | 10% | 30% | Tracing prior work |
| `search()+is_oa=True` | 93–100% | 30–50% | When OA is required |
| `search()+primary_topic` | 90% | 30% | Topic purification (MizAR still leaks through) |

**Effect of `per_page` on ArXiv paper count (`search()+is_oa=True`):**

```
  per_page=10 → relevant papers with ArXiv: 3
  per_page=15 → relevant papers with ArXiv: 6  ← minimum practical threshold
  per_page=20 → relevant papers with ArXiv: 7
```

---

## 10. Common pyalex Pitfalls

```
┌─────┬──────────────────────────────────────────────────┐
│ ⚠ 1 │ sort() combined with search() → sort overrides   │
│     │ relevance ranking. Use Python max() instead       │
├─────┼──────────────────────────────────────────────────┤
│ ⚠ 2 │ similar() occasionally returns HTTP 500          │
│     │ → wrap in try/except                             │
├─────┼──────────────────────────────────────────────────┤
│ ⚠ 3 │ abstract_inverted_index must be reconstructed   │
│     │ {"word": [pos1, pos2]} → sort by pos → join      │
├─────┼──────────────────────────────────────────────────┤
│ ⚠ 4 │ is_oa=True ≠ ArXiv                              │
│     │ Check locations[].landing_page_url               │
├─────┼──────────────────────────────────────────────────┤
│ ⚠ 5 │ primary_topic filter is imperfect               │
│     │ MizAR (math paper) is classified as NLP          │
│     │ and still appears in results                     │
├─────┼──────────────────────────────────────────────────┤
│ ⚠ 6 │ filter(cites=) requires bare ID format:          │
│     │ strip the "https://openalex.org/" prefix         │
│     │ work["id"].replace("https://openalex.org/", "")  │
└─────┴──────────────────────────────────────────────────┘
```
