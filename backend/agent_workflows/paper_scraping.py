import json
import re
import time
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional

import arxiv
import click
import pyalex
import requests
from llama_index.core.base.embeddings.base import similarity as cosine_similarity
from llama_index.core.llms import ChatMessage
from llama_index.embeddings.litellm import LiteLLMEmbedding
from llama_index.llms.litellm import LiteLLM
from pyalex import Works
from pydantic import BaseModel

from config import settings
from prompts.prompts import RELEVANCE_SURVEY_HEURISTIC_PMT
import logging
import sys

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class Paper(BaseModel):
    entry_id: str          # OpenAlex work URL, e.g. "https://openalex.org/W2741809807"
    title: str
    authors: List[str]
    summary: str           # reconstructed abstract text; empty string if unavailable
    published: Optional[str] = None
    primary_category: Optional[str] = None
    # primary_category stores primary_topic.display_name (topic-level granularity,
    # e.g. "Natural Language Processing"), NOT field.display_name (field-level,
    # e.g. "Computer Science"). Used by the LLM relevance stage for richer context.
    link: Optional[str] = None
    external_ids: Optional[dict] = None     # {"ArXiv": "1706.03762"} when present
    open_access_pdf: Optional[dict] = None  # {"url": "..."} best OA URL from OpenAlex
    keywords: Optional[List[str]] = None    # keyword display names from OpenAlex
    topics: Optional[List[str]] = None      # topic display names from OpenAlex
    concepts: Optional[List[str]] = None    # concept display names from OpenAlex


# ── OpenAlex module-level config ─────────────────────────────────────────────

pyalex.config.email = settings.OPENALEX_EMAIL
if settings.OPENALEX_API_KEY:
    pyalex.config.api_key = settings.OPENALEX_API_KEY
pyalex.config.max_retries = 5               # recover from transient HTTP 500
pyalex.config.retry_backoff_factor = 0.5    # exponential back-off between retries

# ── OpenAlex helpers ──────────────────────────────────────────────────────────

def _reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct abstract text from OpenAlex abstract_inverted_index format.

    OpenAlex stores abstracts as an inverted index: {word: [pos1, pos2, ...]}
    rather than a plain string. work.get("abstract") always returns None —
    reconstruction from abstract_inverted_index is required.
    Returns empty string when the index is absent or empty (~20% of works
    have no abstract in OpenAlex due to upstream data source limitations).
    """
    if not inverted_index:
        return ""
    word_positions = [
        (pos, word)
        for word, positions in inverted_index.items()
        for pos in positions
    ]
    return " ".join(word for _, word in sorted(word_positions))


def _extract_display_names(items: list) -> Optional[List[str]]:
    """Extract display_name strings from a list of OpenAlex tagged objects.

    OpenAlex returns keywords, topics, and concepts as lists of dicts, each
    with a display_name field. Returns None instead of an empty list to keep
    Paper fields cleanly Optional.
    """
    names = [item["display_name"] for item in items if item.get("display_name")]
    return names or None


def _extract_arxiv_id(work: dict) -> Optional[str]:
    """Extract ArXiv ID from OpenAlex work locations. Strips version suffix.

    ArXiv IDs are NOT in work["ids"] — they appear only in work["locations"]
    landing_page_url values (e.g. "https://arxiv.org/abs/1706.03762v5").
    Version suffix is stripped so constructed PDF URLs always resolve to the
    latest version: https://arxiv.org/pdf/1706.03762
    """
    for loc in work.get("locations", []):
        url = loc.get("landing_page_url") or ""
        if "arxiv.org" in url:
            raw = url.rstrip("/").split("/")[-1]
            return re.sub(r"v\d+$", "", raw)    # "1706.03762v5" → "1706.03762"
    return None


def _paper_filename(paper: "Paper") -> str:
    """Derive a safe, consistent PDF filename from paper identifiers.

    Prefers ArXiv ID (e.g. "1706.03762.pdf") for clean alphanumeric names.
    Falls back to OpenAlex ID (e.g. "W2741809807.pdf") which is always present.
    Avoids using paper title: titles contain special characters, Unicode, and
    variable length that cause cross-platform filesystem issues.
    """
    arxiv_id = (paper.external_ids or {}).get("ArXiv")
    if arxiv_id:
        return f"{arxiv_id}.pdf"
    openalex_id = paper.entry_id.rstrip("/").split("/")[-1]  # "W2741809807"
    return f"{openalex_id}.pdf"


def _work_to_paper(result: dict) -> Paper:
    """Convert an OpenAlex Work dict to a Paper.

    Uses private helpers for all field extraction.
    primary_category uses primary_topic.display_name (topic-level granularity)
    rather than field.display_name for more informative relevance context.
    Abstract is reconstructed from abstract_inverted_index — work["abstract"]
    always returns None from the OpenAlex API.
    """
    authors = [
        a["author"]["display_name"]
        for a in result.get("authorships", [])
        if a.get("author")
    ]
    primary_topic = result.get("primary_topic") or {}
    arxiv_id = _extract_arxiv_id(result)
    oa_url = (result.get("open_access") or {}).get("oa_url")

    return Paper(
        entry_id=result["id"],
        title=result.get("title") or "",
        authors=authors,
        summary=_reconstruct_abstract(result.get("abstract_inverted_index") or {}),
        published=result.get("publication_date"),
        primary_category=primary_topic.get("display_name"),
        link=result.get("doi"),
        external_ids={"ArXiv": arxiv_id} if arxiv_id else {},
        open_access_pdf={"url": oa_url} if oa_url else None,
        keywords=_extract_display_names(result.get("keywords", [])),
        topics=_extract_display_names(result.get("topics", [])),
        concepts=_extract_display_names(result.get("concepts", [])),
    )


# ── Search constants ───────────────────────────────────────────────────────────
_CANDIDATE_OA_STATUS_FILTER = "diamond|gold|green"
# Only open-access statuses that guarantee a downloadable PDF without paywall.


def fetch_candidate_papers(
    topic: str,
    limit: int = settings.PAPER_CANDIDATE_LIMIT,
) -> List[Paper]:
    """Search OpenAlex for open-access academic papers matching *topic*.

    Uses full-text BM25 search with quality filters to surface papers that are:
    - Downloadable (OA status: diamond / gold / green)
    - Established (cited_by_count > PAPER_CANDIDATE_MIN_CITATIONS)
    - Recent (published within the last PAPER_CANDIDATE_YEAR_WINDOW years)
    - Not retracted

    Results are sorted by citation count descending to surface high-impact
    papers first. Suitable as a FunctionTool in LLM agent scenarios.
    """
    year_floor = date.today().year - settings.PAPER_CANDIDATE_YEAR_WINDOW
    works = (
        Works()
        .search(topic)
        .filter(
            is_oa=True,
            oa_status=_CANDIDATE_OA_STATUS_FILTER,
            cited_by_count=f">{settings.PAPER_CANDIDATE_MIN_CITATIONS}",
            publication_year=f">{year_floor}",
            type="!retraction",
        )
        .sort(cited_by_count="desc")
        .get(per_page=limit)
    )
    return [_work_to_paper(w) for w in works]


# ── Relevance filtering ───────────────────────────────────────────────────────

class PaperRelevanceResult(BaseModel):
    is_relevant: bool
    similarity_score: float   # Stage-1 cosine similarity; used for ranking downstream


def _build_paper_embedding_text(paper: Paper) -> str:
    """Concatenate paper fields into a single embedding input string.

    Includes title (always present), plus abstract, keywords, and topics when
    non-empty. Field selection matches the configuration used during threshold
    calibration — do not add or remove fields without recalibrating thresholds.
    """
    parts = [paper.title]
    if paper.summary:
        parts.append(paper.summary)
    if paper.keywords:
        parts.append(", ".join(paper.keywords))
    if paper.topics:
        parts.append(", ".join(paper.topics))
    return " ".join(parts)


class PaperRelevanceFilter:
    """Two-stage paper relevance filter combining embedding pre-screening with LLM verification.

    Stage 1 — Embedding similarity (fast, runs for every paper):
        Computes cosine similarity between the research topic and each paper's
        text (title + abstract + keywords + topics). Papers clearly below the
        threshold are rejected; papers clearly above are accepted immediately.
        Biased toward high recall so borderline papers proceed to Stage 2
        rather than being silently dropped.

    Stage 2 — LLM verification (selective, ~41% of papers in practice):
        Invoked only for papers in the ambiguous similarity band where Stage 1
        is unreliable. Uses a survey-heuristic prompt: "would this paper be
        cited in a survey on the topic?" Eliminates false positives that passed
        Stage 1 without incurring LLM cost on clearly relevant/irrelevant papers.

    Threshold values are empirically calibrated on a balanced validation set
    (60 relevant / 60 irrelevant papers). Do not change without recalibration.
    """

    _STAGE1_THRESH = 0.500
    # Lower bound: papers below this cosine similarity are clearly irrelevant.
    # High-recall bias keeps this value low so borderline papers reach Stage 2.

    _STAGE2_BAND_HI = 0.610
    # Upper bound of the ambiguous band. Papers at or above this score are
    # reliably relevant and accepted without LLM cost.
    # Derived from the empirical maximum similarity score among false positives
    # in the validation set (0.607) plus a 0.003 safety buffer.

    def __init__(self, embed_model: LiteLLMEmbedding, llm: LiteLLM) -> None:
        self._embed_model = embed_model
        self._llm = llm
        self._topic_embedding: Optional[List[float]] = None
        self._topic_cache_key: Optional[str] = None

    def assess_relevance(self, paper: Paper, topic: str) -> tuple[bool, float]:
        """Classify a paper as relevant or not. Returns (is_relevant, similarity_score).

        similarity_score is the Stage-1 cosine similarity value, used downstream
        to rank papers when selecting the top-N to download.
        Topic embedding is cached — safe to call repeatedly for the same topic.
        """
        topic_vec = self._get_topic_embedding(topic)
        paper_vec = self._embed_model.get_text_embedding(
            _build_paper_embedding_text(paper)
        )
        sim = cosine_similarity(topic_vec, paper_vec)

        if sim < self._STAGE1_THRESH:
            return False, sim
        if sim >= self._STAGE2_BAND_HI:
            return True, sim
        # Ambiguous band → Stage-2 LLM re-judgment
        return self._llm_verify(paper, topic), sim

    def _llm_verify(self, paper: Paper, topic: str) -> bool:
        """Survey-heuristic LLM classifier for borderline papers.

        Uses extended metadata (primary topic + concepts) beyond what Stage 1
        embeds to give the LLM maximum context for a borderline decision.
        """
        system = RELEVANCE_SURVEY_HEURISTIC_PMT.format(topic=topic)
        user_content = "\n".join([
            f"Title: {paper.title}",
            f"Abstract: {paper.summary or '(none)'}",
            f"Keywords: {', '.join(paper.keywords or []) or '(none)'}",
            f"Topics: {', '.join(paper.topics or []) or '(none)'}",
            f"Primary topic: {paper.primary_category or '(none)'}",
            f"Concepts: {', '.join(paper.concepts or []) or '(none)'}",
        ])
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=user_content),
        ]
        response = self._llm.chat(messages)
        return response.message.content.strip().lower().startswith("yes")

    def _get_topic_embedding(self, topic: str) -> List[float]:
        if topic != self._topic_cache_key:
            self._topic_embedding = self._embed_model.get_text_embedding(topic)
            self._topic_cache_key = topic
        return self._topic_embedding


# ── PDF download ──────────────────────────────────────────────────────────────

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/pdf,*/*",
}
_ARXIV_REQUEST_DELAY = 3  # seconds between ArXiv requests (ToS compliance)


def _fetch_and_write(url: str, dest: Path) -> None:
    """Download *url* to *dest* using browser-like headers.

    Browser headers are required: some OA publishers (e.g. AAAI OJS) block
    requests with the default python-requests User-Agent with HTTP 403.
    """
    response = requests.get(url, headers=_BROWSER_HEADERS, timeout=30)
    response.raise_for_status()
    dest.write_bytes(response.content)


class PaperDownloader:
    """Download a paper PDF using a four-strategy fallback chain.

    Strategies are tried in order; the first that writes a non-empty file is used.
    Strategies requiring an ArXiv ID are skipped when none is available,
    ensuring coverage of non-ArXiv open-access papers (e.g. AAAI diamond OA).

    Strategy order:
    1. arxiv_api        — arxiv.Client() resolves canonical URL (3s rate-limit delay)
    2. arxiv_direct_url — constructed arxiv.org/pdf/{id} URL (3s rate-limit delay)
    3. pyalex_pdf       — Works()[openalex_id].pdf.get() endpoint (no rate limit)
    4. openalex_oa_url  — open_access.oa_url with browser headers (publisher pages)
    """

    def download(self, paper: Paper, dest_dir: Path, filename: str) -> Optional[Path]:
        """Download *paper* PDF to *dest_dir/filename*. Returns path on success, None on failure."""
        dest = dest_dir / filename
        arxiv_id = (paper.external_ids or {}).get("ArXiv")
        openalex_id = paper.entry_id.rstrip("/").split("/")[-1]  # "W2741809807"
        oa_url = (paper.open_access_pdf or {}).get("url")

        strategies: list[tuple[str, Callable[[], None]]] = []
        if arxiv_id:
            strategies += [
                ("arxiv_api",        lambda: self._arxiv_api(arxiv_id, dest)),
                ("arxiv_direct_url", lambda: self._arxiv_direct_url(arxiv_id, dest)),
            ]
        strategies.append(("pyalex_pdf", lambda: self._pyalex_pdf(openalex_id, dest)))
        if oa_url:
            strategies.append(("openalex_oa_url", lambda: self._openalex_oa_url(oa_url, dest)))

        for name, fn in strategies:
            try:
                fn()
                if dest.exists() and dest.stat().st_size > 0:
                    logging.info(f"Downloaded '{paper.title}' via {name}")
                    return dest
            except Exception as e:
                logging.warning(f"Strategy '{name}' failed for '{paper.title}': {e}")

        logging.error(f"All download strategies exhausted for '{paper.title}'")
        return None

    def _arxiv_api(self, arxiv_id: str, dest: Path) -> None:
        time.sleep(_ARXIV_REQUEST_DELAY)
        result = next(arxiv.Client().results(arxiv.Search(id_list=[arxiv_id])))
        _fetch_and_write(result.pdf_url, dest)

    def _arxiv_direct_url(self, arxiv_id: str, dest: Path) -> None:
        time.sleep(_ARXIV_REQUEST_DELAY)
        _fetch_and_write(f"https://arxiv.org/pdf/{arxiv_id}", dest)

    def _pyalex_pdf(self, openalex_id: str, dest: Path) -> None:
        content = Works()[openalex_id].pdf.get()
        if content is None:
            raise ValueError("pyalex returned no PDF content")
        dest.write_bytes(content if isinstance(content, bytes) else content.encode())

    def _openalex_oa_url(self, oa_url: str, dest: Path) -> None:
        _fetch_and_write(oa_url, dest)


def download_paper_pdfs(papers: List[Paper], dest_dir: Path) -> Path:
    """Download PDFs for *papers* into *dest_dir* using the four-strategy fallback chain.

    Each paper is attempted with PaperDownloader; failures are logged and skipped.
    Filenames use ArXiv ID when available, OpenAlex ID as fallback (see _paper_filename).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    downloader = PaperDownloader()
    for paper in papers:
        downloader.download(paper, dest_dir, _paper_filename(paper))
    return dest_dir


