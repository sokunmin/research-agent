"""
extract-id.py
─────────────
Validate OpenAlex ID extraction and PDF download with fallback chain.

Search strategy
  search(QUERY) + is_oa=True + cited_by_count > CITED_THRESHOLD
  Post-filter to OA status ∈ {diamond, gold, green}

Key finding this script verifies
  ArXiv ID is NOT in work["ids"] — it must be parsed from
  work["locations"][*]["landing_page_url"].

Download fallback chain (tried in order until one succeeds)
  1. ArXiv API     — arxiv.Client() → result.pdf_url → requests.get()
                     (download_pdf() is deprecated upstream; use pdf_url directly)
                     3-second delay before each request (ArXiv rate-limit policy)
  2. Constructed   — https://arxiv.org/pdf/{arxiv_id} → requests.get()
                     same 3-second delay as arxiv_api
  3. pyalex        — Works()[openalex_id].pdf.get()
  4. OpenAlex URL  — work["open_access"]["oa_url"] → requests.get()
"""

import re
import sys
import time
from pydantic import BaseModel
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional

import arxiv
import click
import pyalex
import requests
from dotenv import dotenv_values
from pyalex import Works

# ── Config ────────────────────────────────────────────────────────────────────

_ENV = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
pyalex.config.api_key = _ENV.get("OPENALEX_API_KEY", "")
if email := _ENV.get("OPENALEX_EMAIL", ""):
    pyalex.config.email = email
pyalex.config.max_retries = 5
pyalex.config.retry_backoff_factor = 0.5

QUERY              = "attention mechanism in transformer models"
TARGET_OA_STATUSES = {"diamond", "gold", "green"}
CITED_THRESHOLD    = 10    # minimum cited_by_count for broad search results
PER_PAGE           = 15
YEAR_WINDOW        = 3     # default: current_year - 3
DOWNLOAD_DIR       = Path(__file__).parent / "downloads"
REQUEST_TIMEOUT    = 30   # seconds

ARXIV_DELAY        = 3    # seconds between ArXiv requests (arxiv_api + constructed)
MIN_QUOTA_REMAINING = 10  # minimum credits remaining before refusing to run

# AAAI OJS (and other academic publishers) return 403 when they detect
# "python-requests/x.x.x" as the User-Agent.  A browser UA unblocks them.
# Verified: curl with python-requests UA → 403; with browser UA → 200.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}

# When non-empty, main() searches these titles instead of using search(QUERY).
# Each title is looked up via search_filter(title=) → top-1 result.
PAPER_TITLES: list[str] = [
    "Attention Is All You Need",
    "Informer: Beyond Efficient Transformer for Long Sequence Time-Series Forecasting",
    "TransUNet: Transformers Make Strong Encoders for Medical Image Segmentation",
    "Are Transformers Effective for Time Series Forecasting",
    "Longformer: The Long-Document Transformer",
]


# ── Data models ───────────────────────────────────────────────────────────────

class PaperIDs(BaseModel):
    """All IDs and OA metadata extractable from a single OpenAlex Work dict."""
    openalex_id:   str
    title:         str
    oa_status:     str
    cited_count:   int
    doi:           Optional[str] = None   # e.g. "10.18653/v1/2020.acl-main.703"
    arxiv_id:      Optional[str] = None   # e.g. "1706.03762"
    arxiv_pdf_url: Optional[str] = None   # e.g. "https://arxiv.org/pdf/1706.03762"
    oa_url:        Optional[str] = None   # open_access.oa_url from OpenAlex


class DownloadResult(BaseModel):
    """Outcome of a single download attempt."""
    success:  bool
    strategy: str             # label of the strategy that was tried
    path:     Optional[Path] = None
    error:    Optional[str]  = None


# ── Extractors ────────────────────────────────────────────────────────────────

def extract_openalex_id(work: dict) -> str:
    """Return bare OpenAlex ID, stripping the URL prefix.

    'https://openalex.org/W2741809807' → 'W2741809807'
    """
    return work.get("id", "").replace("https://openalex.org/", "")


