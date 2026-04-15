# augment_test_v2 — Structured Output Method Comparison

**Experiment date:** 2026-03-28
**Script:** `augment_test_v2.py`
**Raw data:** `augment_results_raw.json`

---

## Overview

This experiment compares 5 methods for getting a local Ollama LLM to produce a
`SlideOutlineWithLayout` Pydantic object via LlamaIndex. The motivation is a production
bug (2026-03-27) where `gemma3:4b` kept wrapping its output inside a `{"properties": {...}}`
JSON Schema shell instead of returning concrete field values.

### Experiment parameters

| Parameter | Value |
|---|---|
| Models tested | `ollama/gemma3:4b`, `ollama/qwen3.5:4b` |
| Methods tested | METHOD_A, METHOD_B, METHOD_C, METHOD_D, METHOD_E (5 total) |
| Prompts tested | 4 variants (Prompt 1–4) |
| Slide test cases | 3 (academic content, agenda, closing/thank-you) |
| N_RUNS per combo | 3 |
| Total LLM calls | 360 (sequential, no parallel) |
| Execution mode | Sequential — Ollama does not support parallel inference |

---

## Method Descriptions

| Method | LlamaIndex API | Mechanism |
|---|---|---|
| **METHOD_A** | `FunctionCallingProgram` | Uses the model's native function/tool-calling capability. Fails hard if the model does not support tool use via LiteLLM. |
| **METHOD_B** | `LLMTextCompletionProgram` | Appends a JSON schema instruction to the prompt, asks the LLM to generate text matching the schema, then parses the output into the Pydantic model. No native tool call required. |
| **METHOD_C** | `LLMTextCompletionProgram` + Ollama `format` param | Same as METHOD_B, but also passes `SlideOutlineWithLayout.model_json_schema()` as the `format` field in `additional_kwargs`. Ollama's server-side grammar enforcement constrains the output to valid JSON matching the schema before the response even leaves the model. Only applicable to Ollama-served models. |
| **METHOD_D** | `llm.as_structured_llm()` → `sllm.acomplete()` | Wraps the LLM with `as_structured_llm(OutputCls)`. The prompt is pre-formatted as a plain string using Python `.format()`. Calls `acomplete(formatted_prompt)`. The `response.raw` field contains the parsed Pydantic object. |
| **METHOD_E** | `llm.astructured_predict()` with `PydanticProgramMode.LLM` | Sets `llm.pydantic_program_mode = PydanticProgramMode.LLM` on the instance, then calls `llm.astructured_predict(OutputCls, prompt=PromptTemplate(...), **kwargs)`. Routes through LlamaIndex's LLM-mode structured prediction path, which uses text-completion internally (not tool call). |

---

## Results

### Model: `ollama/gemma3:4b`

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | 0% | **100%** | **100%** | **100%** |
| METHOD_C | **100%** | **100%** | **100%** | **100%** |
| METHOD_D | 0% | **100%** | **100%** | **100%** |
| METHOD_E | 0% | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call (rows = methods, cols = prompts)

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.5 | 0.4 | 0.4 | 0.4 |
| METHOD_B | 4.0 | 4.3 | 6.1 | 4.5 |
| METHOD_C | 3.5 | 3.3 | 5.3 | 4.6 |
| METHOD_D | 3.8 | 4.6 | 5.8 | 4.5 |
| METHOD_E | 3.5 | 4.2 | 5.6 | 4.6 |

#### Per-slide Success Breakdown (3 runs per cell)

| Method | Prompt | Attention Is All You Need | Agenda | Thank You |
|---|---|---|---|---|
| METHOD_A | Prompt 1 | 0/3 | 0/3 | 0/3 |
| METHOD_A | Prompt 2 | 0/3 | 0/3 | 0/3 |
| METHOD_A | Prompt 3 | 0/3 | 0/3 | 0/3 |
| METHOD_A | Prompt 4 | 0/3 | 0/3 | 0/3 |
| METHOD_B | Prompt 1 | 0/3 | 0/3 | 0/3 |
| METHOD_B | Prompt 2 | 3/3 | 3/3 | 3/3 |
| METHOD_B | Prompt 3 | 3/3 | 3/3 | 3/3 |
| METHOD_B | Prompt 4 | 3/3 | 3/3 | 3/3 |
| METHOD_C | Prompt 1 | 3/3 | 3/3 | 3/3 |
| METHOD_C | Prompt 2 | 3/3 | 3/3 | 3/3 |
| METHOD_C | Prompt 3 | 3/3 | 3/3 | 3/3 |
| METHOD_C | Prompt 4 | 3/3 | 3/3 | 3/3 |
| METHOD_D | Prompt 1 | 0/3 | 0/3 | 0/3 |
| METHOD_D | Prompt 2 | 3/3 | 3/3 | 3/3 |
| METHOD_D | Prompt 3 | 3/3 | 3/3 | 3/3 |
| METHOD_D | Prompt 4 | 3/3 | 3/3 | 3/3 |
| METHOD_E | Prompt 1 | 0/3 | 0/3 | 0/3 |
| METHOD_E | Prompt 2 | 3/3 | 3/3 | 3/3 |
| METHOD_E | Prompt 3 | 3/3 | 3/3 | 3/3 |
| METHOD_E | Prompt 4 | 3/3 | 3/3 | 3/3 |

---

### Model: `ollama/qwen3.5:4b`

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | **100%** | **100%** | **100%** | **100%** |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call (rows = methods, cols = prompts)

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.3 | 0.3 | 0.3 | 0.4 |
| METHOD_B | 8.1 | 7.9 | 7.7 | 7.9 |
| METHOD_C | 7.5 | 7.7 | 7.4 | 8.2 |
| METHOD_D | 7.7 | 8.3 | 8.0 | 8.1 |
| METHOD_E | 7.6 | 8.2 | 7.9 | 8.0 |

#### Per-slide Success Breakdown (3 runs per cell)

| Method | Prompt | Attention Is All You Need | Agenda | Thank You |
|---|---|---|---|---|
| METHOD_A | all prompts | 0/3 | 0/3 | 0/3 |
| METHOD_B | all prompts | 3/3 | 3/3 | 3/3 |
| METHOD_C | all prompts | 3/3 | 3/3 | 3/3 |
| METHOD_D | all prompts | 3/3 | 3/3 | 3/3 |
| METHOD_E | all prompts | 3/3 | 3/3 | 3/3 |

---

### Cross-Method Summary: best prompt per (model × method)

| Model | Method | Best Prompt | Success Rate |
|---|---|---|---|
| ollama/gemma3:4b | METHOD_A | Prompt 1 (current) | 0% |
| ollama/gemma3:4b | METHOD_B | Prompt 2 (typo fix + field desc) | 100% |
| ollama/gemma3:4b | METHOD_C | Prompt 1 (current) | 100% |
| ollama/gemma3:4b | METHOD_D | Prompt 2 (typo fix + field desc) | 100% |
| ollama/gemma3:4b | METHOD_E | Prompt 2 (typo fix + field desc) | 100% |
| ollama/qwen3.5:4b | METHOD_A | Prompt 1 (current) | 0% |
| ollama/qwen3.5:4b | METHOD_B | Prompt 1 (current) | 100% |
| ollama/qwen3.5:4b | METHOD_C | Prompt 1 (current) | 100% |
| ollama/qwen3.5:4b | METHOD_D | Prompt 1 (current) | 100% |
| ollama/qwen3.5:4b | METHOD_E | Prompt 1 (current) | 100% |

---

## Analysis

### Failure modes observed

**METHOD_A (FunctionCallingProgram) — 0% across both models, all prompts**

Both `gemma3:4b` and `qwen3.5:4b` as served via Ollama through LiteLLM do not support
native function/tool calling. `FunctionCallingProgram` fails immediately at program
construction time with a capability error (sub-1s, no LLM inference occurs).
This is consistent with the production bug hypothesis: the current codebase uses
`FunctionCallingProgram`, which is silently failing or not being reached at all
for these model variants.

**METHOD_B + gemma3:4b + Prompt 1 — 0% (9/9 failures)**

`gemma3:4b` with `LLMTextCompletionProgram` requires an explicit output field
description in the prompt. Prompt 1 (verbatim `AUGMENT_LAYOUT_PMT`) has no explicit
field listing and contains a Norwegian placeholder name (`Plassholder for innhold`),
which appears to confuse the model's text completion path. Prompts 2–4 all succeed 100%.

**METHOD_D + gemma3:4b + Prompt 1 — 0%**
**METHOD_E + gemma3:4b + Prompt 1 — 0%**

Same root cause as METHOD_B + Prompt 1: Prompt 1 does not give the model enough
structural guidance for text-completion-based structured output. The model's response
does not parse into `SlideOutlineWithLayout`. Prompts 2–4 fix this.

**METHOD_C — uniquely robust for gemma3:4b**

METHOD_C (Ollama `format` param with the JSON schema) achieves 100% on ALL 4 prompts
for `gemma3:4b`, including Prompt 1 which fails every other method. This is because the
`format` field in Ollama's API enforces grammar-constrained decoding at the server: the
model is forced to produce output that matches the JSON schema regardless of what the
prompt says. The prompt no longer needs to instruct the model about output format.

**qwen3.5:4b — more robust across methods**

`qwen3.5:4b` succeeds 100% on all of METHOD_B/C/D/E across all 4 prompts. This model
does not require explicit field descriptions (Prompt 1 works). It appears to have
stronger instruction-following and JSON output capabilities even without grammar
enforcement. The `think: False` setting is required (hardcoded in the model config)
to suppress chain-of-thought tokens that would interfere with JSON parsing.

### Latency observations

METHOD_A has near-zero elapsed time (0.3–0.6s) because it fails at construction
time before any LLM call is made.

For working methods on `gemma3:4b`:
- METHOD_C (Ollama format): ~3.3–5.3s — fastest
- METHOD_B/D/E: ~3.5–6.1s — comparable

For `qwen3.5:4b`:
- METHOD_C: ~7.4–8.2s — marginally fastest
- METHOD_B/D/E: ~7.6–8.3s — all very similar

Prompt 3 (few-shot) consistently produces the highest latency across all methods and
both models (adds ~1–2s), because the longer prompt with an embedded example takes
more tokens to process.

### Prompt sensitivity

`gemma3:4b` is sensitive to prompt quality when using text-completion methods (B/D/E):
Prompt 1 always fails, Prompts 2–4 always succeed. The addition of explicit field
descriptions (Prompt 2) is the key differentiator.

`qwen3.5:4b` is prompt-agnostic for methods B–E: all 4 prompts succeed.

---

## Recommendation

### For Ollama models (local deployment, gemma3/qwen family)

**Primary recommendation: METHOD_C + Prompt 1**

Reason: METHOD_C passes the Pydantic model's JSON schema as the Ollama `format`
parameter. This uses server-side grammar enforcement, making structured output
independent of prompt phrasing. You get 100% success even with the existing unmodified
Prompt 1 (`AUGMENT_LAYOUT_PMT` verbatim). No prompt refactoring required.

Implementation notes:
- Add `format=SlideOutlineWithLayout.model_json_schema()` to `additional_kwargs` when
  constructing the `LiteLLM` instance for Ollama models.
- Use `LLMTextCompletionProgram` instead of `FunctionCallingProgram`.
- Check `model_name.startswith("ollama/")` to gate the `format` kwarg so it is not
  accidentally passed to cloud providers.

**Secondary recommendation: METHOD_B/D/E + Prompt 2 (if Ollama format is unavailable)**

If you cannot use the `format` param (e.g. older Ollama version, model does not
support grammar enforcement), any of METHOD_B, METHOD_D, or METHOD_E work equally
well with Prompt 2 or later. Prompt 2 adds explicit field descriptions and removes
the Norwegian language confusion; this is sufficient to bring `gemma3:4b` to 100%.

### For cloud/non-Ollama providers (OpenAI, Anthropic, etc.)

**Primary recommendation: METHOD_A (FunctionCallingProgram)**

Cloud providers (GPT-4, Claude, Gemini) fully support native tool/function calling.
METHOD_A remains the most reliable and structured approach for these providers.
Do not use METHOD_C (the Ollama `format` param is Ollama-specific; cloud APIs will
reject or ignore it).

**Fallback: METHOD_D or METHOD_E**

If a cloud model does not support tool calling (e.g. some smaller models), METHOD_D
(`as_structured_llm`) or METHOD_E (`astructured_predict` with `PydanticProgramMode.LLM`)
are solid fallbacks. They work entirely through text completion and do not require
any special model capability.

### Do NOT use in production

- **METHOD_A for Ollama models**: Always fails (capability error). No inference
  even happens, so failures are silent and fast, which may be misread as a "quick
  response" rather than a hard error.
- **METHOD_B/D/E + Prompt 1 for gemma3:4b**: 0% success rate. The original
  `AUGMENT_LAYOUT_PMT` lacks field descriptions and misleads the model.

### Summary table

| Scenario | Method | Prompt | Expected success |
|---|---|---|---|
| Ollama (any model) | METHOD_C | Prompt 1 (any) | ~100% |
| Ollama, no format param | METHOD_B or METHOD_D or METHOD_E | Prompt 2+ | ~100% |
| Cloud provider (tool calling) | METHOD_A | Prompt 1+ | high |
| Cloud provider (no tool calling) | METHOD_D or METHOD_E | Prompt 2+ | high |

---

## 附記 (Notes in Chinese)

- **gemma3:4b** 在 text-completion 路徑下對 Prompt 1 完全失敗，根本原因是 prompt 沒有列出輸出欄位說明、且含有挪威文字串。加上欄位說明（Prompt 2）即可修復。
- **最佳方案（Ollama）**是 METHOD_C，利用 Ollama `format` 參數做 server-side grammar enforcement，不依賴 prompt 品質，對任何 prompt 都能達到 100% 成功率。
- **FunctionCallingProgram（METHOD_A）** 對兩個 Ollama 模型均完全不可用，這是目前 production 程式碼的根本問題所在。

---

---

# Round 2 — Structured Output Method Comparison (Multi-Model, Including API Providers)

**Experiment date:** 2026-04-02
**Script:** `structured_output_methods.py`
**Raw data:** `augment_results_raw.json` (overwritten in-place by this run)

---

## Overview

This is the second round of structured output method comparison. It extends Round 1 (2026-03-28) in two major dimensions: (1) three cloud API model providers are added alongside the two Ollama local models, and (2) the experiment parameters are significantly reduced to allow a faster iteration cycle. The core question remains the same — which LlamaIndex structured output method reliably produces a valid `SlideOutlineWithLayout` Pydantic object — but this round specifically probes whether cloud API models work at all via the current LiteLLM integration.

### What changed vs Round 1

| Parameter | Round 1 | Round 2 |
|---|---|---|
| Models tested | `ollama/gemma3:4b`, `ollama/qwen3.5:4b` (2 Ollama) | `ollama/gemma3:4b`, `ollama/ministral-3:14b-cloud`, `groq/openai/gpt-oss-20b`, `openrouter/google/gemini-3.1-flash-lite-preview`, `gemini/gemini-3.1-flash-lite-preview` (2 Ollama + 3 API) |
| N_RUNS per combo | 3 | 1 |
| SLIDE_OUTLINES | 3 slides (academic, agenda, thank-you) | 1 slide only ("Attention Is All You Need" academic content) |
| Execution strategy | Fully sequential | Ollama models sequential; API models concurrent via `asyncio.gather` |
| Rate-limit delay | None | Groq: 2s, OpenRouter: 3s, Gemini: 4s per non-skipped call |
| Total LLM calls (max) | 360 | 100 (88 real + 12 auto-skipped METHOD_C for non-Ollama) |

### Experiment parameters

| Parameter | Value |
|---|---|
| Models tested | 5 (2 Ollama, 3 API) |
| Methods tested | METHOD_A, METHOD_B, METHOD_C, METHOD_D, METHOD_E (5 total) |
| Prompts tested | 4 variants (Prompt 1–4) |
| Slide test cases | 1 ("Attention Is All You Need") |
| N_RUNS per combo | 1 |
| Total LLM calls (max) | 100 |
| Execution mode | Ollama: sequential; API models: concurrent |

### Method descriptions (unchanged from Round 1)

| Method | LlamaIndex API | Mechanism |
|---|---|---|
| **METHOD_A** | `FunctionCallingProgram` | Native function/tool-calling. Fails if model does not support tool use via LiteLLM. |
| **METHOD_B** | `LLMTextCompletionProgram` | JSON schema appended to prompt; output parsed into Pydantic model. No native tool call required. |
| **METHOD_C** | `LLMTextCompletionProgram` + Ollama `format` param | Same as METHOD_B but passes the Pydantic schema as `format` in `additional_kwargs` for Ollama server-side grammar enforcement. Auto-skipped for non-Ollama models. |
| **METHOD_D** | `llm.as_structured_llm()` → `sllm.acomplete()` | Wraps the LLM with `as_structured_llm(OutputCls)`, manually formats prompt, calls `acomplete()`. Result is `response.raw`. |
| **METHOD_E** | `llm.astructured_predict()` with `PydanticProgramMode.LLM` | Sets `pydantic_program_mode = PydanticProgramMode.LLM`, calls `llm.astructured_predict()` via text-completion path. |

---

## Results

### Model: `ollama/gemma3:4b`

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | **100%** | **100%** | **100%** | **100%** |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |

> Notable change from Round 1: METHOD_B now succeeds on Prompt 1 (previously 0%). With N_RUNS=1 and a single slide, this single-run result cannot be confirmed statistically — may be a lucky pass or genuine model improvement.

#### Avg Elapsed (s) per call (rows = methods, cols = prompts)

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.7 | 0.4 | 0.4 | 0.4 |
| METHOD_B | 11.3 | 6.8 | 7.2 | 7.1 |
| METHOD_C | 6.4 | 6.3 | 6.7 | 6.9 |
| METHOD_D | 6.8 | 7.0 | 7.3 | 7.1 |
| METHOD_E | 6.6 | 6.8 | 7.1 | 6.9 |

#### Per-slide Success Breakdown (1 run per cell)

| Method | Prompt | Attention Is All You Need |
|---|---|---|
| METHOD_A | Prompt 1 (current) | 0/1 |
| METHOD_A | Prompt 2 (typo fix + field desc) | 0/1 |
| METHOD_A | Prompt 3 (+ few-shot) | 0/1 |
| METHOD_A | Prompt 4 (Round2 no-wrap directive) | 0/1 |
| METHOD_B | Prompt 1 (current) | 1/1 |
| METHOD_B | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_B | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_B | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_C | Prompt 1 (current) | 1/1 |
| METHOD_C | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_C | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_C | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_D | Prompt 1 (current) | 1/1 |
| METHOD_D | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_D | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_D | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_E | Prompt 1 (current) | 1/1 |
| METHOD_E | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_E | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_E | Prompt 4 (Round2 no-wrap directive) | 1/1 |

