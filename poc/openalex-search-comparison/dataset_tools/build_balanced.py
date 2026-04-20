#!/usr/bin/env python3
"""
build_balanced.py
─────────────────
Build a class-balanced benchmark dataset by sampling N True Positives
and N True Negatives from a groundtruth JSON file.

Uses a fixed random seed so the output is reproducible by default.
Warns (and uses all available) when the pool is smaller than requested.

Usage:
    python build_balanced.py                            # all defaults
    python build_balanced.py --dry-run                  # show counts only
    python build_balanced.py --tp 50 --tn 50 --seed 42
    python build_balanced.py \\
        --source groundtruth-final.json \\
        --output groundtruth-balanced.json
"""

import json
import random
import sys
import click
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

BASE            = Path(__file__).parent
DEFAULT_SOURCE  = BASE / "groundtruth-final.json"
DEFAULT_OUTPUT  = BASE / "groundtruth-balanced.json"
DEFAULT_TP      = 60
DEFAULT_TN      = 60
DEFAULT_SEED    = 42

# ── JSON I/O (reusable, same pattern as merge_candidates.py) ─────────────────

def load_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: list[dict]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Sampling logic ────────────────────────────────────────────────────────────

def _split_by_relevance(
    papers: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Partition papers into (tp_pool, tn_pool) by relevant field."""
    tp = [p for p in papers if p.get("relevant") is True]
    tn = [p for p in papers if p.get("relevant") is False]
    return tp, tn


def _sample_pool(
    pool:      list[dict],
    n:         int,
    label:     str,
    rng:       random.Random,
) -> tuple[list[dict], list[str]]:
    """
    Sample n entries from pool using rng.

    Returns (sampled, warnings).  If pool < n, uses entire pool and warns.
    """
    warnings: list[str] = []
    if len(pool) < n:
        warnings.append(
            f"⚠ Requested {n} {label} but only {len(pool)} available "
            f"— using all {len(pool)}."
        )
        return list(pool), warnings
    return rng.sample(pool, n), warnings


def build_balanced(
    papers:      list[dict],
    n_tp:        int,
    n_tn:        int,
    seed:        int,
    include_ids: list[str] | None = None,
) -> tuple[list[dict], dict]:
    """
    Sample n_tp TPs and n_tn TNs from papers.

    include_ids: IDs that must appear in the TN sample regardless of sampling.
    Forced entries are drawn first; the remainder fills up to n_tn.

    Returns:
        balanced — combined sampled list (shuffled)
        stats    — dict with counts and any warnings
    """
    rng      = random.Random(seed)
    tp_pool, tn_pool = _split_by_relevance(papers)

    sampled_tp, warn_tp = _sample_pool(tp_pool, n_tp, "TP", rng)

    # ── Forced TN entries ────────────────────────────────────────────────────
    include_ids  = include_ids or []
    warnings_tn: list[str] = []
    tn_by_id     = {p["id"]: p for p in tn_pool}

    forced: list[dict] = []
    for id_ in include_ids:
        if id_ not in tn_by_id:
            warnings_tn.append(
                f"⚠ include-ids: '{id_}' not found in TN pool — skipped."
            )
        else:
            forced.append(tn_by_id[id_])

    if len(forced) > n_tn:
        warnings_tn.append(
            f"⚠ {len(forced)} forced IDs exceed n_tn={n_tn} "
            f"— all forced entries included, total TN will exceed n_tn."
        )

    forced_ids  = {p["id"] for p in forced}
    remaining   = [p for p in tn_pool if p["id"] not in forced_ids]
    n_remaining = max(0, n_tn - len(forced))

    sampled_rest, warn_rest = _sample_pool(remaining, n_remaining, "TN (remaining)", rng)
    sampled_tn = forced + sampled_rest
    warnings_tn.extend(warn_rest)

    balanced = sampled_tp + sampled_tn
    rng.shuffle(balanced)

    stats = {
        "tp_pool":     len(tp_pool),
        "tn_pool":     len(tn_pool),
        "unanalysed":  sum(1 for p in papers if p.get("relevant") is None),
        "sampled_tp":  len(sampled_tp),
        "sampled_tn":  len(sampled_tn),
        "forced_tn":   len(forced),
        "total":       len(balanced),
        "warnings":    warn_tp + warnings_tn,
    }
    return balanced, stats


# ── Display helpers ───────────────────────────────────────────────────────────

_SEP = "=" * 62


def _print_header(
    source: Path, output: Path, n_tp: int, n_tn: int,
    seed: int, dry_run: bool, include_ids: list[str],
) -> None:
    print(_SEP)
    print("Build Balanced Benchmark Dataset")
    print(_SEP)
    print(f"  Source      : {source}")
    print(f"  Output      : {output}")
    print(f"  Request     : {n_tp} TP + {n_tn} TN = {n_tp + n_tn} total")
    print(f"  Seed        : {seed}")
    print(f"  Mode        : {'dry-run (no file written)' if dry_run else 'live'}")
    if include_ids:
        print(f"  Forced TN   : {len(include_ids)} IDs")
    print()


def _print_summary(stats: dict, dry_run: bool) -> None:
    print(f"\n{_SEP}")
    print("SUMMARY")
    print(_SEP)
    print(f"  TP pool available  : {stats['tp_pool']}")
    print(f"  TN pool available  : {stats['tn_pool']}")
    if stats["unanalysed"]:
        print(f"  Unanalysed (skipped): {stats['unanalysed']}")
    print(f"  Sampled TP         : {stats['sampled_tp']}")
    print(f"  Sampled TN         : {stats['sampled_tn']}"
          + (f" (incl. {stats['forced_tn']} forced)" if stats.get("forced_tn") else ""))
    print(f"  Total output       : {stats['total']}")
    for w in stats["warnings"]:
        print(f"\n  {w}")
    if not dry_run:
        print(f"\n  Written → output file")


# ── CLI ───────────────────────────────────────────────────────────────────────

@click.command()
@click.option(
    "--source",
    "source_path",
    default=DEFAULT_SOURCE,
    type=click.Path(exists=True, path_type=Path),
    show_default=True,
    help="Groundtruth JSON to sample from.",
)
@click.option(
    "--output",
    "output_path",
    default=DEFAULT_OUTPUT,
    type=click.Path(path_type=Path),
    show_default=True,
    help="Output path for the balanced dataset.",
)
@click.option(
    "--tp",
    "n_tp",
    default=DEFAULT_TP,
    type=int,
    show_default=True,
    help="Number of True Positives to include.",
)
@click.option(
    "--tn",
    "n_tn",
    default=DEFAULT_TN,
    type=int,
    show_default=True,
    help="Number of True Negatives to include.",
)
@click.option(
    "--seed",
    "seed",
    default=DEFAULT_SEED,
    type=int,
    show_default=True,
    help="Random seed for reproducibility.",
)
@click.option(
    "--include-ids",
    "include_ids_str",
    default="",
    show_default=False,
    help="Comma-separated IDs that must be included in the TN sample (hard negatives).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Show what would be selected without writing to disk.",
)
def main(
    source_path:     Path,
    output_path:     Path,
    n_tp:            int,
    n_tn:            int,
    seed:            int,
    include_ids_str: str,
    dry_run:         bool,
) -> None:
    include_ids = [i.strip() for i in include_ids_str.split(",") if i.strip()]

    _print_header(source_path, output_path, n_tp, n_tn, seed, dry_run, include_ids)

    papers          = load_json(source_path)
    balanced, stats = build_balanced(papers, n_tp, n_tn, seed, include_ids)

    _print_summary(stats, dry_run)

    if stats["warnings"] and stats["sampled_tp"] < n_tp:
        sys.exit(1)   # signal failure to caller when TP pool is insufficient

    if not dry_run:
        save_json(output_path, balanced)


if __name__ == "__main__":
    main()
