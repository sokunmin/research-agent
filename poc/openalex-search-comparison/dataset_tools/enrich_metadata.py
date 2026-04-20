#!/usr/bin/env python3
"""
Enrich ArXiv paper metadata in groundtruth JSON files by looking up OpenAlex.

Papers with id starting with `arxiv_` are enriched; papers with `W` IDs are skipped.
"""

import json
import time
import sys
from pathlib import Path
from typing import Optional

import click
from dotenv import dotenv_values
import pyalex
from pyalex import Works

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_ENV_PATH = Path("/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/.env")
_DEFAULT_SOURCE = Path(__file__).parent / "groundtruth-balanced.json"
_DEFAULT_FINAL = Path(__file__).parent / "groundtruth-final.json"

_ENV = dotenv_values(str(_ENV_PATH))
pyalex.config.api_key = _ENV.get("OPENALEX_API_KEY", "")
pyalex.config.email = _ENV.get("OPENALEX_EMAIL", "")
pyalex.config.max_retries = 3
pyalex.config.retry_backoff_factor = 0.5

API_SLEEP = 0.5  # seconds between API calls


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def reconstruct_abstract(work: dict) -> str:
    inv = work.get("abstract_inverted_index") or {}
    if not inv:
        return ""
    pos_word: dict[int, str] = {}
    for word, positions in inv.items():
        for pos in positions:
            pos_word[pos] = word
    return " ".join(pos_word[i] for i in sorted(pos_word))


def lookup_openalex(arxiv_id: str) -> Optional[dict]:
    """
    Look up a paper in OpenAlex by ArXiv ID.

    Strategy:
      1. Primary: fetch by ArXiv DOI (https://doi.org/10.48550/arxiv.<id>)
         This is the canonical DOI assigned by arXiv and is indexed by OpenAlex.
      2. Fallback: filter by DOI via Works().filter(doi=...) in case direct fetch fails.

    Returns the work dict with the highest cited_by_count (among any results), or None.
    """
    arxiv_doi = f"https://doi.org/10.48550/arxiv.{arxiv_id}"

    # Strategy 1: direct object fetch by DOI
    try:
        work = Works()[arxiv_doi]
        if work and work.get("id"):
            return work
    except Exception:
        pass  # fall through to strategy 2

    # Strategy 2: filter by DOI
    try:
        results = Works().filter(doi=arxiv_doi).get()
        if results:
            return max(results, key=lambda w: w.get("cited_by_count") or 0)
    except Exception as exc:
        click.echo(f"  [API error for {arxiv_id}]: {exc}", err=True)

    return None


def enrich_entry(entry: dict, work: dict) -> dict:
    """
    Pure function: return a new entry dict with OpenAlex metadata applied.
    Does NOT modify `relevant` or `reason`.
    """
    updated = dict(entry)

    # Replace id with OpenAlex ID
    oa_id = work.get("id", "")
    if oa_id:
        # OpenAlex IDs come as full URLs like https://openalex.org/W1234567890
        short_id = oa_id.split("/")[-1] if "/" in oa_id else oa_id
        updated["id"] = short_id

    # Keywords
    updated["keywords"] = [k["display_name"] for k in (work.get("keywords") or [])]

    # Topics
    updated["topics"] = [t["display_name"] for t in (work.get("topics") or [])]

    # Primary topic
    updated["primary_topic"] = (work.get("primary_topic") or {}).get("display_name") or ""

    # Concepts
    updated["concepts"] = [c["display_name"] for c in (work.get("concepts") or [])]

    # Abstract — only update if current entry has empty abstract
    if not entry.get("abstract"):
        reconstructed = reconstruct_abstract(work)
        if reconstructed:
            updated["abstract"] = reconstructed

    return updated


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def process_papers(
    source_path: Path,
    output_path: Path,
    dry_run: bool,
    also_update_final: bool,
    final_path: Path,
) -> None:
    data = load_json(source_path)

    # Load final file if needed
    final_data: Optional[list] = None
    if also_update_final and final_path.exists():
        final_data = load_json(final_path)

    enriched_count = 0
    not_found_ids: list[str] = []
    skipped_count = 0

    for i, entry in enumerate(data):
        paper_id = entry.get("id", "")

        # Skip W-IDs (already enriched OpenAlex papers)
        if not paper_id.startswith("arxiv_"):
            skipped_count += 1
            continue

        arxiv_id = paper_id[len("arxiv_"):]  # strip "arxiv_" prefix

        click.echo(f"Looking up {paper_id} ...", nl=False)
        work = lookup_openalex(arxiv_id)
        time.sleep(API_SLEEP)

        if work is None:
            click.echo(f"  ✗ {paper_id} not found in OpenAlex")
            not_found_ids.append(paper_id)
            continue

        enriched_entry = enrich_entry(entry, work)
        new_oa_id = enriched_entry["id"]

        kw_count = len(enriched_entry.get("keywords") or [])
        topic_count = len(enriched_entry.get("topics") or [])
        click.echo(f"  ✓ {paper_id} → {new_oa_id} (keywords: {kw_count}, topics: {topic_count})")

        if not dry_run:
            data[i] = enriched_entry
            # Write incrementally (crash-safe)
            save_json(output_path, data)

            # Also update final file if requested
            if final_data is not None:
                for j, fentry in enumerate(final_data):
                    if fentry.get("id") == paper_id:
                        final_data[j] = enrich_entry(fentry, work)
                save_json(final_path, final_data)

        enriched_count += 1

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo(f"Enriched : {enriched_count}")
    click.echo(f"Not found: {len(not_found_ids)}" + (f"  {not_found_ids}" if not_found_ids else ""))
    click.echo(f"Skipped  : {skipped_count}  (already W-IDs)")
    if dry_run:
        click.echo("\n[DRY RUN] No files were written.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.command()
@click.option(
    "--source",
    "source_path",
    default=str(_DEFAULT_SOURCE),
    show_default=True,
    type=click.Path(exists=True, path_type=Path),
    help="Input JSON file to enrich.",
)
@click.option(
    "--output",
    "output_path",
    default=None,
    type=click.Path(path_type=Path),
    help="Output path (defaults to source path for in-place update).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would change without writing any files.",
)
@click.option(
    "--also-update-final",
    is_flag=True,
    default=False,
    help=f"Also update {_DEFAULT_FINAL.name} for the same papers.",
)
@click.option(
    "--final-path",
    "final_path",
    default=str(_DEFAULT_FINAL),
    show_default=True,
    type=click.Path(path_type=Path),
    help="Path to the final groundtruth file.",
)
def main(
    source_path: Path,
    output_path: Optional[Path],
    dry_run: bool,
    also_update_final: bool,
    final_path: Path,
) -> None:
    """Enrich ArXiv paper metadata in groundtruth JSON files via OpenAlex."""
    if output_path is None:
        output_path = source_path  # in-place

    click.echo(f"Source : {source_path}")
    click.echo(f"Output : {output_path}")
    if dry_run:
        click.echo("Mode   : DRY RUN")
    if also_update_final:
        click.echo(f"Also updating final: {final_path}")
    click.echo("")

    process_papers(
        source_path=source_path,
        output_path=output_path,
        dry_run=dry_run,
        also_update_final=also_update_final,
        final_path=final_path,
    )


if __name__ == "__main__":
    main()
