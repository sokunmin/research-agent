"""
services/llms.py — LLM singletons and factories.
Provider is configured via .env (LLM_SMART_MODEL, LLM_FAST_MODEL).
VLM (vision) still uses Azure until Phase 4 (litellm-vlm).
"""
from llama_index.multi_modal_llms.azure_openai import AzureOpenAIMultiModal

from config import settings
from services.model_factory import model_factory

# ── Text LLM singletons (purpose-based names) ────────────────────────────────
llm = model_factory.smart_llm()

# ── VLM singleton — still Azure until Phase 4 ────────────────────────────────
vlm = AzureOpenAIMultiModal(
    azure_deployment=settings.AZURE_OPENAI_GPT4O_MODEL,
    model=settings.AZURE_OPENAI_GPT4O_MODEL,
    temperature=0.0,
    max_new_tokens=settings.MAX_TOKENS,
    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
    api_key=settings.AZURE_OPENAI_API_KEY,
    api_version=settings.AZURE_OPENAI_API_VERSION,
)


# ── Factories ─────────────────────────────────────────────────────────────────
def new_llm(temperature: float = 0.0):
    return model_factory.smart_llm(temperature=temperature)


def new_fast_llm(temperature: float = 0.0):
    return model_factory.fast_llm(temperature=temperature)


def new_vlm(temperature: float = 0.0, callback_manager=None):
    """VLM factory — still Azure until Phase 4."""
    return AzureOpenAIMultiModal(
        azure_deployment=settings.AZURE_OPENAI_GPT4O_MODEL,
        model=settings.AZURE_OPENAI_GPT4O_MODEL,
        temperature=temperature,
        max_new_tokens=settings.MAX_TOKENS,
        azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        api_key=settings.AZURE_OPENAI_API_KEY,
        api_version=settings.AZURE_OPENAI_API_VERSION,
        callback_manager=callback_manager,
    )
