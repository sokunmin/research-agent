"""Shared utilities for docling-qdrant POC checks A1–A5."""
import json
import sys
from pathlib import Path

import psutil
from docling.chunking import HybridChunker
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.hierarchical_chunker import DocChunk
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc import DoclingDocument
from transformers import AutoTokenizer


class PocReporter:
    """Standardized pass/fail reporting. Tracks all checks; prints summary at end."""

    def __init__(self, check_id: str):
        self.check_id = check_id
        self.results: list[tuple[str, bool]] = []

    def check(self, label: str, condition: bool, detail: str = "") -> bool:
        status = "✅" if condition else "❌"
        msg = f"[{self.check_id}] {status} {label}"
        if detail:
            msg += f": {detail}"
        print(msg)
        self.results.append((label, condition))
        return condition

    def summary(self) -> bool:
        passed = all(r[1] for r in self.results)
        ok = sum(r[1] for r in self.results)
        total = len(self.results)
        label = "PASS ✅" if passed else "FAIL ❌"
        print(f"\n[{self.check_id}] {label} ({ok}/{total} checks passed)")
        return passed


class DoclingPoc:
    """Shared setup and utilities reused across A1–A5.

    All file paths are relative to the repo root. Run scripts from the repo root:
        micromamba run -n py3.12 python poc/docling-qdrant/a1_parse.py
    """

    PDF_PATH  = Path("poc/docling-qdrant/data/1706.03762.pdf")
    JSON_PATH = Path("poc/docling-qdrant/data/1706.03762.json")
    MD_PATH   = Path("poc/docling-qdrant/data/1706.03762.md")
    DATA_DIR  = Path("poc/docling-qdrant/data")

    _NOMIC_TOKENIZER_ID = "nomic-ai/nomic-embed-text-v1"

    @staticmethod
    def build_converter() -> DocumentConverter:
        """Build DocumentConverter singleton with full M1-compatible options.

        Must be created once and reused — never call inside a per-paper loop.
        """
        opts = PdfPipelineOptions()
        opts.do_ocr                    = False
        opts.do_table_structure        = True
        opts.table_structure_options   = TableStructureOptions(
            mode=TableFormerMode.ACCURATE,
            do_cell_matching=True,
        )
        opts.do_formula_enrichment     = True
        opts.do_code_enrichment        = True
        opts.do_picture_classification = True
        opts.generate_picture_images   = True
        opts.images_scale              = 2.0
        opts.do_picture_description    = False  # too slow on M1; enable in Phase 2
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )

    @staticmethod
    def build_analysis_converter() -> DocumentConverter:
        """Minimal converter for heading analysis — no formula/table/code enrichment."""
        opts = PdfPipelineOptions()
        opts.do_ocr = False
        opts.do_table_structure = False
        opts.do_formula_enrichment = False
        opts.do_code_enrichment = False
        opts.do_picture_classification = False
        opts.do_picture_description = False
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )

    @staticmethod
    def load_doc() -> DoclingDocument:
        """Load DoclingDocument from JSON cache written by A1.

        Milliseconds vs 30–120s re-parse. A1 must have run successfully first.
        """
        if not DoclingPoc.JSON_PATH.exists():
            sys.exit(f"[ERROR] JSON cache not found: {DoclingPoc.JSON_PATH}. Run A1 first.")
        return DoclingDocument.model_validate(
            json.loads(DoclingPoc.JSON_PATH.read_text())
        )

    @staticmethod
    def build_chunker(max_tokens: int = 512) -> HybridChunker:
        """Build HybridChunker with nomic-embed-text tokenizer.

        Uses trust_remote_code=True — required for nomic tokenizer.
        """
        tokenizer = AutoTokenizer.from_pretrained(
            DoclingPoc._NOMIC_TOKENIZER_ID, trust_remote_code=True
        )
        return HybridChunker(
            tokenizer=HuggingFaceTokenizer(tokenizer=tokenizer, max_tokens=max_tokens)
        )

    @staticmethod
    def get_chunks(doc: DoclingDocument, chunker: HybridChunker) -> list[DocChunk]:
        """Return all DocChunk objects for a document.

        DocChunk.model_validate() is required to access .meta.headings —
        raw BaseChunk from chunker.chunk() does not expose metadata.
        """
        return [DocChunk.model_validate(c) for c in chunker.chunk(dl_doc=doc)]

    @staticmethod
    def embed(text: str) -> list[float]:
        """Get 768-dim embedding from nomic-embed-text via LiteLLMEmbedding.

        Uses the same LiteLLM + ollama/ prefix pattern as model_factory.relevance_embed_model()
        in the production pipeline. Do NOT call this in a tight loop — instantiates the
        model each call. Use a shared LiteLLMEmbedding instance in loops instead.
        """
        from llama_index.embeddings.litellm import LiteLLMEmbedding
        model = LiteLLMEmbedding(model_name="ollama/nomic-embed-text")
        return model.get_text_embedding("search_query: " + text)

    @staticmethod
    def ram_gb() -> float:
        """Return available RAM in GB."""
        return psutil.virtual_memory().available / (1024 ** 3)
