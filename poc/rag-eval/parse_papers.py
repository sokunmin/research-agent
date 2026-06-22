"""Parse all ML paper PDFs with Docling and save JSON + Markdown per paper.

Run from repo root (dev/):
    micromamba run -n py3.12 python poc/rag-eval/parse_papers.py 2>&1 | tee poc/rag-eval/parse_papers.log

Output:
    poc/rag-eval/parsed_papers/{arxiv_id}.json  — full DoclingDocument (used by experiment scripts)
    poc/rag-eval/parsed_papers/{arxiv_id}.md    — markdown (used by GT generation agents)

The converter is built once and reused across all papers — never instantiate inside the loop.
First call downloads TableFormer model (~2 min one-time). Subsequent papers are faster (30–120s each).
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")  # repo root — for poc.poc_base
from poc.poc_base import DoclingPoc

import argparse

PDF_DIR = Path("poc/pdfs")
OUT_DIR = Path("poc/rag-eval/parsed_papers")
OUT_DIR.mkdir(parents=True, exist_ok=True)

parser = argparse.ArgumentParser(description="Parse ML paper PDFs with Docling.")
parser.add_argument(
    "--start-index", type=int, default=1, metavar="N",
    help="1-based paper index to start from (default: 1). Use to resume after interruption."
)
args = parser.parse_args()

pdf_paths = sorted(PDF_DIR.glob("*.pdf"))
print(f"[INFO] Found {len(pdf_paths)} PDFs in {PDF_DIR}")
print(f"[INFO] Output → {OUT_DIR}")
if args.start_index > 1:
    print(f"[INFO] Resuming from index {args.start_index} (papers 1–{args.start_index - 1} skipped)")
print()

converter = DoclingPoc.build_rag_converter()

total_t0 = time.perf_counter()
failed = []

for i, pdf_path in enumerate(pdf_paths, start=1):
    arxiv_id = pdf_path.stem
    json_path = OUT_DIR / f"{arxiv_id}.json"
    md_path   = OUT_DIR / f"{arxiv_id}.md"

    if i < args.start_index:
        print(f"[SKIP] [{i}/{len(pdf_paths)}] {arxiv_id} — index below --start-index {args.start_index}")
        continue

    if json_path.exists() and md_path.exists():
        print(f"[SKIP] [{i}/{len(pdf_paths)}] {arxiv_id} — already parsed")
        continue

    print(f"[PARSE] [{i}/{len(pdf_paths)}] {arxiv_id} ...", flush=True)
    t0 = time.perf_counter()
    try:
        result = converter.convert(str(pdf_path))
        doc = result.document
        json_path.write_text(doc.model_dump_json())
        md_path.write_text(doc.export_to_markdown())
        elapsed = time.perf_counter() - t0
        print(f"[OK]   [{i}/{len(pdf_paths)}] {arxiv_id} — {elapsed:.1f}s")
    except Exception as e:
        elapsed = time.perf_counter() - t0
        print(f"[ERROR] [{i}/{len(pdf_paths)}] {arxiv_id} — {elapsed:.1f}s — {e}")
        failed.append(arxiv_id)

total_elapsed = time.perf_counter() - total_t0
parsed = len(list(OUT_DIR.glob("*.json")))
print()
print(f"[DONE] {parsed}/{len(pdf_paths)} papers parsed in {total_elapsed:.1f}s")
if failed:
    print(f"[FAILED] {len(failed)} papers: {', '.join(failed)}")
