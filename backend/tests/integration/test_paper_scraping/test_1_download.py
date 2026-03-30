"""
test_1_download.py
Tests for download_paper_arxiv() and download_relevant_citations().
Requires network access; no LLM API key required.
"""
import pytest

from agent_workflows.paper_scraping import (
    download_paper_arxiv,
    download_relevant_citations,
    Paper,
    IsCitationRelevant,
)

ARXIV_VIT = "2010.11929"  # "An Image is Worth 16x16 Words" (ViT paper)


@pytest.mark.integration
@pytest.mark.network
class TestDownloadPaperArxiv:
    def test_creates_pdf_file(self, tmp_path):
        pdf_path = tmp_path / "vit_paper.pdf"
        download_paper_arxiv(ARXIV_VIT, str(tmp_path), "vit_paper.pdf")
        assert pdf_path.exists(), f"PDF file not found at {pdf_path}"
        assert pdf_path.stat().st_size > 0, "PDF file is empty"

    def test_pdf_has_valid_magic_bytes(self, tmp_path):
        pdf_path = tmp_path / "vit_paper.pdf"
        download_paper_arxiv(ARXIV_VIT, str(tmp_path), "vit_paper.pdf")
        with open(pdf_path, "rb") as fh:
            magic = fh.read(4)
        assert magic == b"%PDF", f"File does not look like a PDF (magic bytes: {magic!r})"


@pytest.mark.integration
@pytest.mark.network
class TestDownloadRelevantCitations:
    def test_downloads_relevant_papers_only(self, tmp_path):
        relevant_paper = Paper(
            entry_id="https://openalex.org/W2964445608",
            title="vit_test_paper",
            authors=["Dosovitskiy et al."],
            summary="An image is worth 16x16 words.",
            external_ids={"ArXiv": ARXIV_VIT},
        )
        irrelevant_paper = Paper(
            entry_id="https://openalex.org/W9999999999",
            title="completely_unrelated_paper",
            authors=["Nobody"],
            summary="This paper is about stock price prediction.",
            external_ids={"ArXiv": "1234.56789"},  # fake ID, must not be fetched
        )
        citation_dict = {
            0: {
                "citation": relevant_paper,
                "is_relevant": IsCitationRelevant(score=1, reason="Very relevant"),
            },
            1: {
                "citation": irrelevant_paper,
                "is_relevant": IsCitationRelevant(score=0, reason="Not relevant"),
            },
        }

        returned_dir = download_relevant_citations(citation_dict, paper_dir=tmp_path)

        expected_pdf = tmp_path / f"{relevant_paper.title}.pdf"
        assert expected_pdf.exists(), f"Expected PDF not found: {expected_pdf}"
        assert expected_pdf.stat().st_size > 0, "Relevant paper PDF is empty"

    def test_skips_irrelevant_papers(self, tmp_path):
        relevant_paper = Paper(
            entry_id="https://openalex.org/W2964445608",
            title="vit_test_paper",
            authors=["Dosovitskiy et al."],
            summary="An image is worth 16x16 words.",
            external_ids={"ArXiv": ARXIV_VIT},
        )
        irrelevant_paper = Paper(
            entry_id="https://openalex.org/W9999999999",
            title="completely_unrelated_paper",
            authors=["Nobody"],
            summary="This paper is about stock price prediction.",
            external_ids={"ArXiv": "1234.56789"},
        )
        citation_dict = {
            0: {
                "citation": relevant_paper,
                "is_relevant": IsCitationRelevant(score=1, reason="Very relevant"),
            },
            1: {
                "citation": irrelevant_paper,
                "is_relevant": IsCitationRelevant(score=0, reason="Not relevant"),
            },
        }

        returned_dir = download_relevant_citations(citation_dict, paper_dir=tmp_path)

        unexpected_pdf = tmp_path / f"{irrelevant_paper.title}.pdf"
        assert not unexpected_pdf.exists(), (
            f"Irrelevant paper was downloaded but should have been skipped: {unexpected_pdf}"
        )
        assert returned_dir == tmp_path, (
            f"Return value mismatch: got {returned_dir}, expected {tmp_path}"
        )
