"""A1: Verify Docling parses 1706.03762.pdf correctly on M1."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from poc_base import DoclingPoc, PocReporter

from docling_core.types.doc import PictureItem


def run() -> bool:
    r = PocReporter("A1")
    print(f"[A1] RAM before parse: {DoclingPoc.ram_gb():.1f} GB available")

    converter = DoclingPoc.build_converter()

    t0 = time.time()
    result = converter.convert(str(DoclingPoc.PDF_PATH), max_num_pages=50)
    elapsed = time.time() - t0
    print(f"[A1] Parse complete in {elapsed:.1f}s")

    md = result.document.export_to_markdown()
    r.check("section headers (##) ≥ 3", md.count("\n##") >= 3, f"{md.count(chr(10) + '##')} found")
    r.check("table rows (|) present", "|" in md)
    r.check("formulas ($$) present", "$$" in md)

    pic_count = 0
    sample_saved = False
    for el, _ in result.document.iterate_items():
        if isinstance(el, PictureItem):
            pil_img = el.get_image(result.document)
            if pil_img is not None:
                if not sample_saved:
                    DoclingPoc.DATA_DIR.mkdir(parents=True, exist_ok=True)
                    pil_img.save(str(DoclingPoc.DATA_DIR / "sample_picture.png"), "PNG")
                    sample_saved = True
                pic_count += 1

    r.check("PictureItem found", pic_count > 0, f"{pic_count} pictures")
    r.check("picture image accessible (PIL not None)", sample_saved)
    r.check("no MPS error", True)  # reaching here means no crash
    r.check("RAM headroom > 2 GB", DoclingPoc.ram_gb() > 2, f"{DoclingPoc.ram_gb():.1f} GB")

    # Save outputs for A2–A5
    result.document.save_as_json(DoclingPoc.JSON_PATH)
    DoclingPoc.MD_PATH.write_text(md, encoding="utf-8")
    json_mb = DoclingPoc.JSON_PATH.stat().st_size / (1024 ** 2)
    print(f"[A1] Saved JSON cache ({json_mb:.1f} MB): {DoclingPoc.JSON_PATH}")
    print(f"[A1] Saved markdown ({len(md):,} chars): {DoclingPoc.MD_PATH}")
    print(f"[A1] Parse time: {elapsed:.1f}s")

    return r.summary()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
