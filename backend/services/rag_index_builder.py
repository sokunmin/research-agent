from docling_core.types.doc import DoclingDocument
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import TextNode

from services.docling_chunker import DoclingChunker
from tools.filter_tools import ChunkFilter


class RAGIndexBuilder:
    """Builds a per-paper in-memory VectorStoreIndex for RAG-based summarization.

    Receives DoclingChunker and ChunkFilter via dependency injection.
    ChunkFilter excludes boilerplate sections before embedding.
    """

    def __init__(self, chunker: DoclingChunker, chunk_filter: ChunkFilter):
        self._chunker = chunker
        self._filter = chunk_filter

    def build(self, doc: DoclingDocument, embed_model) -> VectorStoreIndex:
        """Chunk doc, filter boilerplate, embed kept chunks, return in-memory index."""
        paper_chunks = self._chunker.extract_chunks(doc, self._filter)
        nodes = [
            TextNode(
                text=pc.enriched_text,
                metadata={"headings": pc.headings, "page_no": pc.page_no},
            )
            for pc in paper_chunks
        ]
        return VectorStoreIndex(nodes, embed_model=embed_model, show_progress=False)
