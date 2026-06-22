"""Shared utilities for docling-qdrant POC checks A1–A5."""
import json
import re
import sys
import unicodedata
import uuid
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
    def build_rag_converter() -> DocumentConverter:
        """Build a faster DocumentConverter for RAG experiments on Apple Silicon.

        Compared to build_converter():
        - AcceleratorDevice.MPS: enables Apple Silicon GPU for layout detection
        - TableFormerMode.FAST: heuristic table parsing (MPS not supported by TableFormer;
          FAST avoids the per-cell ML inference cost on CPU)
        - formula/code/picture enrichment disabled: these add per-element ML passes
          that do not improve text retrieval quality
        - generate_picture_images disabled: images are not needed for text-based RAG

        Use this method for all rag-eval experiment scripts.
        Use build_converter() only when picture or formula fidelity matters.
        """
        from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
        opts = PdfPipelineOptions()
        opts.do_ocr                    = False
        opts.do_table_structure        = True
        opts.table_structure_options   = TableStructureOptions(
            mode=TableFormerMode.FAST,
            do_cell_matching=True,
        )
        opts.do_formula_enrichment     = False
        opts.do_code_enrichment        = False
        opts.do_picture_classification = False
        opts.generate_picture_images   = False
        opts.do_picture_description    = False
        return DocumentConverter(
            accelerator_options=AcceleratorOptions(device=AcceleratorDevice.MPS),
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


# ── Evaluation Experiment Utilities ───────────────────────────────────────────

import time
import csv
import math
import litellm
from abc import ABC, abstractmethod
from datetime import datetime


class ExperimentLogger:
    """Structured [TAG] logging that produces machine-parseable output.

    Each line uses a [TAG] prefix with key=value pairs so automated tools
    can extract metrics from log files without parsing free-form text.

    Usage:
        logger = ExperimentLogger("chunking_ablation")
        logger.header(embed="nomic-embed-text", k=10)
        logger.result(paper="1706.03762", variant="D", recall5=0.88, ndcg5=0.91)
        logger.skip(paper="2106.09685", query_type="Negative", reason="empty_gt_passages")
        logger.error(paper="2303.01469", stage="embed", msg="connection refused")
        logger.summary(variant="D", mean_recall5=0.87, mean_ndcg5=0.90)
        logger.winner(variant="D", recall5=0.87)
        logger.end()
    """

    def __init__(self, name: str):
        self._name = name
        self._t0 = time.perf_counter()

    def _fmt(self, tag: str, **kwargs) -> str:
        pairs = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        return f"[{tag}] {pairs}"

    def header(self, **kwargs):
        print(f"[EXPERIMENT] {self._name}", flush=True)
        print(f"[TIMESTAMP] {datetime.now().isoformat(timespec='seconds')}", flush=True)
        if kwargs:
            print(self._fmt("ENV", **kwargs), flush=True)

    def result(self, **kwargs):
        print(self._fmt("RESULT", **kwargs), flush=True)

    def skip(self, **kwargs):
        print(self._fmt("SKIP", **kwargs), flush=True)

    def error(self, **kwargs):
        print(self._fmt("ERROR", **kwargs), flush=True)

    def summary(self, **kwargs):
        print(self._fmt("SUMMARY", **kwargs), flush=True)

    def winner(self, **kwargs):
        print(self._fmt("WINNER", **kwargs), flush=True)

    def log(self, tag: str, **kwargs) -> None:
        """Print a structured [TAG] line with key=value pairs.

        Use for structural markers that don't fit the standard tags
        (e.g. CONFIG_START, CONFIG_END, SANITY, INDEX, INFO).
        Output format: [TAG] key=value | key=value
        If no kwargs, prints just: [TAG]
        """
        body = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        print(f"[{tag.upper()}] {body}" if body else f"[{tag.upper()}]", flush=True)

    def end(self):
        elapsed = time.perf_counter() - self._t0
        print(f"[ELAPSED] total={elapsed:.1f}s", flush=True)
        print(f"[END] {self._name}", flush=True)


class PaperCorpus:
    """Manages the shared PDF corpus, parsed papers, and ground-truth dataset.

    All paths are relative to the repo root. Run scripts from the repo root:
        micromamba run -n py3.12 python poc/rag-eval/some_script.py
    """

    PDF_DIR    = Path("poc/pdfs")
    PARSED_DIR = Path("poc/rag-eval/parsed_papers")
    GT_PATH    = Path("poc/rag-eval/gt_dataset_per_paper.json")

    def paper_ids(self) -> list[str]:
        """Return sorted list of all paper IDs (stems of PDF filenames)."""
        return sorted(p.stem for p in self.PDF_DIR.glob("*.pdf"))

    def load_gt(self, exclude_negative: bool = False) -> list[dict]:
        """Load ground-truth dataset. Set exclude_negative=True to skip unanswerable queries."""
        import json
        samples = json.loads(self.GT_PATH.read_text())
        if exclude_negative:
            samples = [s for s in samples if not s.get("is_negative", False)]
        return samples

    def load_doc(self, paper_id: str):
        """Load a parsed DoclingDocument from its cached JSON file.

        Raises FileNotFoundError if the paper has not been parsed yet.
        Parse all papers first by running poc/rag-eval/parse_papers.py.
        """
        import json
        from docling_core.types.doc import DoclingDocument
        json_path = self.PARSED_DIR / f"{paper_id}.json"
        if not json_path.exists():
            raise FileNotFoundError(
                f"Parsed paper not found: {json_path}. Run phase0_parse.py first."
            )
        return DoclingDocument.model_validate(json.loads(json_path.read_text()))


class MetricsCalculator:
    """Recall@k and nDCG@k for retrieval evaluation.

    Usage:
        relevant_ids = MetricsCalculator.find_relevant_ids(all_nodes, sample["gt_passages"])
        retrieved_ids = [n.node_id for n in retriever.retrieve(query)[:5]]
        recall = MetricsCalculator.recall_at_k(retrieved_ids, relevant_ids, k=5)
        ndcg   = MetricsCalculator.ndcg_at_k(retrieved_ids, relevant_ids, k=5)

    Both methods return None when relevant_ids is empty (unanswerable query) —
    the caller is responsible for logging a skip and excluding from aggregates.
    """

    @staticmethod
    def _normalize(text: str) -> str:
        # strip markdown table pipes so table-format GT passages match CSV-format chunks
        return re.sub(r"\s*\|\s*", " ", text).strip()

    @staticmethod
    def find_relevant_ids(nodes: list, gt_passages: list[str]) -> list[str]:
        """Map ground-truth passage text to node IDs via substring match.

        A node is marked relevant if any gt_passage string appears within node.text.
        Node IDs are transient (generated at index time) — this mapping is only
        valid within a single script execution.
        """
        relevant = []
        for node in nodes:
            for passage in gt_passages:
                if MetricsCalculator._normalize(passage) in MetricsCalculator._normalize(node.text):
                    relevant.append(node.node_id)
                    break
        return relevant

    @staticmethod
    def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float | None:
        """Fraction of relevant chunks found in the top-k retrieved results.

        Returns None if there are no relevant chunks (unanswerable query).
        """
        if not relevant_ids:
            return None
        hits = sum(1 for r in retrieved_ids[:k] if r in set(relevant_ids))
        return hits / len(relevant_ids)

    @staticmethod
    def ndcg_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float | None:
        """Normalized Discounted Cumulative Gain at k.

        Rewards retrieving relevant chunks at higher ranks. Returns None if there
        are no relevant chunks (unanswerable query).
        """
        if not relevant_ids:
            return None
        relevant_set = set(relevant_ids)
        dcg = sum(
            1.0 / math.log2(i + 2)
            for i, rid in enumerate(retrieved_ids[:k])
            if rid in relevant_set
        )
        ideal_hits = min(len(relevant_ids), k)
        idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
        return dcg / idcg if idcg > 0 else 0.0


class BaseExperiment(ABC):
    """Abstract base class for retrieval and summarization experiment scripts."""

    def __init__(self, corpus: PaperCorpus, logger: ExperimentLogger):
        self.corpus = corpus
        self.logger = logger
        self.results: list[dict] = []

    @abstractmethod
    def run(self): ...

    def save_csv(self, path: Path):
        """Write self.results to a CSV file, creating parent directories as needed."""
        if not self.results:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.results[0].keys())
            writer.writeheader()
            writer.writerows(self.results)


