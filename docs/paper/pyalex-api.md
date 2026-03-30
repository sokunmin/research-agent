# pyalex API Reference

> Based on the official pyalex documentation (J535D165/pyalex) and experimental results (Exp 01–20).
> OpenAlex API key is required as of 2026-02-13.

---

## Initialization

```python
import pyalex
from pyalex import Works, Authors, Sources, Institutions, Topics, Publishers, Funders

pyalex.config.api_key = "your-key"          # required (since 2026-02)
pyalex.config.email  = "you@example.com"    # optional, enters polite pool (higher rate limit)
```

---

## Category A: Search Methods (how to find papers)

| Feature | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **Full-text relevance search** | `Works().search("query").get()` | BM25 relevance ranking over title, abstract, and full text | Primary entry point; relevance consistently 93–100%; surfaces high-citation representative papers (e.g. "Attention Is All You Need") |
| **Title+Abstract exact search** | `Works().search_filter(title_and_abstract="query").get()` | Matches only title and abstract with AND logic | Use when keywords must appear exactly; excludes papers where query terms only appear in full text |
| **Title exact search** | `Works().search_filter(title="query").get()` | Matches only title | Most restrictive; 0% ArXiv coverage (papers tend to be in journals); use when exact title is known |
| **Semantic search (AI)** | `Works().similar("query").get()` | Embedding vector distance; finds semantically similar papers | Supplements keyword methods; may return HTTP 500 — wrap in try/except |
| **Incoming citations** | `Works().filter(cites="W_ID").get()` | Finds all papers that cite a given paper | Expands from a high-citation seed; high topic drift risk — broader seeds attract cross-domain citations |
| **Outgoing citations** | `Works()[work["referenced_works"]]` | Retrieves the reference list of a paper | Traces sources cited by the seed; low relevance (~10%), useful for finding foundational prior work |

### Search Method Behavior Comparison

```
               Topic Precision
               HIGH ─────────────────────── LOW
                │                             │
 Coverage HIGH  │  search()    similar()       │
                │                             │
          LOW   │  s_filter()  filter(cites=)  │
                └─────────────────────────────┘

ArXiv Coverage (downloadability): search() ≈ similar() >> search_filter() >> filter(cites=)
```

---

## Category B: Filter Conditions (narrowing scope, improving quality)

| Feature | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **OA filter** | `.filter(is_oa=True)` | Returns only Open Access papers | Ensures papers are accessible; status includes gold/green/diamond/hybrid — does not guarantee an ArXiv PDF |
| **Year filter (exact)** | `.filter(publication_year=2023)` | Filter by specific publication year | Restrict to a single year |
| **Year filter (range)** | `.filter(publication_year=">2020")` | Inequality: `>` and `<` supported | Limit to recent papers; combine `">2020"` and `"<2024"` for a range |
| **Citation threshold** | `.filter(cited_by_count=">100")` | Inequality filter on citation count | Quality floor — only papers with established academic impact |
| **Paper type** | `.filter(type="article")` | Types: `article` / `dataset` / `preprint` / `book` / etc. | Exclude non-papers (datasets, editorials); ensure results are academic papers |
| **Topic filter** | `.filter(primary_topic={"id": "T_ID"})` | Filter by OpenAlex topic ID | Improves topic purity; note that MizAR (math paper) is classified under NLP — not a perfect filter |
| **NOT (negation)** | `.filter(cited_by_count="!0")` | `!` prefix negates the value | Exclude papers with zero citations (e.g. newly published work with no citations yet) |
| **OR within filter** | `.filter(institutions={"country_code": "us\|gb"})` | `\|` separator means OR | Match multiple values simultaneously (e.g. papers from US or UK institutions) |
| **AND within filter (nested)** | `.filter(institutions={"country_code": ["us", "gb"]})` | List means AND | Require co-authorship from multiple countries simultaneously |
| **Author filter** | `.filter(author={"id": "A_ID"})` | Filter by OpenAlex author ID | Find other works by the seed paper's authors |
| **Institution filter** | `.filter(authorships={"institutions": {"ror": "ROR_ID"}})` | Filter by institution ROR ID | Find papers from specific institutions (e.g. MIT, Stanford) |
| **Batch DOI query** | `.filter_or(doi=["10.xxx", "10.yyy"])` | OR batch query, up to 100 entries | Known DOI list → batch-fetch OpenAlex metadata in a single request |

