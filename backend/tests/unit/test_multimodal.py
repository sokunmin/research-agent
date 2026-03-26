"""
Unit tests for services/multimodal.py — LiteLLMMultiModal.
All tests use stdlib unittest.mock; no API key required.
"""
import base64
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.multimodal import (
    LiteLLMMultiModal,
    _image_block_to_content_block,
    _image_doc_to_content_block,
)

# ── Test constants ─────────────────────────────────────────────────────────────

# Local Ollama VLM; think mode disabled so responses don't include <think>…</think> tokens.
_TEST_MODEL = "ollama/qwen3.5:2b"
_NO_THINK = {"extra_body": {"think": False}}

# Real JPEG fixture — used wherever image bytes are passed into litellm or conversion helpers.
_FIXTURES = Path(__file__).parent.parent / "fixtures"
_TEST_IMAGE_BYTES: bytes = (_FIXTURES / "test_image.jpg").read_bytes()
_TEST_IMAGE_MIME = "image/jpeg"


# ── Shared factories ───────────────────────────────────────────────────────────

def _make_vlm(**kwargs) -> LiteLLMMultiModal:
    """LiteLLMMultiModal pre-configured for local testing (no cloud key, no think tokens)."""
    return LiteLLMMultiModal(model=_TEST_MODEL, extra_kwargs=_NO_THINK, **kwargs)


def _make_mock_response(text="hello"):
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = text
    return mock_resp


def _bytes_image_doc():
    """SimpleNamespace image doc backed by the fixture JPEG bytes."""
    from types import SimpleNamespace
    return SimpleNamespace(
        image_url=None,
        image=_TEST_IMAGE_BYTES,
        image_path=None,
        image_mimetype=_TEST_IMAGE_MIME,
    )


# ── Image conversion helpers ───────────────────────────────────────────────────

class TestImageDocConversion:
    def test_bytes_doc_returns_base64_block(self):
        block = _image_doc_to_content_block(_bytes_image_doc())
        assert block["type"] == "image_url"
        url = block["image_url"]["url"]
        assert url.startswith(f"data:{_TEST_IMAGE_MIME};base64,")
        assert base64.b64decode(url.split(",", 1)[1]) == _TEST_IMAGE_BYTES

    def test_empty_doc_raises_value_error(self):
        from llama_index.core.schema import ImageDocument
        with pytest.raises(ValueError, match="no image data"):
            _image_doc_to_content_block(ImageDocument())


class TestImageBlockConversion:
    def test_bytes_block_returns_base64_block(self):
        from llama_index.core.llms import ImageBlock
        result = _image_block_to_content_block(
            ImageBlock(image=_TEST_IMAGE_BYTES, image_mimetype=_TEST_IMAGE_MIME)
        )
        assert result["type"] == "image_url"
        assert result["image_url"]["url"].startswith(f"data:{_TEST_IMAGE_MIME};base64,")

    def test_empty_block_raises_value_error(self):
        from llama_index.core.llms import ImageBlock
        with pytest.raises(ValueError, match="no image data"):
            _image_block_to_content_block(ImageBlock())


# ── Metadata ───────────────────────────────────────────────────────────────────

class TestLiteLLMMultiModalMetadata:
    def test_model_name(self):
        assert _make_vlm().metadata.model_name == _TEST_MODEL

    def test_num_output_default(self):
        assert _make_vlm().metadata.num_output == 4096

    def test_num_output_custom(self):
        assert _make_vlm(max_tokens=1024).metadata.num_output == 1024


# ── complete() / acomplete() ───────────────────────────────────────────────────

