#!/usr/bin/env python3
"""
merge_candidates.py
───────────────────
Append new candidate papers into the main groundtruth JSON, skipping
duplicates by both ID and normalised title.

Usage:
    python merge_candidates.py                          # all defaults
    python merge_candidates.py --dry-run                # preview only
    python merge_candidates.py \\
        --candidates candidate-groundtruth.json \\
        --target     groundtruth-final.json
"""

import json
import click
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

BASE             = Path(__file__).parent
DEFAULT_CANDIDATES = BASE / "candidate-groundtruth.json"
DEFAULT_TARGET     = BASE / "groundtruth-final.json"

# ── JSON I/O (reusable) ───────────────────────────────────────────────────────

def load_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: list[dict]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Deduplication helpers ─────────────────────────────────────────────────────

def _normalise_title(title: str) -> str:
    """Lowercase + collapse whitespace for fuzzy title matching."""
    return " ".join(title.lower().split())


def _build_index(entries: list[dict]) -> tuple[set[str], set[str]]:
    """Return (id_set, normalised_title_set) for fast duplicate lookup."""
    ids    = {e["id"] for e in entries}
    titles = {_normalise_title(e["title"]) for e in entries}
    return ids, titles


def _is_duplicate(entry: dict, ids: set[str], titles: set[str]) -> str | None:
    """Return duplicate reason string, or None if entry is new."""
    if entry["id"] in ids:
        return f"duplicate id ({entry['id']})"
    if _normalise_title(entry["title"]) in titles:
        return f"duplicate title"
    return None


# ── Core logic ────────────────────────────────────────────────────────────────

def merge(
    candidates: list[dict],
    target:     list[dict],
) -> tuple[list[dict], list[dict], list[tuple[dict, str]]]:
    """
    Merge candidates into target, deduplicating by id and normalised title.

    Returns:
        merged    — combined list (target + accepted candidates)
        accepted  — candidates that were added
        rejected  — list of (entry, reason) for skipped candidates
    """
    ids, titles = _build_index(target)
    accepted: list[dict]               = []
    rejected: list[tuple[dict, str]]   = []

    for entry in candidates:
        reason = _is_duplicate(entry, ids, titles)
        if reason:
            rejected.append((entry, reason))
        else:
            accepted.append(entry)
            ids.add(entry["id"])
            titles.add(_normalise_title(entry["title"]))

    return target + accepted, accepted, rejected


# ── Display helpers ───────────────────────────────────────────────────────────

_SEP = "=" * 62


def _print_header(candidates_path: Path, target_path: Path, dry_run: bool) -> None:
    print(_SEP)
    print("Merge Candidates → Groundtruth")
    print(_SEP)
    print(f"  Candidates : {candidates_path}")
    print(f"  Target     : {target_path}")
    print(f"  Mode       : {'dry-run (no file written)' if dry_run else 'live'}")
    print()


def _print_summary(
    n_before:  int,
    accepted:  list[dict],
    rejected:  list[tuple[dict, str]],
    n_after:   int,
    dry_run:   bool,
) -> None:
    print(f"\n{_SEP}")
    print("SUMMARY")
    print(_SEP)
    print(f"  Target before  : {n_before}")
    print(f"  Candidates     : {len(accepted) + len(rejected)}")
    print(f"  Accepted       : {len(accepted)}")
    print(f"  Rejected (dup) : {len(rejected)}")
    print(f"  Target after   : {n_after}")
    if rejected:
        print("\n  Skipped entries:")
        for entry, reason in rejected:
            print(f"    ✗ [{reason}] {entry['title'][:60]}")
    if not dry_run:
        print(f"\n  Written → target file")


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option(
    "--candidates",
    "candidates_path",
    default=DEFAULT_CANDIDATES,
    type=click.Path(exists=True, path_type=Path),
    show_default=True,
    help="Source candidate JSON file to merge from.",
)
@click.option(
    "--target",
    "target_path",
    default=DEFAULT_TARGET,
    type=click.Path(exists=True, path_type=Path),
    show_default=True,
    help="Destination groundtruth JSON file to merge into.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview changes without writing to disk.",
)
def main(candidates_path: Path, target_path: Path, dry_run: bool) -> None:
    _print_header(candidates_path, target_path, dry_run)

    candidates = load_json(candidates_path)
    target     = load_json(target_path)
    n_before   = len(target)

    merged, accepted, rejected = merge(candidates, target)

    _print_summary(n_before, accepted, rejected, len(merged), dry_run)

    if not dry_run:
        save_json(target_path, merged)


if __name__ == "__main__":
    main()
