"""
test_3_marker.py
Tests for paper2md(), parse_pdf(), and parse_paper_pdfs().

WARNING: First run will download marker models (~3-5GB).
         This may take 10-20 minutes on a slow connection.

No LLM API key required.
"""
import json
import time
from pathlib import Path

import pytest

from agent_workflows.paper_scraping import (
    download_paper_arxiv,
    paper2md,
    parse_pdf,
    parse_paper_pdfs,
)

ARXIV_VIT = "2010.11929"  # "An Image is Worth 16x16 Words" (ViT paper)
PAPERS_DIR = Path("data") / "papers"


@pytest.fixture(scope="module")
def papers_dir():
    """Ensure PAPERS_DIR has the ViT PDF for testing. Downloads if missing."""
    PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    pdf_filename = f"{ARXIV_VIT}.pdf"
    pdf_path = PAPERS_DIR / pdf_filename

    if not (pdf_path.exists() and pdf_path.stat().st_size > 0):
        download_paper_arxiv(ARXIV_VIT, PAPERS_DIR.as_posix(), pdf_filename)

    assert pdf_path.exists(), f"PDF not found after download: {pdf_path}"
    return PAPERS_DIR


@pytest.mark.integration
@pytest.mark.slow
class TestPaper2md:
    def test_returns_subfolder_path(self, papers_dir, tmp_path):
        pdf_path = papers_dir / f"{ARXIV_VIT}.pdf"
        subfolder = paper2md(pdf_path, tmp_path)
        expected = tmp_path / pdf_path.stem
        assert subfolder == expected, f"Path mismatch: got {subfolder}, expected {expected}"

    def test_creates_markdown_files(self, papers_dir, tmp_path):
        pdf_path = papers_dir / f"{ARXIV_VIT}.pdf"
        subfolder = paper2md(pdf_path, tmp_path)
        md_files = list(subfolder.glob("*.md"))
        assert md_files, f"No .md file found in {subfolder}"

    def test_creates_metadata_json(self, papers_dir, tmp_path):
        pdf_path = papers_dir / f"{ARXIV_VIT}.pdf"
        subfolder = paper2md(pdf_path, tmp_path)
        metadata_path = subfolder / "metadata.json"
        assert metadata_path.exists(), f"metadata.json not found in {subfolder}"

    def test_markdown_has_content(self, papers_dir, tmp_path):
        pdf_path = papers_dir / f"{ARXIV_VIT}.pdf"
        subfolder = paper2md(pdf_path, tmp_path)
        md_files = list(subfolder.glob("*.md"))
        assert md_files
        md_text = md_files[0].read_text(encoding="utf-8")
        assert len(md_text) > 100, f".md file is suspiciously short ({len(md_text)} chars)"

    def test_metadata_is_valid_json(self, papers_dir, tmp_path):
        pdf_path = papers_dir / f"{ARXIV_VIT}.pdf"
        subfolder = paper2md(pdf_path, tmp_path)
        metadata_path = subfolder / "metadata.json"
        meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        assert isinstance(meta, dict)


@pytest.mark.integration
@pytest.mark.slow
class TestParsePdf:
    def test_returns_correct_path(self, papers_dir):
        pdf_path = papers_dir / f"{ARXIV_VIT}.pdf"
        parsed_papers_dir = papers_dir.parent / "parsed_papers"
        subfolder = parse_pdf(pdf_path, force_reparse=True)
        expected = parsed_papers_dir / pdf_path.stem
        assert subfolder == expected, f"Path mismatch: got {subfolder}, expected {expected}"

    def test_creates_output(self, papers_dir):
        pdf_path = papers_dir / f"{ARXIV_VIT}.pdf"
        subfolder = parse_pdf(pdf_path, force_reparse=True)
        md_files = list(subfolder.glob("*.md"))
        assert md_files, f"No .md file in parse_pdf() output: {subfolder}"

    def test_cache_is_fast_on_second_run(self, papers_dir):
        pdf_path = papers_dir / f"{ARXIV_VIT}.pdf"
        # Ensure first run already done (force_reparse=True elsewhere)
        parse_pdf(pdf_path, force_reparse=True)

        t0 = time.monotonic()
        parse_pdf(pdf_path, force_reparse=False)
        elapsed = time.monotonic() - t0

        assert elapsed < 5.0, (
            f"Cache path was slow ({elapsed:.2f}s >= 5.0s) — "
            f"marker may have re-run instead of using cached output"
        )


@pytest.mark.integration
@pytest.mark.slow
class TestPaperPdfBatch:
    def test_batch_processing_completes_without_error(self, papers_dir):
        parse_paper_pdfs(papers_dir, force_reparse=False)

        parsed_papers_dir = papers_dir.parent / "parsed_papers"
        pdf_path = papers_dir / f"{ARXIV_VIT}.pdf"
        parsed_md = list((parsed_papers_dir / pdf_path.stem).glob("*.md"))
        assert parsed_md, f"Output .md missing after parse_paper_pdfs()"
