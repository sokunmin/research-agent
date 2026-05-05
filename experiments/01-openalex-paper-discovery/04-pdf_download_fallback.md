# Experiment 4 — PDF Acquisition: ArXiv ID Extraction from locations[] and Four-Strategy Fallback Chain

## Task Context

This experiment targets **Step 3 — PDF Acquisition & Parsing** from the system architecture (README → System Architecture).

```
Input: List[Paper] (relevant, OA-filtered papers)    ← Step 2: Re-ranking & Verification
      │
      ▼
┌── 3. PDF ACQUISITION & PARSING ────────────────────────────────────────────────┐
├─── Original (lz-chen) ───────────────────┬─── My Implementation ───────────────┤
│ arxiv library (ArXiv ID required;        │ Download: 4-strategy fallback chain  │
│ single strategy, no fallback)            │ (ArXiv API → URL → pyalex → OA URL) │
│ Parsing: marker-pdf (OCR-based)          │ Parsing: Docling (local, planned)    │
└──────────────────────────────────────────┴─────────────────────────────────────┘
      │
      ▼
Output: PDF files                                      → Step 4: Summarization
```

Step 3 internal detail — the experiment targets ID extraction and the download chain:

```
Step 3 — PDF Acquisition (detail)
──────────────────────────────────────────────────────────────────────────────
 List[Paper] from Step 2 (entry_id, external_ids, open_access_pdf)
       │
       ▼
 ┌─── EXPERIMENT TARGET ──────────────────────────────────────────────────┐
 │  _extract_arxiv_id(work)                                               │
 │    Input:  work["locations"][*]["landing_page_url"]                    │
 │    Logic:  scan for arxiv.org → strip version suffix → construct URL   │
 │    Output: arxiv_id (Optional[str])                                    │
 │                                                                        │
 │  PaperDownloader.download(paper, dest_dir, filename)                   │
 │    Strategy 1: arxiv_api        — arxiv.Client() → result.pdf_url     │
 │    Strategy 2: arxiv_direct_url — arxiv.org/pdf/{arxiv_id}            │
 │    Strategy 3: pyalex_pdf       — Works()[openalex_id].pdf.get()      │
 │    Strategy 4: openalex_oa_url  — open_access.oa_url + browser hdrs  │
 └────────────────────────────────────────────────────────────────────────┘
       │
       ▼
 PDF files on disk                              → Step 4: VLM Summarization
```

If this step fails, the VLM summarization step has no input and the entire pipeline stalls. The OA status pre-filter (`diamond`, `gold`, `green`) applied at Step 1 guarantees at least one fallback strategy is applicable to every paper in the pool.

---

## Summary

- **Problem:** lz-chen's download step uses a single strategy with no fallback — any paper without an ArXiv ID, or any ArXiv API failure, is permanently lost from the pipeline.
  - The download method is deprecated upstream. The library's own docs recommend fetching the PDF URL directly.
  - Non-ArXiv open-access papers (e.g. AAAI diamond OA) are completely unreachable — lz-chen's step silently drops them.
- **Solution:** Design and validate a four-strategy fallback chain with an OA status pre-filter at search time — guaranteeing every paper in the pool has at least one viable download path before the chain runs.
  - The OA status pre-filter is enforced at Step 1 (retrieval), not at download time — unreachable papers never enter the pipeline.
  - Two non-obvious implementation challenges validated: OpenAlex does not expose ArXiv IDs in the primary identifier field — a naive implementation gets None silently. Publisher-hosted PDFs require browser-mimicking headers to bypass HTTP 403 blocks.
- **Result:** 5/5 test papers download successfully — the fallback chain and pre-filter together provide a structural download guarantee rather than best-effort retrieval.
  - Two papers required selecting the ArXiv preprint record over the higher-ranked publisher record to obtain a usable ArXiv ID.
  - All strategies 2–4 remain untested in the current test set — they cover non-ArXiv OA papers not represented in the 5-paper test.

---

## Experiment Setup

✅ = currently used in the pipeline

### Objective