---

## Category C: Result Handling (sorting, sampling, pagination)

| Feature | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **Sort** | `.sort(cited_by_count="desc")` | Sort by a field | **Dangerous**: when combined with `search()`, sort completely overrides BM25 relevance ranking, returning high-citation but off-topic papers (the MizAR problem). Use Python `max()` instead |
| **Safe high-citation seed** | `cands = .get(per_page=5)` + `max(cands, key=lambda w: w["cited_by_count"])` | Let BM25 filter first, then pick max in Python | Correct approach to find a quality seed without topic drift from sort() |
| **Field selection** | `.select(["id", "cited_by_count", "display_name", "open_access"])` | Return only specified fields | Reduces response size; use when only certain fields are needed |
| **Random sampling** | `.sample(10, seed=42)` | Reproducible with seed; supports filter chains | Validate search quality with a random sample; `seed` ensures reproducibility |
| **Cursor pagination** | `.paginate(per_page=200, n_max=1000)` | Default cursor paging, up to 10,000 results | Bypass the 200-per-request limit; fetch large batches then filter in Python |
| **Offset pagination** | `.paginate(method="page", per_page=200)` | Traditional paging with 10,000 result cap | Use when random access to a specific page is needed |
| **Count only** | `.count()` | Returns total count without fetching papers | Quickly validate query hit count before fetching; zero API credit cost |
| **Result metadata** | `results = .get()` → `results.meta` | Returns `{'count': X, 'page': Y, 'per_page': Z}` | Check actual total hit count (not just per_page limit); assess query coverage |
| **Group statistics** | `.group_by("primary_topic.id").get()` | Returns grouped counts, not papers | Analyze topic distribution of results; find a topic ID to narrow with primary_topic filter |

---

## Category D: Native Content Retrieval (PDF / TEI)

> pyalex has built-in PDF and TEI download support, replacing manual `requests.get()`.

| Feature | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **Get PDF bytes** | `Works()["W_ID"].pdf.get()` | Returns PDF as binary bytes | Directly retrieve a paper PDF without handling HTTP headers and redirects manually |
| **Download PDF to file** | `Works()["W_ID"].pdf.download("paper.pdf")` | Writes directly to a file | Simplest way to save a PDF; name using paper title or ID |
| **Get PDF URL only** | `Works()["W_ID"].pdf.url` | Returns the URL without downloading | Check if a PDF URL exists before deciding to download; useful for batch existence checks |
| **Get TEI XML** | `Works()["W_ID"].tei.get()` | Structured full text (Text Encoding Initiative XML) | Easier to parse than PDF; contains paragraph and citation markup; suitable for LLM summarization/chunking |
| **Download TEI to file** | `Works()["W_ID"].tei.download("paper.xml")` | Writes directly to an XML file | Input source for full-text processing pipelines |

**Note**: PDF/TEI are singleton calls (per paper) and do not consume list request credits. Availability depends on the publisher's OA license.

---

## Category E: Stability Settings

| Feature | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **Auto-retry** | `pyalex.config.max_retries = 3` | Number of automatic retries on failure (default 0) | Handles intermittent HTTP 500 from `similar()`; setting 3 significantly reduces failure rate |
| **Retry backoff** | `pyalex.config.retry_backoff_factor = 0.5` | Delay multiplier between retries (seconds) | Avoids triggering rate limits with rapid consecutive retries |
| **Retry trigger codes** | `pyalex.config.retry_http_codes = [429, 500, 503]` | Which HTTP status codes trigger retry | 429=rate limit, 500=server error (common with similar()), 503=unavailable |

---

## Category F: Utility Queries

