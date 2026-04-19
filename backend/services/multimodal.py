"""
LiteLLMMultiModal — LlamaIndex-compatible VLM backed by LiteLLM.

Inherits from LlamaIndex's MultiModalLLM abstract base class and is compatible with:
  - MultiModalLLMCompletionProgram.from_defaults(multi_modal_llm=...)  [uses complete()/acomplete()]
  - await vlm.acomplete(prompt, image_documents=[...])                 [uses acomplete()]

Supports any vision-capable model via LiteLLM:
  gemini/gemini-2.5-flash, openai/gpt-4o, anthropic/claude-3-5-sonnet-*, etc.

API notes (verified from wheel source 2026-03):
  - LlamaIndex 0.13+ ChatMessage has .blocks=[ImageBlock(...), TextBlock(...)]
    (0.11 ChatMessage has .content only — getattr fallback handles both)
  - MultiModalLLMCompletionProgram calls complete()/acomplete() — NOT chat()
  - ImageBlock in 0.13.6+: fields are .url, .path, .image (bytes) — NOT .image_url, .image_path
  - MultiModalLLM is a Pydantic BaseModel (via BaseComponent) — use Field declarations
"""
import base64
from pathlib import Path
from typing import Any, Optional, Sequence, Type, Union

import litellm
from pydantic import BaseModel, Field
from llama_index.core.callbacks import CallbackManager
from llama_index.core.multi_modal_llms.base import MultiModalLLM, MultiModalLLMMetadata
from llama_index.core.schema import ImageDocument, ImageNode
from llama_index.core.base.llms.types import (
    CompletionResponse,
    ChatResponse,
    ChatMessage,
    CompletionResponseGen,
    ChatResponseGen,
)
from llama_index.core.llms import ImageBlock, TextBlock


def _image_doc_to_content_block(doc: ImageDocument) -> dict:
    """Convert a LlamaIndex ImageDocument to a LiteLLM image_url content block."""
    if doc.image_path or doc.image:
        raw: bytes = (
            doc.image if isinstance(doc.image, bytes) else Path(doc.image_path).read_bytes()
        )
        b64 = base64.b64encode(raw).decode()
        mime = doc.image_mimetype or "image/jpeg"
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    raise ValueError(f"ImageDocument has no image data: {doc}")


def _image_block_to_content_block(block: ImageBlock) -> dict:
    """Convert a LlamaIndex ImageBlock to a LiteLLM image_url content block."""
    if block.path:
        raw = Path(str(block.path)).read_bytes()
        b64 = base64.b64encode(raw).decode()
        mime = block.image_mimetype or "image/jpeg"
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    if block.image:
        raw = block.image if isinstance(block.image, bytes) else block.image
        b64 = base64.b64encode(raw).decode()
        mime = block.image_mimetype or "image/jpeg"
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
    raise ValueError(f"ImageBlock has no image data: {block}")