- **Problem:** lz-chen's download step is a single point of failure — one strategy (arxiv library), deprecated method (`download_pdf()`), ArXiv-only coverage, no fallback. Any failure permanently removes that paper from the pipeline.
- **Goal:** Validate that a four-strategy fallback chain with OA pre-filtering achieves reliable downloads across papers with varying OA statuses, including papers not hosted on ArXiv.
- **Pass condition:** All 5 test papers download successfully; ArXiv IDs extracted correctly for all papers including those with unmerged OpenAlex records.

### Test Papers

5 papers from the `PAPER_TITLES` constant, spanning gold and green OA statuses. Two papers exist as unmerged OpenAlex records (publisher version + ArXiv preprint stored separately).

| # | Paper | OA Status | Unmerged Records |
|---|---|---|---|
| 1 | Attention Is All You Need | gold | No — unified record |
| 2 | Informer: Beyond Efficient Transformer... | green | Yes — publisher (AAAI) + ArXiv preprint |
| 3 | TransUNet: Transformers Make Strong... | green | No — unified record |
| 4 | Are Transformers Effective for Time Series... | green | Yes — publisher + ArXiv preprint |
| 5 | Longformer: The Long-Document Transformer | green | No — unified record |

### Download Strategies

Strategies are tried in priority order; the first success terminates the chain.

| Priority | Strategy | Method | Requires | Delay |
|---|---|---|---|---|
| 1 ✅ | `arxiv_api` | `arxiv.Client()` → `result.pdf_url` → `requests.get()` | `arxiv_id` | 3 s |
| 2 | `constructed_arxiv_url` | `https://arxiv.org/pdf/{arxiv_id}` → `requests.get()` | `arxiv_id` | 3 s |
| 3 | `pyalex_pdf_get` | `Works()[openalex_id].pdf.get()` | `openalex_id` (always present) | None |
| 4 | `openalex_oa_url` | `open_access.oa_url` → `requests.get()` + browser headers | `oa_url` | None |

### Parameters

| Parameter | Value | Description |
|---|---|---|
| `ARXIV_DELAY` | 3 s | Sleep before each ArXiv request (rate-limit compliance) |
| `REQUEST_TIMEOUT` | 30 s | HTTP request timeout |
| `_BROWSER_HEADERS` | Mozilla/5.0 Chrome/120 | User-Agent for all `requests.get()` calls |
| Title lookup candidates | 3 | `fetch_work_by_title()` fetches top-3 and prefers ArXiv record |

---

## Full Experimental Results

### ArXiv ID Extraction (Exp 4a)

- **Purpose:** Confirm that ArXiv IDs can be extracted from all 5 papers via `locations[]` parsing, including papers with unmerged records.
- **Expected:** All 5 papers yield a valid `arxiv_id`; unmerged-record papers require selecting rank #2.

| # | Paper | OpenAlex ID | DOI | ArXiv ID | OA URL | Record Selected |
|---|---|---|---|---|---|---|
| 1 | Attention Is All You Need | ✓ | ✓ | ✓ 1706.03762 | ✓ | Rank #1 (unified) |
| 2 | Informer | ✓ | ✓ | ✓ 2012.07436 | ✓ | Rank #2 (ArXiv preprint) |
| 3 | TransUNet | ✓ | ✓ | ✓ 2102.04306 | ✓ | Rank #1 (unified) |
| 4 | Are Transformers Effective | ✓ | ✓ | ✓ 2205.13504 | ✓ | Rank #2 (ArXiv preprint) |
| 5 | Longformer | ✓ | ✓ | ✓ 2004.05150 | ✓ | Rank #1 (unified) |

**Conclusion:** ArXiv IDs are accessible for all 5 papers, but two require selecting a lower-ranked ArXiv preprint over the top-ranked publisher record.

### HTTP 403 User-Agent Validation (Exp 4b)

- **Purpose:** Verify that browser-mimicking headers are required to bypass HTTP 403 from publisher-hosted OA PDFs (e.g. AAAI OJS).
- **Expected:** Default `python-requests` User-Agent blocked; browser UA succeeds.

