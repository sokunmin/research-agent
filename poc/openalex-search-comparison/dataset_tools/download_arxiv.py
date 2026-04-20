#!/usr/bin/env python3
"""
download_arxiv.py
─────────────────
Download PDFs directly from ArXiv by ID, without touching OpenAlex.
Simultaneously builds candidate-groundtruth.json in the same schema as
groundtruth-final.json, populated from ArXiv metadata.

Metadata source:
  title, abstract  → ArXiv API (result.title, result.summary)
  keywords         → ArXiv categories (e.g. ["cs.CL", "cs.LG"])
  topics           → [] (OpenAlex-only; filled later if needed)
  primary_topic    → "" (OpenAlex-only; filled later if needed)
  concepts         → [] (OpenAlex-only; filled later if needed)
  id               → "arxiv:<arxiv_id>" (temporary; not an OpenAlex W-ID)

The output JSON is written incrementally after each paper so the file is
valid even if the script is interrupted. Already-processed IDs are skipped
on re-run, making the script safely resumable.

Usage:
    python download_arxiv.py --download 1706.03762 --download 2205.14135
    python download_arxiv.py --download 1706.03762 2205.14135 2304.01852
    python download_arxiv.py --download 1706.03762 --output-json /tmp/gt.json
"""

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import arxiv
import click
import requests

# ── Config ────────────────────────────────────────────────────────────────────

