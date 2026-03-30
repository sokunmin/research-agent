"""
services/llms.py — LLM singletons and factories (all backed by LiteLLM).
Configure via .env: LLM_SMART_MODEL, LLM_FAST_MODEL, LLM_VISION_MODEL.
"""
from services.model_factory import model_factory

# ── Singletons ────────────────────────────────────────────────────────────────
llm = model_factory.smart_llm()
vlm = model_factory.vision_llm()

# ── Factories ─────────────────────────────────────────────────────────────────
def new_llm(temperature: float = 0.0):
    return model_factory.smart_llm(temperature=temperature)


def new_fast_llm(temperature: float = 0.0):
    return model_factory.fast_llm(temperature=temperature)


def new_vlm(temperature: float = 0.0, callback_manager=None):
    return model_factory.vision_llm(temperature=temperature, callback_manager=callback_manager)