class ContextualDoclingNodeParser:
    """Docling-aware node parser that enriches chunks with heading context and filters boilerplate.

    Wraps a Docling chunker (HierarchicalChunker or HybridChunker) and applies two steps
    that plain text splitters cannot do:
      1. contextualize() — prefixes each chunk with its section heading path, so
         "Results: 92.3% accuracy" becomes "Introduction > Results: 92.3% accuracy".
         This improves embedding quality for section-specific queries.
      2. ChunkFilter.should_skip() — removes boilerplate chunks (references, page headers,
         copyright notices) that degrade retrieval quality.

    With HierarchicalChunker (default): chunks follow the document's section hierarchy,
    producing variable-length chunks aligned to section boundaries.

    With HybridChunker(tokenizer=_TokenizerAdapter(max_tokens=512)): chunks are capped
    at 512 tokens using tiktoken (cl100k_base), with no HuggingFace model download required.
    _TokenizerAdapter is available from services.docling_chunker.DoclingChunker._TokenizerAdapter.

    Usage:
        import sys
        sys.path.insert(0, "../research-agent-docling-rag-pipeline/backend")
        from services.docling_chunker import DoclingChunker
        from tools.filter_tools import ChunkFilter
        from docling.chunking import HybridChunker

        chunk_filter = ChunkFilter(config_path=Path("poc/rag-filtering/filter_config.json"))

        # Section-hierarchy chunks (no token limit):
        parser_hier = ContextualDoclingNodeParser(chunk_filter=chunk_filter)

        # Token-capped chunks (512 tokens):
        tokenizer = DoclingChunker._TokenizerAdapter(max_tokens=512)
        parser_hybrid = ContextualDoclingNodeParser(
            chunker=HybridChunker(tokenizer=tokenizer),
            chunk_filter=chunk_filter,
        )
    """

    def __init__(self, chunker=None, chunk_filter=None, use_contextualize: bool = True, prose_only_embed: bool = False):
        from docling.chunking import HierarchicalChunker
        from llama_index.node_parser.docling import DoclingNodeParser
        self._chunker = chunker or HierarchicalChunker()
        self._chunk_filter = chunk_filter
        self._use_contextualize = use_contextualize
        self._prose_only_embed = prose_only_embed
        self._base = DoclingNodeParser(chunker=self._chunker)

    def parse_nodes(self, documents, show_progress: bool = False):
        """Parse LlamaIndex documents into enriched TextNodes."""
        from docling_core.transforms.chunker.hierarchical_chunker import DocChunk
        from docling_core.types.doc import DoclingDocument as DLDocument
        from llama_index.core.schema import TextNode
        results = []
        for li_doc in documents:
            dl_doc = DLDocument.model_validate_json(li_doc.get_content())
            for raw_chunk in self._chunker.chunk(dl_doc=dl_doc):
                doc_chunk = DocChunk.model_validate(raw_chunk)
                if self._chunk_filter and self._chunk_filter.should_skip(doc_chunk):
                    continue
                if self._use_contextualize:
                    stored_text = self._chunker.contextualize(chunk=raw_chunk)
                else:
                    stored_text = raw_chunk.text
                node = TextNode(text=stored_text)
                if self._prose_only_embed and self._use_contextualize:
                    # prose_only_embed: embed prose only, but LLM reads heading + prose.
                    # Store prose in metadata so the embedding loop uses it instead of node.text.
                    node.metadata["_embed_text"] = raw_chunk.text
                results.append(node)
        return results

    def get_nodes_from_documents(self, documents, show_progress: bool = False):
        return self.parse_nodes(documents, show_progress=show_progress)