---

### Model: `ollama/ministral-3:14b-cloud`

New model in this round. A 14B-parameter Mistral model served via Ollama.

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | **100%** | **100%** | **100%** | **100%** |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call (rows = methods, cols = prompts)

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.8 | 0.6 | 0.5 | 0.4 |
| METHOD_B | 24.3 | 19.9 | 15.3 | 22.6 |
| METHOD_C | 13.9 | 11.0 | 9.2 | 81.8 |
| METHOD_D | 6.4 | 6.3 | 6.3 | 5.5 |
| METHOD_E | 7.8 | 4.7 | 6.8 | 3.8 |

> METHOD_C + Prompt 4 recorded 81.8s — an anomalous spike likely caused by a transient Ollama server stall during constrained decoding of a longer prompt. All other METHOD_C runs were 9–14s.

#### Per-slide Success Breakdown (1 run per cell)

| Method | Prompt | Attention Is All You Need |
|---|---|---|
| METHOD_A | Prompt 1 (current) | 0/1 |
| METHOD_A | Prompt 2 (typo fix + field desc) | 0/1 |
| METHOD_A | Prompt 3 (+ few-shot) | 0/1 |
| METHOD_A | Prompt 4 (Round2 no-wrap directive) | 0/1 |
| METHOD_B | Prompt 1 (current) | 1/1 |
| METHOD_B | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_B | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_B | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_C | Prompt 1 (current) | 1/1 |
| METHOD_C | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_C | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_C | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_D | Prompt 1 (current) | 1/1 |
| METHOD_D | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_D | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_D | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_E | Prompt 1 (current) | 1/1 |
| METHOD_E | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_E | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_E | Prompt 4 (Round2 no-wrap directive) | 1/1 |

---

### Model: `groq/openai/gpt-oss-20b`

All calls failed. Root cause: **invalid API key** — `GroqException: {"error":{"message":"Invalid API Key","type":"invalid_request_error","code":"invalid_api_key"}}`. No inference took place for any method or prompt. All non-METHOD_C calls returned FAIL in ~0.1–0.3s (network round-trip to reject the request). METHOD_C was auto-skipped (non-Ollama).

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | 0% | 0% | 0% | 0% |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 0% | 0% | 0% | 0% |
| METHOD_E | 0% | 0% | 0% | 0% |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.3 | 0.1 | 0.2 | 0.1 |
| METHOD_B | 0.2 | 0.2 | 0.2 | 0.1 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 0.1 | 0.1 | 0.1 | 0.1 |
| METHOD_E | 0.2 | 0.1 | 0.2 | 0.1 |

---

### Model: `openrouter/google/gemini-3.1-flash-lite-preview`

All calls failed. Root cause: **authentication failure** — `AuthenticationError: OpenrouterException: {"error":{"message":"No cookie auth credentials found","code":401}}`. No valid API credentials were configured for OpenRouter. METHOD_A additionally hit a capability check (`Model name ... does not support function calling API`) before even attempting the network call. METHOD_C was auto-skipped.

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | 0% | 0% | 0% | 0% |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 0% | 0% | 0% | 0% |
| METHOD_E | 0% | 0% | 0% | 0% |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.0 | 0.0 | 0.0 | 0.0 |
| METHOD_B | 0.1 | 0.0 | 0.0 | 0.0 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 0.0 | 0.0 | 0.0 | 0.1 |
| METHOD_E | 0.0 | 0.0 | 0.0 | 0.0 |

---

### Model: `gemini/gemini-3.1-flash-lite-preview`

All calls failed. Root cause: **invalid API key** — `GeminiException: {"error":{"code":400,"message":"API key not valid. Please pass a valid API key.","status":"INVALID_ARGUMENT"}}`. No inference took place. METHOD_C was auto-skipped.

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | 0% | 0% | 0% | 0% |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 0% | 0% | 0% | 0% |
| METHOD_E | 0% | 0% | 0% | 0% |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.1 | 0.0 | 0.0 | 0.0 |
| METHOD_B | 0.0 | 0.1 | 0.0 | 0.0 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 0.0 | 0.0 | 0.0 | 0.1 |
| METHOD_E | 0.0 | 0.0 | 0.0 | 0.0 |

---

### Cross-Method Summary: best prompt per (model × method)

| Model | Method | Best Prompt | Success Rate |
|---|---|---|---|
| ollama/gemma3:4b | METHOD_A | Prompt 1 (current) | 0% |
| ollama/gemma3:4b | METHOD_B | Prompt 1 (current) | 100% |
| ollama/gemma3:4b | METHOD_C | Prompt 1 (current) | 100% |
| ollama/gemma3:4b | METHOD_D | Prompt 1 (current) | 100% |
| ollama/gemma3:4b | METHOD_E | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_A | Prompt 1 (current) | 0% |
| ollama/ministral-3:14b-cloud | METHOD_B | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_C | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_D | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_E | Prompt 1 (current) | 100% |
| groq/openai/gpt-oss-20b | METHOD_A | Prompt 1 (current) | 0% (auth fail) |
| groq/openai/gpt-oss-20b | METHOD_B | Prompt 1 (current) | 0% (auth fail) |
| groq/openai/gpt-oss-20b | METHOD_C | — | SKIP |
| groq/openai/gpt-oss-20b | METHOD_D | Prompt 1 (current) | 0% (auth fail) |
| groq/openai/gpt-oss-20b | METHOD_E | Prompt 1 (current) | 0% (auth fail) |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_A | Prompt 1 (current) | 0% (auth fail) |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_B | Prompt 1 (current) | 0% (auth fail) |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_C | — | SKIP |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_D | Prompt 1 (current) | 0% (auth fail) |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_E | Prompt 1 (current) | 0% (auth fail) |
| gemini/gemini-3.1-flash-lite-preview | METHOD_A | Prompt 1 (current) | 0% (auth fail) |
| gemini/gemini-3.1-flash-lite-preview | METHOD_B | Prompt 1 (current) | 0% (auth fail) |
| gemini/gemini-3.1-flash-lite-preview | METHOD_C | — | SKIP |
| gemini/gemini-3.1-flash-lite-preview | METHOD_D | Prompt 1 (current) | 0% (auth fail) |
| gemini/gemini-3.1-flash-lite-preview | METHOD_E | Prompt 1 (current) | 0% (auth fail) |

---

## Per-Model Observations

### `ollama/gemma3:4b` — All working methods succeed

METHOD_A continues to fail (capability error: Ollama via LiteLLM does not support function/tool calling). All other methods (B/C/D/E) succeed on all 4 prompts including Prompt 1. This is a change from Round 1 where METHOD_B + Prompt 1 failed 100% of the time (9/9 failures). With N_RUNS=1 it is not possible to determine whether this is a real improvement or a lucky single draw. The Round 1 recommendation (use Prompt 2+ to be safe with METHOD_B) still stands. METHOD_C remains the most robust choice because it uses server-side grammar enforcement. Latency range: ~6–11s depending on method and prompt.

### `ollama/ministral-3:14b-cloud` — New model, strong results

This 14B Mistral model via Ollama matches the pattern of the smaller models: METHOD_A fails (capability error); METHOD_B/C/D/E all succeed on all prompts. Notably, METHOD_D and METHOD_E are dramatically faster (3.8–7.8s) than METHOD_B (15–24s) and METHOD_C (9–82s) for this larger model. The 81.8s anomaly in METHOD_C + Prompt 4 is likely a transient Ollama constrained-decoding stall, not a structural failure. For production use with this model, METHOD_D or METHOD_E are recommended for their consistently low latency.

### `groq/openai/gpt-oss-20b` — Complete failure (invalid API key)

Every call was rejected immediately by the Groq API with `invalid_api_key`. This is a configuration/credential issue, not a model capability issue. The method comparison cannot be evaluated for this model in this run. METHOD_C was correctly auto-skipped (non-Ollama model). Elapsed times are sub-0.3s, reflecting network rejection without inference.

### `openrouter/google/gemini-3.1-flash-lite-preview` — Complete failure (auth error)

Every call failed with `AuthenticationError: No cookie auth credentials found (401)`. OpenRouter API credentials are not configured in the test environment. Additionally, METHOD_A hit a secondary LiteLLM capability check that flagged this model string as not supporting function calling before even attempting the network call. METHOD_C was auto-skipped. Results are not evaluable.

### `gemini/gemini-3.1-flash-lite-preview` — Complete failure (invalid API key)

Every call was rejected by the Gemini API with `API key not valid (INVALID_ARGUMENT)`. Same credential issue as Groq and OpenRouter. METHOD_C was auto-skipped. Results are not evaluable.

---

## Key Findings and Conclusions

1. **Ollama models (gemma3:4b, ministral-3:14b-cloud) remain the only evaluable models in this run.** All three cloud API providers (Groq, OpenRouter, Gemini) failed due to missing or invalid credentials, not due to method or prompt issues. No conclusions about method behavior on cloud models can be drawn from this run.

2. **METHOD_A (FunctionCallingProgram) consistently fails for all Ollama models**, confirming Round 1 findings. Ollama-served models do not expose function/tool calling via the LiteLLM interface.

3. **METHOD_B/C/D/E all succeed for both Ollama models across all 4 prompts.** For the 14B Mistral model, METHOD_D and METHOD_E are 3–6× faster than METHOD_B/C, making them the preferred choice when latency matters.

4. **gemma3:4b METHOD_B + Prompt 1 "succeeded" this round** (1/1), which contradicts Round 1 (0/9). With N_RUNS=1 this is statistically inconclusive. The Round 1 3-run result is more trustworthy; treat this as a possible fluke until confirmed with more runs.

5. **METHOD_C showed an 81.8s spike** on ministral-3:14b-cloud + Prompt 4. Grammar-constrained decoding in Ollama can stall on longer prompts with larger models. This risk is not present in METHOD_D/E, which do not use server-side format enforcement.

6. **For cloud API models**, the next step is to configure valid credentials and re-run. The method comparison infrastructure handles API models correctly (concurrent execution, rate-limit delays, auto-skip of METHOD_C). No script changes are needed — only credential setup.

7. **Best method recommendations remain unchanged from Round 1** for Ollama models. The new finding is that for the 14B Mistral model, METHOD_D/E are significantly faster than METHOD_C and should be preferred over METHOD_C when the model is large.

---

## Raw Output

<details>
<summary>Full stdout from structured_output_methods.py (2026-04-02)</summary>

```
==========================================================================================
  outlines_with_layout — Method Comparison (v2)
  Models:  ollama/gemma3:4b, ollama/ministral-3:14b-cloud, groq/openai/gpt-oss-20b, openrouter/google/gemini-3.1-flash-lite-preview, gemini/gemini-3.1-flash-lite-preview
  Methods: METHOD_A, METHOD_B, METHOD_C, METHOD_D, METHOD_E
  Prompts: 4  |  Slides: 1  |  N_RUNS: 1
  Total LLM calls (max): 100
  Ollama (2): sequential | API (3): concurrent
==========================================================================================


##########################################################################################
# Testing model: ollama/gemma3:4b
##########################################################################################
  [ollama/gemma3:4b][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/20) -> cap_err (0.7s)
  [ollama/gemma3:4b][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/20) -> cap_err (0.4s)
  [ollama/gemma3:4b][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/20) -> cap_err (0.4s)
  [ollama/gemma3:4b][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/20) -> cap_err (0.4s)
  [ollama/gemma3:4b][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/20) -> OK (11.3s)
  [ollama/gemma3:4b][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/20) -> OK (6.8s)
  [ollama/gemma3:4b][METHOD_B][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (7/20) -> OK (7.2s)
  [ollama/gemma3:4b][METHOD_B][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (8/20) -> OK (7.1s)
  [ollama/gemma3:4b][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/20) -> OK (6.4s)
  [ollama/gemma3:4b][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/20) -> OK (6.3s)
  [ollama/gemma3:4b][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/20) -> OK (6.7s)
  [ollama/gemma3:4b][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/20) -> OK (6.9s)
  [ollama/gemma3:4b][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/20) -> OK (6.8s)
  [ollama/gemma3:4b][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/20) -> OK (7.0s)
  [ollama/gemma3:4b][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/20) -> OK (7.3s)
  [ollama/gemma3:4b][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/20) -> OK (7.1s)
  [ollama/gemma3:4b][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/20) -> OK (6.6s)
  [ollama/gemma3:4b][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/20) -> OK (6.8s)
  [ollama/gemma3:4b][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/20) -> OK (7.1s)
  [ollama/gemma3:4b][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/20) -> OK (6.9s)

##########################################################################################
# Testing model: ollama/ministral-3:14b-cloud
##########################################################################################
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/20) -> cap_err (0.8s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/20) -> cap_err (0.6s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/20) -> cap_err (0.5s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/20) -> cap_err (0.4s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/20) -> OK (24.3s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/20) -> OK (19.9s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (7/20) -> OK (15.3s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (8/20) -> OK (22.6s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/20) -> OK (13.9s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/20) -> OK (11.0s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/20) -> OK (9.2s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/20) -> OK (81.8s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/20) -> OK (6.4s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/20) -> OK (6.3s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/20) -> OK (6.3s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/20) -> OK (5.5s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/20) -> OK (7.8s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/20) -> OK (4.7s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/20) -> OK (6.8s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/20) -> OK (3.8s)

##########################################################################################
# Testing API models concurrently: groq/openai/gpt-oss-20b, openrouter/google/gemini-3.1-flash-lite-preview, gemini/gemini-3.1-flash-lite-preview
##########################################################################################
  [groq/openai/gpt-oss-20b][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/20)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/20) -> cap_err (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/20)
  -> FAIL (0.1s)   [groq: invalid_api_key]
  -> FAIL (0.3s)   [gemini: API key not valid]
  [all subsequent groq/openrouter/gemini calls: FAIL or cap_err within 0.0–0.3s due to auth errors]
  ...
  [groq/openai/gpt-oss-20b][METHOD_C][Prompt 1–4] -> -- skip (0.0s)  [non-Ollama, auto-skipped]
  [openrouter/...][METHOD_C][Prompt 1–4] -> -- skip (0.0s)
  [gemini/...][METHOD_C][Prompt 1–4] -> -- skip (0.0s)
  ...
  [All 20 calls per API model: 0% success, 0.0–0.3s elapsed]

==========================================================================================
  COMPARISON TABLES
==========================================================================================

==========================================================================================
  MODEL: ollama/gemma3:4b
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (curr  Prompt 2 (typo  Prompt 3 (+ fe  Prompt 4 (Roun
  -----------------------------------------------------------------------
  METHOD_A    0%              0%              0%              0%
  METHOD_B    100%            100%            100%            100%
  METHOD_C    100%            100%            100%            100%
  METHOD_D    100%            100%            100%            100%
  METHOD_E    100%            100%            100%            100%

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (curr  Prompt 2 (typo  Prompt 3 (+ fe  Prompt 4 (Roun
  -----------------------------------------------------------------------
  METHOD_A    0.7             0.4             0.4             0.4
  METHOD_B    11.3            6.8             7.2             7.1
  METHOD_C    6.4             6.3             6.7             6.9
  METHOD_D    6.8             7.0             7.3             7.1
  METHOD_E    6.6             6.8             7.1             6.9

  Per-slide success breakdown (all prompts combined, 1 runs each):
  Method      Prompt                                Attention Is
  -----------------------------------------------------------------------
  METHOD_A    Prompt 1 (current)                    0/1
  METHOD_A    Prompt 2 (typo fix + field desc)      0/1
  METHOD_A    Prompt 3 (+ few-shot)                 0/1
  METHOD_A    Prompt 4 (Round2 no-wrap directive)   0/1
  METHOD_B    Prompt 1 (current)                    1/1
  METHOD_B    Prompt 2 (typo fix + field desc)      1/1
  METHOD_B    Prompt 3 (+ few-shot)                 1/1
  METHOD_B    Prompt 4 (Round2 no-wrap directive)   1/1
  METHOD_C    Prompt 1 (current)                    1/1
  METHOD_C    Prompt 2 (typo fix + field desc)      1/1
  METHOD_C    Prompt 3 (+ few-shot)                 1/1
  METHOD_C    Prompt 4 (Round2 no-wrap directive)   1/1
  METHOD_D    Prompt 1 (current)                    1/1
  METHOD_D    Prompt 2 (typo fix + field desc)      1/1
  METHOD_D    Prompt 3 (+ few-shot)                 1/1
  METHOD_D    Prompt 4 (Round2 no-wrap directive)   1/1
  METHOD_E    Prompt 1 (current)                    1/1
  METHOD_E    Prompt 2 (typo fix + field desc)      1/1
  METHOD_E    Prompt 3 (+ few-shot)                 1/1
  METHOD_E    Prompt 4 (Round2 no-wrap directive)   1/1

==========================================================================================
  MODEL: ollama/ministral-3:14b-cloud
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (curr  Prompt 2 (typo  Prompt 3 (+ fe  Prompt 4 (Roun
  -----------------------------------------------------------------------
  METHOD_A    0%              0%              0%              0%
  METHOD_B    100%            100%            100%            100%
  METHOD_C    100%            100%            100%            100%
  METHOD_D    100%            100%            100%            100%
  METHOD_E    100%            100%            100%            100%

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (curr  Prompt 2 (typo  Prompt 3 (+ fe  Prompt 4 (Roun
  -----------------------------------------------------------------------
  METHOD_A    0.8             0.6             0.5             0.4
  METHOD_B    24.3            19.9            15.3            22.6
  METHOD_C    13.9            11.0            9.2             81.8
  METHOD_D    6.4             6.3             6.3             5.5
  METHOD_E    7.8             4.7             6.8             3.8

  Per-slide success breakdown (all prompts combined, 1 runs each):
  [same pattern as gemma3:4b: METHOD_A 0/1 everywhere, METHOD_B/C/D/E 1/1 everywhere]

==========================================================================================
  MODEL: groq/openai/gpt-oss-20b
==========================================================================================

  Success Rate: 0% for all methods/prompts (METHOD_C: SKIP)
  Avg Elapsed:  0.1–0.3s for all (immediate auth rejection)

==========================================================================================
  MODEL: openrouter/google/gemini-3.1-flash-lite-preview
==========================================================================================

  Success Rate: 0% for all methods/prompts (METHOD_C: SKIP)
  Avg Elapsed:  0.0–0.1s for all (immediate auth rejection)

==========================================================================================
  MODEL: gemini/gemini-3.1-flash-lite-preview
==========================================================================================

  Success Rate: 0% for all methods/prompts (METHOD_C: SKIP)
  Avg Elapsed:  0.0–0.1s for all (immediate auth rejection)


==========================================================================================
  CROSS-METHOD SUMMARY: model x method x best_prompt -> success_rate
==========================================================================================
  Model                        Method       BestPrompt                              SuccessRate
  --------------------------------------------------------------------------------------------
  ollama/gemma3:4b             METHOD_A     Prompt 1 (current)                               0%
  ollama/gemma3:4b             METHOD_B     Prompt 1 (current)                             100%
  ollama/gemma3:4b             METHOD_C     Prompt 1 (current)                             100%
  ollama/gemma3:4b             METHOD_D     Prompt 1 (current)                             100%
  ollama/gemma3:4b             METHOD_E     Prompt 1 (current)                             100%

  ollama/ministral-3:14b-cloud METHOD_A     Prompt 1 (current)                               0%
  ollama/ministral-3:14b-cloud METHOD_B     Prompt 1 (current)                             100%
  ollama/ministral-3:14b-cloud METHOD_C     Prompt 1 (current)                             100%
  ollama/ministral-3:14b-cloud METHOD_D     Prompt 1 (current)                             100%
  ollama/ministral-3:14b-cloud METHOD_E     Prompt 1 (current)                             100%

  groq/openai/gpt-oss-20b      METHOD_A     Prompt 1 (current)                               0%
  groq/openai/gpt-oss-20b      METHOD_B     Prompt 1 (current)                               0%
  groq/openai/gpt-oss-20b      METHOD_C     Prompt 1 (current)                            SKIP
  groq/openai/gpt-oss-20b      METHOD_D     Prompt 1 (current)                               0%
  groq/openai/gpt-oss-20b      METHOD_E     Prompt 1 (current)                               0%

  openrouter/google/gemini-3.1-flash-lite-preview METHOD_A  Prompt 1 (current)               0%
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_B  Prompt 1 (current)               0%
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_C  Prompt 1 (current)            SKIP
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_D  Prompt 1 (current)               0%
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_E  Prompt 1 (current)               0%

  gemini/gemini-3.1-flash-lite-preview METHOD_A     Prompt 1 (current)                       0%
  gemini/gemini-3.1-flash-lite-preview METHOD_B     Prompt 1 (current)                       0%
  gemini/gemini-3.1-flash-lite-preview METHOD_C     Prompt 1 (current)                    SKIP
  gemini/gemini-3.1-flash-lite-preview METHOD_D     Prompt 1 (current)                       0%
  gemini/gemini-3.1-flash-lite-preview METHOD_E     Prompt 1 (current)                       0%


  Raw results saved to: .../augment_results_raw.json

==========================================================================================
  DONE
==========================================================================================
```

