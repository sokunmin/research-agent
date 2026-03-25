import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import arxiv
import click
import pyalex
from llama_index.core.program import FunctionCallingProgram
from pyalex import Works
from pydantic import BaseModel

from config import settings
from prompts.prompts import IS_CITATION_RELEVANT_PMT
from services import llms
import logging
import sys

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


class Paper(BaseModel):
    entry_id: str
    title: str
    authors: List[str]
    summary: str
    published: Optional[str] = None
    primary_category: Optional[str] = None
    link: Optional[str] = None
    external_ids: Optional[dict] = None
    open_access_pdf: Optional[dict] = None


class IsCitationRelevant(BaseModel):
    score: int
    reason: str


# ── OpenAlex module-level config ─────────────────────────────────────────────

pyalex.config.email = settings.OPENALEX_EMAIL
if settings.OPENALEX_API_KEY:
    pyalex.config.api_key = settings.OPENALEX_API_KEY

# ── OpenAlex helpers ──────────────────────────────────────────────────────────

def _extract_arxiv_id(work: dict) -> Optional[str]:
    """Extract ArXiv paper ID from OpenAlex work locations list."""
    for loc in work.get("locations", []):
        url = loc.get("landing_page_url") or ""
        if "arxiv.org" in url:
            # e.g. https://arxiv.org/abs/2101.03961 → "2101.03961"
            return url.rstrip("/").split("/")[-1]
    return None


def _work_to_paper(result: dict) -> Paper:
    """Convert an OpenAlex Work dict to the Paper model."""
    authors = [
        a["author"]["display_name"]
        for a in result.get("authorships", [])
        if a.get("author")
    ]
    primary_topic = result.get("primary_topic") or {}
    field = (primary_topic.get("field") or {}).get("display_name")

    arxiv_id = _extract_arxiv_id(result)
    oa_url = (result.get("open_access") or {}).get("oa_url")

    return Paper(
        entry_id=result["id"],
        title=result.get("title") or "",
        authors=authors,
        summary=result.get("abstract") or "",
        published=result.get("publication_date"),
        primary_category=field,
        link=result.get("doi"),
        external_ids={"ArXiv": arxiv_id} if arxiv_id else {},
        open_access_pdf={"url": oa_url} if oa_url else None,
    )


def search_papers(query: str, limit: int = 1) -> List[Paper]:
    results = Works().search_filter(title_and_abstract=query).get(per_page=limit)
    return [_work_to_paper(r) for r in results]


def get_citing_papers(paper: Paper, limit: int = settings.NUM_MAX_CITING_PAPERS) -> List[Paper]:
    """Return papers that cite *paper* (incoming citations)."""
    results = Works().filter(cites=paper.entry_id).get(per_page=limit)
    papers = []
    for r in results:
        try:
            papers.append(_work_to_paper(r))
        except Exception as e:
            logging.warning(f"Error parsing citation '{r.get('title')}': {e}")
    return papers


def get_paper_with_citations(query: str, limit: int = 1) -> List[Paper]:
    """Search for *query*, then collect its incoming citations."""
    papers = search_papers(query, limit=limit)
    if not papers:
        logging.warning(f"No papers found for query: '{query}'")
        return []
    logging.info(f"Found paper: {papers[0].title}")
    citations = get_citing_papers(papers[0])
    logging.info(f"Found {len(citations)} citations")
    citations.append(papers[0])
    return citations


# ── Relevance filtering (unchanged) ──────────────────────────────────────────

async def process_citation(i, research_topic, citation, llm):
    program = FunctionCallingProgram.from_defaults(
        llm=llm,
        output_cls=IsCitationRelevant,
        prompt_template_str=IS_CITATION_RELEVANT_PMT,
        verbose=True,
    )
    response = await program.acall(
        research_topic=research_topic,
        title=citation.title,
        abstract=citation.summary,
        description="Data model for whether the paper is relevant to the research topic.",
    )
    return i, response


async def filter_relevant_citations(
    research_topic: str, citations: List[Paper]
) -> Dict[str, Any]:
    llm = llms.new_fast_llm(temperature=0.0)
    tasks = [
        process_citation(i, research_topic, citation, llm)
        for i, citation in enumerate(citations)
    ]
    results = await asyncio.gather(*tasks)

    citations_w_relevance = {}
    for i, response in results:
        citations_w_relevance[i] = {
            "citation": citations[i],
            "is_relevant": response,
        }
    return citations_w_relevance


# ── ArXiv download (unchanged) ────────────────────────────────────────────────

def download_paper_arxiv(paper_id: str, download_dir: str, filename: str):
    max_retries = 3
    retry_delay = 5

    for attempt in range(max_retries):
        try:
            paper = next(arxiv.Client().results(arxiv.Search(id_list=[paper_id])))
            logging.info(f"Downloading: {paper.title} → {download_dir}/{filename}")
            paper.download_pdf(dirpath=download_dir, filename=filename)
            logging.info("Done!")
            return
        except Exception as e:
            logging.warning(f"Download attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                logging.info(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                logging.error("Max retries reached.")
                raise


def download_relevant_citations(
    citation_dict: Dict[str, Any], paper_dir: Path = None
) -> Path:
    if not paper_dir:
        paper_dir = Path(__file__).parent / "data" / "papers"
    paper_dir.mkdir(parents=True, exist_ok=True)

    relevant = [
        v for v in citation_dict.values() if v["is_relevant"].score > 0
    ]
    logging.info(f"Downloading {len(relevant)} relevant papers...")

    for v in citation_dict.values():
        if v["is_relevant"].score > 0:
            ext_ids = v["citation"].external_ids or {}
            if "ArXiv" in ext_ids and ext_ids["ArXiv"]:
                logging.info(f"Downloading: {v['citation'].title}")
                download_paper_arxiv(
                    ext_ids["ArXiv"],
                    paper_dir.as_posix(),
                    f"{v['citation'].title}.pdf",
                )
            else:
                logging.info(f"No ArXiv ID for '{v['citation'].title}', skipping.")
    return paper_dir


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
@click.argument(
    "research_topic",
    type=str,
    default="Automatic Presentation Slides Generation",
)
@click.argument(
    "entry_paper_title",
    type=str,
    default="DOC2PPT: Automatic Presentation Slides Generation from Scientific Documents",
)
def main(research_topic: str, entry_paper_title: str):
    citations = get_paper_with_citations(entry_paper_title)
    if citations:
        relevant_citations = asyncio.run(
            filter_relevant_citations(research_topic, citations)
        )
        paper_dir = download_relevant_citations(relevant_citations)
        parse_paper_pdfs(paper_dir)


if __name__ == "__main__":
    main()
