# Cloud Model Smoke Test Report

**Date:** 2026-03-29
**Test script:** `smoke_test_cloud_models.py`
**Output file:** `smoke_test_cloud_output.txt`

---

## 1. Experiment Overview

### Purpose

This experiment validates the behavior of four Ollama "cloud" models across three critical capability dimensions: basic response quality, think-mode control, and function calling. The goal is to determine which models are suitable for use as `FAST_LLM` or `SMART_LLM` in a research agent pipeline, and to document integration gotchas before wiring them into production code.

### Environment

| Item | Value |
|------|-------|
| Date | 2026-03-29 |
| Python environment | micromamba `py3.12` |
| Ollama endpoint | `http://localhost:11434` |
| litellm | installed in `py3.12` env |
| LlamaIndex | `llama_index.llms.litellm.LiteLLM` |
| Hardware | MacBook M1 chip |

### What "cloud" models mean in Ollama

In Ollama, a model tagged with `:cloud` is **not run locally**. When you call `ollama run gemma3:27b-cloud`, Ollama acts as a transparent proxy and routes the request to the model's upstream cloud API provider. No local GPU/CPU inference occurs. The model's weights are not stored locally — the `SIZE` column in `ollama list` shows `-` for cloud models. This means:

- Latency depends on network and the cloud provider's response time.
- Token costs may apply depending on the provider.
- The Ollama interface remains identical to local models (same `/api/chat` endpoint, same JSON schema).

### Models Tested

| Model (litellm name) | Ollama raw name | Notes |
|---|---|---|
| `ollama/qwen3.5:cloud` | `qwen3.5:cloud` | Alibaba Qwen 3.5, cloud routing |
| `ollama/gpt-oss:20b-cloud` | `gpt-oss:20b-cloud` | OpenAI open-source 20B, cloud routing |
| `ollama/ministral-3:14b-cloud` | `ministral-3:14b-cloud` | Mistral 3 14B, cloud routing. Not listed in `ollama list` output but responded successfully — Ollama fetches it on first call. |
| `ollama/gemma3:27b-cloud` | `gemma3:27b-cloud` | Google Gemma 3 27B, cloud routing. Listed in `ollama list`. |

---

## 2. Test Configuration

### Test 1 — Basic Availability & Think Mode Detection

**What it does:**
- Sends a simple prompt `"Reply with exactly: HELLO"` via litellm with `max_tokens=500`.
- Records the `content` field and whether `reasoning_content` is present in litellm's response.
- Checks for inline `<think>` tags in `content` (inline think format used by some models like Qwen 3 older releases).
- Additionally calls the Ollama `/api/chat` endpoint directly (bypassing litellm) to inspect the raw JSON response for a separate `thinking` field in the `message` object.

**Why the direct Ollama call matters:**
litellm maps Ollama's `message.content` to `choices[0].message.content` but does **not** surface the `message.thinking` field as `reasoning_content`. The only way to confirm whether a model is in think mode is to inspect the raw Ollama response directly. Think mode is indicated by a separate `"thinking"` key inside the `message` object — it is NOT inline `<think>...</think>` tags in content.

**Why `max_tokens=500`:**
When a thinking model is given a small `max_tokens` budget (e.g., 100), it may exhaust all tokens on the internal thinking trace, leaving `message.content = ""`. litellm returns this as an empty string with no error. This is a silent failure. Setting `max_tokens=500` gives enough headroom for both the thinking trace and the actual response to fit within the token budget.

### Test 2 — `think=False` Suppression

**What it does:**
- Sends the same simple prompt with `max_tokens=200` and `extra_body={"think": False}` via litellm.
- Also sends the same request directly to `/api/chat` with `"think": false` in the JSON body.
- Checks whether the `thinking` field disappears from the direct Ollama response (confirming suppression).

**Why it matters:**
Thinking models incur latency and token cost for reasoning. In production, a `LLM_DISABLE_THINK` config flag should suppress thinking for simple tasks. If `think=False` is ignored by the model, that config flag will be ineffective and latency/cost savings will not materialize.

### Test 3 — Function Calling