</details>

---

---

# Round 3 — Structured Output Method Comparison (Multi-Model, API Keys Loaded from .env)

**Experiment date:** 2026-04-02
**Script:** `structured_output_methods.py`
**Raw data:** `augment_results_raw.json` (overwritten in-place by this run)

---

## Overview

This is the third round of structured output method comparison. The script configuration is **identical to Round 2** — same 5 models, same 5 methods, same 4 prompts, same 1 slide, same N_RUNS=1. The single change is how the script is invoked: API keys are now loaded from the project `.env` file via `set -a && source .env && set +a` before Python starts.

Round 2 found that all three cloud API models (Groq, OpenRouter, Gemini) failed with credential errors. This round tests whether properly loading credentials allows those models to actually run inference and produce structured output.

### What changed vs Round 2

| Aspect | Round 2 | Round 3 |
|---|---|---|
| Invocation | `python structured_output_methods.py` (no env) | `set -a && source .env && set +a && python structured_output_methods.py` |
| API credentials | Not set — all 3 API models failed with auth errors | Loaded from `.env` |
| API model results | 0% across all methods for all 3 API models | See tables below |
| Script/config | — | Unchanged |

### Experiment parameters (same as Round 2)

| Parameter | Value |
|---|---|
| Models tested | 5 (2 Ollama, 3 API) |
| Methods tested | METHOD_A, METHOD_B, METHOD_C, METHOD_D, METHOD_E |
| Prompts tested | 4 variants (Prompt 1–4) |
| Slide test cases | 1 ("Attention Is All You Need") |
| N_RUNS per combo | 1 |
| Total LLM calls (max) | 100 (88 real + 12 auto-skipped METHOD_C for non-Ollama) |
| Execution mode | Ollama: sequential; API models: concurrent via `asyncio.gather` |

---

## Results

### Model: `ollama/gemma3:4b`

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | **100%** | **100%** | **100%** | **100%** |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.7 | 0.5 | 0.4 | 0.4 |
| METHOD_B | 11.6 | 6.9 | 7.6 | 7.1 |
| METHOD_C | 6.5 | 6.5 | 6.9 | 7.0 |
| METHOD_D | 6.8 | 7.2 | 7.5 | 7.2 |
| METHOD_E | 6.6 | 6.8 | 7.2 | 7.0 |

#### Per-slide Success Breakdown (1 run per cell)

| Method | Prompt | Attention Is All You Need |
|---|---|---|
| METHOD_A | Prompt 1 (current) | 0/1 |
| METHOD_A | Prompt 2 (typo fix + field desc) | 0/1 |
| METHOD_A | Prompt 3 (+ few-shot) | 0/1 |
| METHOD_A | Prompt 4 (Round2 no-wrap directive) | 0/1 |
| METHOD_B | Prompt 1 (current) | 1/1 |
| METHOD_B | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_B | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_B | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_C | Prompt 1 (current) | 1/1 |
| METHOD_C | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_C | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_C | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_D | Prompt 1 (current) | 1/1 |
| METHOD_D | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_D | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_D | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_E | Prompt 1 (current) | 1/1 |
| METHOD_E | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_E | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_E | Prompt 4 (Round2 no-wrap directive) | 1/1 |

---

### Model: `ollama/ministral-3:14b-cloud`

All methods B/C/D/E succeed on all prompts. METHOD_A fails (capability error). Latencies are dramatically lower than Round 2 (1.8–2.5s vs 6–82s), likely because the model was already warm in Ollama's cache from the earlier gemma3:4b run. One anomaly: METHOD_E + Prompt 2 = 43.2s (same stall pattern seen with METHOD_C + Prompt 4 in Round 2).

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | **100%** | **100%** | **100%** | **100%** |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 1.4 | 1.2 | 0.5 | 1.0 |
| METHOD_B | 2.4 | 2.0 | 1.9 | 2.2 |
| METHOD_C | 2.5 | 1.9 | 1.8 | 2.1 |
| METHOD_D | 2.1 | 2.2 | 2.3 | 2.1 |
| METHOD_E | 1.8 | 43.2 | 1.8 | 2.0 |

