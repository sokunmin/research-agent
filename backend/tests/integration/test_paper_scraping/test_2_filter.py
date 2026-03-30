"""
test_2_filter.py
Tests for filter_relevant_citations() and process_citation().
Requires GEMINI_API_KEY (or another LiteLLM-compatible key).
conftest.py autoskip handles the missing key case.
"""
import asyncio
import pytest

from agent_workflows.paper_scraping import Paper, filter_relevant_citations, process_citation
from services import llms

# ── Hardcoded Paper objects ────────────────────────────────────────────────────

vit_paper = Paper(
    entry_id="https://openalex.org/W2964445608",
    title="An Image is Worth 16x16 Words: Transformers for Image Recognition at Scale",
    authors=["Alexey Dosovitskiy", "Lucas Beyer", "Alexander Kolesnikov"],
    summary=(
        "We show that a pure transformer applied directly to sequences of image patches can "
        "perform very well on image classification tasks. When pre-trained on large amounts of "
        "data and transferred to multiple mid-sized or small image recognition benchmarks "
        "(ImageNet, CIFAR-100, VTAB, etc.), Vision Transformer (ViT) attains excellent results "
        "compared to state-of-the-art convolutional networks while requiring substantially fewer "
        "computational resources to train."
    ),
)

bert_paper = Paper(
    entry_id="https://openalex.org/W2963403341",
    title="BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
    authors=["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee", "Kristina Toutanova"],
    summary=(
        "We introduce a new language representation model called BERT, which stands for "
        "Bidirectional Encoder Representations from Transformers. Unlike recent language "
        "representation models, BERT is designed to pre-train deep bidirectional representations "
        "from unlabeled text by jointly conditioning on both left and right context in all layers. "
        "The pre-trained BERT model can be fine-tuned with just one additional output layer to "
        "create state-of-the-art models for a wide range of tasks."
    ),
)

stock_paper = Paper(
    entry_id="https://openalex.org/W1111111111",
    title="Deep Learning for Stock Price Prediction Using LSTM Networks",
    authors=["John Smith", "Jane Doe"],
    summary=(
        "We present a long short-term memory (LSTM) based deep learning model for predicting "
        "stock market prices. Using historical price and volume data from the S&P 500 index, "
        "our model achieves significantly better mean absolute error compared to traditional "
        "time-series forecasting methods such as ARIMA. The approach leverages multi-step ahead "
        "forecasting and achieves strong out-of-sample performance on unseen trading days."
    ),
)

RESEARCH_TOPIC = "Vision Transformer image classification"
ALL_PAPERS = [vit_paper, bert_paper, stock_paper]


@pytest.mark.integration
@pytest.mark.llm
class TestProcessCitation:
    def test_returns_valid_response(self):
        llm = llms.new_fast_llm(temperature=0.0)
        idx, response = asyncio.run(
            process_citation(0, RESEARCH_TOPIC, vit_paper, llm)
        )
        assert idx == 0
        assert hasattr(response, "score"), "Response missing 'score' attribute"
        assert hasattr(response, "reason"), "Response missing 'reason' attribute"

    def test_vit_paper_scores_above_zero(self):
        llm = llms.new_fast_llm(temperature=0.0)
        _, response = asyncio.run(
            process_citation(0, RESEARCH_TOPIC, vit_paper, llm)
        )
        assert response.score > 0, (
            f"ViT paper unexpectedly scored 0 for topic '{RESEARCH_TOPIC}'"
        )


@pytest.mark.integration
@pytest.mark.llm
class TestFilterRelevantCitations:
    def test_batch_processing_len(self):
        results = asyncio.run(filter_relevant_citations(RESEARCH_TOPIC, ALL_PAPERS))
        assert len(results) == len(ALL_PAPERS)

    def test_batch_result_has_citation_and_is_relevant_keys(self):
        results = asyncio.run(filter_relevant_citations(RESEARCH_TOPIC, ALL_PAPERS))
        for i in range(len(ALL_PAPERS)):
            assert "citation" in results[i], f"Entry {i} missing 'citation' key"
            assert "is_relevant" in results[i], f"Entry {i} missing 'is_relevant' key"

    def test_vit_paper_is_relevant_in_batch(self):
        results = asyncio.run(filter_relevant_citations(RESEARCH_TOPIC, ALL_PAPERS))
        vit_score = results[0]["is_relevant"].score
        assert vit_score > 0, f"ViT paper unexpectedly scored 0 for topic '{RESEARCH_TOPIC}'"

    def test_stock_paper_is_irrelevant(self):
        results = asyncio.run(filter_relevant_citations(RESEARCH_TOPIC, ALL_PAPERS))
        stock_score = results[2]["is_relevant"].score
        assert stock_score == 0, (
            f"Stock paper scored {stock_score} (expected 0) — "
            f"LLM may have misclassified it"
        )