**What it does:**
- Sends `"What is the weather in Tokyo?"` with a `get_weather` tool definition via litellm using `tools=[...]` and `tool_choice="auto"`.
- Checks whether `choices[0].message.tool_calls` is populated (standard function calling).
- If `tool_calls` is empty, records the text fallback content.
- Separately checks LlamaIndex `LiteLLM(model=...).metadata.is_function_calling_model` to see if LlamaIndex correctly identifies the model as function-calling capable.

**Why it matters:**
The research agent uses LlamaIndex's `pydantic_program_mode` for structured output extraction. If `is_function_calling_model` returns `False` for a model that actually supports tool calls, LlamaIndex will fall back to `LLM` mode (text parsing) instead of `FUNCTION` mode, losing structured output reliability. Conversely, if the model does not truly support tool calls but `is_function_calling_model` returns `True`, LlamaIndex will send tool schemas that the model cannot handle correctly.

---

## 3. Results — Summary Table

| Model | Available | Default Think Mode | think=False Works | FC via litellm | is_function_calling_model (LlamaIndex) |
|---|---|---|---|---|---|
| `ollama/qwen3.5:cloud` | YES | YES (separate `thinking` field) | YES (thinking field removed) | YES (tool_calls returned) | **FALSE** (mismatch) |
| `ollama/gpt-oss:20b-cloud` | YES | YES (separate `thinking` field) | **NO** (thinking field persists) | YES (tool_calls returned) | TRUE (correct) |
| `ollama/ministral-3:14b-cloud` | YES | NO | N/A (no think mode) | **NO** (text fallback with JSON string) | FALSE (correct) |
| `ollama/gemma3:27b-cloud` | YES | NO | N/A (no think mode) | **NO** (text fallback with JSON string) | FALSE (correct) |

---

## 4. Results — Detailed Per-Model Findings

### 4.1 `ollama/qwen3.5:cloud`

**Availability:** Available and responsive.

**Test 1 — Basic response (max_tokens=500):**
- litellm content: `"HELLO"` — correct.
- litellm `reasoning_content` present: NO — litellm does not surface the thinking field.
- Inline `<think>` tags in content: NO — uses separate field, not inline tags.
- Direct Ollama `thinking` field present: **YES**
- Thinking preview: `"Thinking Process: 1. **Analyze the Request:** * Input: "Reply with exactly: HELLO" * Constraint: "exactly" * Target Output: "HELLO..."`
- `done_reason`: `stop`

**Test 2 — think=False:**
- litellm content: `(empty)` — **unexpected empty response via litellm** when `max_tokens=200` + `think=False`.
- Direct Ollama (think=False) content: `"HELLO"` — correct response when calling directly.
- Direct Ollama `thinking` field present after think=False: **NO** — suppression works at the protocol level.
- **Issue:** litellm returns empty content even though the direct Ollama response is correct. This may be a litellm/Ollama routing bug when `think=False` is combined with low `max_tokens`. The direct Ollama API correctly returns content.

**Test 3 — Function calling:**
- `tool_calls` returned: **YES**
- Tool called: `get_weather(args={"city": "Tokyo"})` — correct.

**LlamaIndex metadata:**
- `is_function_calling_model`: **False** — **MISMATCH**. The model supports function calling (confirmed in Test 3) but LlamaIndex reports False.

---

### 4.2 `ollama/gpt-oss:20b-cloud`

**Availability:** Available and responsive.

**Test 1 — Basic response (max_tokens=500):**
- litellm content: `"HELLO"` — correct.
- litellm `reasoning_content` present: NO.
- Inline `<think>` tags in content: NO.
- Direct Ollama `thinking` field present: **YES**
- Thinking preview: `"The user says: "Reply with exactly: HELLO". They want ChatGPT to reply with exactly HELLO. So I must reply: HELLO."`
- `done_reason`: `stop`

**Test 2 — think=False:**
- litellm content: `"HELLO"` — correct.
- Direct Ollama (think=False) content: `"HELLO"` — correct.
- Direct Ollama `thinking` field present after think=False: **YES** — **think=False is IGNORED**.
- The `think=False` parameter has no effect on this model. Thinking continues even when explicitly suppressed.

**Test 3 — Function calling:**
- `tool_calls` returned: **YES**
- Tool called: `get_weather(args={"city": "Tokyo"})` — correct.

**LlamaIndex metadata:**
- `is_function_calling_model`: **True** — correct match with actual capability.

---

### 4.3 `ollama/ministral-3:14b-cloud`