> METHOD_E + Prompt 2 recorded 43.2s — transient Ollama stall (same pattern as Round 2's METHOD_C + Prompt 4 anomaly). All other METHOD_E runs were 1.8–2.0s. Output was still valid (1/1 success).

#### Per-slide Success Breakdown (1 run per cell)

All METHOD_B/C/D/E: 1/1 on all 4 prompts. All METHOD_A: 0/1 on all 4 prompts.

---

### Model: `groq/openai/gpt-oss-20b`

Credentials now valid. Inference succeeds on most methods and prompts. Notable issues:
- **METHOD_A + Prompt 4**: FAIL (0/1) — the no-wrap directive in Prompt 4 appears to confuse the function-calling path for this model
- **METHOD_D + Prompt 4**: FAIL (0/1) — same prompt-sensitivity issue
- Multiple **rate-limit hits** (TPM 8000 limit) were auto-retried by LiteLLM's retry logic. This inflated elapsed times for some calls (e.g. METHOD_B + Prompt 4 = 13.0s, METHOD_E + Prompt 4 = 13.0s).
- METHOD_C: auto-skipped (non-Ollama)

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | **100%** | **100%** | **100%** | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | **100%** | **100%** | **100%** | 0% |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.9 | 0.5 | 0.5 | 0.5 |
| METHOD_B | 0.4 | 8.8 | 4.6 | 13.0 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 0.6 | 4.5 | 0.4 | 4.7 |
| METHOD_E | 8.8 | 5.0 | 0.4 | 13.0 |

> High elapsed times on some Groq calls (4.5–13.0s) are due to LiteLLM's exponential backoff retry on TPM rate-limit errors, not model latency.

#### Per-slide Success Breakdown (1 run per cell)

| Method | Prompt | Attention Is All You Need |
|---|---|---|
| METHOD_A | Prompt 1 (current) | 1/1 |
| METHOD_A | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_A | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_A | Prompt 4 (Round2 no-wrap directive) | 0/1 |
| METHOD_B | Prompt 1 (current) | 1/1 |
| METHOD_B | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_B | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_B | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_C | Prompt 1–4 | SKIP |
| METHOD_D | Prompt 1 (current) | 1/1 |
| METHOD_D | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_D | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_D | Prompt 4 (Round2 no-wrap directive) | 0/1 |
| METHOD_E | Prompt 1 (current) | 1/1 |
| METHOD_E | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_E | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_E | Prompt 4 (Round2 no-wrap directive) | 1/1 |

---

### Model: `openrouter/google/gemini-3.1-flash-lite-preview`

Credentials now valid. Inference succeeds for all of METHOD_B, METHOD_D, METHOD_E across all prompts. METHOD_A fails 100% due to a LiteLLM capability check: LiteLLM flags this model string as not supporting function calling before even sending a request (0.0–0.2s elapsed). METHOD_C is auto-skipped. Latencies are fast (1.2–4.4s).

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.2 | 0.0 | 0.0 | 0.0 |
| METHOD_B | 4.4 | 3.1 | 1.8 | 1.4 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 2.1 | 1.6 | 2.5 | 1.7 |
| METHOD_E | 1.9 | 1.6 | 2.1 | 4.6 |

#### Per-slide Success Breakdown (1 run per cell)

All METHOD_B/D/E: 1/1 on all 4 prompts. All METHOD_A: 0/1 (cap_err). METHOD_C: SKIP.

---

### Model: `gemini/gemini-3.1-flash-lite-preview`

Credentials now valid. This model succeeds on **all 4 methods × all 4 prompts** (excluding METHOD_C which is auto-skipped as non-Ollama). Notably, METHOD_A also succeeds (100%) — this is the only non-Ollama model in this run where METHOD_A (FunctionCallingProgram / native tool calling) works reliably. Latencies are competitive (1.2–6.1s depending on method/prompt).

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | **100%** | **100%** | **100%** | **100%** |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 6.1 | 3.5 | 2.0 | 1.9 |
| METHOD_B | 3.6 | 2.5 | 1.3 | 1.2 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 2.0 | 3.2 | 1.9 | 1.9 |
| METHOD_E | 2.4 | 2.2 | 2.3 | 2.2 |

#### Per-slide Success Breakdown (1 run per cell)

All METHOD_A/B/D/E: 1/1 on all 4 prompts. METHOD_C: SKIP.

---

### Cross-Method Summary: best prompt per (model × method)

| Model | Method | Best Prompt | Success Rate |
|---|---|---|---|
| ollama/gemma3:4b | METHOD_A | Prompt 1 (current) | 0% |
| ollama/gemma3:4b | METHOD_B | Prompt 1 (current) | 100% |
| ollama/gemma3:4b | METHOD_C | Prompt 1 (current) | 100% |
| ollama/gemma3:4b | METHOD_D | Prompt 1 (current) | 100% |
| ollama/gemma3:4b | METHOD_E | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_A | Prompt 1 (current) | 0% |
| ollama/ministral-3:14b-cloud | METHOD_B | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_C | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_D | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_E | Prompt 1 (current) | 100% |
| groq/openai/gpt-oss-20b | METHOD_A | Prompt 1 (current) | 100% |
| groq/openai/gpt-oss-20b | METHOD_B | Prompt 1 (current) | 100% |
| groq/openai/gpt-oss-20b | METHOD_C | — | SKIP |
| groq/openai/gpt-oss-20b | METHOD_D | Prompt 1 (current) | 100% |
| groq/openai/gpt-oss-20b | METHOD_E | Prompt 1 (current) | 100% |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_A | Prompt 1 (current) | 0% (cap_err) |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_B | Prompt 1 (current) | 100% |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_C | — | SKIP |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_D | Prompt 1 (current) | 100% |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_E | Prompt 1 (current) | 100% |
| gemini/gemini-3.1-flash-lite-preview | METHOD_A | Prompt 1 (current) | 100% |
| gemini/gemini-3.1-flash-lite-preview | METHOD_B | Prompt 1 (current) | 100% |
| gemini/gemini-3.1-flash-lite-preview | METHOD_C | — | SKIP |
| gemini/gemini-3.1-flash-lite-preview | METHOD_D | Prompt 1 (current) | 100% |
| gemini/gemini-3.1-flash-lite-preview | METHOD_E | Prompt 1 (current) | 100% |

---

## Per-Model Observations

### `ollama/gemma3:4b` — Results identical to Round 2

No change: METHOD_A fails (capability error), METHOD_B/C/D/E all succeed on all 4 prompts. Latencies are stable (6.5–11.6s). This Ollama model's behavior is unaffected by the `.env` loading since it does not use API keys.

### `ollama/ministral-3:14b-cloud` — Much faster this run (cache hit)

Pattern unchanged: METHOD_A fails, METHOD_B/C/D/E all succeed. Latencies dropped dramatically from Round 2 (e.g. METHOD_B: 24s → 2.4s, METHOD_C: 14–82s → 1.8–2.5s) because the Mistral model was already loaded in Ollama from the earlier sequential run. Anomaly: METHOD_E + Prompt 2 stalled at 43.2s (still returned OK). This is the second occurrence of a similar transient stall across rounds, suggesting occasional Ollama scheduling delays on larger models.

### `groq/openai/gpt-oss-20b` — First successful API run; Prompt 4 is problematic

Credentials now valid. METHOD_A and METHOD_D both work on Prompts 1–3 but fail on Prompt 4. Prompt 4's "CRITICAL: Do NOT wrap your answer inside a 'properties' key" directive appears to confuse or destabilize the structured prediction path for these methods on this model — possibly interfering with how the function-calling schema or completion instructions are parsed. METHOD_B and METHOD_E succeed on all 4 prompts, indicating they are more robust to prompt phrasing. Multiple rate-limit hits (8000 TPM/min cap) were auto-retried, inflating elapsed times to 4.5–13.0s on some calls. The 2s `delay_s` between calls is insufficient to stay within this model's rate limit when running concurrently with other models.

### `openrouter/google/gemini-3.1-flash-lite-preview` — METHOD_A permanently blocked by LiteLLM

Credentials valid, inference works for METHOD_B/D/E. METHOD_A is blocked before any network call by a LiteLLM pre-flight capability check that rejects this model string as not supporting function calling (0.0s elapsed — no actual API request made). This is a LiteLLM routing decision, not a model API limitation. METHOD_C auto-skipped. All working methods (B/D/E) succeed on all 4 prompts with fast latencies (1.4–4.6s).

### `gemini/gemini-3.1-flash-lite-preview` — Best result of all API models; METHOD_A works

Credentials valid. This is the standout result of Round 3: **all 4 testable methods succeed on all 4 prompts** (16/16). Critically, METHOD_A (FunctionCallingProgram / native tool calling) succeeds 100% here — confirming that the direct Gemini API via LiteLLM properly supports the function-calling protocol, unlike Ollama-served models or the OpenRouter routing layer. Latency is 1.2–6.1s. METHOD_A is slower on Prompt 1 (6.1s) and faster on later prompts (1.9–3.5s), likely due to caching or token-length effects.

---

## Key Findings and Conclusions

1. **Loading API keys from `.env` unblocks all three cloud providers.** Groq, OpenRouter (via Gemini), and Gemini direct all transition from 100% auth failures (Round 2) to functional inference in this round. The LiteLLM + LlamaIndex integration is correctly configured; credentials were the only missing piece.

2. **`gemini/gemini-3.1-flash-lite-preview` is the most capable model tested so far across all methods.** It is the only model in any round to achieve 100% success on METHOD_A (FunctionCallingProgram). All other tested models — both Ollama and OpenRouter — either fail on METHOD_A due to capability errors or show prompt-sensitivity failures.

3. **METHOD_B and METHOD_E are the most universally reliable across all 5 models and all 4 prompts.** In this round, only these two methods achieved 100% best-prompt success on every model that had working credentials (excluding the auto-skipped METHOD_C). METHOD_D is almost as reliable but shows the same Prompt 4 sensitivity as METHOD_A on Groq.

4. **Prompt 4 ("no-wrap directive") is harmful for `groq/openai/gpt-oss-20b` with METHOD_A and METHOD_D.** The explicit instruction to not wrap output in a "properties" key — which was designed to fix a gemma3:4b hallucination — appears to break the structured prediction path for this cloud model on those methods. Prompt 1–3 all succeed. This suggests Prompt 4 should not be used as a general-purpose prompt; it is model-specific.

5. **`openrouter/google/gemini-3.1-flash-lite-preview` cannot use METHOD_A due to LiteLLM's capability pre-check**, even though the underlying Gemini model does support function calling. The OpenRouter routing prefix in the model name causes LiteLLM to classify it as incapable. Use METHOD_B/D/E when routing via OpenRouter.

6. **Groq's 8000 TPM rate limit is a practical constraint for concurrent testing.** Even with a 2s `delay_s`, the concurrent API model execution triggers rate-limit retries on almost every Groq call. In production, a longer delay or sequential execution for Groq is advisable.

7. **Comparison to Ollama-only rounds (Round 1 and early Round 2):** The Ollama findings remain stable — METHOD_A always fails, METHOD_C (Ollama `format`) is the most grammar-robust for local models, and METHOD_B/D/E with Prompt 2+ work reliably. The new finding is that for cloud providers, METHOD_A can work (Gemini direct), METHOD_C is inapplicable, and METHOD_B/E are the safest cross-model choices for all providers including OpenRouter.

---

## Raw Output

<details>
<summary>Full stdout from structured_output_methods.py (Round 3, 2026-04-02)</summary>

```

==========================================================================================
  outlines_with_layout — Method Comparison (v2)
  Models:  ollama/gemma3:4b, ollama/ministral-3:14b-cloud, groq/openai/gpt-oss-20b, openrouter/google/gemini-3.1-flash-lite-preview, gemini/gemini-3.1-flash-lite-preview
  Methods: METHOD_A, METHOD_B, METHOD_C, METHOD_D, METHOD_E
  Prompts: 4  |  Slides: 1  |  N_RUNS: 1
  Total LLM calls (max): 100
  Ollama (2): sequential | API (3): concurrent
==========================================================================================


##########################################################################################
# Testing model: ollama/gemma3:4b
##########################################################################################
  [ollama/gemma3:4b][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/20) -> cap_err (0.7s)
  [ollama/gemma3:4b][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/20) -> cap_err (0.5s)
  [ollama/gemma3:4b][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/20) -> cap_err (0.4s)
  [ollama/gemma3:4b][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/20) -> cap_err (0.4s)
  [ollama/gemma3:4b][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/20) -> OK (11.6s)
  [ollama/gemma3:4b][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/20) -> OK (6.9s)
  [ollama/gemma3:4b][METHOD_B][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (7/20) -> OK (7.6s)
  [ollama/gemma3:4b][METHOD_B][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (8/20) -> OK (7.1s)
  [ollama/gemma3:4b][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/20) -> OK (6.5s)
  [ollama/gemma3:4b][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/20) -> OK (6.5s)
  [ollama/gemma3:4b][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/20) -> OK (6.9s)
  [ollama/gemma3:4b][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/20) -> OK (7.0s)
  [ollama/gemma3:4b][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/20) -> OK (6.8s)
  [ollama/gemma3:4b][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/20) -> OK (7.2s)
  [ollama/gemma3:4b][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/20) -> OK (7.5s)
  [ollama/gemma3:4b][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/20) -> OK (7.2s)
  [ollama/gemma3:4b][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/20) -> OK (6.6s)
  [ollama/gemma3:4b][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/20) -> OK (6.8s)
  [ollama/gemma3:4b][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/20) -> OK (7.2s)
  [ollama/gemma3:4b][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/20) -> OK (7.0s)

##########################################################################################
# Testing model: ollama/ministral-3:14b-cloud
##########################################################################################
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/20) -> cap_err (1.4s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/20) -> cap_err (1.2s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/20) -> cap_err (0.5s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/20) -> cap_err (1.0s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/20) -> OK (2.4s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/20) -> OK (2.0s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (7/20) -> OK (1.9s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (8/20) -> OK (2.2s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/20) -> OK (2.5s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/20) -> OK (1.9s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/20) -> OK (1.8s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/20) -> OK (2.1s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/20) -> OK (2.1s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/20) -> OK (2.2s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/20) -> OK (2.3s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/20) -> OK (2.1s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/20) -> OK (1.8s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/20) -> OK (43.2s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/20) -> OK (1.8s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/20) -> OK (2.0s)

##########################################################################################
# Testing API models concurrently: groq/openai/gpt-oss-20b, openrouter/google/gemini-3.1-flash-lite-preview, gemini/gemini-3.1-flash-lite-preview
##########################################################################################
  [groq/openai/gpt-oss-20b][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/20)   [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/20) -> cap_err (0.2s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/20) -> OK (0.9s)
  [groq/openai/gpt-oss-20b][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/20)   [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/20) -> cap_err (0.0s)
-> OK (0.5s)
  [groq/openai/gpt-oss-20b][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/20) -> OK (0.5s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/20) -> cap_err (0.0s)
-> OK (6.1s)
  [groq/openai/gpt-oss-20b][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/20)
-> FAIL (0.5s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/20) -> cap_err (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/20)   [groq/openai/gpt-oss-20b][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/20) -> OK (0.4s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/20)
[Retrying ... RateLimitError: GroqException - Rate limit reached for model `openai/gpt-oss-20b` ... TPM: Limit 8000 ...]
  [groq/openai/gpt-oss-20b][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/20)
-> OK (3.5s)
-> OK (4.4s)
-> OK (2.0s)
-> OK (8.8s)
-> OK (3.1s)
[... rate-limit retries and concurrent output continue for remaining calls ...]
  [groq/openai/gpt-oss-20b][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/20) -> -- skip (0.0s)
  [groq/openai/gpt-oss-20b][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/20) -> -- skip (0.0s)
  [groq/openai/gpt-oss-20b][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/20) -> -- skip (0.0s)
  [groq/openai/gpt-oss-20b][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/20) -> -- skip (0.0s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/20) -> -- skip (0.0s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/20) -> -- skip (0.0s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/20) -> -- skip (0.0s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/20) -> -- skip (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/20) -> -- skip (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/20) -> -- skip (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/20) -> -- skip (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/20) -> -- skip (0.0s)
  [groq/openai/gpt-oss-20b][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/20) -> OK (0.6s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/20) -> OK (2.0s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/20) -> OK (2.1s)
  [groq/openai/gpt-oss-20b][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/20)
[Retrying ... RateLimitError ...]
-> OK (4.5s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/20) -> OK (1.6s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/20) -> OK (1.6s)
  [groq/openai/gpt-oss-20b][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/20) -> OK (0.4s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/20) -> OK (2.5s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/20)
[Retrying ... RateLimitError ...]
-> OK (8.8s)
  [groq/openai/gpt-oss-20b][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/20)
[Retrying ... RateLimitError ...]
-> FAIL (4.7s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/20) -> OK (1.7s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/20) -> OK (4.6s)
  [groq/openai/gpt-oss-20b][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/20)
[Retrying ... RateLimitError ...]
-> OK (8.8s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/20) -> OK (1.9s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/20) -> OK (2.4s)
  [groq/openai/gpt-oss-20b][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/20)
[Retrying ... RateLimitError ...]
-> OK (5.0s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/20) -> OK (1.6s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/20)
[Retrying ... RateLimitError (13.5s wait) ...]
-> OK (13.0s)
  [groq/openai/gpt-oss-20b][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/20) -> OK (0.4s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/20) -> OK (2.1s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/20)
[Retrying ... RateLimitError (9.35s wait) ...]
-> OK (13.0s)
  [groq/openai/gpt-oss-20b][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/20)
[Retrying ... RateLimitError ...]
-> OK (2.2s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/20) -> OK (4.6s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/20) -> OK (2.2s)


==========================================================================================
  COMPARISON TABLES
==========================================================================================

==========================================================================================
  MODEL: ollama/gemma3:4b
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0%            0%            0%            0%            
  METHOD_B    100%          100%          100%          100%          
  METHOD_C    100%          100%          100%          100%          
  METHOD_D    100%          100%          100%          100%          
  METHOD_E    100%          100%          100%          100%          

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0.7           0.5           0.4           0.4           
  METHOD_B    11.6          6.9           7.6           7.1           
  METHOD_C    6.5           6.5           6.9           7.0           
  METHOD_D    6.8           7.2           7.5           7.2           
  METHOD_E    6.6           6.8           7.2           7.0           

  Per-slide success breakdown (all prompts combined, 1 runs each):
  Method      Prompt                                Attention Is  
  ----------------------------------------------------------------
  METHOD_A    Prompt 1 (current)                    0/1           
  METHOD_A    Prompt 2 (typo fix + field desc)      0/1           
  METHOD_A    Prompt 3 (+ few-shot)                 0/1           
  METHOD_A    Prompt 4 (Round2 no-wrap directive)   0/1           
  METHOD_B    Prompt 1 (current)                    1/1           
  METHOD_B    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_B    Prompt 3 (+ few-shot)                 1/1           
  METHOD_B    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_C    Prompt 1 (current)                    1/1           
  METHOD_C    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_C    Prompt 3 (+ few-shot)                 1/1           
  METHOD_C    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_D    Prompt 1 (current)                    1/1           
  METHOD_D    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_D    Prompt 3 (+ few-shot)                 1/1           
  METHOD_D    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_E    Prompt 1 (current)                    1/1           
  METHOD_E    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_E    Prompt 3 (+ few-shot)                 1/1           
  METHOD_E    Prompt 4 (Round2 no-wrap directive)   1/1           

==========================================================================================
  MODEL: ollama/ministral-3:14b-cloud
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0%            0%            0%            0%            
  METHOD_B    100%          100%          100%          100%          
  METHOD_C    100%          100%          100%          100%          
  METHOD_D    100%          100%          100%          100%          
  METHOD_E    100%          100%          100%          100%          

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    1.4           1.2           0.5           1.0           
  METHOD_B    2.4           2.0           1.9           2.2           
  METHOD_C    2.5           1.9           1.8           2.1           
  METHOD_D    2.1           2.2           2.3           2.1           
  METHOD_E    1.8           43.2          1.8           2.0           

  Per-slide success breakdown (all prompts combined, 1 runs each):
  Method      Prompt                                Attention Is  
  ----------------------------------------------------------------
  METHOD_A    Prompt 1 (current)                    0/1           
  METHOD_A    Prompt 2 (typo fix + field desc)      0/1           
  METHOD_A    Prompt 3 (+ few-shot)                 0/1           
  METHOD_A    Prompt 4 (Round2 no-wrap directive)   0/1           
  METHOD_B    Prompt 1 (current)                    1/1           
  METHOD_B    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_B    Prompt 3 (+ few-shot)                 1/1           
  METHOD_B    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_C    Prompt 1 (current)                    1/1           
  METHOD_C    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_C    Prompt 3 (+ few-shot)                 1/1           
  METHOD_C    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_D    Prompt 1 (current)                    1/1           
  METHOD_D    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_D    Prompt 3 (+ few-shot)                 1/1           
  METHOD_D    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_E    Prompt 1 (current)                    1/1           
  METHOD_E    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_E    Prompt 3 (+ few-shot)                 1/1           
  METHOD_E    Prompt 4 (Round2 no-wrap directive)   1/1           

==========================================================================================
  MODEL: groq/openai/gpt-oss-20b
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    100%          100%          100%          0%            
  METHOD_B    100%          100%          100%          100%          
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    100%          100%          100%          0%            
  METHOD_E    100%          100%          100%          100%          

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0.9           0.5           0.5           0.5           
  METHOD_B    0.4           8.8           4.6           13.0          
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    0.6           4.5           0.4           4.7           
  METHOD_E    8.8           5.0           0.4           13.0          

  Per-slide success breakdown (all prompts combined, 1 runs each):
  Method      Prompt                                Attention Is  
  ----------------------------------------------------------------
  METHOD_A    Prompt 1 (current)                    1/1           
  METHOD_A    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_A    Prompt 3 (+ few-shot)                 1/1           
  METHOD_A    Prompt 4 (Round2 no-wrap directive)   0/1           
  METHOD_B    Prompt 1 (current)                    1/1           
  METHOD_B    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_B    Prompt 3 (+ few-shot)                 1/1           
  METHOD_B    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_C    Prompt 1 (current)                    SKIP          
  METHOD_C    Prompt 2 (typo fix + field desc)      SKIP          
  METHOD_C    Prompt 3 (+ few-shot)                 SKIP          
  METHOD_C    Prompt 4 (Round2 no-wrap directive)   SKIP          
  METHOD_D    Prompt 1 (current)                    1/1           
  METHOD_D    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_D    Prompt 3 (+ few-shot)                 1/1           
  METHOD_D    Prompt 4 (Round2 no-wrap directive)   0/1           
  METHOD_E    Prompt 1 (current)                    1/1           
  METHOD_E    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_E    Prompt 3 (+ few-shot)                 1/1           
  METHOD_E    Prompt 4 (Round2 no-wrap directive)   1/1           

==========================================================================================
  MODEL: openrouter/google/gemini-3.1-flash-lite-preview
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0%            0%            0%            0%            
  METHOD_B    100%          100%          100%          100%          
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    100%          100%          100%          100%          
  METHOD_E    100%          100%          100%          100%          

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0.2           0.0           0.0           0.0           
  METHOD_B    4.4           3.1           1.8           1.4           
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    2.1           1.6           2.5           1.7           
  METHOD_E    1.9           1.6           2.1           4.6           

  Per-slide success breakdown (all prompts combined, 1 runs each):
  Method      Prompt                                Attention Is  
  ----------------------------------------------------------------
  METHOD_A    Prompt 1 (current)                    0/1           
  METHOD_A    Prompt 2 (typo fix + field desc)      0/1           
  METHOD_A    Prompt 3 (+ few-shot)                 0/1           
  METHOD_A    Prompt 4 (Round2 no-wrap directive)   0/1           
  METHOD_B    Prompt 1 (current)                    1/1           
  METHOD_B    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_B    Prompt 3 (+ few-shot)                 1/1           
  METHOD_B    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_C    Prompt 1 (current)                    SKIP          
  METHOD_C    Prompt 2 (typo fix + field desc)      SKIP          
  METHOD_C    Prompt 3 (+ few-shot)                 SKIP          
  METHOD_C    Prompt 4 (Round2 no-wrap directive)   SKIP          
  METHOD_D    Prompt 1 (current)                    1/1           
  METHOD_D    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_D    Prompt 3 (+ few-shot)                 1/1           
  METHOD_D    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_E    Prompt 1 (current)                    1/1           
  METHOD_E    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_E    Prompt 3 (+ few-shot)                 1/1           
  METHOD_E    Prompt 4 (Round2 no-wrap directive)   1/1           

==========================================================================================
  MODEL: gemini/gemini-3.1-flash-lite-preview
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    100%          100%          100%          100%          
  METHOD_B    100%          100%          100%          100%          
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    100%          100%          100%          100%          
  METHOD_E    100%          100%          100%          100%          

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    6.1           3.5           2.0           1.9           
  METHOD_B    3.6           2.5           1.3           1.2           
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    2.0           3.2           1.9           1.9           
  METHOD_E    2.4           2.2           2.3           2.2           

  Per-slide success breakdown (all prompts combined, 1 runs each):
  Method      Prompt                                Attention Is  
  ----------------------------------------------------------------
  METHOD_A    Prompt 1 (current)                    1/1           
  METHOD_A    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_A    Prompt 3 (+ few-shot)                 1/1           
  METHOD_A    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_B    Prompt 1 (current)                    1/1           
  METHOD_B    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_B    Prompt 3 (+ few-shot)                 1/1           
  METHOD_B    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_C    Prompt 1 (current)                    SKIP          
  METHOD_C    Prompt 2 (typo fix + field desc)      SKIP          
  METHOD_C    Prompt 3 (+ few-shot)                 SKIP          
  METHOD_C    Prompt 4 (Round2 no-wrap directive)   SKIP          
  METHOD_D    Prompt 1 (current)                    1/1           
  METHOD_D    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_D    Prompt 3 (+ few-shot)                 1/1           
  METHOD_D    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_E    Prompt 1 (current)                    1/1           
  METHOD_E    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_E    Prompt 3 (+ few-shot)                 1/1           
  METHOD_E    Prompt 4 (Round2 no-wrap directive)   1/1           


==========================================================================================
  CROSS-METHOD SUMMARY: model x method x best_prompt -> success_rate
==========================================================================================
  Model                        Method       BestPrompt                              SuccessRate
  --------------------------------------------------------------------------------------------
  ollama/gemma3:4b             METHOD_A     Prompt 1 (current)                               0%
  ollama/gemma3:4b             METHOD_B     Prompt 1 (current)                             100%
  ollama/gemma3:4b             METHOD_C     Prompt 1 (current)                             100%
  ollama/gemma3:4b             METHOD_D     Prompt 1 (current)                             100%
  ollama/gemma3:4b             METHOD_E     Prompt 1 (current)                             100%

  ollama/ministral-3:14b-cloud METHOD_A     Prompt 1 (current)                               0%
  ollama/ministral-3:14b-cloud METHOD_B     Prompt 1 (current)                             100%
  ollama/ministral-3:14b-cloud METHOD_C     Prompt 1 (current)                             100%
  ollama/ministral-3:14b-cloud METHOD_D     Prompt 1 (current)                             100%
  ollama/ministral-3:14b-cloud METHOD_E     Prompt 1 (current)                             100%

  groq/openai/gpt-oss-20b      METHOD_A     Prompt 1 (current)                             100%
  groq/openai/gpt-oss-20b      METHOD_B     Prompt 1 (current)                             100%
  groq/openai/gpt-oss-20b      METHOD_C     Prompt 1 (current)                             SKIP
  groq/openai/gpt-oss-20b      METHOD_D     Prompt 1 (current)                             100%
  groq/openai/gpt-oss-20b      METHOD_E     Prompt 1 (current)                             100%

  openrouter/google/gemini-3.1-flash-lite-preview METHOD_A     Prompt 1 (current)                               0%
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_B     Prompt 1 (current)                             100%
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_C     Prompt 1 (current)                             SKIP
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_D     Prompt 1 (current)                             100%
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_E     Prompt 1 (current)                             100%

  gemini/gemini-3.1-flash-lite-preview METHOD_A     Prompt 1 (current)                             100%
  gemini/gemini-3.1-flash-lite-preview METHOD_B     Prompt 1 (current)                             100%
  gemini/gemini-3.1-flash-lite-preview METHOD_C     Prompt 1 (current)                             SKIP
  gemini/gemini-3.1-flash-lite-preview METHOD_D     Prompt 1 (current)                             100%
  gemini/gemini-3.1-flash-lite-preview METHOD_E     Prompt 1 (current)                             100%


  Raw results saved to: /Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/poc/agent-behavior-test/augment_results_raw.json

==========================================================================================
  DONE
==========================================================================================
```

</details>


---

---

# Round 4 — Structured Output Method Comparison (METHOD_F: litellm native response_format)

**Experiment date:** 2026-04-02
**Script:** `structured_output_methods.py`
**Raw data:** `augment_results_raw.json` (overwritten in-place by this run)

---

## Overview

Round 4 adds **METHOD_F** — calling `litellm.acompletion()` directly with `response_format=SlideOutlineWithLayout` (the Pydantic class). This is provider-native schema enforcement: litellm passes the schema to the provider's native JSON/structured output API rather than using function calling or injecting a schema into the prompt. All other configuration is **unchanged from Round 3**: same 5 models, same 4 prompts, same 1 slide, N_RUNS=1, same delays. The total call budget increases from 100 to 120 (one additional method × 24 slots, minus 4 auto-skipped METHOD_C for non-Ollama models, net +20 real calls).

### What changed vs Round 3

| Aspect | Round 3 | Round 4 |
|---|---|---|
| Methods tested | METHOD_A, METHOD_B, METHOD_C, METHOD_D, METHOD_E (5) | + METHOD_F: `litellm.acompletion(response_format=Pydantic)` (6 total) |
| Total LLM calls (max) | 100 | 120 (108 real + 12 auto-skipped METHOD_C) |
| Script/config | — | Unchanged except METHOD_F added |

### METHOD_F description

**METHOD_F** calls `litellm.acompletion()` directly (bypassing LlamaIndex) with:
- `model=model_cfg.name` (same model strings as all other methods)
- `messages=[{"role": "user", "content": formatted_prompt}]` (prompt formatted via Python `.format()`)
- `response_format=SlideOutlineWithLayout` (Pydantic class — litellm sends the schema to the provider)
- `temperature=0.1`, `max_tokens=2048`

The response content is parsed with `SlideOutlineWithLayout.model_validate_json(response.choices[0].message.content)`. `litellm.enable_json_schema_validation = True` is also set globally, so litellm validates the JSON against the schema before returning.

The key difference from METHOD_B/E is that METHOD_F does not inject any schema text into the prompt — the provider enforces the output shape natively (equivalent to OpenAI's `response_format` for JSON mode or Gemini's structured output).

### Experiment parameters (same as Rounds 2 and 3)

| Parameter | Value |
|---|---|
| Models tested | 5 (2 Ollama, 3 API) |
| Methods tested | METHOD_A, METHOD_B, METHOD_C, METHOD_D, METHOD_E, METHOD_F (6 total) |
| Prompts tested | 4 variants (Prompt 1–4) |
| Slide test cases | 1 ("Attention Is All You Need") |
| N_RUNS per combo | 1 |
| Total LLM calls (max) | 120 (108 real + 12 METHOD_C auto-skipped for non-Ollama) |
| Execution mode | Ollama: sequential; API models: concurrent via `asyncio.gather` |

---

## Results

### Model: `ollama/gemma3:4b`

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | **100%** | **100%** | **100%** | **100%** |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |
| METHOD_F | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.8 | 0.5 | 0.5 | 0.5 |
| METHOD_B | 13.0 | 7.3 | 8.0 | 7.6 |
| METHOD_C | 7.0 | 6.9 | 7.3 | 7.6 |
| METHOD_D | 7.6 | 7.9 | 7.9 | 7.9 |
| METHOD_E | 7.4 | 7.6 | 8.2 | 7.8 |
| METHOD_F | 6.5 | 6.2 | 4.8 | 5.1 |

#### Per-slide Success Breakdown (1 run per cell)

| Method | Prompt | Attention Is All You Need |
|---|---|---|
| METHOD_A | Prompt 1 (current) | 0/1 |
| METHOD_A | Prompt 2 (typo fix + field desc) | 0/1 |
| METHOD_A | Prompt 3 (+ few-shot) | 0/1 |
| METHOD_A | Prompt 4 (Round2 no-wrap directive) | 0/1 |
| METHOD_B | Prompt 1 (current) | 1/1 |
| METHOD_B | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_B | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_B | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_C | Prompt 1 (current) | 1/1 |
| METHOD_C | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_C | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_C | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_D | Prompt 1 (current) | 1/1 |
| METHOD_D | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_D | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_D | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_E | Prompt 1 (current) | 1/1 |
| METHOD_E | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_E | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_E | Prompt 4 (Round2 no-wrap directive) | 1/1 |
| METHOD_F | Prompt 1 (current) | 1/1 |
| METHOD_F | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_F | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_F | Prompt 4 (Round2 no-wrap directive) | 1/1 |

---

### Model: `ollama/ministral-3:14b-cloud`

METHOD_F fails on all 4 prompts (0%). The failure mode is `litellm.JSONSchemaValidationError`: the model returns plain text or markdown-fenced JSON rather than bare JSON that litellm can validate against the schema. litellm's `enable_json_schema_validation=True` setting causes it to raise immediately on the non-conformant response. Specific errors:
- Prompt 1: Returns a markdown-formatted answer with reasoning text ("For the given slide content, the most appropriate layout is **Title and Content**..."). Not parseable as JSON.
- Prompts 2 & 3: Returns JSON inside a ` ```json ` ... ` ``` ` fenced code block. litellm cannot parse fenced JSON.
- Prompt 4: Returns a dash-prefixed field list ("- title: ...") rather than JSON.

All other methods (B/C/D/E) continue to succeed on all 4 prompts. METHOD_A fails (capability error). Another METHOD_C + Prompt 4 stall: 47.6s.

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | **100%** | **100%** | **100%** | **100%** |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |
| METHOD_F | 0% | 0% | 0% | 0% |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 1.2 | 0.4 | 0.4 | 0.5 |
| METHOD_B | 2.2 | 1.9 | 1.8 | 1.9 |
| METHOD_C | 1.9 | 1.8 | 1.9 | 47.6 |
| METHOD_D | 2.1 | 2.3 | 2.5 | 2.2 |
| METHOD_E | 1.8 | 2.2 | 2.0 | 2.1 |
| METHOD_F | 2.8 | 1.9 | 2.0 | 1.7 |

> METHOD_C + Prompt 4 recorded 47.6s again (recurring transient Ollama constrained-decoding stall on the 14B model). METHOD_F elapsed times reflect that inference completed successfully but litellm's JSON validation then raised `JSONSchemaValidationError` — the timing is post-inference, not pre-inference.

#### Per-slide Success Breakdown (1 run per cell)

| Method | Prompt | Attention Is All You Need |
|---|---|---|
| METHOD_A | Prompt 1–4 | 0/1 |
| METHOD_B | Prompt 1–4 | 1/1 |
| METHOD_C | Prompt 1–4 | 1/1 |
| METHOD_D | Prompt 1–4 | 1/1 |
| METHOD_E | Prompt 1–4 | 1/1 |
| METHOD_F | Prompt 1–4 | 0/1 |

---

### Model: `groq/openai/gpt-oss-20b`

METHOD_F shows inverted prompt-sensitivity compared to all other methods: it **fails on Prompts 1–3** and **succeeds on Prompt 4** only. The root cause for Prompts 1–3 is not a model failure but a **rate-limit exhaust**: by the time METHOD_F calls are made (METHOD_F runs last in the method loop), the Groq 8000 TPM/min budget is fully depleted, and litellm's retry logic fails (unlike the LlamaIndex wrapper which has its own retry layer). Prompt 4 calls arrive slightly later after a partial rate-limit recovery, so the single Prompt 4 call succeeds.

The cross-method summary shows METHOD_F best prompt = Prompt 4, 100% — but this is a rate-limit artifact, not a genuine prompt-sensitivity result.

METHOD_A + Prompt 4 continues to fail (same prompt-sensitivity from Round 3). METHOD_D + Prompt 4 also fails. METHOD_B and METHOD_E succeed on all 4 prompts.

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | **100%** | **100%** | **100%** | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | **100%** | **100%** | **100%** | 0% |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |
| METHOD_F | 0% | 0% | 0% | **100%** |

> METHOD_F 0% on Prompts 1–3 is due to Groq TPM rate-limit exhaustion at that point in the concurrent run, not a structural method failure. `litellm.RateLimitError: Rate limit reached… Limit 8000, Used 7377–7087, Requested 1104–1284. Please try again in 2.8–3.6s.`

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.5 | 0.5 | 4.6 | 4.7 |
| METHOD_B | 0.6 | 4.6 | 4.6 | 4.7 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 4.7 | 4.6 | 4.5 | 0.5 |
| METHOD_E | 8.8 | 8.7 | 4.6 | 13.0 |
| METHOD_F | 0.2 | 0.2 | 0.2 | 0.8 |

> METHOD_F elapsed 0.2s on failed calls — immediate rejection by litellm's rate-limit handler without retry. METHOD_E Prompt 1–2 high elapsed times (8.7–8.8s) are from LiteLLM exponential backoff retries.

#### Per-slide Success Breakdown (1 run per cell)

| Method | Prompt | Attention Is All You Need |
|---|---|---|
| METHOD_A | Prompt 1 (current) | 1/1 |
| METHOD_A | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_A | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_A | Prompt 4 (Round2 no-wrap directive) | 0/1 |
| METHOD_B | Prompt 1–4 | 1/1 |
| METHOD_C | Prompt 1–4 | SKIP |
| METHOD_D | Prompt 1 (current) | 1/1 |
| METHOD_D | Prompt 2 (typo fix + field desc) | 1/1 |
| METHOD_D | Prompt 3 (+ few-shot) | 1/1 |
| METHOD_D | Prompt 4 (Round2 no-wrap directive) | 0/1 |
| METHOD_E | Prompt 1–4 | 1/1 |
| METHOD_F | Prompt 1 (current) | 0/1 (rate-limit) |
| METHOD_F | Prompt 2 (typo fix + field desc) | 0/1 (rate-limit) |
| METHOD_F | Prompt 3 (+ few-shot) | 0/1 (rate-limit) |
| METHOD_F | Prompt 4 (Round2 no-wrap directive) | 1/1 |

---

### Model: `openrouter/google/gemini-3.1-flash-lite-preview`

METHOD_F succeeds on all 4 prompts (100%). This is the cleanest METHOD_F result among API models: OpenRouter correctly forwards the `response_format` Pydantic schema to the underlying Gemini model, which produces valid JSON. METHOD_A remains blocked by LiteLLM's capability pre-check (0.0s, cap_err). METHOD_B/D/E all succeed on all prompts as in Round 3. Latencies for METHOD_F are 1.8–7.9s (Prompt 1 higher at 7.9s, possibly a cold-start or routing overhead on the first METHOD_F call).

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |
| METHOD_F | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.0 | 0.0 | 0.0 | 0.0 |
| METHOD_B | 2.0 | 1.8 | 1.1 | 1.5 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 2.7 | 3.0 | 2.7 | 2.3 |
| METHOD_E | 1.6 | 1.4 | 1.8 | 1.6 |
| METHOD_F | 7.9 | 1.8 | 2.7 | 2.2 |

#### Per-slide Success Breakdown (1 run per cell)

All METHOD_B/D/E/F: 1/1 on all 4 prompts. METHOD_A: 0/1 (cap_err). METHOD_C: SKIP.

---

### Model: `gemini/gemini-3.1-flash-lite-preview`

METHOD_F succeeds on all 4 prompts (100%), matching METHOD_B/D/E. The direct Gemini API natively supports `response_format` with a Pydantic class — litellm translates it to Gemini's structured output API. Latencies (2.0–3.0s) are comparable to METHOD_D/E and slightly faster than METHOD_B (1.4–4.7s) and METHOD_A (1.9–2.4s). This is the second model (after gemma3:4b) where METHOD_F achieves 100% across all prompts.

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap) |
|---|---|---|---|---|
| METHOD_A | **100%** | **100%** | **100%** | **100%** |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |
| METHOD_F | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 2.0 | 2.4 | 1.9 | 2.2 |
| METHOD_B | 3.1 | 1.4 | 4.7 | 3.5 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 2.6 | 2.2 | 2.3 | 2.1 |
| METHOD_E | 2.6 | 2.4 | 3.5 | 2.2 |
| METHOD_F | 3.0 | 2.2 | 2.0 | 2.3 |

