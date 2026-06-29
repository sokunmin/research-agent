"""
ModelFactory — provider-agnostic LLM/embedding factory backed by LiteLLM.
Switch providers by editing data/model_profiles.json — no code changes needed.
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

import litellm

logger = logging.getLogger(__name__)

from llama_index.core.callbacks import CallbackManager
from llama_index.embeddings.litellm import LiteLLMEmbedding
from services.smart_llm import SmartLiteLLM
from pydantic import BaseModel, ConfigDict
from services.multimodal import LiteLLMMultiModal


class LLMSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    model: str
    extra_body: dict = {}

    def make_llm(self, temperature: float, max_tokens: int | None = None,
                 callback_manager: Optional[CallbackManager] = None) -> SmartLiteLLM:
        kw: dict = {"model": self.model, "temperature": temperature}
        if max_tokens is not None:
            kw["max_tokens"] = max_tokens
        if self.extra_body:
            kw["additional_kwargs"] = {"extra_body": self.extra_body}
        if callback_manager:
            kw["callback_manager"] = callback_manager
        logger.info("[LLMSpec] SmartLiteLLM: %s", kw)
        return SmartLiteLLM(**kw)


class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    smart_model: LLMSpec
    fast_model: LLMSpec
    vision_model: str
    vision_fallback_model: str
    embed_model: str
    max_tokens: int = 4096


class ModelFactory:
    """Provider-agnostic LLM/Embedding factory backed by LiteLLM."""

    def __init__(self, config: ModelConfig):
        self._config = config

    def smart_llm(self, temperature: float = 0.0,
                  callback_manager: Optional[CallbackManager] = None) -> SmartLiteLLM:
        return self._config.smart_model.make_llm(temperature, self._config.max_tokens, callback_manager)

    def fast_llm(self, temperature: float = 0.0) -> SmartLiteLLM:
        return self._config.fast_model.make_llm(temperature)

    def embed_model(self) -> LiteLLMEmbedding:
        """Embedding model for relevance filtering, RAG summarization, and Qdrant indexing."""
        return LiteLLMEmbedding(model_name=self._config.embed_model)

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


def _build() -> ModelFactory:
    from config import settings
    raw = json.loads(Path(settings.MODEL_PROFILES_PATH).read_text())
    roles = raw["roles"]
    model_args = raw.get("models", {})

    def _make_model_spec(model_str: str) -> LLMSpec:
        extra_body = model_args.get(model_str, {}).get("extra_body", {})
        return LLMSpec(model=model_str, extra_body=extra_body)

    config = ModelConfig(
        smart_model=_make_model_spec(roles["smart"]),
        fast_model=_make_model_spec(roles["fast"]),
        vision_model=roles["vision"],
        vision_fallback_model=roles.get("vision_fallback", ""),
        embed_model=roles["embed"],
        max_tokens=settings.MAX_TOKENS,
    )
    logger.info(
        "[ModelFactory] config loaded: smart=%s fast=%s vision=%s embed=%s OLLAMA_API_BASE=%s",
        config.smart_model.model, config.fast_model.model, config.vision_model, config.embed_model,
        os.getenv("OLLAMA_API_BASE", "(not set)"),
    )
    if any(s.model.startswith("ollama") for s in [config.smart_model, config.fast_model]):
        litellm.drop_params = True
    return ModelFactory(config)


model_factory: ModelFactory = _build()
