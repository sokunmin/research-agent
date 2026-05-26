"""A5: Verify smart_llm summary quality using full-paper RAG retrieval."""
import sys
import time
from pathlib import Path

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import TextNode

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
sys.path.insert(0, str(Path(__file__).parent))
from poc_base import DoclingPoc, PocReporter

from prompts.prompts import SUMMARIZE_PAPER_PMT
from services.model_factory import model_factory

_RETRIEVAL_QUERIES = [
    "What problem does this paper address and what is the proposed solution?",
    "What is the key approach, model architecture, or algorithm introduced?",
    "What are the key components or steps in the method?",
    "How was the model trained or finetuned, including loss functions and optimization?",
    "What datasets were used, including size, type, source, and availability?",
    "What evaluation methods, benchmarks, and metrics were used?",
    "What are the conclusions, significance, limitations, and suggested future work?",
    "Who are the authors and what is the publication year?",
]


def run() -> bool:
    r = PocReporter("A5")
    doc = DoclingPoc.load_doc()
    chunker = DoclingPoc.build_chunker()

    # ALL chunks required — 8 queries × top-5 = up to 40 unique chunks
    raw_chunks = list(chunker.chunk(dl_doc=doc))
    nodes = []
    for raw, doc_chunk in zip(raw_chunks, DoclingPoc.get_chunks(doc, chunker)):
        enriched = chunker.contextualize(chunk=raw)
        nodes.append(TextNode(
            text="search_document: " + enriched,
            metadata={"headings": doc_chunk.meta.headings or []},
        ))
    print(f"[A5] Built index with {len(nodes)} nodes")

    embed_model = model_factory.relevance_embed_model()
    index = VectorStoreIndex(nodes, embed_model=embed_model, show_progress=False)
    retriever = index.as_retriever(similarity_top_k=5)

    seen_ids: set[str] = set()
    context_chunks: list[str] = []
    for query in _RETRIEVAL_QUERIES:
        for nws in retriever.retrieve("search_query: " + query):
            if nws.node.node_id not in seen_ids:
                seen_ids.add(nws.node.node_id)
                context_chunks.append(nws.node.text)

    print(f"[A5] Retrieved {len(context_chunks)} unique chunks")
    context_text = "\n\n---\n\n".join(context_chunks)
    prompt = f"{SUMMARIZE_PAPER_PMT}\n\n---\n\n{context_text}"

    import asyncio
    llm = model_factory.smart_llm(temperature=0.0)
    t0 = time.time()
    response = asyncio.run(llm.acomplete(prompt))
    elapsed = time.time() - t0

    text = response.text.strip().removeprefix("```markdown").removeprefix("```").removesuffix("```").strip()
    print(f"\n[A5] Summary ({elapsed:.1f}s):\n{'─'*60}\n{text}\n{'─'*60}\n")

    (DoclingPoc.DATA_DIR / "1706.03762_summary.md").write_text(text, encoding="utf-8")

    # Visual pass criteria
    # C1: EN-DE BLEU score
    r.check("contains EN-DE BLEU 28.4", "28.4" in text)

    # C2: EN-FR BLEU score
    r.check("contains EN-FR BLEU 41.8 or 41.0", "41.8" in text or "41.0" in text)

    # C3: core architecture term
    r.check("contains multi-head attention", "multi-head attention" in text.lower())

    # C4: training details
    r.check("contains training details (Adam/warmup/4000)",
            any(kw in text for kw in ["Adam", "warmup", "4000"]))

    # C5: dataset name
    r.check("contains WMT 2014 and dataset name",
            "WMT 2014" in text and any(d in text for d in ["English-German", "English-French"]))

    return r.summary()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