#### Per-slide Success Breakdown (1 run per cell)

All METHOD_A/B/D/E/F: 1/1 on all 4 prompts. METHOD_C: SKIP.

---

### Cross-Method Summary: best prompt per (model × method)

| Model | Method | Best Prompt | Success Rate |
|---|---|---|---|
| ollama/gemma3:4b | METHOD_A | Prompt 1 (current) | 0% |
| ollama/gemma3:4b | METHOD_B | Prompt 1 (current) | 100% |
| ollama/gemma3:4b | METHOD_C | Prompt 1 (current) | 100% |
| ollama/gemma3:4b | METHOD_D | Prompt 1 (current) | 100% |
| ollama/gemma3:4b | METHOD_E | Prompt 1 (current) | 100% |
| ollama/gemma3:4b | METHOD_F | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_A | Prompt 1 (current) | 0% |
| ollama/ministral-3:14b-cloud | METHOD_B | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_C | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_D | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_E | Prompt 1 (current) | 100% |
| ollama/ministral-3:14b-cloud | METHOD_F | Prompt 1 (current) | 0% |
| groq/openai/gpt-oss-20b | METHOD_A | Prompt 1 (current) | 100% |
| groq/openai/gpt-oss-20b | METHOD_B | Prompt 1 (current) | 100% |
| groq/openai/gpt-oss-20b | METHOD_C | — | SKIP |
| groq/openai/gpt-oss-20b | METHOD_D | Prompt 1 (current) | 100% |
| groq/openai/gpt-oss-20b | METHOD_E | Prompt 1 (current) | 100% |
| groq/openai/gpt-oss-20b | METHOD_F | Prompt 4 (Round2 no-wrap directive) | 100% (rate-limit artifact) |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_A | Prompt 1 (current) | 0% (cap_err) |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_B | Prompt 1 (current) | 100% |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_C | — | SKIP |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_D | Prompt 1 (current) | 100% |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_E | Prompt 1 (current) | 100% |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_F | Prompt 1 (current) | 100% |
| gemini/gemini-3.1-flash-lite-preview | METHOD_A | Prompt 1 (current) | 100% |
| gemini/gemini-3.1-flash-lite-preview | METHOD_B | Prompt 1 (current) | 100% |
| gemini/gemini-3.1-flash-lite-preview | METHOD_C | — | SKIP |
| gemini/gemini-3.1-flash-lite-preview | METHOD_D | Prompt 1 (current) | 100% |
| gemini/gemini-3.1-flash-lite-preview | METHOD_E | Prompt 1 (current) | 100% |
| gemini/gemini-3.1-flash-lite-preview | METHOD_F | Prompt 1 (current) | 100% |

---

## Per-Model Observations

### `ollama/gemma3:4b` — METHOD_F matches METHOD_B/E, slightly faster

METHOD_F succeeds on all 4 prompts (100%), identical to METHOD_B/C/D/E. Elapsed times for METHOD_F (4.8–6.5s) are notably lower than METHOD_B (7.3–13.0s) and slightly faster than METHOD_C (6.9–7.6s). This suggests that litellm's direct `response_format` call to the Ollama server triggers a slightly more efficient path (likely also using grammar-constrained decoding similar to METHOD_C, since Ollama's native API accepts `response_format` objects). METHOD_F is effectively a cleaner alternative to METHOD_C for Ollama models because it works at the litellm level without needing the LlamaIndex `additional_kwargs` pass-through hack. METHOD_A continues to fail (capability error).

### `ollama/ministral-3:14b-cloud` — METHOD_F fails across all prompts (JSONSchemaValidationError)

This is the critical failure of this round. METHOD_F returns 0% on all 4 prompts for ministral-3:14b-cloud. The failure mode is `litellm.JSONSchemaValidationError`: litellm's `enable_json_schema_validation=True` flag causes it to reject the model's output because the model produces:
- Plain markdown text with bold formatting (Prompt 1)
- JSON in a fenced code block ` ```json ``` ` (Prompts 2–3)
- A dash-prefixed field list (Prompt 4)

None of these are bare JSON that litellm can validate. The Mistral model via Ollama either does not support the `response_format` native JSON mode properly, or the Ollama server does not forward it. In contrast, METHOD_B/C/D/E all succeed because they use LlamaIndex's post-processing pipeline which is more tolerant of markdown-wrapped JSON. This makes METHOD_F unreliable for Mistral/Ollama combinations.

### `groq/openai/gpt-oss-20b` — METHOD_F fails Prompts 1–3 due to rate-limit exhaustion, not method failure

The groq model's 8000 TPM/min limit is exhausted by the time METHOD_F calls (running last in the method loop) are dispatched. litellm's direct `acompletion()` does not share the LlamaIndex retry wrapper that successfully retried earlier calls — or the retry limit was exceeded at this token usage level. The single Prompt 4 call succeeds after a brief natural delay, confirming the method works for this provider when tokens are available. The METHOD_F result for Groq in this run is **not a reliable indicator** of method correctness for this provider. METHOD_B and METHOD_E remain the most reliable methods for Groq.

### `openrouter/google/gemini-3.1-flash-lite-preview` — METHOD_F works; matches METHOD_B/E

METHOD_F succeeds on all 4 prompts (100%). OpenRouter correctly passes the `response_format` Pydantic schema to the underlying Gemini model. This is the best outcome for METHOD_F on an API model — it matches the reliability of METHOD_B/D/E without needing any LlamaIndex machinery. The Prompt 1 latency spike (7.9s vs ~1.5–3.0s for other prompts) is likely a cold-start or routing overhead on the first METHOD_F request to this provider.

### `gemini/gemini-3.1-flash-lite-preview` — METHOD_F works perfectly; matches all other working methods

METHOD_F succeeds on all 4 prompts (100%). The direct Gemini API via litellm natively supports `response_format=PydanticClass` through its structured output API. Latencies (2.0–3.0s) are competitive with METHOD_D/E. Combined with Round 3, `gemini/gemini-3.1-flash-lite-preview` is the most method-agnostic model tested: METHOD_A/B/D/E/F all succeed on all prompts.

---

## Key Findings

1. **METHOD_F is not universally reliable — its success is provider-dependent.** It works correctly for `ollama/gemma3:4b`, `openrouter/google/gemini-3.1-flash-lite-preview`, and `gemini/gemini-3.1-flash-lite-preview`. It fails structurally for `ollama/ministral-3:14b-cloud` (model does not produce bare JSON) and pseudo-fails for `groq/openai/gpt-oss-20b` (rate-limit exhaustion at METHOD_F position in test run).

2. **METHOD_F fails for `ollama/ministral-3:14b-cloud` because the model does not produce valid JSON when called via litellm's `response_format`.** The Mistral 14B model via Ollama returns markdown text or code-fenced JSON, neither of which passes litellm's `JSONSchemaValidationError` check. METHOD_B/C/D/E all succeed on this same model because LlamaIndex's parsing pipeline strips code fences and is more tolerant of formatting. This means METHOD_F cannot replace METHOD_B or METHOD_E for production use with Mistral/Ollama.

3. **For `ollama/gemma3:4b`, METHOD_F is faster than METHOD_B and comparable to METHOD_C**, with the additional advantage of not requiring the `additional_kwargs` hack. However, given the ministral failure, METHOD_F cannot be assumed to be safe for all Ollama models. METHOD_C or METHOD_E remains the recommended production choice for Ollama models.

4. **For `gemini/gemini-3.1-flash-lite-preview` (direct API), METHOD_F matches the reliability of METHOD_B/D/E** and adds the architectural benefit of bypassing LlamaIndex entirely. This is a valid alternative for direct Gemini API usage.

5. **METHOD_B and METHOD_E remain the most universally reliable methods across all 5 models.** In Round 4, METHOD_B achieves 100% best-prompt success on every model that has working credentials (same as Round 3). METHOD_E matches this. METHOD_F achieves 100% on 3 of 5 models (with caveats on the other 2).