def extract_doi(work: dict) -> Optional[str]:
    """Return bare DOI, or None if absent.

    Checks both work['ids']['doi'] and work['doi'] (top-level alias).
    'https://doi.org/10.18653/v1/2020.acl-main.703' → '10.18653/v1/2020.acl-main.703'
    """
    raw = (work.get("ids") or {}).get("doi") or work.get("doi")
    if not raw:
        return None
    return raw.replace("https://doi.org/", "")


def extract_arxiv(work: dict) -> tuple[Optional[str], Optional[str]]:
    """Scan work['locations'] for an arxiv.org entry.

    Returns (arxiv_id, pdf_url) — both are Optional.

    Why locations, not work['ids']?
    OpenAlex does not include ArXiv in the ids object.  The only reliable
    source is the locations list, where arxiv.org appears as landing_page_url.

    Version stripping:
    OpenAlex locations may carry versioned URLs (e.g. arxiv.org/abs/1706.03762v5
    or arxiv.org/pdf/1706.03762v5).  We always strip the version suffix so that
    the pdf_url points to the unversioned endpoint, which ArXiv redirects to the
    latest version automatically.

    pdf_url is always constructed from the unversioned arxiv_id.
    loc["pdf_url"] is intentionally ignored because it may be pinned to an
    older version (e.g. "...v5" while v7 is the latest).

    Example:
        landing_page_url = 'https://arxiv.org/abs/1706.03762v5'
        → raw segment    = '1706.03762v5'
        → arxiv_id       = '1706.03762'          (version stripped)
        → pdf_url        = 'https://arxiv.org/pdf/1706.03762'  (latest)
    """
    for loc in work.get("locations", []):
        landing = loc.get("landing_page_url") or ""
        if "arxiv.org" in landing:
            raw      = landing.rstrip("/").split("/")[-1]
            arxiv_id = re.sub(r"v\d+$", "", raw)   # strip version suffix
            pdf_url  = f"https://arxiv.org/pdf/{arxiv_id}"   # always unversioned
            return arxiv_id, pdf_url
    return None, None


def extract_oa_status(work: dict) -> str:
    return (work.get("open_access") or {}).get("oa_status", "unknown")


def extract_oa_url(work: dict) -> Optional[str]:
    """Return open_access.oa_url — OpenAlex's best known OA landing/PDF URL."""
    return (work.get("open_access") or {}).get("oa_url")


def work_to_paper_ids(work: dict) -> PaperIDs:
    """Convert a raw OpenAlex Work dict into a PaperIDs model."""
    arxiv_id, arxiv_pdf_url = extract_arxiv(work)
    return PaperIDs(
        openalex_id   = extract_openalex_id(work),
        title         = work.get("display_name") or work.get("title") or "(no title)",
        oa_status     = extract_oa_status(work),
        cited_count   = work.get("cited_by_count", 0),
        doi           = extract_doi(work),
        arxiv_id      = arxiv_id,
        arxiv_pdf_url = arxiv_pdf_url,
        oa_url        = extract_oa_url(work),
    )


# ── Download helpers ──────────────────────────────────────────────────────────

def _safe_filename(title: str, fallback: str) -> str:
    """Sanitise a paper title into a filesystem-safe filename (no extension)."""
    name = title[:80]                          # cap length
    name = re.sub(r'[\\/*?:"<>|]', "_", name) # replace illegal chars
    name = name.strip(". ")                    # strip leading/trailing dots & spaces
    return name or fallback


