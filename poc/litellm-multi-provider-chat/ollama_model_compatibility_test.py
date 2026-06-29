"""
Comprehensive smoke test: ollama/ vs ollama_chat/ prefix × acomplete/achat × think configs.
Tests 4 models with model-specific think parameter variations.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../backend"))

from llama_index.core.llms import ChatMessage
from services.smart_llm import SmartLiteLLM

OLLAMA_BASE = os.getenv("OLLAMA_API_BASE", "http://localhost:11434")
PROMPT = "Say hello in one word."
TIMEOUT = 60

# Model-specific think configs to test
# Format: (label, extra_body_dict)
MODEL_CONFIGS = {
    "ministral-3:14b-cloud": [
        ("default", {}),
    ],
    "qwen3.5:cloud": [
        ("default",      {}),
        ("think=False",  {"think": False}),
        ("think=low",    {"think": "low"}),
    ],
    "gpt-oss:20b-cloud": [
        ("default",      {}),
        ("think=False",  {"think": False}),
        ("think=low",    {"think": "low"}),
    ],
    "nemotron-3-super:cloud": [
        ("default",      {}),
        ("think=False",  {"think": False}),
        ("think=low",    {"think": "low"}),
    ],
    "gemma4:31b-cloud": [
        ("default",      {}),
        ("think=False",  {"think": False}),
        ("think=low",    {"think": "low"}),
    ],
}

PREFIXES = ["ollama", "ollama_chat"]
METHODS  = ["acomplete", "achat"]


async def test_case(model_str: str, method: str, extra_body: dict) -> tuple[bool, str]:
    try:
        additional_kwargs = {"api_base": OLLAMA_BASE}
        if extra_body:
            additional_kwargs["extra_body"] = extra_body

        llm = SmartLiteLLM(
            model=model_str,
            temperature=0.0,
            max_tokens=128,
            additional_kwargs=additional_kwargs,
        )
        if method == "acomplete":
            resp = await asyncio.wait_for(llm.acomplete(PROMPT), timeout=TIMEOUT)
            text = (resp.text or "").strip()
        else:
            resp = await asyncio.wait_for(
                llm.achat([ChatMessage(role="user", content=PROMPT)]),
                timeout=TIMEOUT,
            )
            text = (resp.message.content or "").strip()

        if not text:
            return False, "(empty response)"
        return True, text[:60]
    except asyncio.TimeoutError:
        return False, f"(timeout >{TIMEOUT}s)"
    except Exception as e:
        return False, str(e)[:100]


async def main():
    # results[(model, prefix, method, label)] = (ok, msg)
    results = {}

    for model, configs in MODEL_CONFIGS.items():
        print(f"\n{'═'*70}")
        print(f"Model: {model}")
        print('═'*70)
        for prefix in PREFIXES:
            for method in METHODS:
                for label, extra_body in configs:
                    model_str = f"{prefix}/{model}"
                    key = (model, prefix, method, label)
                    ok, msg = await test_case(model_str, method, extra_body)
                    results[key] = (ok, msg)
                    status = "✅" if ok else "❌"
                    print(f"  {status} [{prefix}/{method}] think={label:<12} → {msg}")

    # Summary matrix per model
    print(f"\n\n{'═'*70}")
    print("RESULT MATRIX")
    print('═'*70)

    for model, configs in MODEL_CONFIGS.items():
        print(f"\nModel: {model}")
        col_w = 20
        header = f"  {'think config':<14}" + "".join(
            f"{f'{p}/{m}':<{col_w}}" for p in PREFIXES for m in METHODS
        )
        print(header)
        print("  " + "─" * (14 + col_w * len(PREFIXES) * len(METHODS)))
        for label, _ in configs:
            row = f"  {label:<14}"
            for prefix in PREFIXES:
                for method in METHODS:
                    ok = results[(model, prefix, method, label)][0]
                    row += f"{'✅' if ok else '❌':<{col_w}}"
            print(row)

    print("\n\nDONE")


asyncio.run(main())