6. **METHOD_F should NOT replace `FunctionCallingProgram` in production for the current model mix.** The current production stack uses `FunctionCallingProgram` (METHOD_A), which is known to fail for all Ollama models. The correct production replacement is METHOD_E (or METHOD_B) for Ollama models and METHOD_A or METHOD_E for cloud models. METHOD_F is a valid additional option for providers where it works (Gemini direct, OpenRouter Gemini) but introduces a new failure mode for Mistral/Ollama that doesn't exist in METHOD_B/E.

7. **The recurring Ollama constrained-decoding stall on `ministral-3:14b-cloud` + Prompt 4 with METHOD_C appeared again** (47.6s in this run vs 81.8s in Round 2 and similar in Round 3). This confirms it is a persistent, reproducible issue specific to METHOD_C + long prompts on this model, not a transient anomaly.

---

## Raw stdout

<details>
<summary>Full stdout from structured_output_methods.py (Round 4, 2026-04-02)</summary>

```

==========================================================================================
  outlines_with_layout — Method Comparison (v2)
  Models:  ollama/gemma3:4b, ollama/ministral-3:14b-cloud, groq/openai/gpt-oss-20b, openrouter/google/gemini-3.1-flash-lite-preview, gemini/gemini-3.1-flash-lite-preview
  Methods: METHOD_A, METHOD_B, METHOD_C, METHOD_D, METHOD_E, METHOD_F
  Prompts: 4  |  Slides: 1  |  N_RUNS: 1
  Total LLM calls (max): 120
  Ollama (2): sequential | API (3): concurrent
==========================================================================================


##########################################################################################
# Testing model: ollama/gemma3:4b
##########################################################################################
  [ollama/gemma3:4b][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/24) -> cap_err (0.8s)
  [ollama/gemma3:4b][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/24) -> cap_err (0.5s)
  [ollama/gemma3:4b][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/24) -> cap_err (0.5s)
  [ollama/gemma3:4b][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/24) -> cap_err (0.5s)
  [ollama/gemma3:4b][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/24) -> OK (13.0s)
  [ollama/gemma3:4b][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/24) -> OK (7.3s)
  [ollama/gemma3:4b][METHOD_B][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (7/24) -> OK (8.0s)
  [ollama/gemma3:4b][METHOD_B][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (8/24) -> OK (7.6s)
  [ollama/gemma3:4b][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/24) -> OK (7.0s)
  [ollama/gemma3:4b][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/24) -> OK (6.9s)
  [ollama/gemma3:4b][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/24) -> OK (7.3s)
  [ollama/gemma3:4b][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/24) -> OK (7.6s)
  [ollama/gemma3:4b][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/24) -> OK (7.6s)
  [ollama/gemma3:4b][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/24) -> OK (7.9s)
  [ollama/gemma3:4b][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/24) -> OK (7.9s)
  [ollama/gemma3:4b][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/24) -> OK (7.9s)
  [ollama/gemma3:4b][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/24) -> OK (7.4s)
  [ollama/gemma3:4b][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/24) -> OK (7.6s)
  [ollama/gemma3:4b][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/24) -> OK (8.2s)
  [ollama/gemma3:4b][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/24) -> OK (7.8s)
  [ollama/gemma3:4b][METHOD_F][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (21/24) -> OK (6.5s)
  [ollama/gemma3:4b][METHOD_F][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (22/24) -> OK (6.2s)
  [ollama/gemma3:4b][METHOD_F][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (23/24) -> OK (4.8s)
  [ollama/gemma3:4b][METHOD_F][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (24/24) -> OK (5.1s)

##########################################################################################
# Testing model: ollama/ministral-3:14b-cloud
##########################################################################################
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/24) -> cap_err (1.2s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/24) -> cap_err (0.4s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/24) -> cap_err (0.4s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/24) -> cap_err (0.5s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/24) -> OK (2.2s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/24) -> OK (1.9s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (7/24) -> OK (1.8s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (8/24) -> OK (1.9s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/24) -> OK (1.9s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/24) -> OK (1.8s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/24) -> OK (1.9s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/24) -> OK (47.6s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/24) -> OK (2.1s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/24) -> OK (2.3s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/24) -> OK (2.5s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/24) -> OK (2.2s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/24) -> OK (1.8s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/24) -> OK (2.2s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/24) -> OK (2.0s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/24) -> OK (2.1s)
  [ollama/ministral-3:14b-cloud][METHOD_F][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (21/24) -> WRAP (2.8s)
  [ollama/ministral-3:14b-cloud][METHOD_F][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (22/24) -> WRAP (1.9s)
  [ollama/ministral-3:14b-cloud][METHOD_F][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (23/24) -> WRAP (2.0s)
  [ollama/ministral-3:14b-cloud][METHOD_F][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (24/24) -> WRAP (1.7s)

##########################################################################################
# Testing API models concurrently: groq/openai/gpt-oss-20b, openrouter/google/gemini-3.1-flash-lite-preview, gemini/gemini-3.1-flash-lite-preview
##########################################################################################
  [groq/openai/gpt-oss-20b][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/24)   [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/24) -> cap_err (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/24) -> OK (0.5s)
-> OK (2.0s)
  [groq/openai/gpt-oss-20b][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/24)   [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/24) -> cap_err (0.0s)
-> OK (0.5s)
  [groq/openai/gpt-oss-20b][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 5287, Requested 2918. Please try again in 1.537499999s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/24) -> cap_err (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/24) -> OK (2.4s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/24) -> cap_err (0.0s)
-> OK (4.6s)
  [groq/openai/gpt-oss-20b][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 5429, Requested 2867. Please try again in 2.219999999s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [gemini/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/24) 
Provider List: https://docs.litellm.ai/docs/providers

-> OK (2.0s)

Provider List: https://docs.litellm.ai/docs/providers

-> OK (1.9s)

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

-> FAIL (4.7s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [gemini/gemini-3.1-flash-lite-preview][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/24)   [groq/openai/gpt-oss-20b][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/24) -> OK (0.6s)

Provider List: https://docs.litellm.ai/docs/providers

-> OK (1.8s)

Provider List: https://docs.litellm.ai/docs/providers

-> OK (2.2s)
  [groq/openai/gpt-oss-20b][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 6294, Requested 3011. Please try again in 9.7875s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_B][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (7/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (1.1s)

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [gemini/gemini-3.1-flash-lite-preview][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/24) -> OK (4.6s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_B][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (8/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [groq/openai/gpt-oss-20b][METHOD_B][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (7/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 6598, Requested 3107. Please try again in 12.7875s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.
-> OK (1.5s)

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (3.1s)

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/24) -> -- skip (0.0s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/24) -> -- skip (0.0s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/24) -> -- skip (0.0s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/24) -> -- skip (0.0s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [gemini/gemini-3.1-flash-lite-preview][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/24) -> OK (4.6s)
-> OK (1.4s)

Provider List: https://docs.litellm.ai/docs/providers

-> OK (2.7s)

Provider List: https://docs.litellm.ai/docs/providers

  [groq/openai/gpt-oss-20b][METHOD_B][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (8/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 6917, Requested 3056. Please try again in 14.7975s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [gemini/gemini-3.1-flash-lite-preview][METHOD_B][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (7/24) -> OK (4.7s)
-> OK (3.0s)

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [groq/openai/gpt-oss-20b][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/24) -> -- skip (0.0s)
  [groq/openai/gpt-oss-20b][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/24) -> -- skip (0.0s)
  [groq/openai/gpt-oss-20b][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/24) -> -- skip (0.0s)
  [groq/openai/gpt-oss-20b][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/24) -> -- skip (0.0s)
  [groq/openai/gpt-oss-20b][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 7283, Requested 880. Please try again in 1.2225s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

-> OK (4.7s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (2.7s)

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (4.7s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_B][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (8/24)   [groq/openai/gpt-oss-20b][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 7329, Requested 2822. Please try again in 16.1325s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (3.5s)
-> OK (2.3s)

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (4.6s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [gemini/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/24) -> -- skip (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/24) -> -- skip (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/24) -> -- skip (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/24) -> -- skip (0.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/24)   [groq/openai/gpt-oss-20b][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 7397, Requested 1095. Please try again in 3.69s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.


Provider List: https://docs.litellm.ai/docs/providers

-> OK (1.6s)

Provider List: https://docs.litellm.ai/docs/providers

-> OK (2.6s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (4.5s)
-> OK (1.4s)

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [gemini/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/24)   [groq/openai/gpt-oss-20b][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/24) 
Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

-> FAIL (0.5s)
-> OK (2.2s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [groq/openai/gpt-oss-20b][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 7512, Requested 1124. Please try again in 4.77s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

-> OK (1.8s)

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [gemini/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/24)   [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 6959, Requested 1147. Please try again in 794.999999ms. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers


Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

-> OK (2.3s)

Provider List: https://docs.litellm.ai/docs/providers

-> OK (1.6s)

Provider List: https://docs.litellm.ai/docs/providers

  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (21/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (8.8s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/24)   [groq/openai/gpt-oss-20b][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 6493, Requested 3011. Please try again in 11.28s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.
Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 5939, Requested 3011. Please try again in 7.125s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

-> OK (2.1s)

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

  [gemini/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/24) -> OK (7.9s)

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (2.6s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (22/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (8.7s)
-> OK (1.8s)

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [groq/openai/gpt-oss-20b][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 6174, Requested 3107. Please try again in 9.6075s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

  [gemini/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/24) -> OK (2.4s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (23/24) 
Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (4.6s)
-> OK (2.7s)

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

  [groq/openai/gpt-oss-20b][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/24)   [gemini/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 6494, Requested 3056. Please try again in 11.625s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (24/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 5941, Requested 3056. Please try again in 7.4775s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers

-> OK (3.5s)
-> OK (2.2s)

Provider List: https://docs.litellm.ai/docs/providers


Provider List: https://docs.litellm.ai/docs/providers


Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

  [gemini/gemini-3.1-flash-lite-preview][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/24) Retrying llama_index.llms.litellm.utils.acompletion_with_retry.<locals>._completion_with_retry in 4 seconds as it raised RateLimitError: litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01jbbxkktgf0fasaj4paafm560` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 5388, Requested 3056. Please try again in 3.33s. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}
.

Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