JUDGE_PROMPT = """You are an expert ML paper evaluator.
Score the following paper summary:
1. Completeness (1-5): Does it cover main contribution, dataset, and results?
2. Specificity (1-5): Does it mention specific numbers, model names, benchmarks?

Summary:
{summary}

Respond in this exact format:
Completeness: <score>
Specificity: <score>
Reason: <one sentence>"""


class VLMSummarizer:
    """Summarizes a PDF paper by passing all pages as images to a vision-language model.

    Accepts the VLM as an external dependency so it can be configured and shared
    by the caller (same interface as RAGSummarizer for symmetrical usage).

    Usage:
        from services.multimodal import LiteLLMMultiModal
        vlm = LiteLLMMultiModal(model="ollama/gemma4:31b-cloud", max_tokens=4096, temperature=0.0)
        summarizer = VLMSummarizer(vlm=vlm)
        text, latency_seconds = summarizer.summarize("1706.03762", corpus)
    """

    def __init__(self, vlm):
        self.vlm = vlm

    def summarize(self, paper_id: str, corpus: PaperCorpus) -> tuple[str, float, int]:
        """Returns (summary_text, wall_clock_seconds, output_token_count)."""
        import sys
        import tempfile
        sys.path.insert(0, "../research-agent-docling-rag-pipeline/backend")
        from llama_index.core.schema import ImageDocument
        from utils.file_processing import pdf2images
        from agent_workflows.summary_gen import SUMMARIZE_PAPER_PMT
        t0 = time.perf_counter()
        pdf_path = corpus.PDF_DIR / f"{paper_id}.pdf"
        with tempfile.TemporaryDirectory() as tmp:
            pdf2images(pdf_path, Path(tmp))
            img_docs = [
                ImageDocument(image_path=str(p))
                for p in sorted(Path(tmp).iterdir())
            ]
            # VLM call is inside the with block so temp files still exist when read
            resp = self.vlm.complete(SUMMARIZE_PAPER_PMT, image_documents=img_docs)
        return resp.text, time.perf_counter() - t0, self._count_output_tokens(resp)

    def _count_output_tokens(self, resp) -> int:
        try:
            return resp.raw.usage.completion_tokens  # attribute chain — resp.raw is a typed object, NOT a dict
        except AttributeError:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(resp.text))


