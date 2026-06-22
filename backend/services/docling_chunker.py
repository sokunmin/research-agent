from docling.chunking import HybridChunker
from docling_core.transforms.chunker.hierarchical_chunker import DocChunk
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc import DoclingDocument
from llama_index.core import Settings
from pydantic import BaseModel


class PaperChunk(BaseModel):
    enriched_text: str
    headings: list[str]
    page_no: int | None


class DoclingChunker:
    """HybridChunker wrapper. Create once in workflow __init__, inject everywhere.

    Uses _TokenizerAdapter to delegate token counting to LlamaIndex Settings.tokenizer
    (tiktoken cl100k_base by default). No HuggingFace model download required.
    """

    class _TokenizerAdapter(BaseTokenizer):
        max_tokens: int

        def count_tokens(self, text: str) -> int:
            return len(Settings.tokenizer(text))

        def get_max_tokens(self) -> int:
            return self.max_tokens

        def get_tokenizer(self):
            tokenizer = Settings.tokenizer
            return lambda text: len(tokenizer(text))

    def __init__(self, max_tokens: int = 512):
        self._chunker = HybridChunker(
            tokenizer=DoclingChunker._TokenizerAdapter(max_tokens=max_tokens)
        )

    def extract_chunks(self, doc: DoclingDocument, chunk_filter) -> list[PaperChunk]:
        """Chunk doc, filter boilerplate, return enriched PaperChunk list.

        Single pass shared by RAGIndexBuilder and PaperVectorStore — the document
        is chunked exactly once regardless of how many consumers call this.
        """
        results = []
        for raw in list(self._chunker.chunk(dl_doc=doc)):
            doc_chunk = DocChunk.model_validate(raw)
            if chunk_filter.should_skip(doc_chunk):
                continue
            enriched = self._chunker.contextualize(chunk=raw)
            page_no = None
            if doc_chunk.meta.doc_items:
                for item in doc_chunk.meta.doc_items:
                    if item.prov:
                        page_no = item.prov[0].page_no
                        break
            results.append(PaperChunk(
                enriched_text=enriched,
                headings=doc_chunk.meta.headings or [],
                page_no=page_no,
            ))
        return results
