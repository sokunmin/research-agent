"""
test_1_download.py
Tests for PaperDownloader, _paper_filename, and download_paper_pdfs.
Unit tests require no network. Integration smoke test requires network access.
"""
import pytest
from unittest.mock import MagicMock, patch

from agent_workflows.paper_scraping import (
    Paper, PaperDownloader, download_paper_pdfs,
    _paper_filename,
)

ARXIV_VIT = "2010.11929"
OPENALEX_VIT = "W2964445608"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def vit_paper():
    return Paper(
        entry_id=f"https://openalex.org/{OPENALEX_VIT}",
        title="An Image is Worth 16x16 Words",
        authors=["Dosovitskiy et al."],
        summary="ViT paper.",
        external_ids={"ArXiv": ARXIV_VIT},
        open_access_pdf={"url": f"https://arxiv.org/pdf/{ARXIV_VIT}"},
    )


@pytest.fixture
def paper_no_arxiv():
    return Paper(
        entry_id="https://openalex.org/W9999999999",
        title="AAAI Diamond OA Paper",
        authors=["Author A"],
        summary="A paper with no ArXiv ID.",
        external_ids={},
        open_access_pdf={"url": "https://ojs.aaai.org/some/paper.pdf"},
    )


# ── TestPaperFilename — pure unit ─────────────────────────────────────────────

class TestPaperFilename:
    def test_arxiv_id_preferred(self, vit_paper):
        assert _paper_filename(vit_paper) == f"{ARXIV_VIT}.pdf"

    def test_openalex_id_fallback(self, paper_no_arxiv):
        assert _paper_filename(paper_no_arxiv) == "W9999999999.pdf"


# ── TestPaperDownloaderStrategies — unit, test each strategy method ───────────

class TestPaperDownloaderStrategies:
    @pytest.fixture
    def downloader(self):
        return PaperDownloader()

    def test_arxiv_api_calls_fetch_and_write(self, downloader, tmp_path):
        dest = tmp_path / "out.pdf"
        mock_result = MagicMock()
        mock_result.pdf_url = f"https://arxiv.org/pdf/{ARXIV_VIT}"
        with patch("agent_workflows.paper_scraping.arxiv.Client") as MockClient, \
             patch("agent_workflows.paper_scraping._fetch_and_write") as mock_fetch, \
             patch("agent_workflows.paper_scraping.time.sleep"):
            MockClient.return_value.results.return_value = iter([mock_result])
            mock_fetch.side_effect = lambda url, d: d.write_bytes(b"%PDF")
            downloader._arxiv_api(ARXIV_VIT, dest)
        mock_fetch.assert_called_once_with(mock_result.pdf_url, dest)

    def test_arxiv_direct_url_calls_fetch_and_write(self, downloader, tmp_path):
        dest = tmp_path / "out.pdf"
        with patch("agent_workflows.paper_scraping._fetch_and_write") as mock_fetch, \
             patch("agent_workflows.paper_scraping.time.sleep"):
            mock_fetch.side_effect = lambda url, d: d.write_bytes(b"%PDF")
            downloader._arxiv_direct_url(ARXIV_VIT, dest)
        mock_fetch.assert_called_once_with(f"https://arxiv.org/pdf/{ARXIV_VIT}", dest)

    def test_pyalex_pdf_writes_bytes_content(self, downloader, tmp_path):
        dest = tmp_path / "out.pdf"
        with patch("agent_workflows.paper_scraping.Works") as MockWorks:
            MockWorks.return_value.__getitem__.return_value.pdf.get.return_value = b"%PDF-pyalex"
            downloader._pyalex_pdf(OPENALEX_VIT, dest)
        assert dest.read_bytes() == b"%PDF-pyalex"

    def test_pyalex_pdf_raises_when_content_none(self, downloader, tmp_path):
        dest = tmp_path / "out.pdf"
        with patch("agent_workflows.paper_scraping.Works") as MockWorks:
            MockWorks.return_value.__getitem__.return_value.pdf.get.return_value = None
            with pytest.raises(ValueError, match="pyalex returned no PDF content"):
                downloader._pyalex_pdf(OPENALEX_VIT, dest)

    def test_openalex_oa_url_calls_fetch_and_write(self, downloader, tmp_path):
        dest = tmp_path / "out.pdf"
        with patch("agent_workflows.paper_scraping._fetch_and_write") as mock_fetch:
            mock_fetch.side_effect = lambda url, d: d.write_bytes(b"%PDF-oa")
            downloader._openalex_oa_url("https://ojs.aaai.org/paper.pdf", dest)
        mock_fetch.assert_called_once_with("https://ojs.aaai.org/paper.pdf", dest)