# ── marker PDF → markdown (updated to new API) ───────────────────────────────

def paper2md(fname: Path, output_dir: Path, disable_ocr: bool = False) -> Path:
    """
    Convert a PDF to markdown using marker (new API >= 1.0.0).

    Output layout:
        output_dir/{fname.stem}/
            {fname.stem}.md      — full markdown with tables & LaTeX
            metadata.json        — table of contents + page stats
            *.png / *.jpg        — extracted figures
    """
    from marker.converters.pdf import PdfConverter
    from marker.models import create_model_dict
    from marker.output import text_from_rendered
    from marker.config.parser import ConfigParser
    from marker.schema import BlockTypes

    if disable_ocr:
        config = ConfigParser({"skip_ocr_blocks": list(BlockTypes)})
        converter = PdfConverter(
            config=config.generate_config_dict(),
            artifact_dict=create_model_dict(),
        )
    else:
        converter = PdfConverter(artifact_dict=create_model_dict())
    rendered = converter(fname.as_posix())
    markdown_text, _, images = text_from_rendered(rendered)

    subfolder = output_dir / fname.stem
    subfolder.mkdir(parents=True, exist_ok=True)

    (subfolder / f"{fname.stem}.md").write_text(markdown_text, encoding="utf-8")

    for img_name, img_pil in images.items():
        img_pil.save(subfolder / img_name)

    (subfolder / "metadata.json").write_text(
        json.dumps(rendered.metadata, indent=2, default=str), encoding="utf-8"
    )

    logging.info(
        f"marker: saved markdown + {len(images)} image(s) to '{subfolder}'"
    )
    return subfolder