| Feature | Syntax | Description | Use Case |
|---------|--------|-------------|----------|
| **Autocomplete** | `Works().autocomplete("attention mech")` | Returns completion suggestions from partial input | Quickly find the correct topic name or entity ID; replaces manual group_by lookups |
| **Autocomplete + filter** | `Works().filter(publication_year=2023).autocomplete("query")` | Autocomplete within a filtered scope | Narrows autocomplete to a specific context for better accuracy |
| **Topics entity** | `Topics().search("NLP").get()` | Directly query topic objects to get topic IDs | More direct than using group_by to find a topic ID |
| **Authors entity** | `Authors().search("Hinton").get()` | Search author information | Find an author's ID, then use `.filter(author={"id": ...})` to retrieve all their works |
| **Single paper by DOI** | `Works()["https://doi.org/10.xxx"]` | Singleton lookup, 0 credits | Retrieve full paper metadata when the DOI is known |
| **Single paper by ID** | `Works()["W2626778328"]` | Singleton lookup, 0 credits | Use when the OpenAlex ID is known |
| **Abstract reconstruction** | `work["abstract"]` | pyalex auto-converts the inverted index to plain text | Get a readable abstract without manual reconstruction; only available on singleton-fetched Works |

---

## Common Query Patterns

### Find recent high-quality OA papers (primary path)

```python
results = (
    Works()
    .search("attention mechanism transformer")
    .filter(is_oa=True, publication_year=">2020", type="article")
    .get(per_page=20)
)
# Safe seed selection (avoid sort())
seed = max(results, key=lambda w: w.get("cited_by_count", 0))
```

### Fetch large result sets (pagination)

```python
from itertools import chain

all_works = list(chain(*
    Works()
    .search("attention mechanism transformer")
    .filter(is_oa=True)
    .paginate(per_page=200, n_max=500)
))
```

### Check hit count before fetching

```python
n = Works().search("topic").filter(is_oa=True, type="article").count()
if n > 0:
    results = Works().search("topic").filter(is_oa=True, type="article").get(per_page=20)
```

### Stable similar() (with retry)

```python
pyalex.config.max_retries = 3
pyalex.config.retry_backoff_factor = 0.5
pyalex.config.retry_http_codes = [429, 500, 503]

results = Works().similar("query").filter(is_oa=True).get(per_page=10)
```

### PDF download (native)

```python
w = Works()["W2626778328"]   # singleton, 0 credits
try:
    w.pdf.download(f"{w['id']}.pdf")
except Exception:
    tei = w.tei.get()        # fall back to TEI if PDF unavailable
```

### Find a topic ID (two approaches)

```python
# Method A: group_by (get topic distribution from search results)
groups = Works().search("query").group_by("primary_topic.id").get()
topic_id = next(g["key"] for g in groups if "natural language" in g.get("key_display_name","").lower())

# Method B: Topics entity (direct lookup, more concise)
topics = Topics().search("natural language processing").get()
topic_id = topics[0]["id"]
```

---

## Parameter Quick Reference

```
filter() common parameters:
  is_oa                  bool
  publication_year       int | ">YYYY" | "<YYYY"
  cited_by_count         int | ">N" | "<N" | "!N"
  type                   "article" | "dataset" | "preprint" | "book" | ...
  primary_topic          {"id": "T_ID"}
  cites                  "W_ID"
  author                 {"id": "A_ID"}
  authorships            {"institutions": {"ror": "ROR_ID"}}
  institutions           {"country_code": "us"} | {"country_code": "us|gb"}
  doi                    "10.xxx/yyy"

logical prefixes in values:
  "!value"   → NOT
  "v1|v2"    → OR (within a filter value)
  [v1, v2]   → AND (nested filter)

get() parameters:
  per_page   int, max 200

paginate() parameters:
  per_page   int, max 200
  n_max      int | None (None = fetch all)
  method     "cursor" (default) | "page"

sample() parameters:
  n          int, number of results
  seed       int, reproducible random seed

config parameters:
  api_key              str
  email                str
  max_retries          int (default 0)
  retry_backoff_factor float (default 0.1)
  retry_http_codes     list[int] (default [429, 500, 503])
```
