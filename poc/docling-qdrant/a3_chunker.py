"""A3: Verify HybridChunker produces correctly structured chunks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from poc_base import DoclingPoc, PocReporter


def run() -> bool:
    r = PocReporter("A3")
    doc = DoclingPoc.load_doc()
    chunker = DoclingPoc.build_chunker()
    chunks = DoclingPoc.get_chunks(doc, chunker)

    r.check("chunks non-empty", len(chunks) > 0, f"{len(chunks)} total chunks")

    has_headings = any(bool(c.meta.headings) for c in chunks)
    r.check("at least one chunk has headings", has_headings)

    # Re-iterate raw chunks for contextualize() (needs original BaseChunk)
    raw_chunks = list(chunker.chunk(dl_doc=doc))
    heading_prepended = False
    for raw, doc_chunk in zip(raw_chunks[:10], chunks[:10]):
        enriched = chunker.contextualize(chunk=raw)
        if doc_chunk.meta.headings and enriched.startswith(doc_chunk.meta.headings[0]):
            heading_prepended = True
        non_empty = bool(enriched.strip())
        print(f"  headings={doc_chunk.meta.headings} | words={len(enriched.split())} | non-empty={non_empty}")
        print(f"  preview: {enriched[:120]}\n")

    r.check("contextualize() prepends heading", heading_prepended)
    r.check("printed chunks all non-empty", all(bool(c.text.strip()) for c in chunks[:10]))

    return r.summary()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
