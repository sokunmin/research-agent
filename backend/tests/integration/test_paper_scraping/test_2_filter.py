"""
test_2_filter.py
Tests for PaperRelevanceFilter, _build_paper_embedding_text, _reconstruct_abstract.
Unit tests require no network or LLM. Integration test requires Ollama + LLM key.
"""
import pytest
from unittest.mock import MagicMock, patch

from agent_workflows.paper_scraping import (
    Paper, PaperRelevanceFilter,
    _build_paper_embedding_text, _reconstruct_abstract,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def vit_paper():
    return Paper(
        entry_id="https://openalex.org/W2964445608",
        title="An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale",
        authors=["Alexey Dosovitskiy"],
        summary=(
            "We show that a pure transformer applied directly to sequences of image patches "
            "can perform very well on image classification tasks."
        ),
        keywords=["Vision Transformer", "Image Classification", "Self-attention"],
        topics=["Natural Language Processing", "Computer Vision"],
    )


@pytest.fixture
def stock_paper():
    return Paper(
        entry_id="https://openalex.org/W1111111111",
        title="Deep Learning for Stock Price Prediction Using LSTM Networks",
        authors=["John Smith"],
        summary="We present a LSTM-based model for predicting stock market prices.",
        keywords=["LSTM", "Stock prediction", "Time series"],
        topics=["Finance", "Econometrics"],
    )


# ── Helper ────────────────────────────────────────────────────────────────────

def _make_filter(sim_value: float, llm_says: str = "yes") -> PaperRelevanceFilter:
    """Return a PaperRelevanceFilter with mocked embed model and LLM.

    cosine_similarity is patched per-test; embed return values are irrelevant
    because cosine_similarity is intercepted before it executes.
    """
    embed_mock = MagicMock()
    embed_mock.get_text_embedding.return_value = [1.0]
    llm_mock = MagicMock()
    llm_mock.chat.return_value.message.content = llm_says
    return PaperRelevanceFilter(embed_model=embed_mock, llm=llm_mock)


# ── TestReconstructAbstract — pure unit ───────────────────────────────────────

class TestReconstructAbstract:
    def test_reconstructs_from_inverted_index(self):
        inv = {"Attention": [0], "is": [1], "all": [2], "you": [3], "need": [4]}
        assert _reconstruct_abstract(inv) == "Attention is all you need"

    def test_returns_empty_string_for_empty_index(self):
        assert _reconstruct_abstract({}) == ""

    def test_handles_none_input(self):
        assert _reconstruct_abstract(None) == ""


# ── TestBuildPaperEmbeddingText — pure unit ───────────────────────────────────

class TestBuildPaperEmbeddingText:
    def test_title_always_present(self, vit_paper):
        assert vit_paper.title in _build_paper_embedding_text(vit_paper)

    def test_summary_included_when_present(self, vit_paper):
        assert vit_paper.summary in _build_paper_embedding_text(vit_paper)

    def test_keywords_joined_and_included(self, vit_paper):
        text = _build_paper_embedding_text(vit_paper)
        assert "Vision Transformer" in text and "Image Classification" in text

    def test_empty_optional_fields_excluded(self):
        bare = Paper(entry_id="https://openalex.org/W0", title="Bare title",
                     authors=[], summary="")
        assert _build_paper_embedding_text(bare) == "Bare title"


# ── TestPaperRelevanceFilterUnit — unit, cosine_similarity patched ────────────

class TestPaperRelevanceFilterUnit:
    def test_below_threshold_rejected_no_llm(self, vit_paper):
        f = _make_filter(sim_value=0.49)
        with patch("agent_workflows.paper_scraping.cosine_similarity", return_value=0.49):
            is_rel, score = f.assess_relevance(vit_paper, "vision transformer")
        assert is_rel is False
        assert score == pytest.approx(0.49)
        f._llm.chat.assert_not_called()

    def test_above_band_accepted_no_llm(self, vit_paper):
        f = _make_filter(sim_value=0.62)
        with patch("agent_workflows.paper_scraping.cosine_similarity", return_value=0.62):
            is_rel, score = f.assess_relevance(vit_paper, "vision transformer")
        assert is_rel is True
        f._llm.chat.assert_not_called()

    def test_borderline_yes_llm_returns_true(self, vit_paper):
        f = _make_filter(sim_value=0.55, llm_says="yes")
        with patch("agent_workflows.paper_scraping.cosine_similarity", return_value=0.55):
            is_rel, _ = f.assess_relevance(vit_paper, "vision transformer")
        assert is_rel is True
        f._llm.chat.assert_called_once()

    def test_borderline_no_llm_returns_false(self, vit_paper):
        f = _make_filter(sim_value=0.55, llm_says="no")
        with patch("agent_workflows.paper_scraping.cosine_similarity", return_value=0.55):
            is_rel, _ = f.assess_relevance(vit_paper, "vision transformer")
        assert is_rel is False

    def test_topic_embedding_cached(self, vit_paper, stock_paper):
        """Same topic × 2 papers: embed called 3 times (1 topic + 2 papers)."""
        f = _make_filter(sim_value=0.62)
        with patch("agent_workflows.paper_scraping.cosine_similarity", return_value=0.62):
            f.assess_relevance(vit_paper, "vision transformer")
            f.assess_relevance(stock_paper, "vision transformer")
        assert f._embed_model.get_text_embedding.call_count == 3


# ── TestPaperRelevanceFilterIntegration — real Ollama embed + LLM ─────────────

@pytest.mark.integration
@pytest.mark.llm
class TestPaperRelevanceFilterIntegration:
    def test_vit_paper_scores_above_stock_paper(self, vit_paper, stock_paper):
        """Stage-1 similarity for ViT must exceed stock prediction paper for vision topic."""
        from services.model_factory import model_factory
        rf = PaperRelevanceFilter(
            embed_model=model_factory.relevance_embed_model(),
            llm=model_factory.fast_llm(temperature=0.0),
        )
        topic = "Vision Transformer image classification"
        _, vit_score = rf.assess_relevance(vit_paper, topic)
        _, stock_score = rf.assess_relevance(stock_paper, topic)
        assert vit_score > stock_score, (
            f"ViT score ({vit_score:.3f}) should exceed stock score ({stock_score:.3f})"
        )
