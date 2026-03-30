# Cloud Model Smoke Test — Function Calling and Think-Mode Verification

**Date:** 2026-03-29

---

## Background & Motivation

The research agent pipeline uses two LLM roles: a "fast" model for simple tasks and a "smart" model for reasoning-heavy tasks. Ollama supports "cloud" model tags that transparently proxy requests to upstream cloud providers (Alibaba, OpenAI, Mistral, Google) without storing model weights locally. Before wiring any of these models into production code, their actual capabilities need to be verified — specifically whether they support the structured `tool_calls` API format (required for function calling in LlamaIndex), and whether their internal "think mode" (chain-of-thought reasoning) can be disabled to reduce latency.

A prior experiment (`structured_output_methods.md`) confirmed that function calling fails for local Ollama models. This experiment checks whether cloud-routed models through Ollama behave differently, and documents integration gotchas that are not visible from model names or documentation.

---

## Experiment Setup

**4 cloud models tested** (all accessed via Ollama's transparent cloud proxy):

| Model (LiteLLM name) | Ollama raw name | Cloud provider |
|---|---|---|
| `ollama/qwen3.5:cloud` | `qwen3.5:cloud` | Alibaba Qwen |
| `ollama/gpt-oss:20b-cloud` | `gpt-oss:20b-cloud` | OpenAI (open-source 20B) |
| `ollama/ministral-3:14b-cloud` | `ministral-3:14b-cloud` | Mistral |
| `ollama/gemma3:27b-cloud` | `gemma3:27b-cloud` | Google Gemma 3 |

**3 tests per model:**

1. **Basic availability and think mode detection**: sends a simple "Reply with exactly: HELLO" prompt. Checks the raw Ollama `/api/chat` response for a separate `thinking` field (think mode indicator). Note: LiteLLM does not surface this field as `reasoning_content` — the raw Ollama API must be queried directly. `max_tokens=500` used to prevent silent empty responses from thinking models exhausting their token budget.

2. **Think-mode suppression (`think=False`)**: sends the same prompt with `extra_body={"think": False}` via LiteLLM and directly via the Ollama API. Checks whether the `thinking` field disappears. If suppression fails, the `LLM_DISABLE_THINK` config flag will have no effect on latency or cost for that model.

3. **Function calling**: sends "What is the weather in Tokyo?" with a `get_weather` tool definition. Checks whether `choices[0].message.tool_calls` is populated (structured function calling). Also checks LlamaIndex's `LiteLLM(model=...).metadata.is_function_calling_model` to verify whether LlamaIndex correctly auto-detects the capability.

**Hardware:** MacBook M1. All requests route through Ollama at `http://localhost:11434` to upstream cloud providers.

---

## Results

### Summary Table

| Model | Available | Default Think Mode | think=False Works | Function Calling via LiteLLM | LlamaIndex is_function_calling_model |
|---|---|---|---|---|---|
| `ollama/qwen3.5:cloud` | Yes | Yes (separate `thinking` field) | Yes (thinking field removed) | Yes (tool_calls returned) | **False (mismatch)** |
| `ollama/gpt-oss:20b-cloud` | Yes | Yes (separate `thinking` field) | **No (thinking field persists)** | Yes (tool_calls returned) | True (correct) |
| `ollama/ministral-3:14b-cloud` | Yes | No | N/A (no think mode) | **No (plain text JSON fallback)** | False (correct) |
| `ollama/gemma3:27b-cloud` | Yes | No | N/A (no think mode) | **No (plain text JSON fallback)** | False (correct) |

### Per-Model Details

**qwen3.5:cloud:**
- Think mode: active by default — `thinking` field present in raw Ollama response. LiteLLM does not surface this field.
- `think=False`: suppression works at the Ollama protocol level (thinking field removed). However, when called via LiteLLM with `max_tokens=200` + `think=False`, LiteLLM returns empty content — a routing interaction bug. Direct Ollama API call returns correct content.
- Function calling: returns proper `tool_calls` with `get_weather(args={"city": "Tokyo"})`.
- LlamaIndex metadata: `is_function_calling_model = False` — **incorrect (false negative)**. The model supports function calling but LlamaIndex will use text-parsing mode by default.

**gpt-oss:20b-cloud:**
- Think mode: active by default — `thinking` field present. Thinking preview: "The user says: 'Reply with exactly: HELLO'. They want ChatGPT to reply with exactly HELLO."
- `think=False`: **ignored** — the `thinking` field persists even with `think=False` set both via LiteLLM `extra_body` and directly in the Ollama JSON body. This model always thinks.
- Function calling: returns proper `tool_calls` with `get_weather(args={"city": "Tokyo"})`.
- LlamaIndex metadata: `is_function_calling_model = True` — correct.

**ministral-3:14b-cloud:**
- Think mode: none. No `thinking` field in the raw Ollama response.
- `think=False`: no-op (no think mode to suppress).
- Function calling: returns JSON as plain text in a code block (` ```json {"name": "get_weather", "arguments": {"city": "Tokyo"}} ``` `) instead of populating `tool_calls`. The model understands function calling semantically but does not implement the structured tool_calls API format.
- LlamaIndex metadata: `is_function_calling_model = False` — correct.
- Note: this model did not appear in `ollama list` before the test but responded successfully — Ollama fetches cloud model metadata on-demand.

**gemma3:27b-cloud:**
- Think mode: none.
- `think=False`: no-op.
- Function calling: same pattern as ministral-3 — returns JSON code block as plain text, no `tool_calls`. Response has a trailing space: `"HELLO "`.
- LlamaIndex metadata: `is_function_calling_model = False` — correct.

### Think Mode Status

| Model | Default Think Mode | think=False Effect |
|---|---|---|
| `qwen3.5:cloud` | Yes | Effective at protocol level; LiteLLM bug with low max_tokens |
| `gpt-oss:20b-cloud` | Yes | **Ignored — always thinks** |
| `ministral-3:14b-cloud` | No | N/A |
| `gemma3:27b-cloud` | No | N/A |

### Function Calling Support

| Model | tool_calls Format | LlamaIndex Detects Correctly |
|---|---|---|
| `qwen3.5:cloud` | Yes | **No — false negative** |
| `gpt-oss:20b-cloud` | Yes | Yes |
| `ministral-3:14b-cloud` | No | Yes |
| `gemma3:27b-cloud` | No | Yes |

---

## Key Findings

- **2 models support function calling, 2 do not**: `qwen3.5:cloud` and `gpt-oss:20b-cloud` return proper `tool_calls`. `ministral-3:14b-cloud` and `gemma3:27b-cloud` output JSON as plain text and cannot be used with LlamaIndex's function-calling-based structured output.
- **`gpt-oss:20b-cloud` ignores `think=False`**: the model always runs in think mode regardless of the `think=False` parameter. Any `LLM_DISABLE_THINK` configuration relying on this flag will have no effect on latency or cost for this model.
- **LlamaIndex misdetects `qwen3.5:cloud` as not supporting function calling**: `is_function_calling_model` returns `False` for this model even though it correctly returns `tool_calls`. If LlamaIndex auto-selects the program mode, it will use slower text-parsing instead of function calling. A manual override is required.
- **Silent empty response risk for thinking models with low `max_tokens`**: when a thinking model exhausts its token budget on the internal reasoning trace, `message.content` becomes an empty string with `finish_reason = stop` and no error. Setting `max_tokens >= 500` for thinking models is required to prevent this.
- **LiteLLM does not surface the `thinking` field**: both `qwen3.5:cloud` and `gpt-oss:20b-cloud` return a `message.thinking` field in the raw Ollama API response, but LiteLLM maps only `message.content` and never exposes `reasoning_content`. Direct Ollama API calls are required to inspect reasoning chains.

---

## Decision

**Recommended role assignments:**

| Model | Role | Rationale |
|---|---|---|
| `ollama/qwen3.5:cloud` | SMART_LLM | Strong reasoning, function calling. Requires manual `pydantic_program_mode=FUNCTION` override in LlamaIndex. Use `max_tokens >= 500`. |
| `ollama/gpt-oss:20b-cloud` | SMART_LLM | Think mode always on (cannot disable), function calling works, LlamaIndex metadata is correct. Best for deep reasoning tasks. |
| `ollama/ministral-3:14b-cloud` | FAST_LLM | No think mode (low latency), but no `tool_calls` support. Suitable for simple text-in/text-out tasks only — not for structured extraction pipelines using function calling. Use `PydanticProgramMode.LLM`. |
| `ollama/gemma3:27b-cloud` | SMART_LLM (text only) | No think mode, no `tool_calls`. Good for large-context text tasks such as summarization. Use `PydanticProgramMode.LLM`. |

**Minimum `max_tokens` settings:**

| Model | Minimum Recommended max_tokens |
|---|---|
| `qwen3.5:cloud` | 500 |
| `gpt-oss:20b-cloud` | 500 |
| `ministral-3:14b-cloud` | 200 |
| `gemma3:27b-cloud` | 200 |
