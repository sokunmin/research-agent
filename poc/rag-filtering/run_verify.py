"""Phase 2C — verify ChunkFilter against all 28 PDFs.

Prints per-paper keep/drop stats and an overall summary with top dropped headings.
Run from repo root:
    micromamba run -n py3.12 python poc/rag-filtering/run_verify.py 2>/dev/null
"""
from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from poc_base import DoclingPoc
from chunk_filter import ChunkFilter


def _heading_of(chunk) -> str:
    """Return the first heading of a chunk, or empty string."""
    headings = chunk.meta.headings
    return headings[0] if headings else ""


def main() -> None:
    pdf_dir = Path("poc/rag-filtering/pdfs")
    config_path = Path("poc/rag-filtering/filter_config.json")

    chunk_filter = ChunkFilter(config_path)
    converter = DoclingPoc.build_analysis_converter()
    chunker = DoclingPoc.build_chunker(512)

    pdfs = sorted(pdf_dir.glob("*.pdf"))

    total_chunks = 0
    total_kept = 0
    total_dropped = 0
    # heading_lower -> {"count": int, "reason": str}
    dropped_heading_counts: dict[str, dict] = defaultdict(lambda: {"count": 0, "reason": ""})

    for idx, pdf_path in enumerate(pdfs, start=1):
        try:
            result = converter.convert(str(pdf_path), max_num_pages=50)
            chunks = DoclingPoc.get_chunks(result.document, chunker)
        except Exception as exc:
            print(f"[{idx}] {pdf_path.name}  SKIP: {exc}")
            continue

        kept, dropped = chunk_filter.filter_chunks(chunks)

        # Tally per-paper dropped headings
        paper_dropped: dict[str, dict] = defaultdict(lambda: {"count": 0, "reason": ""})
        for chunk in dropped:
            h = _heading_of(chunk)
            normalized = h.lower().strip()
            _, reason = chunk_filter.should_filter(h)
            paper_dropped[normalized]["count"] += 1
            paper_dropped[normalized]["reason"] = reason
            dropped_heading_counts[normalized]["count"] += 1
            dropped_heading_counts[normalized]["reason"] = reason

        total_chunks += len(chunks)
        total_kept += len(kept)
        total_dropped += len(dropped)

        # Build compact dropped summary: "references (exact) ×5 | ..."
        parts = [
            f"{h} ({info['reason']}) ×{info['count']}"
            for h, info in sorted(paper_dropped.items(), key=lambda x: -x[1]["count"])
        ]
        dropped_str = " | ".join(parts) if parts else "—"
        print(
            f"[{idx}] {pdf_path.name:<22} "
            f"total={len(chunks):<4} kept={len(kept):<4} dropped={len(dropped)}"
        )
        if parts:
            print(f"    DROPPED: {dropped_str}")

    # Summary
    kept_pct = 100 * total_kept / total_chunks if total_chunks else 0.0
    drop_pct = 100 * total_dropped / total_chunks if total_chunks else 0.0

    print("\n=== Summary ===")
    print(f"Total chunks : {total_chunks}")
    print(f"Kept         : {total_kept}  ({kept_pct:.1f}%)")
    print(f"Dropped      : {total_dropped}  ({drop_pct:.1f}%)")

    if dropped_heading_counts:
        print("\nTop dropped headings:")
        for h, info in sorted(
            dropped_heading_counts.items(), key=lambda x: -x[1]["count"]
        ):
            print(f"  {h:<28} ×{info['count']:>3}  ({info['reason']})")


if __name__ == "__main__":
    main()