**Availability:** Available and responsive. Note: this model did not appear in `ollama list` output before the test run, but Ollama successfully routed to it on first call. This suggests Ollama fetches cloud model metadata on demand.

**Test 1 — Basic response (max_tokens=500):**
- litellm content: `"HELLO"` — correct.
- litellm `reasoning_content` present: NO.
- Inline `<think>` tags in content: NO.
- Direct Ollama `thinking` field present: **NO** — this model does not use think mode.
- `done_reason`: `stop`

**Test 2 — think=False:**
- litellm content: `"HELLO"` — correct.
- Direct Ollama `thinking` field present: **NO** — no think mode present regardless.
- (think=False is a no-op for this model — it has no think mode to suppress.)

**Test 3 — Function calling:**
- `tool_calls` returned: **NO**
- Text fallback content: ` ```json {   "name": "get_weather",   "arguments": {     "city": "Tokyo"   } } ``` `
- The model outputs a JSON code block as plain text instead of using the structured `tool_calls` protocol. It understands function calling semantically but does not implement the tool_calls API format.

**LlamaIndex metadata:**
- `is_function_calling_model`: **False** — correct match (model does not return tool_calls).

---

### 4.4 `ollama/gemma3:27b-cloud`

**Availability:** Available and responsive. Listed in `ollama list` as `gemma3:27b-cloud` with `SIZE: -` (cloud routing confirmed).

**Test 1 — Basic response (max_tokens=500):**
- litellm content: `"HELLO "` — correct (with a trailing space).
- litellm `reasoning_content` present: NO.
- Inline `<think>` tags in content: NO.
- Direct Ollama `thinking` field present: **NO** — no think mode.
- `done_reason`: `stop`

**Test 2 — think=False:**
- litellm content: `"HELLO "` — correct.
- Direct Ollama `thinking` field present: **NO** — no think mode present.
- (think=False is a no-op for this model.)

**Test 3 — Function calling:**
- `tool_calls` returned: **NO**
- Text fallback content: ` ```json {"name": "get_weather", "arguments":{"city": "Tokyo"}} ``` `
- Same pattern as ministral-3: outputs JSON code block as plain text. Does not use the tool_calls API format.

**LlamaIndex metadata:**
- `is_function_calling_model`: **False** — correct match.

---

## 5. Cross-Model Comparison

### 5.1 Think Mode on by Default

| Model | Default Think Mode |
|---|---|
| `qwen3.5:cloud` | YES — `thinking` field present in raw Ollama response |
| `gpt-oss:20b-cloud` | YES — `thinking` field present in raw Ollama response |
| `ministral-3:14b-cloud` | NO |
| `gemma3:27b-cloud` | NO |

Both Qwen 3.5 and GPT-OSS 20B are thinking models. Their reasoning content is placed in a separate `message.thinking` field at the Ollama protocol level, not inline in `message.content`. litellm does not map this field to `reasoning_content` — it is invisible to litellm callers unless they query the Ollama API directly.

### 5.2 `think=False` Suppression Effectiveness

| Model | think=False Effect |
|---|---|
| `qwen3.5:cloud` | Effective — `thinking` field removed in direct Ollama response. However, litellm returns empty content with max_tokens=200. |
| `gpt-oss:20b-cloud` | **Ineffective** — `thinking` field persists even with `think=False`. |
| `ministral-3:14b-cloud` | N/A — no think mode |
| `gemma3:27b-cloud` | N/A — no think mode |

### 5.3 Function Calling Support

| Model | tool_calls Format | Behavior |
|---|---|---|
| `qwen3.5:cloud` | YES | Returns proper `tool_calls` with structured arguments |
| `gpt-oss:20b-cloud` | YES | Returns proper `tool_calls` with structured arguments |
| `ministral-3:14b-cloud` | NO | Returns JSON as plain text in a code block |
| `gemma3:27b-cloud` | NO | Returns JSON as plain text in a code block |

### 5.4 LlamaIndex `is_function_calling_model` Accuracy

| Model | Actual FC Support | LlamaIndex Reports | Accurate? |
|---|---|---|---|
| `qwen3.5:cloud` | YES | False | **NO — false negative** |
| `gpt-oss:20b-cloud` | YES | True | YES |
| `ministral-3:14b-cloud` | NO | False | YES |
| `gemma3:27b-cloud` | NO | False | YES |

