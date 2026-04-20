#!/usr/bin/env python3
"""
Parse extract-pdfs.txt into structured JSON (groundtruth-final.json).
"""

import re
import ast
import json
from pathlib import Path

INPUT_FILE = Path(__file__).parent / "extract-pdfs.txt"
OUTPUT_FILE = Path(__file__).parent / "groundtruth-final.json"

# Regex to detect the start of a paper block
PAPER_BLOCK_RE = re.compile(r'^#\d+\s+\[')

def parse_list_field(raw: str) -> list:
    """Parse a Python list repr string into a real list."""
    raw = raw.strip()
    if not raw or raw == "—":
        return []
    try:
        result = ast.literal_eval(raw)
        if isinstance(result, list):
            return result
        return []
    except Exception:
        return []

def parse_log(text: str) -> list:
    papers = []
    current_lines = []

    def flush_block(lines):
        if not lines:
            return None
        # Gather all relevant fields
        paper = {
            "id": "",
            "title": "",
            "abstract": "",
            "keywords": [],
            "topics": [],
            "primary_topic": "",
            "concepts": [],
            "relevant": False,
        }
        for line in lines:
            # Title
            m = re.match(r'^\s+Title\s+:\s+(.+)$', line)
            if m:
                paper["title"] = m.group(1).strip()
                continue

            # OpenAlex ID
            m = re.match(r'^\s+OpenAlex\s+:\s+[✓✗]\s+(W\d+)', line)
            if m:
                paper["id"] = m.group(1).strip()
                continue

            # Abstract
            m = re.match(r'^\s+Abstract\s+:\s+(.+)$', line)
            if m:
                val = m.group(1).strip()
                paper["abstract"] = "" if val == "—" else val
                continue

            # Keywords
            m = re.match(r'^\s+Keywords\s+:\s+(.+)$', line)
            if m:
                paper["keywords"] = parse_list_field(m.group(1).strip())
                continue

            # Topics
            m = re.match(r'^\s+Topics\s+:\s+(.+)$', line)
            if m:
                paper["topics"] = parse_list_field(m.group(1).strip())
                continue

            # PrimaryTopic (no alignment spaces after colon label)
            m = re.match(r'^\s+PrimaryTopic:\s+(.+)$', line)
            if m:
                paper["primary_topic"] = m.group(1).strip()
                continue

            # Concepts
            m = re.match(r'^\s+Concepts\s+:\s+(.+)$', line)
            if m:
                paper["concepts"] = parse_list_field(m.group(1).strip())
                continue

        # Only add if we got an ID (otherwise it's a non-paper block)
        if paper["id"]:
            return paper
        return None

    lines = text.splitlines()
    in_paper = False

    for line in lines:
        if PAPER_BLOCK_RE.match(line):
            # Flush previous block
            if in_paper and current_lines:
                result = flush_block(current_lines)
                if result:
                    papers.append(result)
            current_lines = [line]
            in_paper = True
        elif in_paper:
            # Skip Download lines entirely
            if re.match(r'^\s+Download\s+:', line):
                continue
            current_lines.append(line)

    # Don't forget the last block
    if in_paper and current_lines:
        result = flush_block(current_lines)
        if result:
            papers.append(result)

    return papers


def main():
    text = INPUT_FILE.read_text(encoding="utf-8")
    papers = parse_log(text)

    print(f"Total papers parsed: {len(papers)}")
    print("\nFirst 3 papers:")
    for p in papers[:3]:
        print(f"  id={p['id']}  title={p['title']}")

    OUTPUT_FILE.write_text(
        json.dumps(papers, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\nOutput written to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