class RAGSummarizer:
    """Summarizes a paper by retrieving relevant chunks and passing them to an LLM.

    The chunker and retrieval mode are injected by the caller so the same class
    can be configured with whichever chunking strategy and hybrid/dense mode
    performed best in prior ablation experiments.

    Usage:
        from services.rag_index_builder import RAGIndexBuilder
        from llama_index.embeddings.litellm import LiteLLMEmbedding
        from llama_index.llms.litellm import LiteLLM

        embed_model = LiteLLMEmbedding(model_name="ollama/nomic-embed-text")
        llm = LiteLLM(model="ollama/gemma4:31b-cloud", max_tokens=4096, temperature=0.0)
        summarizer = RAGSummarizer(
            chunker=best_chunker,
            chunk_filter=chunk_filter,
            embed_model=embed_model,
            queries=retrieval_queries,  # list of strings covering different aspects
            llm=llm,
            use_hybrid=True,  # True = dense + BM25 sparse hybrid; False = dense only
        )
        text, latency_seconds = summarizer.summarize("1706.03762", corpus)
    """

    def __init__(self, chunker, chunk_filter, embed_model, queries: list[str], llm,
                 use_hybrid: bool = False):
        import sys
        sys.path.insert(0, "../research-agent-docling-rag-pipeline/backend")
        from services.rag_index_builder import RAGIndexBuilder
        self._index_builder = RAGIndexBuilder(chunker, chunk_filter)
        self._embed_model = embed_model
        self._queries = queries
        self._llm = llm
        self._use_hybrid = use_hybrid

    def summarize(self, paper_id: str, corpus: PaperCorpus) -> tuple[str, float, int]:
        """Returns (summary_text, wall_clock_seconds, output_token_count)."""
        import json
        import sys
        sys.path.insert(0, "../research-agent-docling-rag-pipeline/backend")
        from docling_core.types.doc import DoclingDocument
        from agent_workflows.summary_gen import SUMMARIZE_PAPER_PMT
        t0 = time.perf_counter()
        doc = DoclingDocument.model_validate(
            json.loads((corpus.PARSED_DIR / f"{paper_id}.json").read_text())
        )
        index = self._index_builder.build(doc, self._embed_model)
        retriever = index.as_retriever(
            vector_store_query_mode="hybrid" if self._use_hybrid else "default",
            similarity_top_k=10,
        )
        seen_ids: set[str] = set()
        chunks: list[str] = []
        for query in self._queries:
            for node in retriever.retrieve(query):
                if node.node_id not in seen_ids:
                    seen_ids.add(node.node_id)
                    chunks.append(node.text)
        context = "\n\n---\n\n".join(chunks)
        resp = self._llm.complete(SUMMARIZE_PAPER_PMT + f"\n\n{context}")
        return resp.text, time.perf_counter() - t0, self._count_output_tokens(resp)

    def _count_output_tokens(self, resp) -> int:
        try:
            return resp.raw.usage.completion_tokens  # attribute chain — resp.raw is a typed object, NOT a dict
        except AttributeError:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(resp.text))


class JudgeLLM:
    """LLM-as-judge that scores paper summaries on completeness and specificity.

    Uses nemotron-3-super:cloud via litellm.completion directly (not the LlamaIndex
    wrapper). Requires extra_body={"think": False} — this model has a thinking mode
    that causes litellm to receive an unexpected JSON field, silently discarding the
    response content. Disabling thinking prevents this.

    Usage:
        judge = JudgeLLM()
        scores = judge.score(summary_text)
        # {"completeness": 4, "specificity": 3, "reason": "..."}
    """

    def score(self, summary: str) -> dict:
        resp = litellm.completion(
            model="ollama/nemotron-3-super:cloud",
            messages=[{"role": "user", "content": JUDGE_PROMPT.format(summary=summary)}],
            max_tokens=256,
            temperature=0.0,
            extra_body={"think": False},
        )
        return self._parse(resp.choices[0].message.content)

    def _parse(self, text: str) -> dict:
        lines = {}
        for line in text.strip().splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                lines[k.strip()] = v.strip()
        return {
            "completeness": int(lines.get("Completeness", 0)),
            "specificity":  int(lines.get("Specificity", 0)),
            "reason":       lines.get("Reason", ""),
        }


# ── BERT Tokenizer for embedding pre-truncation ───────────────────────────────

from transformers import AutoTokenizer

# Loaded once at module level so all experiment scripts share the same tokenizer instance.
# bert-base-uncased is the tokenizer used by nomic-embed-text (the embedding model).
# Used to pre-truncate text before sending to Ollama to prevent HTTP 400 errors.
_BERT_TOKENIZER = AutoTokenizer.from_pretrained("bert-base-uncased")

# nomic-embed-text has a 2048 BERT token hard limit (including 2 special tokens CLS/SEP).
# We use 1900 (not 2046) as the safe limit for two reasons:
#   1. Ollama's GGUF tokenizer diverges from HuggingFace for some Unicode characters
#      (e.g. "…" U+2026 counts as 1 token in HuggingFace but 2 in Ollama's llama.cpp).
#      NFKC normalization eliminates most such characters, but the 7% buffer handles residual drift.
#   2. Markdown table separator lines like "|---|---|" tokenize to ~8 tokens in BPE (tiktoken)
#      but ~90 tokens in BERT WordPiece — a chunk that measures 990 tiktoken tokens can be
#      2400+ BERT tokens. Truncation prevents Ollama returning HTTP 400.
_BERT_MAX_TOKENS = 1900