# ── TestPaperDownloaderFallback — unit, test orchestration of download() ──────

class TestPaperDownloaderFallback:
    @pytest.fixture
    def downloader(self):
        return PaperDownloader()

    def test_returns_path_on_first_strategy_success(self, downloader, vit_paper, tmp_path):
        with patch.object(downloader, "_arxiv_api") as mock:
            mock.side_effect = lambda arxiv_id, dest: dest.write_bytes(b"%PDF")
            result = downloader.download(vit_paper, tmp_path, "out.pdf")
        assert result == tmp_path / "out.pdf"

    def test_skips_arxiv_strategies_for_non_arxiv_paper(self, downloader, paper_no_arxiv, tmp_path):
        with patch.object(downloader, "_arxiv_api") as mock_api, \
             patch.object(downloader, "_arxiv_direct_url") as mock_direct, \
             patch.object(downloader, "_pyalex_pdf") as mock_pyalex:
            mock_pyalex.side_effect = lambda oa_id, dest: dest.write_bytes(b"%PDF")
            downloader.download(paper_no_arxiv, tmp_path, "out.pdf")
        mock_api.assert_not_called()
        mock_direct.assert_not_called()

    def test_falls_back_when_first_strategy_fails(self, downloader, vit_paper, tmp_path):
        with patch.object(downloader, "_arxiv_api", side_effect=Exception("api fail")), \
             patch.object(downloader, "_arxiv_direct_url") as mock_direct:
            mock_direct.side_effect = lambda arxiv_id, dest: dest.write_bytes(b"%PDF")
            result = downloader.download(vit_paper, tmp_path, "out.pdf")
        assert result is not None

    def test_returns_none_when_all_strategies_fail(self, downloader, vit_paper, tmp_path):
        with patch.object(downloader, "_arxiv_api", side_effect=Exception("fail")), \
             patch.object(downloader, "_arxiv_direct_url", side_effect=Exception("fail")), \
             patch.object(downloader, "_pyalex_pdf", side_effect=Exception("fail")), \
             patch.object(downloader, "_openalex_oa_url", side_effect=Exception("fail")):
            result = downloader.download(vit_paper, tmp_path, "out.pdf")
        assert result is None


# ── TestDownloadPaperPdfs — unit, patch PaperDownloader ───────────────────────

class TestDownloadPaperPdfs:
    def test_calls_downloader_for_each_paper(self, vit_paper, paper_no_arxiv, tmp_path):
        with patch("agent_workflows.paper_scraping.PaperDownloader") as MockDownloader:
            mock_inst = MockDownloader.return_value
            mock_inst.download.return_value = tmp_path / "dummy.pdf"
            download_paper_pdfs([vit_paper, paper_no_arxiv], tmp_path)
        assert mock_inst.download.call_count == 2

    def test_creates_dest_dir(self, vit_paper, tmp_path):
        dest = tmp_path / "new_subdir"
        with patch("agent_workflows.paper_scraping.PaperDownloader") as MockDownloader:
            MockDownloader.return_value.download.return_value = None
            download_paper_pdfs([vit_paper], dest)
        assert dest.exists()


# ── TestDownloadIntegration — real network ────────────────────────────────────

@pytest.mark.integration
@pytest.mark.network
class TestDownloadIntegration:
    def test_downloads_vit_via_arxiv(self, vit_paper, tmp_path):
        """Smoke: downloads real ViT PDF, verifies %PDF magic bytes."""
        downloader = PaperDownloader()
        result = downloader.download(vit_paper, tmp_path, _paper_filename(vit_paper))
        assert result is not None, "All download strategies failed"
        assert result.stat().st_size > 0
        assert result.read_bytes()[:4] == b"%PDF"
