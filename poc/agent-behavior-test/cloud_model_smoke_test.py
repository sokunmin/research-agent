"""
Smoke test for Ollama cloud models.
Tests: basic availability, think mode detection, think=False suppression, function calling.

NOTE on qwen3.5:cloud architecture:
  The model returns thinking tokens in a SEPARATE 'thinking' field (not inline <think> tags).
  litellm uses /api/generate endpoint and reads only the 'response' field.
  When max_tokens is small, the model may exhaust all tokens on thinking,
  leaving response=''. We use max_tokens=500 for Test 1 to avoid this.
  think=False suppresses the thinking field entirely (verified via /api/generate).
"""

import sys
sys.path.insert(0, '/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/backend')

import json
import requests
import litellm

litellm.set_verbose = False  # keep output clean

OLLAMA_BASE = "http://localhost:11434"

# ── Models to test ────────────────────────────────────────────────────────────
# Each entry is a dict with:
#   "candidates": list of name variants to try in order; first success wins.
#   "think_disable": extra_body payload to suppress thinking for Test 2.
#       qwen3 accepts a boolean False; gpt-oss only accepts string levels.
MODELS_TO_TRY = [
    {
        "candidates": ["ollama/qwen3.5:cloud", "ollama/qwen3.5-cloud"],
        "think_disable": {"think": False},        # boolean works for qwen3
        "think_disable_label": 'think=False',
    },
    {
        "candidates": ["ollama/gpt-oss:20b-cloud", "ollama/gpt-oss-20b-cloud"],
        "think_disable": {"think": "low"},         # gpt-oss only accepts string levels
        "think_disable_label": 'think="low" (minimum — cannot fully disable)',
    },
    {
        "candidates": ["ollama/ministral-3:14b-cloud", "ollama/ministral-3-14b-cloud"],
        "think_disable": {"think": False},
        "think_disable_label": 'think=False',
    },
    {
        "candidates": ["ollama/gemma3:27b-cloud", "ollama/gemma3-27b-cloud"],
        "think_disable": {"think": False},
        "think_disable_label": 'think=False',
    },
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def has_think_tags(text: str) -> bool:
    return "<think>" in text if text else False


def is_not_available_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in ["model not found", "404", "not found", "pull", "no such model"])


def preview(text: str, max_len: int = 120) -> str:
    if not text:
        return "(empty)"
    text = text.replace("\n", " ")
    return text[:max_len] + ("..." if len(text) > max_len else "")


def ollama_model_name(litellm_model: str) -> str:
    """Strip 'ollama/' prefix for raw Ollama API calls."""
    return litellm_model.removeprefix("ollama/")


SIMPLE_PROMPT = [{"role": "user", "content": "Reply with exactly: HELLO"}]

TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get weather for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "City name"}
            },
            "required": ["city"]
        }
    }
}]

# ── Direct Ollama API probe ────────────────────────────────────────────────────

def probe_ollama_direct(model_name: str) -> dict:
    """
    Call Ollama /api/chat directly to check for a 'thinking' field
    independent of litellm's response mapping.
    Returns dict with keys: content, has_thinking, thinking_preview, done_reason.
    """
    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/api/chat",
            json={
                "model": model_name,
                "messages": [{"role": "user", "content": "Reply with exactly: HELLO"}],
                "stream": False,
            },
            timeout=90,
        )
        if resp.status_code == 404:
            return {"error": "404 not found"}
        data = resp.json()
        msg = data.get("message", {})
        return {
            "content": msg.get("content", ""),
            "has_thinking": "thinking" in msg,
            "thinking_preview": preview(msg.get("thinking", ""), 150),
            "done_reason": data.get("done_reason", ""),
        }
    except Exception as exc:
        return {"error": str(exc)}


# ── Per-model test runner ──────────────────────────────────────────────────────

