# extract-id.py — Research Report

## Purpose

Validate the complete pipeline of:
1. Looking up academic papers in OpenAlex by title
2. Extracting all available IDs (OpenAlex ID, DOI, ArXiv ID)
3. Downloading the PDF using a 4-strategy fallback chain

This script was written as a proof-of-concept to determine whether OpenAlex can fully replace Tavily as the paper discovery layer in the research-agent workflow.

---

## Environment

- Python 3.12 (micromamba env `py3.12`)
- Key dependencies: `pyalex`, `arxiv`, `requests`, `python-dotenv`
- `.env` location: two levels above the script (`dev/.env`)
- Required env vars: `OPENALEX_API_KEY`, `OPENALEX_EMAIL`

---

## OpenAlex ID Structure

A single OpenAlex Work dict exposes IDs through different fields. The locations of each ID are **not uniform**.

### work["ids"] — directly available

| ID type | Field | Example |
|---------|-------|---------|
| OpenAlex ID | `work["id"]` or `work["ids"]["openalex"]` | `https://openalex.org/W2626778328` |
| DOI | `work["ids"]["doi"]` or `work["doi"]` | `https://doi.org/10.48550/arxiv.1706.03762` |
| MAG | `work["ids"]["mag"]` | `2626778328` |
| PMID | `work["ids"]["pmid"]` | (PubMed, when present) |
| PMCID | `work["ids"]["pmcid"]` | (PubMed Central, when present) |

All values include a URL prefix that must be stripped for bare use.

### ArXiv ID — NOT in work["ids"]

**ArXiv ID is absent from `work["ids"]`.** It must be parsed from `work["locations"]`:

```python
for loc in work.get("locations", []):
    landing = loc.get("landing_page_url") or ""
    if "arxiv.org" in landing:
        arxiv_id = landing.rstrip("/").split("/")[-1]
```

**Critical: version suffix stripping.**
OpenAlex sometimes stores versioned URLs (e.g. `arxiv.org/abs/1706.03762v5`). The version suffix must be stripped with `re.sub(r"v\d+$", "", raw)` to always obtain the latest version. The `loc["pdf_url"]` field is intentionally ignored because it may also be pinned to an old version.

```
landing_page_url = "https://arxiv.org/abs/1706.03762v5"
→ raw      = "1706.03762v5"
→ arxiv_id = "1706.03762"          ← version stripped
→ pdf_url  = "https://arxiv.org/pdf/1706.03762"  ← always unversioned → latest
```

The unversioned URL `https://arxiv.org/pdf/{arxiv_id}` is redirected by ArXiv to the latest version automatically.

---

## Search Modes

The script supports two modes controlled by the `PAPER_TITLES` constant.

### Mode 1 — Title lookup (default, `PAPER_TITLES` non-empty)

```python
Works().search_filter(title=title).get(per_page=3)
```

Fetches **3 candidates** per title, not 1. Reason: some papers exist as two unmerged OpenAlex records (publisher version + ArXiv preprint). The publisher version ranks first but has no ArXiv location. The preprint record, ranked lower, contains the ArXiv ID needed for download.

Selection logic:
1. Return the first candidate that has an `arxiv.org` URL in any location
2. If none have ArXiv → return top-1 (highest relevance score)

**Example — Informer paper (unmerged records):**
```
#1 W3177318507  DOI: 10.1609/aaai.v35i12.17325  locations: [AAAI only]   cited: 5484
#2 W3111507638  DOI: 10.48550/arxiv.2012.07436  locations: [arxiv.org ✓] cited: 460
→ Script selects #2 to obtain ArXiv ID
```

### Mode 2 — Broad semantic search (`PAPER_TITLES` empty)

```python
Works().similar(query).filter(is_oa=True, cited_by_count=f">{CITED_THRESHOLD}").get(per_page=PER_PAGE)
```

Followed by Python-side post-filter for OA status `{diamond, gold, green}`.

The OA status filter is applied in Python (not at the API level) because the nested-dict OR syntax `open_access={"oa_status": "gold|diamond"}` is not officially documented by OpenAlex.

---

## OpenAlex Deduplication Issue

Some papers exist as **two separate, unmerged records** in OpenAlex:

| Record | Represents | DOI type | ArXiv in locations |
|--------|-----------|----------|--------------------|
| Publisher version | AAAI / NeurIPS / etc. final paper | `10.1609/...` (publisher) | ✗ |
| ArXiv preprint | arXiv-first version | `10.48550/arxiv.*` | ✓ |

`any_repository_has_fulltext: False` in the publisher record is OpenAlex's own signal that no repository (ArXiv) copy is linked to that record.

**Affected papers in test set:** Informer, Are Transformers Effective for Time Series Forecasting.
**Unaffected:** Attention Is All You Need, TransUNet, Longformer (all have merged single records).

**Why do some papers merge and others don't?**
Papers where ArXiv is the canonical primary source (DOI starts with `10.48550/arxiv.*`) are stored as unified records. Papers published at venues (AAAI, NeurIPS) with a publisher DOI are often stored separately from their ArXiv preprints, especially when OpenAlex's deduplication heuristics fail to link them.

---

## ArXiv Version Policy

In ML/CS research, the typical publication timeline is:

```
ArXiv preprint (v1) → Conference submission → Peer review
→ Camera-ready (AAAI/NeurIPS) → Authors post revised ArXiv (v2, v3...)
```

ArXiv usually comes **before** the conference, not after. Post-publication, authors often upload updated versions to ArXiv that:
- Incorporate reviewer feedback corrections
- Restore content cut due to conference page limits
- Add supplementary experiments

**Consequence:** The ArXiv latest version is typically the most complete and corrected version, making it the preferred source for downstream tasks like summarization and slide generation.

**Version behaviour of each download strategy:**

| Strategy | URL | Version obtained |
|----------|-----|-----------------|
| `arxiv_api` | `result.pdf_url` = `.../1706.03762v7` | Explicitly the latest (API confirms current version number) |
| `constructed_arxiv_url` | `arxiv.org/pdf/1706.03762` (no version) | Latest via ArXiv redirect |

Both strategies yield the latest version after the version-strip fix.

---

## Download Fallback Chain

Strategies are tried in order; the first success terminates the chain.

```
_DOWNLOAD_STRATEGIES = [
    _strategy_arxiv_api,              # 1
    _strategy_constructed_arxiv_url,  # 2
    _strategy_pyalex_pdf_get,         # 3
    _strategy_openalex_url,           # 4
]
```

### Strategy 1 — `arxiv_api`

```python
result = next(arxiv.Client().results(arxiv.Search(id_list=[paper.arxiv_id])))
time.sleep(ARXIV_DELAY)   # 3 seconds
requests.get(result.pdf_url, headers=_BROWSER_HEADERS)
```

- Requires: `arxiv_id`
- Uses official `arxiv` Python library to resolve the canonical latest-version URL
- `download_pdf()` method deprecated upstream; `result.pdf_url` + `requests.get()` used instead
- 3-second delay before each request (ArXiv rate-limit compliance)

### Strategy 2 — `constructed_arxiv_url`

```python
url = f"https://arxiv.org/pdf/{paper.arxiv_id}"
time.sleep(ARXIV_DELAY)   # 3 seconds, same as strategy 1
requests.get(url, headers=_BROWSER_HEADERS)
```

- Requires: `arxiv_id`
- Bypasses the arxiv library API call; constructs the URL directly
- Unversioned URL → ArXiv server redirects to latest
- Same 3-second delay as Strategy 1 (both hit ArXiv servers)

### Strategy 3 — `pyalex_pdf_get`

```python
content = Works()[paper.openalex_id].pdf.get()
```

- Requires: `openalex_id` (always available)
- pyalex resolves PDF via OpenAlex's internal content endpoint
- Not subject to publisher User-Agent blocks
- Useful for AAAI diamond papers that have no ArXiv ID

### Strategy 4 — `openalex_url`

```python
requests.get(paper.oa_url, headers=_BROWSER_HEADERS)
```

- Requires: `oa_url` from `work["open_access"]["oa_url"]`
- Directly fetches OpenAlex's best-known OA URL
- May point to publisher page, institutional repo, or ArXiv

---

## 403 Forbidden — Publisher User-Agent Block