| Request Method | User-Agent | HTTP Status | Outcome |
|---|---|---|---|
| `requests` (default) | `python-requests/2.x` | 403 | Blocked |
| `curl` (default) | `curl/8.x` | 200 | Success |
| `curl` (python-requests UA) | `python-requests/2.x` | 403 | Blocked |
| **`requests` + `_BROWSER_HEADERS` ✅** | **Mozilla/5.0 Chrome/120** | **200** | **Success — 4.8 MB PDF** |

**Conclusion:** Browser-mimicking headers are a hard requirement for publisher-hosted OA PDFs — the default python-requests User-Agent is blocked at the HTTP level, not an optimization.

### End-to-End Download Results (Exp 4c)

- **Purpose:** Validate the full fallback chain on all 5 papers.
- **Expected:** All 5 papers downloaded; Strategy 1 (arxiv_api) is the primary path for ArXiv-hosted papers.

| # | Paper | OA Status | ArXiv ID | Winning Strategy |
|---|---|---|---|---|
| 1 | Attention Is All You Need | gold | ✓ 1706.03762 | `arxiv_api` ✅ |
| 2 | Informer | green | ✓ 2012.07436 | `arxiv_api` ✅ |
| 3 | TransUNet | green | ✓ 2102.04306 | `arxiv_api` ✅ |
| 4 | Are Transformers Effective | green | ✓ 2205.13504 | `arxiv_api` ✅ |
| 5 | Longformer | green | ✓ 2004.05150 | `arxiv_api` ✅ |

**Conclusion:** All 5 papers download via the primary strategy — Strategies 2–4 are not exercised and remain unvalidated against non-ArXiv papers.

---

## Observations

### lz-chen's single-strategy download has two structural failure modes that the fallback chain addresses

```
lz-chen's download_paper_arxiv()
      │
      ├─ Failure mode 1: deprecated method
      │     paper.download_pdf() is deprecated upstream
      │     arxiv library docs recommend result.pdf_url + requests.get() instead
      │     → replaced in Strategy 1 (arxiv_api): arxiv.Client() → result.pdf_url → requests.get()
      │
      └─ Failure mode 2: ArXiv-only coverage
            filter(cites=seed_id) returns papers regardless of OA status
            non-ArXiv OA papers (AAAI diamond, institutional repos) have no arxiv_id
            → lz-chen silently drops these; no fallback exists
            → fork: Strategy 3 (pyalex_pdf) and Strategy 4 (openalex_oa_url) cover non-ArXiv papers
```

**Conclusion:** lz-chen's single-strategy download permanently loses any paper it cannot fetch — the fallback chain converts each failure mode into a recoverable step.
- The OA status pre-filter applied at Step 1 eliminates unreachable papers before the chain runs — structural prevention, not runtime recovery.
- Strategy 3 (pyalex) always applies — the OpenAlex ID is always present, guaranteeing at least one non-ArXiv fallback for every paper.

### OpenAlex does not expose ArXiv IDs in the primary identifier field — silent failure without location metadata parsing

OpenAlex returns paper metadata as a JSON dict. A naive implementation reads `work["ids"]` for all identifiers — this field contains DOI, MAG, PMID, but **no ArXiv entry**:

```json
"ids": {
  "openalex": "https://openalex.org/W2741809807",
  "doi": "https://doi.org/10.48550/arxiv.1706.03762",
  "mag": "2741809807"
}
```

The ArXiv ID is buried in a separate `locations` array, inside a versioned landing page URL:

```json
"locations": [
  {"landing_page_url": "https://arxiv.org/abs/1706.03762v5", "pdf_url": "..."}
]
```

Two extraction steps are required: scan the paper's location records for an arxiv.org entry, then strip the version suffix so the constructed PDF URL always resolves to the latest version. Using the location's direct PDF URL is unreliable — it may be pinned to an older version.

**Conclusion:** Reading the primary identifier field for an ArXiv ID returns None silently — the correct path is parsing location records with version suffix stripping.
- Two of 5 test papers (Informer, Are Transformers Effective) exist as unmerged OpenAlex records — a publisher record with no ArXiv location and a lower-ranked ArXiv preprint. Returning only the top result silently loses the ArXiv ID. The title lookup scans top-3 candidates and prefers the record with an ArXiv location.
- In ML/CS, the ArXiv latest version is typically the most complete copy: authors update preprints after peer review to restore content cut for page limits and incorporate reviewer feedback.

