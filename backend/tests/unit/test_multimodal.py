"""
Unit tests for services/multimodal.py — LiteLLMMultiModal.
All tests use stdlib unittest.mock; no API key required.
"""
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.multimodal import (
    LiteLLMMultiModal,
    _image_block_to_content_block,
    _image_doc_to_content_block,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mock_response(text="hello"):
    mock_resp = MagicMock()
    mock_resp.choices[0].message.content = text
    return mock_resp


# ── Image conversion helpers ───────────────────────────────────────────────────

class TestImageDocConversion:
    def test_url_doc_returns_image_url_block(self):
        # Use SimpleNamespace to bypass LlamaIndex URL validation
        from types import SimpleNamespace
        doc = SimpleNamespace(
            image_url="https://example.com/img.jpg",
            image=None,
            image_path=None,
            image_mimetype=None,
        )
        block = _image_doc_to_content_block(doc)
        assert block["type"] == "image_url"
        assert block["image_url"]["url"] == "https://example.com/img.jpg"

    def test_bytes_doc_returns_base64_block(self):
        # Use SimpleNamespace to control image field directly
        from types import SimpleNamespace
        raw = b"\xff\xd8\xff"  # JPEG magic bytes
        doc = SimpleNamespace(
            image_url=None,
            image=raw,
            image_path=None,
            image_mimetype="image/jpeg",
        )
        block = _image_doc_to_content_block(doc)
        assert block["type"] == "image_url"
        url = block["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        decoded = base64.b64decode(url.split(",", 1)[1])
        assert decoded == raw

    def test_empty_doc_raises_value_error(self):
        from llama_index.core.schema import ImageDocument
        doc = ImageDocument()
        with pytest.raises(ValueError, match="no image data"):
            _image_doc_to_content_block(doc)


class TestImageBlockConversion:
    def test_url_block_returns_image_url_block(self):
        from llama_index.core.llms import ImageBlock
        block = ImageBlock(url="https://example.com/img.png")
        result = _image_block_to_content_block(block)
        assert result["type"] == "image_url"
        assert "example.com" in result["image_url"]["url"]

    def test_bytes_block_returns_base64_block(self):
        from llama_index.core.llms import ImageBlock
        # LlamaIndex may encode image bytes internally; just verify the URL format is correct
        raw = b"\x89PNG"  # PNG magic bytes
        block = ImageBlock(image=raw, image_mimetype="image/png")
        result = _image_block_to_content_block(block)
        assert result["type"] == "image_url"
        url = result["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")

    def test_empty_block_raises_value_error(self):
        from llama_index.core.llms import ImageBlock
        block = ImageBlock()
        with pytest.raises(ValueError, match="no image data"):
            _image_block_to_content_block(block)


# ── Metadata ───────────────────────────────────────────────────────────────────

class TestLiteLLMMultiModalMetadata:
    def test_model_name(self):
        vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
        assert vlm.metadata.model_name == "gemini/gemini-2.5-flash"

    def test_num_output_default(self):
        vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
        assert vlm.metadata.num_output == 4096

    def test_num_output_custom(self):
        vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash", max_tokens=1024)
        assert vlm.metadata.num_output == 1024


# ── complete() / acomplete() ───────────────────────────────────────────────────

class TestLiteLLMMultiModalComplete:
    def test_complete_returns_text(self):
        with patch(
            "services.multimodal.litellm.completion",
            return_value=_make_mock_response("hello"),
        ) as mock_call:
            vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
            resp = vlm.complete("Say hello", image_documents=[])
            assert resp.text == "hello"
            assert mock_call.call_args[1]["model"] == "gemini/gemini-2.5-flash"

    def test_complete_passes_temperature(self):
        with patch(
            "services.multimodal.litellm.completion",
            return_value=_make_mock_response(),
        ) as mock_call:
            vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash", temperature=0.7)
            vlm.complete("prompt", image_documents=[])
            assert mock_call.call_args[1]["temperature"] == 0.7

    def test_complete_with_image_doc_passes_content(self):
        # Use SimpleNamespace to bypass LlamaIndex URL validation
        from types import SimpleNamespace
        with patch(
            "services.multimodal.litellm.completion",
            return_value=_make_mock_response("described"),
        ) as mock_call:
            vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
            doc = SimpleNamespace(
                image_url="https://example.com/img.jpg",
                image=None,
                image_path=None,
                image_mimetype=None,
            )
            vlm.complete("Describe", image_documents=[doc])
            messages = mock_call.call_args[1]["messages"]
            content = messages[0]["content"]
            assert content[0]["type"] == "text"
            assert content[1]["type"] == "image_url"

    async def test_acomplete_returns_text(self):
        mock_resp = _make_mock_response("async hello")
        with patch(
            "services.multimodal.litellm.acompletion",
            new=AsyncMock(return_value=mock_resp),
        ):
            vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
            resp = await vlm.acomplete("Say hello", image_documents=[])
            assert resp.text == "async hello"

    async def test_acomplete_passes_model(self):
        mock_resp = _make_mock_response()
        with patch(
            "services.multimodal.litellm.acompletion",
            new=AsyncMock(return_value=mock_resp),
        ) as mock_call:
            vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
            await vlm.acomplete("prompt", image_documents=[])
            assert mock_call.call_args[1]["model"] == "gemini/gemini-2.5-flash"


# ── chat() / achat() ──────────────────────────────────────────────────────────

class TestLiteLLMMultiModalChat:
    def test_chat_plain_content(self):
        from llama_index.core.base.llms.types import ChatMessage, MessageRole
        with patch(
            "services.multimodal.litellm.completion",
            return_value=_make_mock_response("pong"),
        ) as mock_call:
            vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
            msg = ChatMessage(role=MessageRole.USER, content="ping")
            resp = vlm.chat([msg])
            assert resp.message.content == "pong"
            sent = mock_call.call_args[1]["messages"]
            # In LlamaIndex 0.13+, content may be a list of blocks or a plain string
            sent_content = sent[0]["content"]
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
            vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
            msg = ChatMessage(
                role=MessageRole.USER,
                blocks=[
                    TextBlock(text="What is in this image?"),
                    ImageBlock(url="https://example.com/img.jpg"),
                ],
            )
            vlm.chat([msg])
            sent = mock_call.call_args[1]["messages"]
            content = sent[0]["content"]
            assert any(b["type"] == "text" for b in content)
            assert any(b["type"] == "image_url" for b in content)

    async def test_achat_returns_text(self):
        from llama_index.core.base.llms.types import ChatMessage, MessageRole
        mock_resp = _make_mock_response("async pong")
        with patch(
            "services.multimodal.litellm.acompletion",
            new=AsyncMock(return_value=mock_resp),
        ):
            vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
            msg = ChatMessage(role=MessageRole.USER, content="ping")
            resp = await vlm.achat([msg])
            assert resp.message.content == "async pong"


# ── Streaming — raises NotImplementedError ────────────────────────────────────

class TestLiteLLMMultiModalStreamingNotImplemented:
    def test_stream_complete_raises(self):
        vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
        with pytest.raises(NotImplementedError):
            vlm.stream_complete("prompt", image_documents=[])

    def test_stream_chat_raises(self):
        vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
        with pytest.raises(NotImplementedError):
            vlm.stream_chat([])

    async def test_astream_complete_raises(self):
        vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
        with pytest.raises(NotImplementedError):
            await vlm.astream_complete("prompt", image_documents=[])

    async def test_astream_chat_raises(self):
        vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
        with pytest.raises(NotImplementedError):
            await vlm.astream_chat([])