**Problem:** AAAI OJS (and other academic publishers) return HTTP 403 when the request User-Agent is `python-requests/x.x.x`.

**Verified:**
```
curl (default UA: curl/8.x)              → 200 ✓
curl -H "User-Agent: python-requests/..."→ 403 ✗
curl -H "User-Agent: Mozilla/5.0 ..."   → 200 ✓
requests (default)                       → 403 ✗
requests + _BROWSER_HEADERS              → 200 ✓  4.8 MB PDF
```

**Fix:** All `requests.get()` calls use `_BROWSER_HEADERS`:
```python
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; ...) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
}
```

---

## Test Results (5 papers, Python 3.12)

| # | Paper | OA Status | ArXiv ID | Winning Strategy |
|---|-------|-----------|----------|-----------------|
| 1 | Attention Is All You Need | gold | ✓ 1706.03762 | `arxiv_api` |
| 2 | Informer | green (preprint record) | ✓ 2012.07436 | `arxiv_api` |
| 3 | TransUNet | green | ✓ 2102.04306 | `arxiv_api` |
| 4 | Are Transformers Effective | green (preprint record) | ✓ 2205.13504 | `arxiv_api` |
| 5 | Longformer | green | ✓ 2004.05150 | `arxiv_api` |

**Final coverage:** OpenAlex ID 5/5 · DOI 5/5 · ArXiv ID 5/5 · OA URL 5/5
All 5 papers downloaded successfully via `arxiv_api` (Strategy 1).

---

## Configuration Reference

| Constant | Default | Description |
|----------|---------|-------------|
| `QUERY` | `"attention mechanism in transformer models"` | Query for broad `similar()` mode |
| `TARGET_OA_STATUSES` | `{"diamond", "gold", "green"}` | OA status post-filter |
| `CITED_THRESHOLD` | `100` | Minimum `cited_by_count` for broad mode |
| `PER_PAGE` | `25` | Results per OpenAlex API page |
| `DOWNLOAD_DIR` | `./downloads/` | PDF output directory |
| `REQUEST_TIMEOUT` | `30` | HTTP request timeout in seconds |
| `ARXIV_DELAY` | `3` | Seconds to sleep before each ArXiv request |
| `PAPER_TITLES` | `[...]` | If non-empty, runs title-lookup mode |

---

## Reusable Components

The following functions are designed to be imported independently:

| Function | Input | Output | Notes |
|----------|-------|--------|-------|
| `extract_openalex_id(work)` | OpenAlex Work dict | `str` | Strips URL prefix |
| `extract_doi(work)` | OpenAlex Work dict | `Optional[str]` | Strips URL prefix |
| `extract_arxiv(work)` | OpenAlex Work dict | `(arxiv_id, pdf_url)` | Strips version suffix |
| `extract_oa_status(work)` | OpenAlex Work dict | `str` | |
| `extract_oa_url(work)` | OpenAlex Work dict | `Optional[str]` | |
| `work_to_paper_ids(work)` | OpenAlex Work dict | `PaperIDs` | Aggregates all extractors |
| `fetch_work_by_title(title)` | title string | `Optional[dict]` | Prefers ArXiv record |
| `download_pdf_with_fallback(paper)` | `PaperIDs` | `list[DownloadResult]` | Full fallback chain |

---

## Known Limitations

1. **`fetch_work_by_title` scans only top 3 candidates.** If the ArXiv preprint record is ranked 4th or lower, it will be missed and the publisher record (without ArXiv ID) is returned. In practice this is rare but possible for papers with many near-duplicate titles.

2. **Strategy 3 (`pyalex_pdf_get`) version is uncontrolled.** pyalex's `pdf.get()` resolves the PDF via OpenAlex's content endpoint; which version it returns depends on what OpenAlex indexes and is not guaranteed to be the latest ArXiv version.

3. **`cited_count` in `PaperIDs` reflects only the selected record.** For papers with unmerged records (Informer, Are Transformers Effective), the ArXiv preprint record has a lower `cited_count` than the publisher record. The true citation count is in the publisher record that was bypassed.

4. **ArXiv-only search.** Strategies 1 and 2 require `arxiv_id`. Papers published only at closed-access venues with no ArXiv preprint will fall through to Strategy 3 or 4.