def truncate_to_bert_limit(text: str) -> str:
    """Truncate text to fit within nomic-embed-text's 2048 BERT token limit.

    Two-layer protection:
      Step 1 — NFKC normalization: converts Unicode compatibility characters to ASCII
               equivalents ("…" → "...", "ﬁ" → "fi"). Eliminates tokenizer divergence
               between HuggingFace bert-base-uncased and Ollama's GGUF llama.cpp build.
      Step 2 — Truncate to 1900 tokens: 7% headroom beyond the NFKC fix to handle
               any residual GGUF tokenizer drift for uncommon Unicode characters.

    The original text is NOT modified in the caller — only the text sent to the
    embedding model is truncated. Retrieved node.text remains the full original text.
    """
    text = unicodedata.normalize("NFKC", text)
    token_ids = _BERT_TOKENIZER.encode(text, add_special_tokens=False)
    if len(token_ids) <= _BERT_MAX_TOKENS:
        return text
    return _BERT_TOKENIZER.decode(token_ids[:_BERT_MAX_TOKENS], skip_special_tokens=True)


# ── Qdrant persistent index for retrieval experiments ─────────────────────────

class QdrantPaperIndex:
    """Persistent Qdrant vector index for the 28 ML paper corpus used in retrieval experiments.

    Stores all paper chunks as dense + sparse (BM25) vectors in a single Qdrant collection
    on disk. Multiple retrieval configs in the same experiment can share this index — building it once
    saves re-embedding time on every run.

    Indexing completion is tracked using a sentinel point: a special Qdrant point with
    payload {"type": "index_complete"} written ONLY after ALL chunks for a paper are
    successfully upserted. This makes Qdrant the single source of truth — no external
    marker file that can get out of sync with the actual Qdrant data.

    Crash recovery: if the script crashes mid-upsert, no sentinel exists for that paper.
    On the next run, all partial points for that paper are deleted before re-indexing,
    ensuring a clean state. Delete-before-upsert is always safe even if chunk count
    changes between runs (prevents stale chunks from an earlier indexing from polluting
    retrieval results).

    The sentinel point uses a zero vector and is inserted directly via QdrantClient
    (not via VectorStoreIndex), so LlamaIndex's internal doc store never registers it.
    It will never appear in retrieval results.
    """

    # All 28 papers share a single Qdrant collection.
    # Each paper's chunks are identified by a "paper_id" payload field.
    COLLECTION_NAME = "ml_papers_docling_hybrid_512_retrieval"

    # Payload value used to identify sentinel points.
    # A sentinel point exists for paper X iff all of X's chunks were successfully upserted.
    SENTINEL_TYPE_VALUE = "index_complete"

    # nomic-embed-text output dimension. Must match the collection vector size.
    EMBEDDING_DIM = 768

    def __init__(self, index_dir: Path, embed_model, collection_name: str = None):
        """
        Args:
            index_dir: Directory where Qdrant stores its data files on disk.
                       Created automatically if it does not exist.
            embed_model: LiteLLMEmbedding instance for nomic-embed-text.
                         Used when embedding chunks during index building.
            collection_name: Override the default COLLECTION_NAME class attribute.
                             Used when a single script needs multiple isolated indices
                             (e.g. a sentence_splitter experiment uses a separate index from the docling_hybrid index).
        """
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        index_dir.mkdir(parents=True, exist_ok=True)
        self._client = QdrantClient(path=str(index_dir))
        self._embed_model = embed_model
        if collection_name is not None:
            self.COLLECTION_NAME = collection_name

        # The Qdrant collection is created lazily on the first _embed_and_upsert() call.
        # QdrantVectorStore does not create the collection at construction time —
        # collection creation only happens inside VectorStoreIndex(nodes=nodes, ...)
        # when nodes is non-empty (triggers vector_store.add() internally).
        # All methods that read from Qdrant have explicit collection_exists() guards.

    def build_or_load(self, paper_id: str, nodes: list) -> tuple:
        """Build the index for one paper (first run) or load it from disk (subsequent runs).

        The caller always provides freshly re-chunked nodes (re-chunking is fast, ~2 min
        for all 28 papers, and is required to rebuild the in-memory nodes list needed by
        find_relevant_ids() for GT passage substring matching).

        On cache hit (sentinel found): skip embedding, load index from Qdrant disk.
        On cache miss or crash recovery: delete any partial points, embed all chunks,
        upsert to Qdrant, then write the sentinel point.

        Returns:
            (VectorStoreIndex, nodes, was_already_indexed): index for retrieval,
            nodes for find_relevant_ids(), and was_already_indexed (bool): True if the
            paper was loaded from cache, False if it was freshly embedded.
        """
        from llama_index.vector_stores.qdrant import QdrantVectorStore
        from llama_index.core import VectorStoreIndex

        was_already_indexed = self.is_paper_indexed(paper_id)
        if not was_already_indexed:
            self._delete_paper_points(paper_id)
            self._embed_and_upsert(paper_id, nodes)
            self._write_sentinel(paper_id, chunk_count=len(nodes))
        else:
            # Cache hit: _embed_and_upsert was skipped, so in-memory nodes have
            # random LlamaIndex UUIDs. Stamp the same deterministic uuid5 IDs that
            # _embed_and_upsert assigned during the original indexing run so that
            # find_relevant_ids() produces IDs that match what Qdrant returns.
            for i, node in enumerate(nodes):
                node.node_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{paper_id}_chunk_{i}"))

        vector_store = QdrantVectorStore(
            client=self._client,
            collection_name=self.COLLECTION_NAME,
            enable_hybrid=True,
            fastembed_sparse_model="Qdrant/bm25",
        )
        index = VectorStoreIndex.from_vector_store(
            vector_store, embed_model=self._embed_model
        )
        return index, nodes, was_already_indexed

    def is_paper_indexed(self, paper_id: str) -> bool:
        """Return True iff all chunks for this paper were successfully upserted.

        Checks for the sentinel point — NOT collection_exists() or count() > 0.
        Both of those return True for partial writes after a crash.
        """
        if not self._client.collection_exists(self.COLLECTION_NAME):
            return False
        from qdrant_client.models import Filter, FieldCondition, MatchValue

        results, _ = self._client.scroll(
            collection_name=self.COLLECTION_NAME,
            scroll_filter=Filter(must=[
                FieldCondition(
                    key="type",
                    match=MatchValue(value=self.SENTINEL_TYPE_VALUE),
                ),
                FieldCondition(
                    key="paper_id",
                    match=MatchValue(value=paper_id),
                ),
            ]),
            limit=1,
            with_payload=False,
            with_vectors=False,
        )
        return len(results) > 0

    def rebuild_all(self, paper_ids: list) -> None:
        """Drop the entire Qdrant collection and mark all papers as unindexed.

        Used by the --rebuild-index CLI flag to force a full re-index from scratch.
        Because Qdrant is the single source of truth (no external marker file),
        this only needs to clear Qdrant — nothing else to synchronize.
        """
        if self._client.collection_exists(self.COLLECTION_NAME):
            self._client.delete_collection(self.COLLECTION_NAME)
        # Collection will be recreated lazily on the first _embed_and_upsert() call.
        # QdrantVectorStore does not create collections at construction time —
        # collection creation only happens inside VectorStoreIndex(nodes=nodes, ...)
        # when nodes is non-empty.

    def _delete_paper_points(self, paper_id: str) -> None:
        """Delete all Qdrant points for one paper (chunks + sentinel if any).

        Called before re-indexing to ensure a clean slate. Safe to call even if no
        points exist for this paper. Required before re-upsert because if chunking
        parameters change and chunk count decreases (e.g. 80 → 60), the old chunks
        61–80 would remain in Qdrant and pollute retrieval results if not deleted first.
        """
        if not self._client.collection_exists(self.COLLECTION_NAME):
            return  # collection not yet created — nothing to delete
        from qdrant_client.models import Filter, FieldCondition, MatchValue, FilterSelector

        self._client.delete(
            collection_name=self.COLLECTION_NAME,
            points_selector=FilterSelector(
                filter=Filter(must=[
                    FieldCondition(
                        key="paper_id",
                        match=MatchValue(value=paper_id),
                    )
                ])
            ),
        )

    def _embed_and_upsert(self, paper_id: str, nodes: list) -> None:
        """Embed all chunks for one paper and upsert them into Qdrant.

        Assigns deterministic UUIDs (uuid5) to each chunk node so that node IDs are
        identical across script re-runs. This is required for find_relevant_ids() to
        work correctly when the index is loaded from disk on subsequent runs —
        the in-memory nodes list and the Qdrant-stored vectors must have matching IDs.

        Uses the same uuid5 pattern as backend/services/vector_store.py line 76.
        """
        from llama_index.vector_stores.qdrant import QdrantVectorStore
        from llama_index.core import StorageContext, VectorStoreIndex

        for chunk_index, node in enumerate(nodes):
            node.id_ = str(uuid.uuid5(
                uuid.NAMESPACE_DNS, f"{paper_id}_chunk_{chunk_index}"
            ))
            node.metadata["paper_id"] = paper_id
            node.embedding = self._embed_model.get_text_embedding(
                truncate_to_bert_limit(node.text)
            )

        vector_store = QdrantVectorStore(
            client=self._client,
            collection_name=self.COLLECTION_NAME,
            enable_hybrid=True,
            fastembed_sparse_model="Qdrant/bm25",
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        VectorStoreIndex(nodes=nodes, storage_context=storage_context, embed_model=self._embed_model)

    def _write_sentinel(self, paper_id: str, chunk_count: int) -> None:
        """Write the indexing-complete sentinel point for one paper.

        Must be called ONLY after all chunks have been successfully upserted.
        The sentinel's presence is what is_paper_indexed() checks — calling this
        prematurely would incorrectly mark an incomplete index as done.

        The sentinel uses a zero vector (same dimension as chunk embeddings) so it
        is never the nearest neighbor for any real query. It is not registered in
        LlamaIndex's internal doc store and will never appear in retrieval results.
        """
        from qdrant_client.models import PointStruct
        from llama_index.vector_stores.qdrant.base import DEFAULT_DENSE_VECTOR_NAME

        if not self._client.collection_exists(self.COLLECTION_NAME):
            raise RuntimeError(
                f"collection '{self.COLLECTION_NAME}' does not exist when writing sentinel "
                f"for paper '{paper_id}' — _embed_and_upsert likely failed mid-way"
            )

        self._client.upsert(
            collection_name=self.COLLECTION_NAME,
            points=[
                PointStruct(
                    id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{paper_id}__sentinel__")),
                    vector={DEFAULT_DENSE_VECTOR_NAME: [0.0] * self.EMBEDDING_DIM},
                    payload={
                        "type": self.SENTINEL_TYPE_VALUE,
                        "paper_id": paper_id,
                        "chunk_count": chunk_count,
                    },
                )
            ],
        )

    def close(self) -> None:
        """Explicitly close the Qdrant client connection.

        Call this when the index is no longer needed to prevent a harmless but
        noisy ImportError from QdrantClient.__del__ during Python shutdown.
        """
        self._client.close()


# ── Per-config result file manager for retrieval experiments ──────────────────

class ConfigResultTracker:
    """Per-config JSON result file manager for the retrieval strategy comparison experiment.

    Each retrieval configuration (e.g. hybrid_bm25_with_reranker) has its own JSON file
    at results_dir/<config_name>.json. The file stores per-sample evaluation outcomes
    (success or failure) so the experiment can resume after a crash without re-running
    samples that already succeeded.

    Source of truth for resume logic — NOT the log file. Log files require regex parsing
    and can contain ambiguous duplicate entries if a config crashes and is re-run.
    JSON has an explicit "status" field per sample with no ambiguity.

    Write pattern: one sample at a time, written immediately after evaluation completes.
    Never batch writes — if one sample in a batch fails, all results in that batch are lost.

    Atomic writes: uses write-to-temp-then-rename so a crash during the write leaves
    either the old complete file or the new complete file — never a half-written file.
    """

    def __init__(self, results_dir: Path, config_name: str):
        """
        Args:
            results_dir: Directory where per-config JSON files are stored.
                         Created automatically if it does not exist.
            config_name: Human-readable config name (e.g. "hybrid_bm25_with_reranker").
                         Used as the JSON filename stem.
        """
        results_dir.mkdir(parents=True, exist_ok=True)
        self._path = results_dir / f"{config_name}.json"
        self._config_name = config_name
        self._data = self._load()

    def is_sample_done(self, paper_id: str, query_type: str) -> bool:
        """Return True if this (paper, query_type) sample was already successfully evaluated."""
        return any(
            s["paper_id"] == paper_id
            and s["query_type"] == query_type
            and s["status"] == "success"
            for s in self._data["samples"]
        )

    def is_config_done(self) -> bool:
        """Return True if all samples for this config have been evaluated and the config is marked complete."""
        return self._data.get("status") == "complete"

    def write_result(self, paper_id: str, query_type: str, **metrics) -> None:
        """Record a successful sample result and immediately persist to disk.

        Args:
            paper_id:   ArXiv paper ID (e.g. "1608.06993").
            query_type: One of Factual / Keyword-heavy / Semantic / Multi-hop.
            **metrics:  All numeric results: recall_at_5, ndcg_at_5, context_recall,
                        faithfulness, context_precision, and any extras.
        """
        self._data["samples"].append({
            "paper_id": paper_id,
            "query_type": query_type,
            "status": "success",
            **metrics,
        })
        self._persist()

    def write_error(self, paper_id: str, query_type: str, error: str) -> None:
        """Record a failed sample and immediately persist to disk.

        Failed samples are written so they appear in the JSON for inspection,
        but they are NOT skipped on resume — a failed sample is retried on the next run.
        Only successful samples (status="success") are skipped on resume.
        """
        self._data["samples"].append({
            "paper_id": paper_id,
            "query_type": query_type,
            "status": "failed",
            "error": error,
        })
        self._persist()

    def mark_config_complete(self) -> None:
        """Mark this entire config as finished. Sets status="complete" in the JSON."""
        self._data["status"] = "complete"
        self._persist()

    def reset(self) -> None:
        """Clear all sample records and reset status to in_progress. Used when --force is passed."""
        self._data = {"retrieval_config": self._config_name, "status": "in_progress", "samples": []}
        self._persist()

    def is_paper_done(self, paper_id: str) -> bool:
        """Check if a paper-level result (no query_type dimension) was already recorded."""
        return self.is_sample_done(paper_id, "summary")

    def write_paper_result(self, paper_id: str, **metrics) -> None:
        """Write a paper-level result using 'summary' as the query_type sentinel."""
        self.write_result(paper_id, "summary", **metrics)

    def _load(self) -> dict:
        if self._path.exists():
            return json.loads(self._path.read_text())
        return {
            "retrieval_config": self._config_name,
            "status": "in_progress",
            "samples": [],
        }

    def _persist(self) -> None:
        """Write JSON atomically: write to .tmp file then rename to final path.

        rename() on the same filesystem is an atomic OS operation — the file
        is always either fully written (new) or untouched (old), never partial.
        """
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self._data, indent=2))
        tmp_path.rename(self._path)