def parse_pdf(pdf_path: Path, force_reparse: bool = False, disable_ocr: bool = False) -> Path:
    md_output_dir = pdf_path.parents[1] / "parsed_papers"

    existing = list((md_output_dir / pdf_path.stem).glob("*.md"))
    if existing and not force_reparse:
        logging.info(
            f"Markdown already exists for '{pdf_path.name}', skipping "
            f"(use force_reparse=True to re-parse)"
        )
        return md_output_dir / pdf_path.stem

    logging.info(f"Converting '{pdf_path.name}' to markdown via marker...")
    return paper2md(pdf_path, md_output_dir, disable_ocr=disable_ocr)


def parse_paper_pdfs(papers_dir: Path, force_reparse: bool = False, disable_ocr: bool = False):
    for f in papers_dir.rglob("*.pdf"):
        summary_exists = (
            f.parents[1] / "summaries" / f"{f.stem}_summary.md"
        ).exists()
        if summary_exists:
            logging.info(f"Summary already exists for '{f.name}', skipping")
            continue
        logging.info(f"Parsing '{f.name}'...")
        parse_pdf(f, force_reparse, disable_ocr=disable_ocr)


# ── CLI entry point ───────────────────────────────────────────────────────────

@click.command()
@click.argument("research_topic", type=str, default="Automatic Presentation Slides Generation")
def main(research_topic: str):
    papers = fetch_candidate_papers(research_topic)
    logging.info(f"Found {len(papers)} candidate papers")
    if papers:
        download_paper_pdfs(papers, Path(__file__).parent / "data" / "papers")


if __name__ == "__main__":
    main()