def run_tests_for_model(model: str, model_cfg: dict):
    print(f"\n{'='*50}")
    print(f"MODEL: {model}")
    print('='*50)

    raw_name = ollama_model_name(model)
    think_disable = model_cfg["think_disable"]
    think_disable_label = model_cfg["think_disable_label"]

    # ── Test 1: Basic response ─────────────────────────────────────────────────
    print("\nTest 1 — Basic response (max_tokens=500):")
    test1_ok = False
    try:
        resp = litellm.completion(
            model=model,
            messages=SIMPLE_PROMPT,
            max_tokens=500,  # generous to let thinking+response both fit
        )
        content = resp.choices[0].message.content or ""
        reasoning = getattr(resp.choices[0].message, "reasoning_content", None) or ""
        think_inline = has_think_tags(content)
        print(f"  Status: OK")
        print(f"  litellm content: \"{preview(content)}\"")
        print(f"  litellm reasoning_content present: {'YES' if reasoning else 'NO'}")
        print(f"  Has inline <think> tags in content: {'YES' if think_inline else 'NO'}")

        # Also check via direct Ollama API for the 'thinking' field
        direct = probe_ollama_direct(raw_name)
        if "error" not in direct:
            print(f"  [Direct Ollama] content: \"{preview(direct['content'])}\"")
            print(f"  [Direct Ollama] separate 'thinking' field present: {'YES' if direct['has_thinking'] else 'NO'}")
            if direct['has_thinking']:
                print(f"  [Direct Ollama] thinking preview: \"{direct['thinking_preview']}\"")
            print(f"  [Direct Ollama] done_reason: {direct['done_reason']}")
        else:
            print(f"  [Direct Ollama] error: {direct['error']}")

        test1_ok = True
    except Exception as exc:
        if is_not_available_error(exc):
            print(f"  Status: NOT AVAILABLE")
            print(f"  Error: {exc}")
            print(f"\n  (Skipping remaining tests for this model)\n{'='*50}")
            return False  # signal: model not available
        else:
            print(f"  Status: ERROR")
            print(f"  Error: {exc}")

    # ── Test 2: think suppressed (model-specific value) ───────────────────────
    print(f"\nTest 2 — {think_disable_label} (max_tokens=200):")
    try:
        resp2 = litellm.completion(
            model=model,
            messages=SIMPLE_PROMPT,
            max_tokens=200,
            extra_body=think_disable,
        )
        content2 = resp2.choices[0].message.content or ""
        reasoning2 = getattr(resp2.choices[0].message, "reasoning_content", None) or ""
        think2 = has_think_tags(content2)
        print(f"  Status: OK")
        print(f"  litellm content: \"{preview(content2)}\"")
        print(f"  Has inline <think> tags: {'YES' if think2 else 'NO'}")
        print(f"  reasoning_content present: {'YES' if reasoning2 else 'NO'}")

        # Direct Ollama probe with model-specific think_disable value
        try:
            r = requests.post(
                f"{OLLAMA_BASE}/api/chat",
                json={
                    "model": raw_name,
                    "messages": [{"role": "user", "content": "Reply with exactly: HELLO"}],
                    "stream": False,
                    **think_disable,
                },
                timeout=60,
            )
            d = r.json()
            msg2 = d.get("message", {})
            think_val = think_disable.get("think")
            print(f"  [Direct Ollama think={think_val!r}] content: \"{preview(msg2.get('content', ''))}\"")
            print(f"  [Direct Ollama think={think_val!r}] 'thinking' field present: {'YES' if 'thinking' in msg2 else 'NO'}")
        except Exception as de:
            print(f"  [Direct Ollama think suppress] error: {de}")

    except Exception as exc:
        if is_not_available_error(exc):
            print(f"  Status: NOT AVAILABLE")
            print(f"  Error: {exc}")
        else:
            print(f"  Status: ERROR")
            print(f"  Error: {exc}")

    # ── Test 3: Function calling (litellm direct) ──────────────────────────────
    print("\nTest 3 — Function calling (litellm direct, max_tokens=500):")
    try:
        resp3 = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": "What is the weather in Tokyo?"}],
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=500,
        )
        msg = resp3.choices[0].message
        tool_calls = msg.tool_calls
        if tool_calls:
            print(f"  Status: OK")
            print(f"  tool_calls returned: YES")
            for tc in tool_calls:
                print(f"  Tool called: {tc.function.name}(args={tc.function.arguments})")
        else:
            text_fallback = msg.content or ""
            print(f"  Status: OK")
            print(f"  tool_calls returned: NO")
            print(f"  Text fallback: \"{preview(text_fallback)}\"")
    except Exception as exc:
        if is_not_available_error(exc):
            print(f"  Status: NOT AVAILABLE")
            print(f"  Error: {exc}")
        else:
            print(f"  Status: ERROR")
            print(f"  Error: {exc}")

    # ── LlamaIndex metadata ────────────────────────────────────────────────────
    print("\nLlamaIndex metadata:")
    try:
        from llama_index.llms.litellm import LiteLLM
        llm = LiteLLM(model=model, temperature=0.0)
        is_fc = llm.metadata.is_function_calling_model
        print(f"  is_function_calling_model: {is_fc}")
    except ImportError as ie:
        print(f"  ERROR: LlamaIndex not importable — {ie}")
    except Exception as exc:
        print(f"  ERROR: {exc}")

    print('='*50)
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("Smoke test — Ollama cloud models")
    print(f"Ollama endpoint: {OLLAMA_BASE}")

    for model_cfg in MODELS_TO_TRY:
        available = False
        for model_name in model_cfg["candidates"]:
            print(f"\nTrying model name: {model_name}")
            result = run_tests_for_model(model_name, model_cfg)
            if result:  # model responded (even if some tests errored)
                available = True
                break
            # else: not available, try next name variant
        if not available:
            print(f"\n  All name variants exhausted — model not reachable.")

    print("\n\nDone.")


if __name__ == "__main__":
    main()
