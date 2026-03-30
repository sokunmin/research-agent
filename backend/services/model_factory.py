"""
ModelFactory — provider-agnostic LLM/embedding factory backed by LiteLLM.
Switch providers by changing LLM_*_MODEL env vars in .env — no code changes needed.

Supported model ID formats (LiteLLM):
  gemini/gemini-2.5-flash                           — Google AI Studio (free tier)
  openrouter/meta-llama/llama-3.3-70b-instruct:free — OpenRouter (free tier)
  openai/gpt-4o                                     — OpenAI
  anthropic/claude-3-5-sonnet-20241022              — Anthropic
"""
from dataclasses import dataclass
from typing import Optional

from llama_index.core.callbacks import CallbackManager
from llama_index.llms.litellm import LiteLLM
from llama_index.embeddings.litellm import LiteLLMEmbedding
from services.multimodal import LiteLLMMultiModal


@dataclass
class ModelConfig:
    smart_model: str    # high-capability LLM (was: gpt-4o role)
    fast_model: str     # fast/cheap LLM (was: gpt-4o-mini role)
    vision_model: str   # VLM — used in Phase 4 only
    embed_model: str    # embedding model
    max_tokens: int = 4096


class ModelFactory:
    """Provider-agnostic LLM/Embedding factory backed by LiteLLM."""

    def __init__(self, config: ModelConfig):
        self._config = config

    def smart_llm(self, temperature: float = 0.0,
                  callback_manager: Optional[CallbackManager] = None) -> LiteLLM:
        kw = dict(model=self._config.smart_model, temperature=temperature,
                  max_tokens=self._config.max_tokens)
        if callback_manager:
            kw["callback_manager"] = callback_manager
        return LiteLLM(**kw)

    def fast_llm(self, temperature: float = 0.0) -> LiteLLM:
        return LiteLLM(model=self._config.fast_model, temperature=temperature)

    def embed_model(self) -> LiteLLMEmbedding:
        # NOTE: LiteLLMEmbedding uses `model_name`, not `model`
        return LiteLLMEmbedding(model_name=self._config.embed_model)

    def vision_llm(
        self,
        temperature: float = 0.0,
        callback_manager: Optional[CallbackManager] = None,
    ) -> LiteLLMMultiModal:
        return LiteLLMMultiModal(
            model=self._config.vision_model,
            temperature=temperature,
            max_tokens=self._config.max_tokens,
            callback_manager=callback_manager,
        )


def _build() -> ModelFactory:
    from config import settings
    return ModelFactory(ModelConfig(
        smart_model=settings.LLM_SMART_MODEL,
        fast_model=settings.LLM_FAST_MODEL,
        vision_model=settings.LLM_VISION_MODEL,
        embed_model=settings.LLM_EMBED_MODEL,
        max_tokens=settings.MAX_TOKENS,
    ))


model_factory: ModelFactory = _build()
