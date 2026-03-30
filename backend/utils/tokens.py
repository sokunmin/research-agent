from typing import Literal

import tiktoken
from llama_index.core.callbacks import TokenCountingHandler

# cost in dollars per thousand tokens
MODEL_COST = {
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gemini/gemini-2.5-flash": {"input": 0.0, "output": 0.0},  # free tier
}


def _get_tokenizer(model_name: str):
    """Return tiktoken tokenizer; fall back to cl100k_base for unknown models."""
    try:
        return tiktoken.encoding_for_model(model_name).encode
    except KeyError:
        return tiktoken.get_encoding("cl100k_base").encode


def setup_token_counter(model_name: str) -> TokenCountingHandler:
    token_counter = TokenCountingHandler(tokenizer=_get_tokenizer(model_name))
    token_counter.reset_counts()
    return token_counter


def calculate_cost(
    n_tokens: int, ttype: Literal["input", "output"], model_name: str
) -> float:
    n_tokens = n_tokens / 1000
    unit_cost = MODEL_COST.get(model_name, {}).get(ttype, 0.0)
    return n_tokens * unit_cost
