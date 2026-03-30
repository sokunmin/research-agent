#!/usr/bin/env python3
"""
merge_results.py
────────────────
Merge relevance-results/*.json into groundtruth-final.json.
Updates the `relevant` and `reason` fields for each matched paper.

Usage:
    python merge_results.py           # merge and overwrite groundtruth-final.json
    python merge_results.py --dry-run # preview without writing
"""

import json
import argparse
from pathlib import Path

BASE     = Path(__file__).parent
RES_DIR  = BASE / "relevance-results"
GT_FILE  = BASE / "groundtruth-final.json"


def main():
    parser = argparse.ArgumentParser(description="Merge relevance results into groundtruth-final.json")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    papers  = json.loads(GT_FILE.read_text(encoding="utf-8"))
    index   = {p["id"]: p for p in papers}

    results = list(RES_DIR.glob("*.json"))
    if not results:
        print("No result files found in relevance-results/")
        return

    updated, skipped = 0, 0
    for result_file in sorted(results):
        try:
            r = json.loads(result_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  SKIP {result_file.name}: parse error — {e}")
            skipped += 1
            continue

        pid = r.get("id")
        if pid not in index:
            print(f"  SKIP {pid}: not found in groundtruth-final.json")
            skipped += 1
            continue

        index[pid]["relevant"] = r.get("relevant", False)
        if "reason" in r:
            index[pid]["reason"] = r["reason"]
        updated += 1

    print(f"Updated: {updated}  |  Skipped: {skipped}  |  Total in GT: {len(papers)}")

    if not args.dry_run:
        GT_FILE.write_text(
            json.dumps(papers, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Written → {GT_FILE}")
    else:
        print("(dry-run: no file written)")


if __name__ == "__main__":
    main()