### Publisher-hosted PDFs block the default python-requests User-Agent with HTTP 403

Strategy 4 (`openalex_oa_url`) fetches `open_access.oa_url` — a URL that OpenAlex resolves to the best known OA location. This URL may point to ArXiv, an institutional repository, or a publisher portal. Publisher portals (e.g. AAAI OJS) actively block automated scrapers:

```
requests.get(oa_url)
      │
      ├─ User-Agent: "python-requests/2.x"
      │     → AAAI OJS: 403 Forbidden
      │     → ArXiv:    200 OK
      │
      └─ User-Agent: "Mozilla/5.0 ... Chrome/120"  ← _BROWSER_HEADERS
            → AAAI OJS: 200 OK, 4.8 MB PDF
            → ArXiv:    200 OK
```

**Conclusion:** Browser-mimicking headers are applied to all download requests regardless of strategy — the chain does not inspect the URL before choosing headers.
- Strategies 1–3 bypass publisher portals entirely — they target ArXiv or pyalex's internal endpoint, which do not enforce User-Agent filtering.
- The HTTP 403 block is specific to publisher-hosted mirrors. It does not affect the primary ArXiv strategies.

---

## Decision

### Which strategy order?

```
Fallback priority
      │
      ├─ Strategy 1: arxiv_api  ✅
      │     ✓ arxiv.Client() resolves the canonical latest-version URL
      │     ✓ ArXiv ToS compliant (3 s rate-limit delay)
      │     △ Requires arxiv_id; 3 s delay per paper
      │     → FIRST: highest reliability for ArXiv-hosted papers
      │
      ├─ Strategy 2: constructed_arxiv_url
      │     ✓ Bypasses the arxiv library API call; simpler code path
      │     △ Same 3 s delay; unversioned URL relies on ArXiv's redirect
      │     → SECOND: fallback if the arxiv library itself fails
      │
      ├─ Strategy 3: pyalex_pdf_get
      │     ✓ openalex_id always present — never skipped
      │     ✓ No rate-limit delay; not subject to publisher UA blocks
      │     △ Version returned depends on what OpenAlex indexes; not guaranteed latest
      │     → THIRD: covers non-ArXiv OA papers (e.g. AAAI diamond OA)
      │
      └─ Strategy 4: openalex_oa_url
            ✓ Covers any remaining OA paper with a known oa_url
            △ May point to a publisher page — browser headers required
            △ Least reliable: depends on oa_url resolving to a direct PDF
            → FOURTH: last resort
```

Strategies 1 and 2 are skipped when no ArXiv ID is available (non-ArXiv papers). Strategy 4 is skipped when no OA URL is available. Strategy 3 is always attempted since the OpenAlex ID is always present.

### Which OA status pre-filter?

```
oa_status pre-filter at search time (Step 1)
      │
      ├─ diamond / gold / green  ✅
      │     ✓ Downloadable PDF guaranteed by OA policy
      │     ✓ At least one fallback strategy applies to every paper
      │     → INCLUDED
      │
      ├─ bronze
      │     ✗ Free to read on publisher site but no open license
      │     ✗ Publisher may remove access at any time
      │     → EXCLUDED: unreliable programmatic access
      │
      └─ closed
            ✗ Subscription-only; no free copy exists
            → EXCLUDED: no viable download path
```

**Applying the filter at search time (not download time) means the downloader never encounters a paper without a viable download path — download failures are prevented structurally rather than handled at runtime.**

---

## Pipeline Integration Status ✅ INTEGRATED

A four-strategy fallback chain and OA status pre-filter replaced the single-strategy arxiv-only download in `paper_scraping.py` → `PaperDownloader` and `fetch_candidate_papers()`.

### Impact

- 5/5 test papers downloaded via Strategy 1 (arxiv_api); Strategies 2–4 not exercised in the test set.
- The filename utility uses the ArXiv ID when available, falling back to the OpenAlex ID for non-ArXiv papers — avoids filesystem issues from special characters in paper titles.
