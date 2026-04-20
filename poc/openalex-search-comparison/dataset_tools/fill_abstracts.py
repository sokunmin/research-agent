#!/usr/bin/env python3
"""Fill missing abstracts in groundtruth-balanced.json using OpenAlex."""

import json
import sys
from pathlib import Path
from dotenv import dotenv_values
import pyalex
from pyalex import Works

# --- Setup ---
ENV_PATH = "/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/.env"
DATA_PATH = "/poc/openalex-search-comparison/groundtruth/groundtruth-balanced.json"

_ENV = dotenv_values(ENV_PATH)
pyalex.config.api_key = _ENV.get("OPENALEX_API_KEY", "")
pyalex.config.email   = _ENV.get("OPENALEX_EMAIL", "")
pyalex.config.max_retries = 3
pyalex.config.retry_backoff_factor = 0.5


def reconstruct_abstract(work: dict) -> str:
    inv = work.get("abstract_inverted_index") or {}
    if not inv:
        return ""
    pos_word = {}
    for word, positions in inv.items():
        for pos in positions:
            pos_word[pos] = word
    return " ".join(pos_word[i] for i in sorted(pos_word))


def main():
    data_path = Path(DATA_PATH)

    # Load data
    with open(data_path, "r", encoding="utf-8") as f:
        entries = json.load(f)

    # Identify missing abstracts
    missing = [e for e in entries if not e.get("abstract")]
    print(f"Total entries: {len(entries)}")
    print(f"Entries with empty/missing abstract: {len(missing)}")
    print()

    filled = 0
    still_empty = 0

    for entry in missing:
        eid = entry["id"]
        title = entry.get("title", "")[:50]
        try:
            work = Works()[eid]
            abstract = reconstruct_abstract(work)
            if abstract:
                entry["abstract"] = abstract
                filled += 1
                print(f"✓ {eid} — {title}")
            else:
                still_empty += 1
                print(f"⚠ {eid} — no abstract in OpenAlex")
        except Exception as exc:
            still_empty += 1
            print(f"✗ {eid} — ERROR: {exc}")

        # Write back immediately (crash-safe)
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    print()
    print(f"Summary: filled={filled}, still_empty={still_empty}")


if __name__ == "__main__":
    main()