class TestLiteLLMMultiModalComplete:
    def test_complete_returns_text(self):
        with patch(
            "services.multimodal.litellm.completion",
            return_value=_make_mock_response("hello"),
        ) as mock_call:
            resp = _make_vlm().complete("Say hello", image_documents=[])
            assert resp.text == "hello"
            assert mock_call.call_args[1]["model"] == _TEST_MODEL

    def test_complete_passes_temperature(self):
        with patch(
            "services.multimodal.litellm.completion",
            return_value=_make_mock_response(),
        ) as mock_call:
            _make_vlm(temperature=0.7).complete("prompt", image_documents=[])
            assert mock_call.call_args[1]["temperature"] == 0.7

    def test_complete_with_image_doc_passes_content(self):
        with patch(
            "services.multimodal.litellm.completion",
            return_value=_make_mock_response("described"),
        ) as mock_call:
            _make_vlm().complete("Describe", image_documents=[_bytes_image_doc()])
            content = mock_call.call_args[1]["messages"][0]["content"]
            assert content[0]["type"] == "text"
            assert content[1]["type"] == "image_url"

    async def test_acomplete_returns_text(self):
        with patch(
            "services.multimodal.litellm.acompletion",
            new=AsyncMock(return_value=_make_mock_response("async hello")),
        ):
            resp = await _make_vlm().acomplete("Say hello", image_documents=[])
            assert resp.text == "async hello"

    async def test_acomplete_passes_model(self):
        with patch(
            "services.multimodal.litellm.acompletion",
            new=AsyncMock(return_value=_make_mock_response()),
        ) as mock_call:
            await _make_vlm().acomplete("prompt", image_documents=[])
            assert mock_call.call_args[1]["model"] == _TEST_MODEL


# ── chat() / achat() ──────────────────────────────────────────────────────────

class TestLiteLLMMultiModalChat:
    def test_chat_plain_content(self):
        from llama_index.core.base.llms.types import ChatMessage, MessageRole
        with patch(
            "services.multimodal.litellm.completion",
            return_value=_make_mock_response("pong"),
        ) as mock_call:
            msg = ChatMessage(role=MessageRole.USER, content="ping")
            resp = _make_vlm().chat([msg])
            assert resp.message.content == "pong"
            sent_content = mock_call.call_args[1]["messages"][0]["content"]
            # In LlamaIndex 0.13+, content may be a list of blocks or a plain string
            if isinstance(sent_content, list):
                assert any("ping" in str(b) for b in sent_content)
            else:
                assert sent_content == "ping"

    def test_chat_with_text_and_image_blocks(self):
        from llama_index.core.base.llms.types import ChatMessage, MessageRole
        from llama_index.core.llms import ImageBlock, TextBlock
        with patch(
            "services.multimodal.litellm.completion",
            return_value=_make_mock_response("described"),
        ) as mock_call:
            msg = ChatMessage(
                role=MessageRole.USER,
                blocks=[
                    TextBlock(text="What is in this image?"),
                    ImageBlock(image=_TEST_IMAGE_BYTES, image_mimetype=_TEST_IMAGE_MIME),
                ],
            )
            _make_vlm().chat([msg])
            content = mock_call.call_args[1]["messages"][0]["content"]
            assert any(b["type"] == "text" for b in content)
            assert any(b["type"] == "image_url" for b in content)

    async def test_achat_returns_text(self):
        from llama_index.core.base.llms.types import ChatMessage, MessageRole
        with patch(
            "services.multimodal.litellm.acompletion",
            new=AsyncMock(return_value=_make_mock_response("async pong")),
        ):
            msg = ChatMessage(role=MessageRole.USER, content="ping")
            resp = await _make_vlm().achat([msg])
            assert resp.message.content == "async pong"


# ── Streaming — raises NotImplementedError ────────────────────────────────────

class TestLiteLLMMultiModalStreamingNotImplemented:
    def test_stream_complete_raises(self):
        with pytest.raises(NotImplementedError):
            _make_vlm().stream_complete("prompt", image_documents=[])

    def test_stream_chat_raises(self):
        with pytest.raises(NotImplementedError):
            _make_vlm().stream_chat([])

    async def test_astream_complete_raises(self):
        with pytest.raises(NotImplementedError):
            await _make_vlm().astream_complete("prompt", image_documents=[])

    async def test_astream_chat_raises(self):
        with pytest.raises(NotImplementedError):
            await _make_vlm().astream_chat([])