class LiteLLMMultiModal(MultiModalLLM):
    """
    LlamaIndex MultiModalLLM interface implemented via LiteLLM.
    Configure the model via LLM_VISION_MODEL env var (default: gemini/gemini-2.5-flash).

    Note: MultiModalLLM extends BaseComponent (Pydantic BaseModel),
    so all config must be declared as Pydantic fields.
    """

    model: str = Field(description="LiteLLM model identifier, e.g. 'gemini/gemini-2.5-flash'")
    temperature: float = Field(default=0.0, description="Sampling temperature")
    max_tokens: int = Field(default=4096, description="Max output tokens")
    extra_kwargs: dict = Field(default_factory=dict, description="Additional kwargs for LiteLLM")
    fallback_models: list = Field(default_factory=list, description="Fallback model IDs tried on 429/error, e.g. ['openrouter/google/gemma-3-27b-it:free']")
    # llama-index-core ≥0.14.19: llms/callbacks.py wrapper checks `self.rate_limiter` on any
    # LLM object that goes through the callback system. MultiModalLLM doesn't inherit from
    # BaseLLM so it has no such field — declare it here to stay compatible.
    rate_limiter: Optional[Any] = Field(default=None, exclude=True)

    @property
    def metadata(self) -> MultiModalLLMMetadata:
        return MultiModalLLMMetadata(model_name=self.model, num_output=self.max_tokens)

    def _prompt_to_messages(
        self,
        prompt: str,
        image_documents: Sequence[Union[ImageNode, ImageBlock]],
    ) -> list:
        """Build LiteLLM messages from prompt + image_documents (ImageNode or ImageBlock)."""
        content: list = [{"type": "text", "text": prompt}]
        for doc in image_documents:
            if isinstance(doc, ImageBlock):
                content.append(_image_block_to_content_block(doc))
            else:
                content.append(_image_doc_to_content_block(doc))
        return [{"role": "user", "content": content}]

    def _chat_to_litellm_messages(self, messages: Sequence[ChatMessage]) -> list:
        """
        Convert LlamaIndex ChatMessages to LiteLLM format.
        Handles both 0.13+ blocks-based and legacy plain-content formats.
        """
        result = []
        for m in messages:
            blocks = getattr(m, "blocks", None)
            if blocks:
                content: list = []
                for block in blocks:
                    if isinstance(block, ImageBlock):
                        content.append(_image_block_to_content_block(block))
                    elif isinstance(block, TextBlock):
                        content.append({"type": "text", "text": block.text})
                    else:
                        content.append({"type": "text", "text": str(block)})
                result.append({"role": m.role.value, "content": content})
            else:
                result.append({"role": m.role.value, "content": m.content or ""})
        return result

    # ── Sync methods ──────────────────────────────────────────────────────────

    @staticmethod
    def _clean_response_text(text: str, response_format: Optional[Type[BaseModel]]) -> str:
        """Strip markdown code fences when a structured JSON response is expected.

        Ollama and some open-source fallback models wrap JSON in ```json...```
        fences even when response_format is set. Cloud models (Gemini, OpenAI)
        return pure JSON, so stripping is a no-op for them.
        Only applied when response_format is a Pydantic model class (JSON expected).
        """
        if response_format is None:
            return text
        return text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    def _litellm_kwargs(self) -> dict:
        """Common kwargs for every litellm call, including retry and fallback config."""
        kw = dict(
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            num_retries=3,
            **self.extra_kwargs,
        )
        if self.fallback_models:
            kw["fallbacks"] = self.fallback_models
        return kw

    def complete(
        self,
        prompt: str,
        image_documents: Sequence[Union[ImageNode, ImageBlock]],
        response_format: Optional[Type[BaseModel]] = None,
        **kwargs,
    ) -> CompletionResponse:
        messages = self._prompt_to_messages(prompt, image_documents)
        kw = self._litellm_kwargs()
        if response_format is not None:
            kw["response_format"] = response_format
        resp = litellm.completion(model=self.model, messages=messages, **kw, **kwargs)
        text = self._clean_response_text(resp.choices[0].message.content, response_format)
        return CompletionResponse(text=text, raw=resp)

    def chat(
        self,
        messages: Sequence[ChatMessage],
        response_format: Optional[Type[BaseModel]] = None,
        **kwargs,
    ) -> ChatResponse:
        kw = self._litellm_kwargs()
        if response_format is not None:
            kw["response_format"] = response_format
        resp = litellm.completion(model=self.model, messages=self._chat_to_litellm_messages(messages), **kw, **kwargs)
        return ChatResponse(
            message=ChatMessage(role="assistant", content=resp.choices[0].message.content),
            raw=resp,
        )

    # ── Async methods ─────────────────────────────────────────────────────────

    async def acomplete(
        self,
        prompt: str,
        image_documents: Sequence[Union[ImageNode, ImageBlock]],
        response_format: Optional[Type[BaseModel]] = None,
        **kwargs,
    ) -> CompletionResponse:
        messages = self._prompt_to_messages(prompt, image_documents)
        kw = self._litellm_kwargs()
        if response_format is not None:
            kw["response_format"] = response_format
        resp = await litellm.acompletion(model=self.model, messages=messages, **kw, **kwargs)
        text = self._clean_response_text(resp.choices[0].message.content, response_format)
        return CompletionResponse(text=text, raw=resp)

    async def achat(
        self,
        messages: Sequence[ChatMessage],
        response_format: Optional[Type[BaseModel]] = None,
        **kwargs,
    ) -> ChatResponse:
        kw = self._litellm_kwargs()
        if response_format is not None:
            kw["response_format"] = response_format
        resp = await litellm.acompletion(model=self.model, messages=self._chat_to_litellm_messages(messages), **kw, **kwargs)
        return ChatResponse(
            message=ChatMessage(role="assistant", content=resp.choices[0].message.content),
            raw=resp,
        )

    # ── Streaming — not used in current codebase ──────────────────────────────

    def stream_complete(self, *args, **kwargs) -> CompletionResponseGen:
        raise NotImplementedError

    def stream_chat(self, *args, **kwargs) -> ChatResponseGen:
        raise NotImplementedError

    async def astream_complete(self, *args, **kwargs):
        raise NotImplementedError

    async def astream_chat(self, *args, **kwargs):
        raise NotImplementedError