# ── RAGAS LLM-judge evaluator for retrieval quality assessment ────────────────

class RAGASEvaluator:
    """RAGAS-based LLM-judge evaluator for RAG retrieval quality assessment.

    Evaluates three metrics per query-answer-context triple using
    nemotron-3-super:cloud as the judge LLM (0.9s/call via Ollama):

      Context Recall:    Does the retrieved context cover the reference answer?
                         Score 1.0 = all reference answer claims are supported by context.
      Faithfulness:      Is the generated answer grounded in the retrieved context?
                         Score 1.0 = every claim in the generated answer is supported.
      Context Precision: Are the most relevant chunks ranked near the top?
                         Score 1.0 = all top-ranked chunks are relevant.

    Used in retrieval strategy comparison and summarization comparison experiments.

    RAGAS import note: ragas 0.4.x requires langchain-community stubs to be in sys.modules
    BEFORE any ragas import. The calling script must insert these stubs at the very top
    (before all other imports) — see the ragas stub fix block in retrieval_strategy_comparison.py.
    """

    def __init__(self):
        import instructor
        import litellm
        from ragas.llms.base import llm_factory
        from ragas.metrics.collections.faithfulness.metric import Faithfulness
        from ragas.metrics.collections.context_recall.metric import ContextRecall
        from ragas.metrics.collections.context_precision.metric import ContextPrecision

        # nemotron-3-super has thinking mode enabled by default.
        # Ollama returns a "thinking" field in the response JSON that LiteLLM cannot parse,
        # causing the content to be silently discarded. Wrap litellm.completion to always
        # pass think=False so Ollama suppresses the thinking field.
        async def _nemotron_acompletion(**kwargs):
            kwargs.setdefault("extra_body", {})["think"] = False
            kwargs.setdefault("temperature", 0.0)
            kwargs.setdefault("seed", 42)
            kwargs.setdefault("num_ctx", 32768)
            return await litellm.acompletion(**kwargs)

        # instructor.from_litellm wraps litellm.acompletion and enforces structured Pydantic
        # output. This is what RAGAS 0.4.3 requires — it no longer accepts LlamaIndexLLMWrapper.
        client = instructor.from_litellm(_nemotron_acompletion, mode=instructor.Mode.JSON)
        judge_llm = llm_factory(
            model="ollama/nemotron-3-super:cloud",
            provider="litellm",
            client=client,
            adapter="litellm",
        )
        self._metrics = [
            Faithfulness(llm=judge_llm),
            ContextRecall(llm=judge_llm),
            ContextPrecision(llm=judge_llm),
        ]

    def evaluate(
        self,
        query: str,
        generated_answer: str,
        retrieved_contexts: list,
        reference_answer: str,
    ) -> dict:
        """Evaluate one query-answer-context sample. Returns a dict of three float scores.

        Args:
            query:               The original user query sent to the retriever.
            generated_answer:    The answer produced by the LLM from retrieved contexts.
            retrieved_contexts:  List of chunk texts returned by the retriever.
            reference_answer:    The ground-truth answer from the GT dataset.

        Returns:
            {"context_recall": float, "faithfulness": float, "context_precision": float}
            Each score is in [0, 1]. Higher is better.

        Note on result indexing: ragas evaluate() returns List[float] per metric even
        for a single sample (e.g. result["faithfulness"] == [0.85], not 0.85).
        We index [0] to return a plain float.
        """
        faithfulness, context_recall, context_precision = self._metrics
        return {
            "faithfulness": faithfulness.score(
                user_input=query,
                response=generated_answer,
                retrieved_contexts=retrieved_contexts,
            ).value,
            "context_recall": context_recall.score(
                user_input=query,
                retrieved_contexts=retrieved_contexts,
                reference=reference_answer,
            ).value,
            "context_precision": context_precision.score(
                user_input=query,
                reference=reference_answer,
                retrieved_contexts=retrieved_contexts,
            ).value,
        }
