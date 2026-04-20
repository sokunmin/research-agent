# Reliable PDF Acquisition via Multi-Strategy Fallback Chains

## Summary
*   **Problem:** Even papers identified as Open Access (OA) are often difficult to retrieve programmatically. Native Python scripts frequently encounter HTTP 403 Forbidden errors when accessing publisher-hosted mirrors, and ArXiv identifiers are often missing from standard metadata fields.
*   **Solution:** Implementation of a **4-strategy fallback chain** combined with a **Browser-mimicking User-Agent**. The discovery pipeline enforces a strict **Quality Filter** (only `diamond`, `gold`, or `green` OA statuses) to ensure downloadability, while the downloader handles the technical retrieval.
*   **Result:** Achieved a **100% download success rate (5/5)** for validated papers. The system successfully bypassed automated scraper blocks and resolved ArXiv IDs from non-standard location metadata.

---

## Transparency & Traceability
*   **Test Script:** `experiments/01-openalex-paper-discovery/pdf_download_fallback.py`
*   **Raw Data:** Terminal logs validating 5 target papers with verified OA statuses.
*   **Hardware:** MacBook M1 / Local Environment.

---

## Task Context
This component bridges the gap between **Metadata Discovery** and **Content Summarization**. By ensuring that 100% of relevant, open-access papers are successfully converted into local PDF files, it provides a stable data foundation for the subsequent VLM (Vision Language Model) analysis.

---

## Strategy & Parameter Definitions

### 1. Download Quality Gate (Pre-Filter)
To avoid broken links and paywalls, the pipeline only accepts papers with the following OpenAlex `oa_status`:
*   **Diamond/Gold**: Published in open-access journals.
*   **Green**: Available via reliable repositories (e.g., ArXiv).
*   *Note: Other statuses (e.g., Bronze/Closed) are excluded as they do not guarantee stable programmatic access.*

### 2. Retrieval Strategies
Four paths are tried in sequence:
1.  **arxiv_api**: Resolves the canonical latest version via the `arxiv` library.
2.  **constructed_arxiv_url**: Direct `https://arxiv.org/pdf/{id}` fallback.
3.  **pyalex_pdf_get**: Retrieval via the `pyalex` internal content endpoint.
4.  **openalex_url**: Direct fetch from the metadata `oa_url`.

---

## Experimental Results

### 1. Bypassing Bot-Detection (User-Agent Validation)
Tests were conducted to see if "Guaranteed Downloadable" papers were still reachable by basic scripts.

| Request Method | Observation | Result |
| :--- | :--- | :--- |
| Standard `requests` | Blocked by publisher security (e.g., OJS-based portals) | 403 Forbidden |
| **`requests` + Browser UA** | **Successfully bypassed block and retrieved full PDF** | **200 OK** |

### 2. Handling Metadata Fragmentation
A critical discovery showed that ArXiv IDs are **absent** from OpenAlex's `work["ids"]` object. They must be parsed from the `landing_page_url` within the `locations` array.

| Target Paper | ArXiv ID Source | Extraction Strategy |
| :--- | :--- | :--- |
| Attention Is All You Need | `locations[].landing_page_url` | Regex Version-Stripping |
| Informer | `locations[].landing_page_url` | Regex Version-Stripping |

### 3. End-to-End Download Success
| # | Paper Title | Open Access Status | Strategy Used | Result |
| :--- | :--- | :--- | :--- | :--- |
| 1 | Attention Is All You Need | gold | arxiv_api | ✓ Success |
| 2 | Informer: Beyond Efficient Transformer... | green | arxiv_api | ✓ Success |
| 3 | TransUNet: Transformers Make Strong... | green | arxiv_api | ✓ Success |
| 4 | Are Transformers Effective... | green | arxiv_api | ✓ Success |
| 5 | Longformer: The Long-Document Transformer | green | arxiv_api | ✓ Success |

---

## Observations

1.  **Strict OA Filtering:** By limiting the pipeline to `diamond/gold/green`, the system avoids "other" OA types (like Bronze) that often lead to intermittent failures.
2.  **Version Stripping Necessity:** Removing version suffixes (e.g., `v5`) from extracted IDs ensures the system always retrieves the **latest corrected version** from ArXiv.
3.  **Header Resilience:** The inclusion of a Browser User-Agent is not just an optimization but a requirement for papers hosted outside of ArXiv's main servers.

---

## Pipeline Integration Status [INTEGRATED]

The 4-strategy fallback logic and ArXiv ID surgery are fully integrated into the `PaperDownloader` class:
*   **Source:** `backend/agent_workflows/paper_scraping.py`
*   **Enforcement:** The `fetch_candidate_papers` function applies the `oa_status` filter before any download attempt is made.