DOWNLOAD_DIR    = Path(__file__).parent / "downloads"
CANDIDATE_JSON  = Path(__file__).parent / "candidate-groundtruth.json"
ARXIV_DELAY     = 3    # seconds between ArXiv requests (rate-limit compliance)
REQUEST_TIMEOUT = 30   # seconds

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,*/*",
}

# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class ArxivMetadata:
    arxiv_id:      str
    title:         str
    abstract:      str
    keywords:      list[str]          # ArXiv categories used as proxy
    topics:        list[str] = field(default_factory=list)
    primary_topic: str       = ""
    concepts:      list[str] = field(default_factory=list)

    def to_groundtruth_entry(self) -> dict:
        return {
            "id":            f"arxiv_{self.arxiv_id}",
            "title":         self.title,
            "abstract":      self.abstract,
            "keywords":      self.keywords,
            "topics":        self.topics,
            "primary_topic": self.primary_topic,
            "concepts":      self.concepts,
            "relevant":      False,
            "reason":        "",
        }


@dataclass
class DownloadResult:
    arxiv_id: str
    success:  bool
    strategy: str
    path:     Optional[Path]         = None
    error:    Optional[str]          = None
    metadata: Optional[ArxivMetadata] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_filename(title: str, fallback: str) -> str:
    """Sanitise a paper title into a filesystem-safe filename (no extension)."""
    name = title[:80]
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.strip(". ")
    return name or fallback


def _get_pdf_via_requests(url: str, dest: Path) -> None:
    """Download a PDF via requests with browser headers. Raises on failure."""
    resp = requests.get(url, headers=_BROWSER_HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "")
    if "pdf" not in content_type and len(resp.content) < 1024:
        raise ValueError(f"Response does not look like a PDF (Content-Type: {content_type})")
    dest.write_bytes(resp.content)


# ── Download strategies ───────────────────────────────────────────────────────

def _try_arxiv_api(arxiv_id: str, output_dir: Path) -> DownloadResult:
    """Strategy 1: arxiv library → metadata + result.pdf_url → requests.

    Fetches full paper metadata (title, abstract, categories) from the ArXiv
    API, then downloads the PDF. Uses title for a human-readable filename.
    """
    try:
        client = arxiv.Client()
        result = next(client.results(arxiv.Search(id_list=[arxiv_id])))

        metadata = ArxivMetadata(
            arxiv_id=arxiv_id,
            title=result.title,
            abstract=result.summary.replace("\n", " ").strip(),
            keywords=list(result.categories) if result.categories else [],
        )

        filename = _safe_filename(result.title, fallback=arxiv_id) + ".pdf"
        dest = output_dir / filename
        time.sleep(ARXIV_DELAY)
        _get_pdf_via_requests(result.pdf_url, dest)
        return DownloadResult(arxiv_id=arxiv_id, success=True,
                              strategy="arxiv_api", path=dest, metadata=metadata)
    except StopIteration:
        return DownloadResult(arxiv_id=arxiv_id, success=False,
                              strategy="arxiv_api", error="ArXiv ID not found")
    except Exception as e:
        return DownloadResult(arxiv_id=arxiv_id, success=False,
                              strategy="arxiv_api", error=str(e))


def _try_constructed_url(arxiv_id: str, output_dir: Path) -> DownloadResult:
    """Strategy 2: construct https://arxiv.org/pdf/{arxiv_id} → requests.

    No metadata lookup — uses arxiv_id as filename. No metadata available.
    ArXiv redirects unversioned URLs to the latest version automatically.
    """
    try:
        url  = f"https://arxiv.org/pdf/{arxiv_id}"
        dest = output_dir / f"{arxiv_id}.pdf"
        time.sleep(ARXIV_DELAY)
        _get_pdf_via_requests(url, dest)
        return DownloadResult(arxiv_id=arxiv_id, success=True,
                              strategy="constructed_arxiv_url", path=dest)
    except Exception as e:
        return DownloadResult(arxiv_id=arxiv_id, success=False,
                              strategy="constructed_arxiv_url", error=str(e))


def download_arxiv_pdf(arxiv_id: str, output_dir: Path) -> list[DownloadResult]:
    """Try arxiv_api first, fall back to constructed URL. Returns all attempts."""
    r1 = _try_arxiv_api(arxiv_id, output_dir)
    if r1.success:
        return [r1]
    r2 = _try_constructed_url(arxiv_id, output_dir)
    return [r1, r2]


# ── Groundtruth JSON helpers ──────────────────────────────────────────────────

def _load_groundtruth(json_path: Path) -> tuple[list[dict], set[str]]:
    """Load existing candidate-groundtruth.json; return (entries, existing_ids)."""
    if not json_path.exists():
        return [], set()
    entries = json.loads(json_path.read_text(encoding="utf-8"))
    existing_ids = {e["id"] for e in entries}
    return entries, existing_ids


def _save_groundtruth(json_path: Path, entries: list[dict]) -> None:
    """Write entries to candidate-groundtruth.json (atomic overwrite)."""
    json_path.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

_SEP = "=" * 62


@click.command()
@click.option(
    "--download",
    "arxiv_ids",
    multiple=True,
    required=True,
    metavar="ARXIV_ID",
    help="ArXiv ID(s) to download. Repeat for multiple: --download ID1 --download ID2",
)
@click.option(
    "--output-dir",
    "output_dir",
    default=None,
    type=click.Path(path_type=Path),
    help=f"PDF destination directory (default: {DOWNLOAD_DIR})",
)
@click.option(
    "--output-json",
    "output_json",
    default=None,
    type=click.Path(path_type=Path),
    help=f"Groundtruth JSON path (default: {CANDIDATE_JSON})",
)
def main(
    arxiv_ids:   tuple[str, ...],
    output_dir:  Optional[Path],
    output_json: Optional[Path],
) -> None:
    dest_dir  = output_dir  or DOWNLOAD_DIR
    json_path = output_json or CANDIDATE_JSON
    dest_dir.mkdir(parents=True, exist_ok=True)

    entries, existing_ids = _load_groundtruth(json_path)

    print(_SEP)
    print("ArXiv PDF Downloader + Groundtruth Builder")
    print(_SEP)
    print(f"  IDs to process  : {len(arxiv_ids)}")
    print(f"  Already in JSON : {len(existing_ids)}")
    print(f"  PDF output dir  : {dest_dir}")
    print(f"  Groundtruth JSON: {json_path}")
    print()

    succeeded, failed, skipped = 0, 0, 0

    for i, arxiv_id in enumerate(arxiv_ids, 1):
        temp_id = f"arxiv_{arxiv_id}"
        print(f"[{i}/{len(arxiv_ids)}] {arxiv_id}")
        if temp_id in existing_ids:
            print(f"  ⊘ already in groundtruth, skipping")
            skipped += 1
            continue

        results = download_arxiv_pdf(arxiv_id, dest_dir)
        final   = results[-1]

        for r in results:
            if r.success:
                print(f"  ✓ [{r.strategy}] → {r.path}")
            else:
                print(f"  ✗ [{r.strategy}] {r.error}")

        if final.success:
            succeeded += 1
            # Use metadata from strategy 1 if available; minimal fallback otherwise
            meta = next((r.metadata for r in results if r.metadata), None)
            if meta:
                entry = meta.to_groundtruth_entry()
                print(f"  ✎ metadata captured: {entry['title'][:60]}")
            else:
                entry = ArxivMetadata(
                    arxiv_id=arxiv_id, title=arxiv_id,
                    abstract="", keywords=[]
                ).to_groundtruth_entry()
                print(f"  ⚠ no metadata (strategy 1 failed); using arxiv_id as title")

            entries.append(entry)
            existing_ids.add(temp_id)
            _save_groundtruth(json_path, entries)  # incremental write
        else:
            failed += 1

    print()
    print(_SEP)
    print(f"  Downloaded  : {succeeded}")
    print(f"  Failed      : {failed}")
    print(f"  Skipped     : {skipped}")
    print(f"  Total in JSON: {len(entries)}")
    print(_SEP)


if __name__ == "__main__":
    main()