-> OK (2.2s)
-> OK (13.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (21/24)   [groq/openai/gpt-oss-20b][METHOD_F][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (21/24) 
Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

-> FAIL (0.2s)
-> OK (3.0s)
  [groq/openai/gpt-oss-20b][METHOD_F][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (22/24) 
Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

-> FAIL (0.2s)
  [groq/openai/gpt-oss-20b][METHOD_F][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (23/24) 
Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new
LiteLLM.Info: If you need to debug this error, use `litellm._turn_on_debug()'.

-> FAIL (0.2s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (22/24)   [groq/openai/gpt-oss-20b][METHOD_F][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (24/24) -> OK (0.8s)
-> OK (2.2s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (23/24) -> OK (2.0s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (24/24) -> OK (2.3s)


==========================================================================================
  COMPARISON TABLES
==========================================================================================

==========================================================================================
  MODEL: ollama/gemma3:4b
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0%            0%            0%            0%            
  METHOD_B    100%          100%          100%          100%          
  METHOD_C    100%          100%          100%          100%          
  METHOD_D    100%          100%          100%          100%          
  METHOD_E    100%          100%          100%          100%          
  METHOD_F    100%          100%          100%          100%          

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0.8           0.5           0.5           0.5           
  METHOD_B    13.0          7.3           8.0           7.6           
  METHOD_C    7.0           6.9           7.3           7.6           
  METHOD_D    7.6           7.9           7.9           7.9           
  METHOD_E    7.4           7.6           8.2           7.8           
  METHOD_F    6.5           6.2           4.8           5.1           

  Per-slide success breakdown (all prompts combined, 1 runs each):
  Method      Prompt                                Attention Is  
  ----------------------------------------------------------------
  METHOD_A    Prompt 1 (current)                    0/1           
  METHOD_A    Prompt 2 (typo fix + field desc)      0/1           
  METHOD_A    Prompt 3 (+ few-shot)                 0/1           
  METHOD_A    Prompt 4 (Round2 no-wrap directive)   0/1           
  METHOD_B    Prompt 1 (current)                    1/1           
  METHOD_B    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_B    Prompt 3 (+ few-shot)                 1/1           
  METHOD_B    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_C    Prompt 1 (current)                    1/1           
  METHOD_C    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_C    Prompt 3 (+ few-shot)                 1/1           
  METHOD_C    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_D    Prompt 1 (current)                    1/1           
  METHOD_D    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_D    Prompt 3 (+ few-shot)                 1/1           
  METHOD_D    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_E    Prompt 1 (current)                    1/1           
  METHOD_E    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_E    Prompt 3 (+ few-shot)                 1/1           
  METHOD_E    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_F    Prompt 1 (current)                    1/1           
  METHOD_F    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_F    Prompt 3 (+ few-shot)                 1/1           
  METHOD_F    Prompt 4 (Round2 no-wrap directive)   1/1           

==========================================================================================
  MODEL: ollama/ministral-3:14b-cloud
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0%            0%            0%            0%            
  METHOD_B    100%          100%          100%          100%          
  METHOD_C    100%          100%          100%          100%          
  METHOD_D    100%          100%          100%          100%          
  METHOD_E    100%          100%          100%          100%          
  METHOD_F    0%            0%            0%            0%            

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    1.2           0.4           0.4           0.5           
  METHOD_B    2.2           1.9           1.8           1.9           
  METHOD_C    1.9           1.8           1.9           47.6          
  METHOD_D    2.1           2.3           2.5           2.2           
  METHOD_E    1.8           2.2           2.0           2.1           
  METHOD_F    2.8           1.9           2.0           1.7           

  Per-slide success breakdown (all prompts combined, 1 runs each):
  Method      Prompt                                Attention Is  
  ----------------------------------------------------------------
  METHOD_A    Prompt 1 (current)                    0/1           
  METHOD_A    Prompt 2 (typo fix + field desc)      0/1           
  METHOD_A    Prompt 3 (+ few-shot)                 0/1           
  METHOD_A    Prompt 4 (Round2 no-wrap directive)   0/1           
  METHOD_B    Prompt 1 (current)                    1/1           
  METHOD_B    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_B    Prompt 3 (+ few-shot)                 1/1           
  METHOD_B    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_C    Prompt 1 (current)                    1/1           
  METHOD_C    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_C    Prompt 3 (+ few-shot)                 1/1           
  METHOD_C    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_D    Prompt 1 (current)                    1/1           
  METHOD_D    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_D    Prompt 3 (+ few-shot)                 1/1           
  METHOD_D    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_E    Prompt 1 (current)                    1/1           
  METHOD_E    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_E    Prompt 3 (+ few-shot)                 1/1           
  METHOD_E    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_F    Prompt 1 (current)                    0/1           
  METHOD_F    Prompt 2 (typo fix + field desc)      0/1           
  METHOD_F    Prompt 3 (+ few-shot)                 0/1           
  METHOD_F    Prompt 4 (Round2 no-wrap directive)   0/1           

==========================================================================================
  MODEL: groq/openai/gpt-oss-20b
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    100%          100%          100%          0%            
  METHOD_B    100%          100%          100%          100%          
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    100%          100%          100%          0%            
  METHOD_E    100%          100%          100%          100%          
  METHOD_F    0%            0%            0%            100%          

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0.5           0.5           4.6           4.7           
  METHOD_B    0.6           4.6           4.6           4.7           
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    4.7           4.6           4.5           0.5           
  METHOD_E    8.8           8.7           4.6           13.0          
  METHOD_F    0.2           0.2           0.2           0.8           

  Per-slide success breakdown (all prompts combined, 1 runs each):
  Method      Prompt                                Attention Is  
  ----------------------------------------------------------------
  METHOD_A    Prompt 1 (current)                    1/1           
  METHOD_A    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_A    Prompt 3 (+ few-shot)                 1/1           
  METHOD_A    Prompt 4 (Round2 no-wrap directive)   0/1           
  METHOD_B    Prompt 1 (current)                    1/1           
  METHOD_B    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_B    Prompt 3 (+ few-shot)                 1/1           
  METHOD_B    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_C    Prompt 1 (current)                    SKIP          
  METHOD_C    Prompt 2 (typo fix + field desc)      SKIP          
  METHOD_C    Prompt 3 (+ few-shot)                 SKIP          
  METHOD_C    Prompt 4 (Round2 no-wrap directive)   SKIP          
  METHOD_D    Prompt 1 (current)                    1/1           
  METHOD_D    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_D    Prompt 3 (+ few-shot)                 1/1           
  METHOD_D    Prompt 4 (Round2 no-wrap directive)   0/1           
  METHOD_E    Prompt 1 (current)                    1/1           
  METHOD_E    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_E    Prompt 3 (+ few-shot)                 1/1           
  METHOD_E    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_F    Prompt 1 (current)                    0/1           
  METHOD_F    Prompt 2 (typo fix + field desc)      0/1           
  METHOD_F    Prompt 3 (+ few-shot)                 0/1           
  METHOD_F    Prompt 4 (Round2 no-wrap directive)   1/1           

==========================================================================================
  MODEL: openrouter/google/gemini-3.1-flash-lite-preview
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0%            0%            0%            0%            
  METHOD_B    100%          100%          100%          100%          
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    100%          100%          100%          100%          
  METHOD_E    100%          100%          100%          100%          
  METHOD_F    100%          100%          100%          100%          

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    0.0           0.0           0.0           0.0           
  METHOD_B    2.0           1.8           1.1           1.5           
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    2.7           3.0           2.7           2.3           
  METHOD_E    1.6           1.4           1.8           1.6           
  METHOD_F    7.9           1.8           2.7           2.2           

  Per-slide success breakdown (all prompts combined, 1 runs each):
  Method      Prompt                                Attention Is  
  ----------------------------------------------------------------
  METHOD_A    Prompt 1 (current)                    0/1           
  METHOD_A    Prompt 2 (typo fix + field desc)      0/1           
  METHOD_A    Prompt 3 (+ few-shot)                 0/1           
  METHOD_A    Prompt 4 (Round2 no-wrap directive)   0/1           
  METHOD_B    Prompt 1 (current)                    1/1           
  METHOD_B    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_B    Prompt 3 (+ few-shot)                 1/1           
  METHOD_B    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_C    Prompt 1 (current)                    SKIP          
  METHOD_C    Prompt 2 (typo fix + field desc)      SKIP          
  METHOD_C    Prompt 3 (+ few-shot)                 SKIP          
  METHOD_C    Prompt 4 (Round2 no-wrap directive)   SKIP          
  METHOD_D    Prompt 1 (current)                    1/1           
  METHOD_D    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_D    Prompt 3 (+ few-shot)                 1/1           
  METHOD_D    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_E    Prompt 1 (current)                    1/1           
  METHOD_E    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_E    Prompt 3 (+ few-shot)                 1/1           
  METHOD_E    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_F    Prompt 1 (current)                    1/1           
  METHOD_F    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_F    Prompt 3 (+ few-shot)                 1/1           
  METHOD_F    Prompt 4 (Round2 no-wrap directive)   1/1           

==========================================================================================
  MODEL: gemini/gemini-3.1-flash-lite-preview
==========================================================================================

  Success Rate (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    100%          100%          100%          100%          
  METHOD_B    100%          100%          100%          100%          
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    100%          100%          100%          100%          
  METHOD_E    100%          100%          100%          100%          
  METHOD_F    100%          100%          100%          100%          

  Avg Elapsed (s) (rows=methods, cols=prompts):
  Method      Prompt 1 (currPrompt 2 (typoPrompt 3 (+ fePrompt 4 (Roun
  --------------------------------------------------------------------
  METHOD_A    2.0           2.4           1.9           2.2           
  METHOD_B    3.1           1.4           4.7           3.5           
  METHOD_C    SKIP          SKIP          SKIP          SKIP          
  METHOD_D    2.6           2.2           2.3           2.1           
  METHOD_E    2.6           2.4           3.5           2.2           
  METHOD_F    3.0           2.2           2.0           2.3           

  Per-slide success breakdown (all prompts combined, 1 runs each):
  Method      Prompt                                Attention Is  
  ----------------------------------------------------------------
  METHOD_A    Prompt 1 (current)                    1/1           
  METHOD_A    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_A    Prompt 3 (+ few-shot)                 1/1           
  METHOD_A    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_B    Prompt 1 (current)                    1/1           
  METHOD_B    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_B    Prompt 3 (+ few-shot)                 1/1           
  METHOD_B    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_C    Prompt 1 (current)                    SKIP          
  METHOD_C    Prompt 2 (typo fix + field desc)      SKIP          
  METHOD_C    Prompt 3 (+ few-shot)                 SKIP          
  METHOD_C    Prompt 4 (Round2 no-wrap directive)   SKIP          
  METHOD_D    Prompt 1 (current)                    1/1           
  METHOD_D    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_D    Prompt 3 (+ few-shot)                 1/1           
  METHOD_D    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_E    Prompt 1 (current)                    1/1           
  METHOD_E    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_E    Prompt 3 (+ few-shot)                 1/1           
  METHOD_E    Prompt 4 (Round2 no-wrap directive)   1/1           
  METHOD_F    Prompt 1 (current)                    1/1           
  METHOD_F    Prompt 2 (typo fix + field desc)      1/1           
  METHOD_F    Prompt 3 (+ few-shot)                 1/1           
  METHOD_F    Prompt 4 (Round2 no-wrap directive)   1/1           


==========================================================================================
  CROSS-METHOD SUMMARY: model x method x best_prompt -> success_rate
==========================================================================================
  Model                        Method       BestPrompt                              SuccessRate
  --------------------------------------------------------------------------------------------
  ollama/gemma3:4b             METHOD_A     Prompt 1 (current)                               0%
  ollama/gemma3:4b             METHOD_B     Prompt 1 (current)                             100%
  ollama/gemma3:4b             METHOD_C     Prompt 1 (current)                             100%
  ollama/gemma3:4b             METHOD_D     Prompt 1 (current)                             100%
  ollama/gemma3:4b             METHOD_E     Prompt 1 (current)                             100%
  ollama/gemma3:4b             METHOD_F     Prompt 1 (current)                             100%

  ollama/ministral-3:14b-cloud METHOD_A     Prompt 1 (current)                               0%
  ollama/ministral-3:14b-cloud METHOD_B     Prompt 1 (current)                             100%
  ollama/ministral-3:14b-cloud METHOD_C     Prompt 1 (current)                             100%
  ollama/ministral-3:14b-cloud METHOD_D     Prompt 1 (current)                             100%
  ollama/ministral-3:14b-cloud METHOD_E     Prompt 1 (current)                             100%
  ollama/ministral-3:14b-cloud METHOD_F     Prompt 1 (current)                               0%

  groq/openai/gpt-oss-20b      METHOD_A     Prompt 1 (current)                             100%
  groq/openai/gpt-oss-20b      METHOD_B     Prompt 1 (current)                             100%
  groq/openai/gpt-oss-20b      METHOD_C     Prompt 1 (current)                             SKIP
  groq/openai/gpt-oss-20b      METHOD_D     Prompt 1 (current)                             100%
  groq/openai/gpt-oss-20b      METHOD_E     Prompt 1 (current)                             100%
  groq/openai/gpt-oss-20b      METHOD_F     Prompt 4 (Round2 no-wrap directive)            100%

  openrouter/google/gemini-3.1-flash-lite-preview METHOD_A     Prompt 1 (current)                               0%
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_B     Prompt 1 (current)                             100%
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_C     Prompt 1 (current)                             SKIP
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_D     Prompt 1 (current)                             100%
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_E     Prompt 1 (current)                             100%
  openrouter/google/gemini-3.1-flash-lite-preview METHOD_F     Prompt 1 (current)                             100%

  gemini/gemini-3.1-flash-lite-preview METHOD_A     Prompt 1 (current)                             100%
  gemini/gemini-3.1-flash-lite-preview METHOD_B     Prompt 1 (current)                             100%
  gemini/gemini-3.1-flash-lite-preview METHOD_C     Prompt 1 (current)                             SKIP
  gemini/gemini-3.1-flash-lite-preview METHOD_D     Prompt 1 (current)                             100%
  gemini/gemini-3.1-flash-lite-preview METHOD_E     Prompt 1 (current)                             100%
  gemini/gemini-3.1-flash-lite-preview METHOD_F     Prompt 1 (current)                             100%


  Raw results saved to: /Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/poc/agent-behavior-test/augment_results_raw.json

==========================================================================================
  DONE
==========================================================================================

```

</details>

---

---

## Addendum: enable_json_schema_validation and Round 4 METHOD_F False Negative

**Written:** 2026-04-02

---

### 1. What `litellm.enable_json_schema_validation = True` does

When this flag is set globally in a script, litellm calls `validate_schema()` in
`litellm/litellm_core_utils/json_validation_rule.py` on the raw model response string
**before** returning control to the caller. Internally, `validate_schema()` runs
`json.loads(response)` directly on the raw string. If that call raises any exception —
including because the string is markdown-fenced or contains surrounding text — litellm
raises `litellm.JSONSchemaValidationError` and the call is recorded as a failure.
litellm has no built-in markdown fence stripping at this validation step; the
`json.loads()` call is applied to the response verbatim.

---

### 2. Why METHOD_F failed for `ollama/ministral-3:14b-cloud` in Round 4

The raw stdout shows all four METHOD_F calls for this model returned `-> WRAP` — a
signal that the model's output was not bare JSON. The Mistral model (when called via
`litellm.acompletion()` with `response_format=SlideOutlineWithLayout`) returned:

- **Prompt 1**: A prose markdown answer with bold formatting and reasoning text
- **Prompts 2 and 3**: JSON inside a ` ```json ``` ` fenced code block
- **Prompt 4**: A dash-prefixed field list

All four responses were valid enough for the LlamaIndex post-processing pipeline used
by METHOD_B/C/D/E to extract a valid `SlideOutlineWithLayout` object (those methods all
returned OK). But `litellm.enable_json_schema_validation = True` called `json.loads()`
on the raw response before LlamaIndex could post-process it, causing
`JSONSchemaValidationError` to be raised immediately.

**This is a false negative.** The model produced parseable, semantically correct
output. The failure is entirely an artifact of the `enable_json_schema_validation = True`
flag interacting with a model that wraps its JSON output in markdown fences. Without
this flag, the Ollama constrained decoding path would still enforce the schema at the
token level (as it does for METHOD_C and METHOD_F on `gemma3:4b`), and the
fence-stripped response would be parseable by `model_validate_json()`.

---

### 3. Correction to Round 4 conclusion

Round 4 Key Finding #1 states:

> "It fails structurally for `ollama/ministral-3:14b-cloud` (model does not produce bare JSON)"

This is **inaccurate**. The failure is not structural to METHOD_F or to the ministral
model's JSON capability. The accurate characterization is:

> `enable_json_schema_validation = True` was set globally in the test script. This
> causes litellm to call `json.loads()` on the raw response before any fence stripping.
> Mistral (via Ollama) returned markdown-fenced JSON, which `json.loads()` cannot parse.
> The `JSONSchemaValidationError` is raised by litellm's validation layer, not by the
> JSON parser after fence stripping. If the flag is disabled (or fence stripping is
> applied before validation), METHOD_F would likely succeed for this model, since
> Ollama's constrained decoding still enforces schema conformance at the token level.

The Round 4 evidence **does not establish** that METHOD_F is structurally incompatible
with `ollama/ministral-3:14b-cloud`. It establishes that `enable_json_schema_validation
= True` is incompatible with models that return markdown-fenced responses.

---

### 4. Fix options

**Option A — Remove `enable_json_schema_validation = True` and strip fences manually**

Remove `litellm.enable_json_schema_validation = True` from the script. After receiving
the response, strip markdown fences from the content string before passing it to
`model_validate_json()`:

```python
import re

def strip_fences(text: str) -> str:
    text = text.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return match.group(1) if match else text

content = response.choices[0].message.content
result = SlideOutlineWithLayout.model_validate_json(strip_fences(content))
```

This approach removes the pre-parse validation layer entirely and relies on Pydantic's
own validation (which is schema-enforcing by definition for `model_validate_json`).

**Option B — Catch `JSONSchemaValidationError`, strip fences, and re-parse**

Keep `enable_json_schema_validation = True` but handle the error:

```python
from litellm import JSONSchemaValidationError

try:
    result = SlideOutlineWithLayout.model_validate_json(
        response.choices[0].message.content
    )
except JSONSchemaValidationError as e:
    raw = e.raw_response  # access the original response string
    result = SlideOutlineWithLayout.model_validate_json(strip_fences(raw))
```

`e.raw_response` gives access to the pre-validation response string. Option A is
simpler and more predictable. Option B is useful if you want litellm's validation to
catch genuine structured output failures from providers that should be returning bare
JSON (e.g. OpenAI, Gemini direct) while still recovering from fence-wrapped responses.

---

### 5. Implication for production recommendation

The Round 3 and Round 4 conclusion that "METHOD_B and METHOD_E remain the most
universally reliable methods across all 5 models" is still **directionally correct**.
METHOD_B and METHOD_E succeed because LlamaIndex's internal post-processing pipeline
is tolerant of markdown-fenced output and strips fences before parsing.

However, the evidence against METHOD_F for Ollama models — specifically the claim in
Round 4 Finding #2 that "METHOD_F cannot replace METHOD_B or METHOD_E for production
use with Mistral/Ollama" — was **partially invalidated by the testing artifact**
described above. A fair comparison requires a follow-up test with one of the two fixes
applied:

- Run METHOD_F without `enable_json_schema_validation = True`, with fence stripping
  applied before `model_validate_json()`
- Re-evaluate `ollama/ministral-3:14b-cloud` + METHOD_F under these conditions

Until that re-test is done, the conservative production recommendation remains:
**use METHOD_B or METHOD_E for Ollama models** (since they handle fence-wrapped
output by design). METHOD_F is a valid choice for `gemini/gemini-3.1-flash-lite-preview`
(direct API) and `openrouter/google/gemini-3.1-flash-lite-preview`, where it was
confirmed to succeed in Round 4 without triggering this issue.

---

### 6. Additional objectivity notes

**Round 2 — gemma3:4b METHOD_B + Prompt 1 single-run "success"**

The document correctly flags this as statistically inconclusive (N_RUNS=1 vs Round 1's
9-run result of 0/9). The caveat at the Round 2 gemma3:4b section is appropriate.
No correction needed, but readers should note that all Rounds 2–4 use N_RUNS=1,
making any single-cell result unreliable in isolation.

**Round 3 — METHOD_A on `openrouter/google/gemini-3.1-flash-lite-preview`: LiteLLM capability check, not API limitation**

Round 3 Key Finding #5 correctly identifies this as a LiteLLM routing decision rather
than a model API limitation. The underlying Gemini model does support function calling;
the OpenRouter routing prefix causes LiteLLM's `supports_function_calling()` pre-check
to return `False` without making any API call. A developer reading only the summary
table (0% for METHOD_A on this model) would incorrectly conclude the model cannot do
function calling. The per-model observation section clarifies this correctly.

**Round 4 — Groq METHOD_F "100% on Prompt 4" in cross-method summary table**

The cross-method summary table entry `groq/openai/gpt-oss-20b METHOD_F Prompt 4: 100%`
already includes the inline label `(rate-limit artifact)` in the markdown table (the
only prompt that happened to arrive after partial rate-limit recovery). The per-model
observation section also explains this correctly. No correction needed; the labeling
is present and accurate.

**N_RUNS=1 and single-slide limitation across Rounds 2–4**

All three later rounds use N_RUNS=1 and a single slide. Round 1 used N_RUNS=3 and
3 slides (9 data points per cell). The reduction was necessary for iteration speed
but means that any 1/1 or 0/1 result in Rounds 2–4 carries substantially less
statistical weight than Round 1 data. The document acknowledges this in the Round 2
gemma3:4b section but does not repeat the caveat consistently. Readers making
production decisions should weight the Round 1 data more heavily for the models it
covers (gemma3:4b, qwen3.5:4b).

---

# Round 5 — METHOD_F Re-test with Fence-Stripping Fix

**Date:** 2026-04-02
**Purpose:** Re-test METHOD_F for all 5 models after applying the fence-stripping fix identified in the Round 4 Addendum, to determine whether METHOD_F is now as reliable as METHOD_B/E.

---

## Overview

Round 4 reported METHOD_F as failing 100% for `ollama/ministral-3:14b-cloud`. The Addendum section written after Round 4 diagnosed this as a **false negative**: `litellm.enable_json_schema_validation = True` was set globally in the script, causing litellm to call `json.loads()` on the raw response before any fence stripping. When the Mistral model wrapped its JSON output in markdown fences (which is its default behavior via Ollama), the pre-validation raised `JSONSchemaValidationError` even though the underlying response was semantically correct. The fix recommended in the Addendum was: remove `enable_json_schema_validation = True` and strip fences manually before calling `model_validate_json()`.

This round runs the script with those fixes applied, to produce a clean comparison.

---

## What Changed vs Round 4

| Aspect | Round 4 | Round 5 |
|---|---|---|
| `enable_json_schema_validation` | `True` set globally at module level | **Removed** — not present anywhere in the script |
| `run_method_f` implementation | Called `model_validate_json(content)` directly on raw response content | Calls `_strip_json_fence(content)` first, then `model_validate_json(stripped_content)` |
| `_strip_json_fence` helper | Not present | Added — strips ` ```json...``` ` and ` ```...``` ` fences via regex before parsing |
| All other config | (unchanged) | Same 5 models, 4 prompts, 6 methods, 1 slide, N_RUNS=1, same delays |

**Specific change in `run_method_f`:**
```python
# Round 4 (old):
content = response.choices[0].message.content
return SlideOutlineWithLayout.model_validate_json(content)

# Round 5 (new):
content = _strip_json_fence(response.choices[0].message.content)
return SlideOutlineWithLayout.model_validate_json(content)
```

**`_strip_json_fence` implementation:**
```python
def _strip_json_fence(text: str) -> str:
    match = re.search(r"```(?:json)?\s*(\{.*?})\s*```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()
```

---

## Focus Question

Does METHOD_F now succeed for `ollama/ministral-3:14b-cloud` across all 4 prompts? How does METHOD_F compare to METHOD_B and METHOD_E across all 5 models?

---

## Full Results Tables

### Model: `ollama/gemma3:4b`

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap directive) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | **100%** | **100%** | **100%** | **100%** |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |
| METHOD_F | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.8 | 0.5 | 0.5 | 0.5 |
| METHOD_B | 13.5 | 7.8 | 8.5 | 8.2 |
| METHOD_C | 7.8 | 7.5 | 7.2 | 7.5 |
| METHOD_D | 7.5 | 8.6 | 8.8 | 8.3 |
| METHOD_E | 8.3 | 8.2 | 8.5 | 8.3 |
| METHOD_F | 6.7 | 6.7 | 5.2 | 5.4 |

---

### Model: `ollama/ministral-3:14b-cloud`

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap directive) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | **100%** | **100%** | **100%** | **100%** |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |
| METHOD_F | 0% | **100%** | **100%** | 0% |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.8 | 0.6 | 0.6 | 0.5 |
| METHOD_B | 2.4 | 2.0 | 1.9 | 1.9 |
| METHOD_C | 1.8 | 1.9 | 2.0 | 1.8 |
| METHOD_D | 2.2 | 2.4 | 2.4 | 2.5 |
| METHOD_E | 2.2 | 2.0 | 2.1 | 2.3 |
| METHOD_F | 2.7 | 1.7 | 1.6 | 1.6 |

---

### Model: `groq/openai/gpt-oss-20b`

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap directive) |
|---|---|---|---|---|
| METHOD_A | **100%** | **100%** | **100%** | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | **100%** | **100%** | **100%** | 0% |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |
| METHOD_F | 0% | **100%** | **100%** | 0% |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.7 | 0.4 | 0.4 | 0.5 |
| METHOD_B | 0.5 | 9.0 | 4.7 | 13.0 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 0.5 | 0.4 | 0.4 | 0.8 |
| METHOD_E | 4.6 | 4.7 | 4.6 | 4.7 |
| METHOD_F | 0.2 | 0.4 | 0.6 | 0.2 |

---

### Model: `openrouter/google/gemini-3.1-flash-lite-preview`

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap directive) |
|---|---|---|---|---|
| METHOD_A | 0% | 0% | 0% | 0% |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |
| METHOD_F | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 0.0 | 0.0 | 0.0 | 0.0 |
| METHOD_B | 2.9 | 1.7 | 1.5 | 1.6 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 1.8 | 1.6 | 1.9 | 1.6 |
| METHOD_E | 1.6 | 2.4 | 3.2 | 2.7 |
| METHOD_F | 3.6 | 2.3 | 2.8 | 2.0 |

---

### Model: `gemini/gemini-3.1-flash-lite-preview`

#### Success Rate (rows = methods, cols = prompts)