def _write_bytes(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def _get_pdf_via_requests(url: str, dest: Path) -> None:
    """Download a PDF from url and write to dest. Raises on any failure.

    Sends browser-like headers to avoid 403 blocks from publishers such as
    AAAI OJS that specifically reject the default "python-requests" User-Agent.
    """
    resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    if "pdf" not in content_type and len(resp.content) < 1024:
        raise ValueError(f"Response does not look like a PDF (Content-Type: {content_type})")
    _write_bytes(dest, resp.content)


# ── Download strategies ───────────────────────────────────────────────────────

def _strategy_arxiv_api(paper: PaperIDs, dest: Path) -> DownloadResult:
    """Strategy 1: arxiv Python library → result.pdf_url → requests.get().

    Uses the official arxiv library to look up the paper and get its canonical
    pdf_url.  download_pdf() is deprecated upstream; we call requests.get()
    on result.pdf_url directly for future-proofing.

    Requires: paper.arxiv_id
    """
    label = "arxiv_api"
    if not paper.arxiv_id:
        return DownloadResult(success=False, strategy=label, error="No ArXiv ID")
    try:
        client  = arxiv.Client()
        search  = arxiv.Search(id_list=[paper.arxiv_id])
        result  = next(client.results(search))
        time.sleep(ARXIV_DELAY)
        _get_pdf_via_requests(result.pdf_url, dest)
        return DownloadResult(success=True, strategy=label, path=dest)
    except StopIteration:
        return DownloadResult(success=False, strategy=label, error="ArXiv ID not found")
    except Exception as e:
        return DownloadResult(success=False, strategy=label, error=str(e))


def _strategy_openalex_url(paper: PaperIDs, dest: Path) -> DownloadResult:
    """Strategy 2: OpenAlex open_access.oa_url → requests.get().

    OpenAlex stores its best-known OA URL in work["open_access"]["oa_url"].
    This may point to an institutional repository, publisher page, or arxiv.

    Requires: paper.oa_url
    """
    label = "openalex_url"
    if not paper.oa_url:
        return DownloadResult(success=False, strategy=label, error="No oa_url in OpenAlex")
    try:
        _get_pdf_via_requests(paper.oa_url, dest)
        return DownloadResult(success=True, strategy=label, path=dest)
    except Exception as e:
        return DownloadResult(success=False, strategy=label, error=str(e))


def _strategy_pyalex_pdf_get(paper: PaperIDs, dest: Path) -> DownloadResult:
    """Strategy 3: pyalex Works()[openalex_id].pdf.get().

    pyalex resolves the PDF via OpenAlex's internal content endpoint.
    Returns bytes or None.

    Requires: paper.openalex_id
    """
    label = "pyalex_pdf_get"
    try:
        single  = Works()[paper.openalex_id]
        content = single.pdf.get()
        if not content:
            return DownloadResult(success=False, strategy=label, error="pdf.get() returned None")
        _write_bytes(dest, content if isinstance(content, bytes) else content.encode())
        return DownloadResult(success=True, strategy=label, path=dest)
    except Exception as e:
        return DownloadResult(success=False, strategy=label, error=str(e))


def _strategy_constructed_arxiv_url(paper: PaperIDs, dest: Path) -> DownloadResult:
    """Strategy 4: construct https://arxiv.org/pdf/{arxiv_id} → requests.get().

    Last resort when no other source works.  The ArXiv PDF URL pattern is
    stable and public, but this bypasses the ArXiv API rate-limit handling
    that the arxiv library provides.

    Requires: paper.arxiv_id
    """
    label = "constructed_arxiv_url"
    if not paper.arxiv_id:
        return DownloadResult(success=False, strategy=label, error="No ArXiv ID")
    try:
        url = f"https://arxiv.org/pdf/{paper.arxiv_id}"
        time.sleep(ARXIV_DELAY)
        _get_pdf_via_requests(url, dest)
        return DownloadResult(success=True, strategy=label, path=dest)
    except Exception as e:
        return DownloadResult(success=False, strategy=label, error=str(e))


# Strategy registry — order defines fallback priority
_DOWNLOAD_STRATEGIES: list[Callable[[PaperIDs, Path], DownloadResult]] = [
    _strategy_arxiv_api,
    _strategy_constructed_arxiv_url,
    _strategy_pyalex_pdf_get,
    _strategy_openalex_url,
]


def download_pdf_with_fallback(
    paper: PaperIDs,
    output_dir: Path = DOWNLOAD_DIR,
) -> list[DownloadResult]:
    """Try each download strategy in priority order until one succeeds.

    Returns all attempted DownloadResult objects so the caller can inspect
    which strategies were tried, which failed, and which finally succeeded.
    The successful result (if any) is the last item with result.success=True.
    """
    filename = _safe_filename(paper.title, fallback=paper.openalex_id) + ".pdf"
    dest     = output_dir / filename
    results: list[DownloadResult] = []

    for strategy_fn in _DOWNLOAD_STRATEGIES:
        result = strategy_fn(paper, dest)
        results.append(result)
        if result.success:
            break   # stop on first success

    return results


# ── Search ────────────────────────────────────────────────────────────────────

def check_quota() -> dict:
    resp = requests.get(
        "https://api.openalex.org/works?per_page=1",
        headers={"Authorization": f"Bearer {pyalex.config.api_key}"},
        timeout=10,
    )
    result = {k: v for k, v in resp.headers.items() if "ratelimit" in k.lower()}
    result["_status_code"] = resp.status_code
    return result


def print_quota(quota: dict) -> None:
    """Display ratelimit headers, converting time values to human-readable form.

    X-RateLimit-Reset is seconds-until-reset (a duration), not a Unix timestamp.
    """
    status = quota.get("_status_code", "?")
    print(f"Quota check (status={status}):")
    now = datetime.now(tz=timezone.utc)
    for key, value in quota.items():
        if key == "_status_code":
            continue
        if key.lower() == "x-ratelimit-reset":
            try:
                seconds_until_reset = int(value)
                reset_at = (now + timedelta(seconds=seconds_until_reset)).astimezone()
                hours   = seconds_until_reset / 3600
                print(f"  {key:<30}: {value}s  →  {reset_at.strftime('%Y-%m-%d %H:%M:%S')}  (resets in {hours:.1f}h)")
                continue
            except (ValueError, TypeError):
                pass
        print(f"  {key:<30}: {value}")


def check_and_assert_quota() -> dict:
    """Check OpenAlex quota and abort if remaining credits are below the minimum."""
    quota = check_quota()
    print_quota(quota)
    # Case-insensitive lookup for x-ratelimit-remaining
    remaining_str = next(
        (v for k, v in quota.items() if k.lower() == "x-ratelimit-remaining"),
        None,
    )
    if remaining_str is not None:
        try:
            remaining = int(remaining_str)
            if remaining < MIN_QUOTA_REMAINING:
                print(f"\nERROR: OpenAlex quota too low ({remaining} remaining, minimum is {MIN_QUOTA_REMAINING}). Aborting.")
                sys.exit(1)
        except (ValueError, TypeError):
            pass
    return quota


def fetch_works(
    query: str,
    cited_threshold: int = CITED_THRESHOLD,
    per_page: int = PER_PAGE,
    year_window: int = YEAR_WINDOW,
    search_filter: str = "full_text",
) -> list[dict]:
    """Fetch works via search(), filtered by OA status and citation count.

    Uses keyword search sorted by cited_by_count desc at the API level,
    so the top results are guaranteed to be the most-cited matching papers.

    Parameters
    ----------
    query:
        Keyword query passed to the OpenAlex search endpoint.
    cited_threshold:
        Minimum cited_by_count; applied as an API-level filter.
    per_page:
        Number of results to fetch (max 200).
    year_window:
        When > 0, restricts results to publication_year > (current_year - year_window).
        Set to 0 to disable the year filter.
    search_filter:
        Field restriction for the search.  One of:
          "full_text"      — search across all indexed fields (default)
          "title_abstract" — restrict to title and abstract fields
          "title_only"     — restrict to the title field only

    OA status sub-filter (diamond/gold/green) is applied separately in
    filter_by_oa_status() to avoid relying on undocumented nested OR syntax.
    """
    filter_kwargs: dict = {"is_oa": True, "cited_by_count": f">{cited_threshold}"}
    if year_window > 0:
        year_floor = date.today().year - year_window
        filter_kwargs["publication_year"] = f">{year_floor}"

    if search_filter == "title_abstract":
        base_query = Works().search_filter(title_and_abstract=query)
    elif search_filter == "title_only":
        base_query = Works().search_filter(title=query)
    else:  # full_text (default)
        base_query = Works().search(query)

    return (
        base_query
        .filter(**filter_kwargs)
        .sort(cited_by_count="desc")
        .get(per_page=per_page)
    )


def fetch_work_by_title(title: str) -> Optional[dict]:
    """Look up a paper by title using search_filter(title=).

    Fetches up to 3 candidates and returns the first one that has an ArXiv
    location.  Falls back to the top-1 result if none have ArXiv.

    Why 3 candidates?
    Some papers exist as two separate OpenAlex records that were not merged:
    one for the publisher version (e.g. AAAI) and one for the ArXiv preprint.
    The publisher version typically ranks first (higher cited_by_count), but
    its locations list contains no arxiv.org entry.  The preprint record,
    ranked lower, holds the ArXiv location we need.

    Example — Informer:
      #1 W3177318507  DOI: 10.1609/aaai.v35i12.17325  locations: [AAAI only]
      #2 W3111507638  DOI: 10.48550/arxiv.2012.07436  locations: [arxiv.org ✓]
    """
    results = Works().search_filter(title=title).get(per_page=3)
    if not results:
        return None

    # Prefer a record that already has an ArXiv location
    for work in results:
        for loc in work.get("locations", []):
            if "arxiv.org" in (loc.get("landing_page_url") or ""):
                return work

    # No ArXiv location in any candidate — return the top-1 (highest relevance)
    return results[0]


def fetch_works_by_titles(titles: list[str]) -> list[tuple[str, Optional[dict]]]:
    """Look up each title in sequence.

    Returns list of (requested_title, work_or_None) so the caller always
    knows which titles failed to match.
    """
    found = []
    for title in titles:
        work = fetch_work_by_title(title)
        found.append((title, work))
        status = f"✓ {work.get('display_name', '')[:60]}" if work else "✗ not found"
        print(f"      {status}")
    return found


def filter_by_oa_status(works: list[dict], statuses: set[str]) -> list[dict]:
    """Keep only works whose oa_status is in the target set."""
    return [w for w in works if extract_oa_status(w) in statuses]


# ── Display ───────────────────────────────────────────────────────────────────

_SEP = "=" * 62


def _check(value: Optional[str]) -> str:
    return "✓" if value else "✗"


def print_paper(index: int, paper: PaperIDs) -> None:
    arxiv_display = (
        f"{paper.arxiv_id}  ({paper.arxiv_pdf_url})"
        if paper.arxiv_id else "—"
    )
    print(f"\n#{index:02d} [{paper.oa_status:<8}] cited:{paper.cited_count:>6}")
    print(f"     Title      : {paper.title}")
    print(f"     OpenAlex   : {_check(paper.openalex_id)} {paper.openalex_id}")
    print(f"     DOI        : {_check(paper.doi)} {paper.doi or '—'}")
    print(f"     ArXiv ID   : {_check(paper.arxiv_id)} {arxiv_display}")
    print(f"     OA URL     : {_check(paper.oa_url)} {paper.oa_url or '—'}")


def print_download_result(results: list[DownloadResult]) -> None:
    for r in results:
        if r.success:
            print(f"     Download   : ✓ [{r.strategy}] → {r.path}")
        else:
            print(f"     Download   : ✗ [{r.strategy}] {r.error}")


def _reconstruct_abstract(work: dict) -> str:
    """Rebuild abstract from OpenAlex abstract_inverted_index.

    OpenAlex stores abstracts as an inverted index {word: [pos, ...]} rather
    than plain text.  Reconstruct by reversing to {pos: word}, sorting, and
    joining.  Returns "" when the index is absent or empty.
    """
    inv = work.get("abstract_inverted_index") or {}
    if not inv:
        return ""
    pos_word: dict[int, str] = {}
    for word, positions in inv.items():
        for pos in positions:
            pos_word[pos] = word
    return " ".join(pos_word[i] for i in sorted(pos_word))


def print_verbose_fields(work: dict) -> None:
    """Print extra metadata fields from a raw OpenAlex Work dict."""
    abstract     = _reconstruct_abstract(work) or "—"
    keywords     = [k.get("display_name", "") for k in (work.get("keywords") or [])]
    topics       = [t.get("display_name", "") for t in (work.get("topics") or [])]
    primary      = (work.get("primary_topic") or {}).get("display_name") or "—"
    concepts     = [c.get("display_name", "") for c in (work.get("concepts") or [])]

    print(f"     Abstract   : {abstract}")
    print(f"     Keywords   : {keywords}")
    print(f"     Topics     : {topics}")
    print(f"     PrimaryTopic: {primary}")
    print(f"     Concepts   : {concepts}")


def run_and_display(
    papers: list[PaperIDs],
    do_download: bool,
    raw_works: list[dict] | None = None,
    verbose: bool = False,
) -> None:
    """Print ID extraction results and optionally download PDFs for each paper."""
    print(f"\n{_SEP}")
    print("RESULTS")
    print(_SEP)
    works_iter = raw_works if (verbose and raw_works) else [None] * len(papers)
    for i, (paper, work) in enumerate(zip(papers, works_iter), 1):
        print_paper(i, paper)
        if verbose and work:
            print_verbose_fields(work)
        if do_download:
            dl_results = download_pdf_with_fallback(paper)
            print_download_result(dl_results)


def print_summary(papers: list[PaperIDs]) -> None:
    n = len(papers)
    if not n:
        print("\n  (no papers to summarise)")
        return

    has_doi    = sum(1 for p in papers if p.doi)
    has_arxiv  = sum(1 for p in papers if p.arxiv_id)
    has_oa_url = sum(1 for p in papers if p.oa_url)
    oa_dist: dict[str, int] = {}
    for p in papers:
        oa_dist[p.oa_status] = oa_dist.get(p.oa_status, 0) + 1

    print(f"\n{_SEP}")
    print("SUMMARY")
    print(_SEP)
    print(f"  Total papers     : {n}")
    print(f"  Has OpenAlex ID  : {n}/{n} = 100%")
    print(f"  Has DOI          : {has_doi}/{n} = {has_doi / n * 100:.0f}%")
    print(f"  Has ArXiv ID     : {has_arxiv}/{n} = {has_arxiv / n * 100:.0f}%")
    print(f"  Has OA URL       : {has_oa_url}/{n} = {has_oa_url / n * 100:.0f}%")
    print(f"  OA status dist   : {oa_dist}")


# ── Entry point ───────────────────────────────────────────────────────────────

@click.command()
@click.option(
    "--broad-search",
    "broad_search",
    default=None,
    metavar="TEXT",
    help=(
        "Run broad search with this query. "
        "If omitted, falls back to title-lookup mode (PAPER_TITLES list)."
    ),
)
@click.option(
    "--filter",
    "search_filter",
    type=click.Choice(["full_text", "title_abstract", "title_only"], case_sensitive=False),
    default="full_text",
    show_default=True,
    help=(
        "Field restriction for broad search. "
        "'full_text' searches all indexed fields (default). "
        "'title_abstract' restricts to title and abstract fields. "
        "'title_only' restricts to the title field only."
    ),
)
@click.option(
    "--cited-threshold",
    "cited_threshold",
    default=CITED_THRESHOLD,
    type=int,
    show_default=True,
    metavar="N",
    help="Minimum cited_by_count to keep a result (broad search mode only).",
)
@click.option(
    "--year-window",
    "year_window",
    default=YEAR_WINDOW,
    type=int,
    show_default=True,
    metavar="N",
    help="Only include papers from the last N years (publication_year > current_year - N). Set 0 to disable.",
)
@click.option(
    "--per-page",
    "per_page",
    default=PER_PAGE,
    type=int,
    show_default=True,
    metavar="N",
    help="Number of results to fetch from OpenAlex per request (max 200).",
)
@click.option(
    "--download",
    "do_download",
    is_flag=True,
    default=False,
    help="Download PDFs via fallback chain. If omitted, only print ID extraction results.",
)
@click.option(
    "--verbose",
    "verbose",
    is_flag=True,
    default=False,
    help="Print extra metadata for each paper: abstract, keywords, topics, primary_topic, concepts.",
)
def main(
    broad_search: Optional[str],
    search_filter: str,
    cited_threshold: int,
    year_window: int,
    per_page: int,
    do_download: bool,
    verbose: bool,
) -> None:
    print(_SEP)
    print("OpenAlex ID Extraction + Download Fallback — Validation Script")
    print(_SEP)
    print(f"  Output dir : {DOWNLOAD_DIR}")
    print(f"  Download   : {'enabled' if do_download else 'disabled (pass --download to enable)'}")

    if do_download:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    print("\n[0/N] Checking OpenAlex quota...")
    check_and_assert_quota()

    # ── Mode: specific titles ─────────────────────────────────────────────────
    if broad_search is None and PAPER_TITLES:
        total_steps = 4 if do_download else 3
        print(f"  Mode       : title lookup ({len(PAPER_TITLES)} papers)")
        print(_SEP)

        print(f"\n[1/{total_steps}] Looking up {len(PAPER_TITLES)} papers by title...")
        title_results = fetch_works_by_titles(PAPER_TITLES)

        matched_works = [(t, w) for t, w in title_results if w is not None]
        not_found     = [t     for t, w in title_results if w is None]
        print(f"      → {len(matched_works)} matched, {len(not_found)} not found")

        print(f"\n[2/{total_steps}] Extracting IDs...")
        papers = [work_to_paper_ids(w) for _, w in matched_works]

        if do_download:
            print(f"\n[3/{total_steps}] Downloading PDFs (fallback chain)...")

        print(f"\n[{3 + int(do_download)}/{total_steps}] Displaying results...")
        raw_works = [w for _, w in matched_works]
        run_and_display(papers, do_download, raw_works=raw_works, verbose=verbose)

        if not_found:
            print(f"\n  Not found in OpenAlex:")
            for t in not_found:
                print(f"    ✗ {t}")

    # ── Mode: broad search ────────────────────────────────────────────────────
    else:
        total_steps = 6 if do_download else 5
        query      = broad_search if broad_search is not None else QUERY
        year_floor = date.today().year - year_window
        year_info  = f"year>{year_floor}" if year_window > 0 else "no year filter"
        print(f"  Mode       : broad search")
        print(f"  Query      : {query}")
        print(f"  Method     : search() + is_oa=True + {year_info} + cited_by_count > {cited_threshold} + sort desc [API sort]")
        print(f"  Filter     : {search_filter}")
        print(f"  OA filter  : {sorted(TARGET_OA_STATUSES)}")
        print(f"  per_page   : {per_page}")
        print(_SEP)

        print(f"\n[1/{total_steps}] Fetching from OpenAlex...")
        raw_works = fetch_works(
            query,
            cited_threshold=cited_threshold,
            year_window=year_window,
            per_page=per_page,
            search_filter=search_filter,
        )
        print(f"      → {len(raw_works)} works returned")

        print(f"\n[2/{total_steps}] Filtering by OA status {sorted(TARGET_OA_STATUSES)}...")
        filtered_works = filter_by_oa_status(raw_works, TARGET_OA_STATUSES)
        print(f"      → {len(filtered_works)} works kept")

        print(f"\n[3/{total_steps}] Extracting IDs...")
        papers = [work_to_paper_ids(w) for w in filtered_works]

        if do_download:
            print(f"\n[4/{total_steps}] Downloading PDFs (fallback chain)...")

        print(f"\n[{4 + int(do_download)}/{total_steps}] Displaying results...")
        run_and_display(papers, do_download, raw_works=filtered_works, verbose=verbose)

    print_summary(papers)


if __name__ == "__main__":
    main()