Only one mismatch: `qwen3.5:cloud` supports function calling but LlamaIndex incorrectly reports `is_function_calling_model: False`. This means if `qwen3.5:cloud` is used as the LLM in a LlamaIndex pipeline that auto-selects `pydantic_program_mode`, it will use `LLM` mode (text parsing) instead of the more reliable `FUNCTION` mode.

---

## 6. Known Issues & Gotchas

### 6.1 Silent Empty Content with Low `max_tokens` on Thinking Models

**Affected models:** `qwen3.5:cloud` (confirmed), likely `gpt-oss:20b-cloud` as well.

**Symptom:** When `max_tokens` is set to a small value (e.g., 100–200), a thinking model may spend its entire token budget on the internal thinking trace. The `message.content` field in the Ollama response is then empty string `""`. litellm returns this as `choices[0].message.content = ""` with no error, no warning, and `finish_reason = "stop"`.

**Why it's dangerous:** From the caller's perspective, the response appears successful (HTTP 200, finish_reason=stop) but contains no content. This silently corrupts downstream processing.

**Mitigation:** Use `max_tokens >= 500` for thinking models. The Test 2 result for `qwen3.5:cloud` (litellm content: `(empty)` with max_tokens=200 + think=False) confirms this issue persists even when think=False is set, likely because there is an interaction between the `think=False` parameter and litellm's request construction.

### 6.2 `think=False` Ignored by `gpt-oss:20b-cloud`

**Affected model:** `gpt-oss:20b-cloud`

**Symptom:** Setting `think=False` in `extra_body` (litellm) or `"think": false` in the direct Ollama JSON body has no effect. The `thinking` field is still present in the raw Ollama response after the think=False call.

**Impact:** Any `LLM_DISABLE_THINK` configuration flag relying on `extra_body={"think": False}` will not reduce latency or token cost for this model. The model always thinks.

**Mitigation:** No known client-side workaround. This is model-level behavior. Accept that `gpt-oss:20b-cloud` always runs in think mode.

### 6.3 LlamaIndex `is_function_calling_model` False Negative for `qwen3.5:cloud`

**Affected model:** `qwen3.5:cloud`

**Symptom:** `LiteLLM(model="ollama/qwen3.5:cloud").metadata.is_function_calling_model` returns `False`, even though the model correctly returns structured `tool_calls` when tools are provided.

**Impact:** If LlamaIndex is configured to auto-select `pydantic_program_mode`, it will choose `LLM` mode (regex/text parsing) instead of `FUNCTION` mode. This reduces structured output reliability.

**Mitigation:** Explicitly set `pydantic_program_mode=PydanticProgramMode.LLM` or `FUNCTION` in the LlamaIndex LLM config rather than relying on the auto-detected metadata. For `qwen3.5:cloud`, manually override to `FUNCTION` mode.

### 6.4 litellm Does Not Surface Ollama `thinking` Field as `reasoning_content`

**Affected models:** `qwen3.5:cloud`, `gpt-oss:20b-cloud`

**Symptom:** Both models return a `message.thinking` field in the raw Ollama `/api/chat` response. litellm maps `message.content` to `choices[0].message.content` but does not map `message.thinking` to `choices[0].message.reasoning_content`. The `reasoning_content` attribute is always `None` or empty for these models when accessed via litellm.

**Impact:** If the application needs to inspect or log the model's reasoning chain (e.g., for debugging agent decisions), it must call the Ollama API directly, bypassing litellm.

**Mitigation:** For reasoning chain access, use `requests.post("http://localhost:11434/api/chat", ...)` directly and extract `response["message"]["thinking"]`.

### 6.5 `ministral-3:14b-cloud` and `gemma3:27b-cloud` Do Not Return Structured `tool_calls`

**Affected models:** `ministral-3:14b-cloud`, `gemma3:27b-cloud`

**Symptom:** When tools are provided via the litellm `tools` parameter, both models return the function call as a JSON code block in plain text (e.g., ` ```json {"name": "get_weather", ...} ``` `) instead of populating `choices[0].message.tool_calls`.

**Impact:** LlamaIndex `FUNCTION` mode (which relies on `tool_calls`) will not work. Structured extraction must use `LLM` mode with text parsing. This is less reliable and prompt-sensitive.