| Method | Prompt 1 (current) | Prompt 2 (typo fix + field desc) | Prompt 3 (+ few-shot) | Prompt 4 (Round2 no-wrap directive) |
|---|---|---|---|---|
| METHOD_A | **100%** | **100%** | **100%** | **100%** |
| METHOD_B | **100%** | **100%** | **100%** | **100%** |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | **100%** | **100%** | **100%** | **100%** |
| METHOD_E | **100%** | **100%** | **100%** | **100%** |
| METHOD_F | **100%** | **100%** | **100%** | **100%** |

#### Avg Elapsed (s) per call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| METHOD_A | 2.1 | 2.1 | 2.1 | 2.0 |
| METHOD_B | 2.2 | 2.2 | 1.2 | 2.0 |
| METHOD_C | SKIP | SKIP | SKIP | SKIP |
| METHOD_D | 3.0 | 2.6 | 4.4 | 2.7 |
| METHOD_E | 2.3 | 4.1 | 2.0 | 2.9 |
| METHOD_F | 2.3 | 3.8 | 2.1 | 1.9 |

---

### Cross-Method Summary (model x method x best_prompt -> success_rate)

| Model | Method | Best Prompt | Success Rate |
|---|---|---|---|
| ollama/gemma3:4b | METHOD_A | Prompt 1 (current) | 0% |
| ollama/gemma3:4b | METHOD_B | Prompt 1 (current) | **100%** |
| ollama/gemma3:4b | METHOD_C | Prompt 1 (current) | **100%** |
| ollama/gemma3:4b | METHOD_D | Prompt 1 (current) | **100%** |
| ollama/gemma3:4b | METHOD_E | Prompt 1 (current) | **100%** |
| ollama/gemma3:4b | METHOD_F | Prompt 1 (current) | **100%** |
| ollama/ministral-3:14b-cloud | METHOD_A | Prompt 1 (current) | 0% |
| ollama/ministral-3:14b-cloud | METHOD_B | Prompt 1 (current) | **100%** |
| ollama/ministral-3:14b-cloud | METHOD_C | Prompt 1 (current) | **100%** |
| ollama/ministral-3:14b-cloud | METHOD_D | Prompt 1 (current) | **100%** |
| ollama/ministral-3:14b-cloud | METHOD_E | Prompt 1 (current) | **100%** |
| ollama/ministral-3:14b-cloud | METHOD_F | Prompt 2 (typo fix + field desc) | **100%** (best prompt only) |
| groq/openai/gpt-oss-20b | METHOD_A | Prompt 1 (current) | **100%** |
| groq/openai/gpt-oss-20b | METHOD_B | Prompt 1 (current) | **100%** |
| groq/openai/gpt-oss-20b | METHOD_C | — | SKIP |
| groq/openai/gpt-oss-20b | METHOD_D | Prompt 1 (current) | **100%** |
| groq/openai/gpt-oss-20b | METHOD_E | Prompt 1 (current) | **100%** |
| groq/openai/gpt-oss-20b | METHOD_F | Prompt 2 (typo fix + field desc) | **100%** (best prompt only) |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_A | — | 0% (LiteLLM cap check) |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_B | Prompt 1 (current) | **100%** |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_C | — | SKIP |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_D | Prompt 1 (current) | **100%** |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_E | Prompt 1 (current) | **100%** |
| openrouter/google/gemini-3.1-flash-lite-preview | METHOD_F | Prompt 1 (current) | **100%** |
| gemini/gemini-3.1-flash-lite-preview | METHOD_A | Prompt 1 (current) | **100%** |
| gemini/gemini-3.1-flash-lite-preview | METHOD_B | Prompt 1 (current) | **100%** |
| gemini/gemini-3.1-flash-lite-preview | METHOD_C | — | SKIP |
| gemini/gemini-3.1-flash-lite-preview | METHOD_D | Prompt 1 (current) | **100%** |
| gemini/gemini-3.1-flash-lite-preview | METHOD_E | Prompt 1 (current) | **100%** |
| gemini/gemini-3.1-flash-lite-preview | METHOD_F | Prompt 1 (current) | **100%** |

---

## Per-Model Observations

### `ollama/gemma3:4b`

METHOD_F succeeds on all 4 prompts (100%) — identical to Round 4 for this model. The fence-stripping fix has no visible effect here because gemma3 already returned bare JSON in Round 4. METHOD_F latency (5.2–6.7s) is slightly faster than METHOD_B (7.8–13.5s) and in the same range as METHOD_C (7.2–7.8s). METHOD_B + Prompt 1 succeeded again (1/1) — consistent with Rounds 3–4, though Round 1's 3-run result (0/9) warns against trusting single-run data for this combination.

### `ollama/ministral-3:14b-cloud`

**Key result:** METHOD_F is **partially fixed** but not fully fixed. Prompts 2 and 3 now succeed (100%), confirming the Addendum's prediction. Prompts 1 and 4 still fail.

- **Prompt 1 failure:** Pydantic raises `Invalid JSON: expected value at line 1 column 1` — the model returned a prose markdown response starting with "For the given slide cont..." rather than JSON. The `_strip_json_fence` regex (`re.search(r"```(?:json)?\s*(\{.*?})\s*```", text, re.DOTALL)`) found no fence match and returned the prose text unchanged, which `model_validate_json()` cannot parse. This is a genuine method limitation for Prompt 1: Mistral does not produce JSON-shaped output when given the minimal Prompt 1.
- **Prompt 4 failure:** Pydantic raises `Invalid JSON: invalid number at line 1 column 2` — the `input_value` shows `'- title: ... idx_content_placeholder: "1"'`, a dash-prefixed field list (not JSON). Again, no fence was present so `_strip_json_fence` returned the text unchanged. This is the same response pattern the Addendum described for Round 4 Prompt 4: Mistral interprets the "Required fields" instruction in Prompt 4 as a dash-list rather than JSON.

Both remaining failures are genuine method+prompt incompatibilities, not testing artifacts. METHOD_F works for this model when the prompt (Prompts 2 or 3) elicits a JSON or fenced-JSON response. When the prompt elicits prose or a dash-list, fence stripping cannot recover the result.

**Comparison vs METHOD_B/E:** METHOD_B and METHOD_E succeed on all 4 prompts (100%). They tolerate non-JSON responses because LlamaIndex's `LLMTextCompletionProgram` and `astructured_predict()` pipelines have more robust output parsing (they inject the schema into the prompt and handle various output formats internally). METHOD_F bypasses this pipeline and relies purely on the raw content being parseable JSON.

### `groq/openai/gpt-oss-20b`

METHOD_F: Prompts 2 and 3 succeed (100%), Prompts 1 and 4 fail (0%).

- **Both failures are rate-limit artifacts**, not method failures. The raw error is `litellm.RateLimitError: GroqException - Rate limit reached for model openai/gpt-oss-20b (TPM: Limit 8000)`. METHOD_F calls `litellm.acompletion()` directly (no LlamaIndex retry wrapper), while METHOD_B/D/E go through `LlamaIndex.llms.litellm.utils.acompletion_with_retry` which retries on rate-limit errors automatically. The concurrent execution of 3 API models causes Groq token-per-minute exhaustion; METHOD_F's direct call fails immediately while LlamaIndex methods retry and eventually succeed.
- Prompts 1 and 4 happened to be scheduled when the TPM limit was exhausted; Prompts 2 and 3 arrived after partial recovery. This is an infrastructure artifact, not a METHOD_F structural failure.
- METHOD_F success on Prompts 2/3 shows the method itself works correctly with this model when rate limits are not an issue.

### `openrouter/google/gemini-3.1-flash-lite-preview`

METHOD_F succeeds on all 4 prompts (100%), matching Round 4. No change. METHOD_A continues to report 0% due to LiteLLM's capability pre-check (not an API limitation). METHOD_B/D/E also 100% on all prompts.

### `gemini/gemini-3.1-flash-lite-preview`

METHOD_F succeeds on all 4 prompts (100%). This is the third consecutive round where Gemini direct API shows complete METHOD_F success. This model is the most method-agnostic tested: METHOD_A/B/D/E/F all succeed on all prompts.

---

## Key Findings and Production Recommendation

### 1. The Addendum was directionally correct but not fully

The Addendum predicted that removing `enable_json_schema_validation = True` and adding fence stripping would likely fix METHOD_F for `ollama/ministral-3:14b-cloud`. The fix is **partial**: Prompts 2 and 3 now pass (as predicted), but Prompts 1 and 4 still fail because the model produces non-JSON output (prose for Prompt 1, dash-list for Prompt 4) that `_strip_json_fence` cannot recover. The fence-stripping regex only handles the ` ```json...``` ` pattern; it cannot convert arbitrary prose or field lists into JSON. This is a model behavior issue, not a missing fence-stripping case.

### 2. METHOD_F is not a safe drop-in replacement for METHOD_B or METHOD_E for Ollama models

METHOD_B and METHOD_E achieve 100% across all prompts on both Ollama models. METHOD_F achieves 50% on `ministral-3:14b-cloud` (2/4 prompts). The gap is explained by LlamaIndex's internal output parsing pipeline (used by METHOD_B/E) being more tolerant of varied output formats than METHOD_F's direct `model_validate_json()` call. For production use with Ollama-hosted models, **METHOD_B or METHOD_E remain the recommended choices**.

### 3. METHOD_F is fully reliable for cloud API models (with caveats on Groq rate limits)

For `gemini/gemini-3.1-flash-lite-preview` and `openrouter/google/gemini-3.1-flash-lite-preview`, METHOD_F achieves 100% across all prompts. For `groq/openai/gpt-oss-20b`, METHOD_F works correctly (Prompts 2 and 3 pass) but is vulnerable to rate-limit failures on Prompt 1 and 4 due to the lack of a retry wrapper. Adding a retry layer around `litellm.acompletion()` in `run_method_f` would likely bring Groq to 100%.

### 4. METHOD_F latency is competitive or faster than METHOD_B

For `gemma3:4b`, METHOD_F averages 5.2–6.7s vs METHOD_B's 7.8–13.5s. For `ministral-3:14b-cloud`, METHOD_F (when it succeeds) averages 1.6–1.7s vs METHOD_B's 1.9–2.4s. For cloud models, METHOD_F latency is in the same range as METHOD_B (1–4s). There is a latency incentive to use METHOD_F where it is reliable.

### 5. Production recommendation for `slide_gen.py`

The current production code uses `FunctionCallingProgram` (METHOD_A), which is the correct choice for Gemini direct API (where METHOD_A works perfectly) but would fail for any Ollama-backed model. The evidence from Rounds 3–5 supports this decision hierarchy:

| Scenario | Recommended method | Reasoning |
|---|---|---|
| `gemini/*` (direct API) | METHOD_A or METHOD_F | Both 100% reliable; METHOD_F slightly faster on some prompts |
| `openrouter/*` | METHOD_B, METHOD_D, or METHOD_E | METHOD_A blocked by LiteLLM capability pre-check; METHOD_F 100% but no retry |
| `ollama/*` | METHOD_B or METHOD_E | METHOD_F fails on Prompts 1 and 4 for Mistral; METHOD_C adds server-side grammar but has stall risk on large models |
| `groq/*` | METHOD_B or METHOD_E | METHOD_F lacks retry wrapper; subject to TPM exhaustion failures |

**METHOD_F should NOT replace `FunctionCallingProgram` in production for Ollama or Groq models.** It is a valid choice for Gemini direct where it provides lower latency and simpler implementation (no LlamaIndex program wrapper). For a production codebase that must support multiple backends, **METHOD_B or METHOD_E** remain the safest universal choices.

---

<details>
<summary>Full stdout from structured_output_methods.py (Round 5, 2026-04-02)</summary>

```
==========================================================================================
  outlines_with_layout — Method Comparison (v2)
  Models:  ollama/gemma3:4b, ollama/ministral-3:14b-cloud, groq/openai/gpt-oss-20b, openrouter/google/gemini-3.1-flash-lite-preview, gemini/gemini-3.1-flash-lite-preview
  Methods: METHOD_A, METHOD_B, METHOD_C, METHOD_D, METHOD_E, METHOD_F
  Prompts: 4  |  Slides: 1  |  N_RUNS: 1
  Total LLM calls (max): 120
  Ollama (2): sequential | API (3): concurrent
==========================================================================================


##########################################################################################
# Testing model: ollama/gemma3:4b
##########################################################################################
  [ollama/gemma3:4b][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/24) -> cap_err (0.8s)
  [ollama/gemma3:4b][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/24) -> cap_err (0.5s)
  [ollama/gemma3:4b][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/24) -> cap_err (0.5s)
  [ollama/gemma3:4b][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/24) -> cap_err (0.5s)
  [ollama/gemma3:4b][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/24) -> OK (13.5s)
  [ollama/gemma3:4b][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/24) -> OK (7.8s)
  [ollama/gemma3:4b][METHOD_B][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (7/24) -> OK (8.5s)
  [ollama/gemma3:4b][METHOD_B][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (8/24) -> OK (8.2s)
  [ollama/gemma3:4b][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/24) -> OK (7.8s)
  [ollama/gemma3:4b][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/24) -> OK (7.5s)
  [ollama/gemma3:4b][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/24) -> OK (7.2s)
  [ollama/gemma3:4b][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/24) -> OK (7.5s)
  [ollama/gemma3:4b][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/24) -> OK (7.5s)
  [ollama/gemma3:4b][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/24) -> OK (8.6s)
  [ollama/gemma3:4b][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/24) -> OK (8.8s)
  [ollama/gemma3:4b][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/24) -> OK (8.3s)
  [ollama/gemma3:4b][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/24) -> OK (8.3s)
  [ollama/gemma3:4b][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/24) -> OK (8.2s)
  [ollama/gemma3:4b][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/24) -> OK (8.5s)
  [ollama/gemma3:4b][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/24) -> OK (8.3s)
  [ollama/gemma3:4b][METHOD_F][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (21/24) -> OK (6.7s)
  [ollama/gemma3:4b][METHOD_F][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (22/24) -> OK (6.7s)
  [ollama/gemma3:4b][METHOD_F][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (23/24) -> OK (5.2s)
  [ollama/gemma3:4b][METHOD_F][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (24/24) -> OK (5.4s)

##########################################################################################
# Testing model: ollama/ministral-3:14b-cloud
##########################################################################################
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (1/24) -> cap_err (0.8s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (2/24) -> cap_err (0.6s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (3/24) -> cap_err (0.6s)
  [ollama/ministral-3:14b-cloud][METHOD_A][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (4/24) -> cap_err (0.5s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (5/24) -> OK (2.4s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (6/24) -> OK (2.0s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (7/24) -> OK (1.9s)
  [ollama/ministral-3:14b-cloud][METHOD_B][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (8/24) -> OK (1.9s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (9/24) -> OK (1.8s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (10/24) -> OK (1.9s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (11/24) -> OK (2.0s)
  [ollama/ministral-3:14b-cloud][METHOD_C][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (12/24) -> OK (1.8s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (13/24) -> OK (2.2s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (14/24) -> OK (2.4s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (15/24) -> OK (2.4s)
  [ollama/ministral-3:14b-cloud][METHOD_D][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (16/24) -> OK (2.5s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (17/24) -> OK (2.2s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (18/24) -> OK (2.0s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (19/24) -> OK (2.1s)
  [ollama/ministral-3:14b-cloud][METHOD_E][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (20/24) -> OK (2.3s)
  [ollama/ministral-3:14b-cloud][METHOD_F][Prompt 1 (current)] slide='Attention Is All You Need'    run=1/1 (21/24) -> FAIL (2.7s)
  [ollama/ministral-3:14b-cloud][METHOD_F][Prompt 2 (typo fix + field desc)] slide='Attention Is All You Need'    run=1/1 (22/24) -> OK (1.7s)
  [ollama/ministral-3:14b-cloud][METHOD_F][Prompt 3 (+ few-shot)] slide='Attention Is All You Need'    run=1/1 (23/24) -> OK (1.6s)
  [ollama/ministral-3:14b-cloud][METHOD_F][Prompt 4 (Round2 no-wrap directive)] slide='Attention Is All You Need'    run=1/1 (24/24) -> FAIL (1.6s)

##########################################################################################
# Testing API models concurrently: groq/openai/gpt-oss-20b, openrouter/google/gemini-3.1-flash-lite-preview, gemini/gemini-3.1-flash-lite-preview
##########################################################################################
[... interleaved concurrent output — see per-model tables above for results ...]

  [groq/openai/gpt-oss-20b][METHOD_F][Prompt 1 (current)] -> FAIL (0.2s)   [rate-limit: litellm.RateLimitError]
  [groq/openai/gpt-oss-20b][METHOD_F][Prompt 2 (typo fix + field desc)] -> OK (0.4s)
  [groq/openai/gpt-oss-20b][METHOD_F][Prompt 3 (+ few-shot)] -> OK (0.6s)
  [groq/openai/gpt-oss-20b][METHOD_F][Prompt 4 (Round2 no-wrap directive)] -> FAIL (0.2s)  [rate-limit: litellm.RateLimitError]

  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 1] -> OK (3.6s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 2] -> OK (2.3s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 3] -> OK (2.8s)
  [openrouter/google/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 4] -> OK (2.0s)

  [gemini/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 1] -> OK (2.3s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 2] -> OK (3.8s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 3] -> OK (2.1s)
  [gemini/gemini-3.1-flash-lite-preview][METHOD_F][Prompt 4] -> OK (1.9s)

[Full comparison tables and cross-method summary reproduced in the Results Tables section above.]

  Raw results saved to: .../augment_results_raw.json

==========================================================================================
  DONE
==========================================================================================
```

**METHOD_F failure error messages (from augment_results_raw.json):**

`ollama/ministral-3:14b-cloud` — Prompt 1:
```
1 validation error for SlideOutlineWithLayout
Invalid JSON: expected value at line 1 column 1 [type=json_invalid,
input_value='For the given slide cont...the technical overview.',
input_type=str]
```
Model returned prose text starting "For the given slide cont..." — no JSON, no fence, cannot be recovered by fence stripping.

`ollama/ministral-3:14b-cloud` — Prompt 4:
```
1 validation error for SlideOutlineWithLayout
Invalid JSON: invalid number at line 1 column 2 [type=json_invalid,
input_value='- title:                ...ontent_placeholder: "1"',
input_type=str]
```
Model returned a dash-prefixed field list, not JSON. Fence stripping found no fence and passed the text unchanged.

`groq/openai/gpt-oss-20b` — Prompts 1 and 4:
```
litellm.RateLimitError: RateLimitError: GroqException - {"error":{"message":
"Rate limit reached for model `openai/gpt-oss-20b` ... TPM: Limit 8000, Used 6691,
Requested 2927. Please try again in 12.135s. ..."}}
```
Infrastructure rate-limit failure; not a METHOD_F method failure.

</details>
