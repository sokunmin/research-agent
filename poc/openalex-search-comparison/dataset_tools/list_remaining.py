#!/usr/bin/env python3
"""
list_remaining.py
─────────────────
List unprocessed papers (no result file in relevance-results/) with their
PDF paths, ready to feed into subagent prompts.

Usage:
    python list_remaining.py              # show all remaining
    python list_remaining.py --limit 20   # show first N remaining
    python list_remaining.py --limit 20 --offset 20  # pagination
"""

import re
import json
import argparse
from pathlib import Path

BASE     = Path(__file__).parent
DL_DIR   = BASE / "downloads"
RES_DIR  = BASE / "relevance-results"
GT_FILE  = BASE / "groundtruth-final.json"


def safe_filename(title: str, fallback: str = "") -> str:
    name = title[:80]
    name = re.sub(r'[\\/*?:"<>|]', "_", name)
    name = name.strip(". ")
    return name or fallback


def main():
    parser = argparse.ArgumentParser(description="List unprocessed papers")
    parser.add_argument("--limit",  type=int, default=None, help="Max papers to show")
    parser.add_argument("--offset", type=int, default=0,    help="Skip first N remaining")
    parser.add_argument("--json",   action="store_true",    help="Output as JSON array")
    args = parser.parse_args()

    downloads = {p.stem: p for p in DL_DIR.glob("*.pdf")}
    done      = {p.stem for p in RES_DIR.glob("*.json")}
    papers    = json.loads(GT_FILE.read_text(encoding="utf-8"))

    remaining = [p for p in papers if p["id"] not in done]
    total_remaining = len(remaining)

    sliced = remaining[args.offset:]
    if args.limit:
        sliced = sliced[:args.limit]

    result = []
    for p in sliced:
        stem = safe_filename(p["title"], fallback=p["id"])
        pdf  = downloads.get(stem)
        result.append({
            "id":           p["id"],
            "title":        p["title"],
            "abstract":     p["abstract"],
            "keywords":     p["keywords"],
            "topics":       p["topics"],
            "primary_topic": p["primary_topic"],
            "pdf_path":     str(pdf) if pdf else None,
        })

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Total remaining: {total_remaining}  |  Showing: {len(result)}")
        print()
        for r in result:
            pdf_status = r["pdf_path"] or "NO PDF"
            print(f"  {r['id']}  {r['title'][:60]}")
            print(f"           pdf: {pdf_status}")


if __name__ == "__main__":
    main()
