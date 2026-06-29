import json
import logging
from pathlib import Path

import pypdf
from docling.chunking import HybridChunker
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.hierarchical_chunker import DocChunk
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.types.doc import DoclingDocument
from llama_index.core import Settings
from pydantic import BaseModel

from config import settings
from tools.filter_tools import ChunkFilter

logger = logging.getLogger(__name__)


class PaperChunk(BaseModel):
    enriched_text: str
    headings: list[str]
    page_no: int | None


class DoclingPipeline:
    """Full Docling pipeline: PDF parsing, document loading, and chunk extraction.

    Owns the DocumentConverter, HybridChunker, and ChunkFilter.
    Create once in workflow __init__, inject into PaperStore.
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

    def __init__(self, max_tokens: int, filter_config_path: Path):
        self._converter = self._build_converter()
        self._chunker = HybridChunker(
            tokenizer=DoclingPipeline._TokenizerAdapter(max_tokens=max_tokens)
        )
        self._filter = ChunkFilter(config_path=filter_config_path)

    def parse_pdf(self, pdf_path: Path, output_dir: Path) -> Path | None:
        """Parse PDF to DoclingDocument JSON + markdown cache.

        Returns json_path on success or cache hit, None on failure.
        Failures: PDF not found (E1), Docling partial parse below threshold (E2).
        """
        subfolder = output_dir / pdf_path.stem
        subfolder.mkdir(parents=True, exist_ok=True)
        json_path = subfolder / f"{pdf_path.stem}.json"
        md_path = subfolder / f"{pdf_path.stem}.md"

        if json_path.exists() and md_path.exists():
            logger.info(f"Cache hit: already parsed '{pdf_path.name}'")
            return json_path

        if not pdf_path.exists():
            logger.warning(f"PDF not found, skipping: '{pdf_path}'")
            return None

        with open(pdf_path, "rb") as f:
            total_pages = len(pypdf.PdfReader(f).pages)

        result = self._converter.convert(str(pdf_path), max_num_pages=50)

        if result.status == ConversionStatus.PARTIAL_SUCCESS:
            parsed_pages = len(result.document.pages)
            success_rate = parsed_pages / total_pages if total_pages > 0 else 0.0
            if success_rate < settings.DOCLING_MIN_SUCCESS_RATE:
                logger.warning(
                    f"Docling PARTIAL_SUCCESS for '{pdf_path.name}': "
                    f"{parsed_pages}/{total_pages} pages ({success_rate:.0%}) — dropping"
                )
                return None

        result.document.save_as_json(json_path)
        md_path.write_text(result.document.export_to_markdown(), encoding="utf-8")
        logger.info(f"Docling: saved JSON + markdown to '{subfolder}'")
        return json_path

    def load_document(self, json_path: Path) -> DoclingDocument:
        """Load DoclingDocument from cached JSON."""
        return DoclingDocument.model_validate(json.loads(json_path.read_text()))

    def chunk(self, doc: DoclingDocument) -> list[PaperChunk]:
        """Chunk document and filter boilerplate. Returns PaperChunks."""
        results = []
        for raw in list(self._chunker.chunk(dl_doc=doc)):
            doc_chunk = DocChunk.model_validate(raw)
            if self._filter.should_skip(doc_chunk):
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

    @staticmethod
    def _build_converter() -> DocumentConverter:
        opts = PdfPipelineOptions()
        opts.do_ocr = False
        opts.do_table_structure = False
        opts.do_formula_enrichment = False
        opts.do_code_enrichment = False
        opts.do_picture_classification = False
        opts.generate_picture_images = False
        opts.do_picture_description = False
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )
