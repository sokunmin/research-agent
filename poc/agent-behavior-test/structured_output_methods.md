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