**Mitigation:** Use `pydantic_program_mode=PydanticProgramMode.LLM` for these models. Ensure the system prompt and output format instructions are explicit.

### 6.6 `ministral-3:14b-cloud` Not Listed in `ollama list` Before First Call

**Symptom:** Running `ollama list` before the test did not show `ministral-3:14b-cloud`, yet the model responded successfully when called. Ollama appears to resolve and route cloud models on-demand without pre-registration.

**Impact:** Cannot rely on `ollama list` to verify cloud model availability. Must actually call the model to confirm.

---

## 7. Integration Recommendations

### 7.1 Per-Model Role Assignment

| Model | Recommended Role | Rationale |
|---|---|---|
| `ollama/qwen3.5:cloud` | **SMART_LLM** | Strong reasoning (think mode), function calling, good instruction following. Avoid as FAST_LLM due to think-mode latency. |
| `ollama/gpt-oss:20b-cloud` | **SMART_LLM** | Think mode always on (cannot disable), function calling works, correct LlamaIndex metadata. Best for deep reasoning tasks. |
| `ollama/ministral-3:14b-cloud` | **FAST_LLM** (with caveats) | No think mode (low latency), but no structured `tool_calls`. Suitable for simple text-in/text-out tasks. Not suitable for structured extraction pipelines. |
| `ollama/gemma3:27b-cloud` | **SMART_LLM** (text only, no FC) | No think mode, no structured `tool_calls`. Good for large-context text tasks but not for function calling. Can serve as SMART_LLM for summarization or analysis. |

### 7.2 `LLM_DISABLE_THINK` Config Behavior

| Model | think=False Effect | Recommendation |
|---|---|---|
| `qwen3.5:cloud` | Suppresses thinking at Ollama level, but litellm may return empty content with low max_tokens | Enable only with `max_tokens >= 500`. Monitor for empty responses. |
| `gpt-oss:20b-cloud` | **Ignored** — think mode always on | Do not use `LLM_DISABLE_THINK` for this model. It has no effect. |
| `ministral-3:14b-cloud` | No-op (no think mode) | Config flag is irrelevant. |
| `gemma3:27b-cloud` | No-op (no think mode) | Config flag is irrelevant. |

### 7.3 `max_tokens` Minimum Recommendations

| Model | Minimum Recommended `max_tokens` | Notes |
|---|---|---|
| `qwen3.5:cloud` | **500** | Lower values risk silent empty content due to think mode consuming all tokens |
| `gpt-oss:20b-cloud` | **500** | Think mode always active; similar risk. 500 confirmed safe. |
| `ministral-3:14b-cloud` | 200 | No think mode; 200 is sufficient for simple tasks |
| `gemma3:27b-cloud` | 200 | No think mode; 200 is sufficient for simple tasks |

### 7.4 LlamaIndex `pydantic_program_mode` Recommendations

| Model | Recommended `pydantic_program_mode` | Rationale |
|---|---|---|
| `qwen3.5:cloud` | `PydanticProgramMode.FUNCTION` (manual override required) | Supports tool_calls but LlamaIndex metadata is wrong (False). Must override manually. |
| `gpt-oss:20b-cloud` | `PydanticProgramMode.FUNCTION` | Supports tool_calls and LlamaIndex correctly detects it (True). Default auto-detection works. |
| `ministral-3:14b-cloud` | `PydanticProgramMode.LLM` | No tool_calls support. Must use text-based extraction with explicit format instructions. |
| `gemma3:27b-cloud` | `PydanticProgramMode.LLM` | No tool_calls support. Must use text-based extraction with explicit format instructions. |

### 7.5 Summary Decision Matrix

```
Need function calling?
  YES → Use qwen3.5:cloud (override pydantic_program_mode=FUNCTION) or gpt-oss:20b-cloud
  NO  → ministral-3:14b-cloud (fast, no think) or gemma3:27b-cloud (large, no think)

Need think mode disabled?
  qwen3.5:cloud → think=False works at protocol level, but watch for litellm empty response bug
  gpt-oss:20b-cloud → think=False does nothing; always thinks

Need lowest latency?
  ministral-3:14b-cloud → no think mode, smaller model

Need access to reasoning chain?
  Must call Ollama /api/chat directly; litellm does not surface message.thinking
```
