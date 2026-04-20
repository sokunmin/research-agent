"""
ModelFactory — provider-agnostic LLM/embedding factory backed by LiteLLM.
Switch providers by changing LLM_*_MODEL env vars in .env — no code changes needed.

Supported model ID formats (LiteLLM):
  gemini/gemini-2.5-flash                           — Google AI Studio (free tier)
  openrouter/meta-llama/llama-3.3-70b-instruct:free — OpenRouter (free tier)
  openai/gpt-4o                                     — OpenAI
  anthropic/claude-3-5-sonnet-20241022              — Anthropic
"""
from typing import Optional

import os
import litellm

from llama_index.core.callbacks import CallbackManager
from llama_index.llms.litellm import LiteLLM
from llama_index.embeddings.litellm import LiteLLMEmbedding
from pydantic import BaseModel, ConfigDict
from services.multimodal import LiteLLMMultiModal


class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    smart_model: str           # high-capability LLM (was: gpt-4o role)
    fast_model: str            # fast/cheap LLM (was: gpt-4o-mini role)
    vision_model: str          # VLM
    vision_fallback_model: str # VLM fallback on 429 (empty string = disabled)
    embed_model: str           # embedding model
    relevance_embed_model: str # embedding model for paper relevance pre-screening
    max_tokens: int = 4096
    disable_ollama_think: bool = False  # pass extra_body={"think": False} (Ollama think-mode models)


class ModelFactory:
    """Provider-agnostic LLM/Embedding factory backed by LiteLLM."""

    def __init__(self, config: ModelConfig):
        self._config = config

    def smart_llm(self, temperature: float = 0.0,
                  callback_manager: Optional[CallbackManager] = None) -> LiteLLM:
        kw = dict(model=self._config.smart_model, temperature=temperature,
                  max_tokens=self._config.max_tokens)
        if self._config.disable_ollama_think:
            kw["additional_kwargs"] = {"extra_body": {"think": False}}
        if callback_manager:
            kw["callback_manager"] = callback_manager
        return LiteLLM(**kw)

    def fast_llm(self, temperature: float = 0.0) -> LiteLLM:
        kw = dict(model=self._config.fast_model, temperature=temperature)
        if self._config.disable_ollama_think:
            kw["additional_kwargs"] = {"extra_body": {"think": False}}
        return LiteLLM(**kw)

    def embed_model(self) -> LiteLLMEmbedding:
        # NOTE: LiteLLMEmbedding uses `model_name`, not `model`
        return LiteLLMEmbedding(model_name=self._config.embed_model)

    def relevance_embed_model(self) -> LiteLLMEmbedding:
        """Embedding model for Stage-1 paper relevance pre-screening.
        Isolated from the general embed_model to allow independent calibration.
        """
        return LiteLLMEmbedding(model_name=self._config.relevance_embed_model)

    def vision_llm(
        self,
        temperature: float = 0.0,
        callback_manager: Optional[CallbackManager] = None,
    ) -> LiteLLMMultiModal:
        kw = dict(
            model=self._config.vision_model,
            temperature=temperature,
            max_tokens=self._config.max_tokens,
        )
        if callback_manager:
            kw["callback_manager"] = callback_manager
        if self._config.vision_fallback_model:
            kw["fallback_models"] = [self._config.vision_fallback_model]
        return LiteLLMMultiModal(**kw)


def _register_ollama_function_calling(config: ModelConfig) -> None:
    """Dynamically register all local Ollama models as function-calling capable.

    Ollama Modelfiles often omit the {{ tools }} block even when the underlying
    engine supports tool calls.  LiteLLM's /api/show heuristic then returns
    supports_function_calling=False, which causes LlamaIndex's
    FunctionCallingProgram guard to raise before any API call is made.

    Only runs when at least one configured model uses the ollama/ provider to
    avoid an unnecessary HTTP call in non-Ollama environments.

    Ref: https://docs.litellm.ai/docs/providers/ollama#tool-calling
    """
    model_names = [config.fast_model, config.smart_model, config.vision_model]
    if not any(m.startswith("ollama/") for m in model_names):
        return

    # Ollama does not support OpenAI-specific params (e.g. parallel_tool_calls)
    # injected by LlamaIndex's FunctionCallingProgram. Drop them silently.
    litellm.drop_params = True

    from litellm.llms.ollama.common_utils import OllamaModelInfo
    api_base = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
    raw_models = OllamaModelInfo().get_models(api_base=api_base)
    # get_models() returns bare names (e.g. "qwen3.5:2b") on success, but
    # silently falls back to prefixed names (e.g. "ollama/llama2") when the
    # Ollama server is unreachable.  Skip prefixed entries to avoid double-
    # prefixing and registering stale fallback models.
    litellm.register_model(model_cost={
        f"ollama/{name}": {"supports_function_calling": True}
        for name in raw_models
        if not name.startswith("ollama/")
    })


def _build() -> ModelFactory:
    from config import settings
    config = ModelConfig(
        smart_model=settings.LLM_SMART_MODEL,
        fast_model=settings.LLM_FAST_MODEL,
        vision_model=settings.LLM_VISION_MODEL,
        vision_fallback_model=settings.LLM_VISION_FALLBACK_MODEL,
        embed_model=settings.LLM_EMBED_MODEL,
        relevance_embed_model=settings.LLM_RELEVANCE_EMBED_MODEL,
        max_tokens=settings.MAX_TOKENS,
        disable_ollama_think=settings.DISABLE_OLLAMA_THINK,
    )
    _register_ollama_function_calling(config)
    return ModelFactory(config)


model_factory: ModelFactory = _build()
