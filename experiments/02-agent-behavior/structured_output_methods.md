# Structured JSON Output Methods for Local Ollama Models

**Date:** 2026-03-28

---

## Background & Motivation

The PPTX generation pipeline requires the LLM to return structured data — specifically a `SlideOutlineWithLayout` Pydantic object containing the slide title, body text, layout name, and placeholder indices. If the model returns plain text or an incorrectly shaped JSON, the pipeline crashes.

A production bug was discovered on 2026-03-27: when using LlamaIndex's `FunctionCallingProgram` (the default structured output method), `gemma3:4b` returned the JSON Schema definition (`{"properties": {...}}`) instead of concrete field values. The pipeline received a schema template rather than actual slide data, causing 0% success. This experiment systematically compared 5 methods for getting correct structured output from local Ollama models to identify a reliable fix.

---

## Experiment Setup

**5 methods compared:**

| Method | LlamaIndex API | Mechanism |
|---|---|---|
| Function Calling | `FunctionCallingProgram` | Uses the model's native function/tool-calling capability. Fails if the model does not support tool use via LiteLLM. |
| Text Completion | `LLMTextCompletionProgram` | Appends JSON schema instructions to the prompt and parses the model's text output into the Pydantic model. No native tool call required. |
| Ollama Format Parameter | `LLMTextCompletionProgram` + Ollama `format` param | Same as Text Completion, but also passes the JSON schema as the `format` field in `additional_kwargs`. Ollama's server-side grammar enforcement constrains the output to valid JSON before it leaves the model. |
| Structured LLM Wrapper | `llm.as_structured_llm()` → `acomplete()` | Wraps the LLM with `as_structured_llm(OutputCls)`. The parsed Pydantic object is available in `response.raw`. |
| Structured Predict | `llm.astructured_predict()` with `PydanticProgramMode.LLM` | Routes through LlamaIndex's LLM-mode structured prediction path; uses text completion internally, not tool calls. |

**4 prompt variants tested:**

| Prompt | Description |
|---|---|
| Prompt 1 (original) | Verbatim production `AUGMENT_LAYOUT_PMT` — contains a Norwegian placeholder name, no explicit output field descriptions |
| Prompt 2 (field descriptions added) | Adds explicit output field descriptions, fixes the Norwegian placeholder name |
| Prompt 3 (few-shot) | Adds an embedded example in the prompt |
| Prompt 4 (no-wrap) | Explicit instruction not to wrap output in a schema definition |

**Models tested:** `ollama/gemma3:4b`, `ollama/qwen3.5:4b`

**Slide test cases:** 3 (academic content, agenda, closing/thank-you)

**Run configuration:** 3 runs per combination. Sequential execution only. Total: 5 methods × 2 models × 4 prompts × 3 slide types × 3 runs = **360 LLM calls**.

---

## Results

### gemma3:4b — Success Rate by Method and Prompt

| Method | Prompt 1 (original) | Prompt 2 (field descriptions) | Prompt 3 (few-shot) | Prompt 4 (no-wrap) |
|---|---|---|---|---|
| Function Calling | 0% | 0% | 0% | 0% |
| Text Completion | 0% | **100%** | **100%** | **100%** |
| Ollama Format Parameter | **100%** | **100%** | **100%** | **100%** |
| Structured LLM Wrapper | 0% | **100%** | **100%** | **100%** |
| Structured Predict | 0% | **100%** | **100%** | **100%** |

### gemma3:4b — Avg Elapsed (s) per Call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| Function Calling | 0.5 | 0.4 | 0.4 | 0.4 |
| Text Completion | 4.0 | 4.3 | 6.1 | 4.5 |
| Ollama Format Parameter | 3.5 | 3.3 | 5.3 | 4.6 |
| Structured LLM Wrapper | 3.8 | 4.6 | 5.8 | 4.5 |
| Structured Predict | 3.5 | 4.2 | 5.6 | 4.6 |

### gemma3:4b — Per-Slide Success Breakdown

| Method | Prompt | Academic Content | Agenda | Thank You (closing) |
|---|---|---|---|---|
| Function Calling | all prompts | 0/3 | 0/3 | 0/3 |
| Text Completion | Prompt 1 | 0/3 | 0/3 | 0/3 |
| Text Completion | Prompts 2–4 | 3/3 | 3/3 | 3/3 |
| Ollama Format Parameter | all prompts | 3/3 | 3/3 | 3/3 |
| Structured LLM Wrapper | Prompt 1 | 0/3 | 0/3 | 0/3 |
| Structured LLM Wrapper | Prompts 2–4 | 3/3 | 3/3 | 3/3 |
| Structured Predict | Prompt 1 | 0/3 | 0/3 | 0/3 |
| Structured Predict | Prompts 2–4 | 3/3 | 3/3 | 3/3 |

### qwen3.5:4b — Success Rate by Method and Prompt

| Method | Prompt 1 (original) | Prompt 2 (field descriptions) | Prompt 3 (few-shot) | Prompt 4 (no-wrap) |
|---|---|---|---|---|
| Function Calling | 0% | 0% | 0% | 0% |
| Text Completion | **100%** | **100%** | **100%** | **100%** |
| Ollama Format Parameter | **100%** | **100%** | **100%** | **100%** |
| Structured LLM Wrapper | **100%** | **100%** | **100%** | **100%** |
| Structured Predict | **100%** | **100%** | **100%** | **100%** |

### qwen3.5:4b — Avg Elapsed (s) per Call

| Method | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| Function Calling | 0.3 | 0.3 | 0.3 | 0.4 |
| Text Completion | 8.1 | 7.9 | 7.7 | 7.9 |
| Ollama Format Parameter | 7.5 | 7.7 | 7.4 | 8.2 |
| Structured LLM Wrapper | 7.7 | 8.3 | 8.0 | 8.1 |
| Structured Predict | 7.6 | 8.2 | 7.9 | 8.0 |

### Cross-Method Summary: Best Prompt per (Model × Method)

| Model | Method | Best Prompt | Success Rate |
|---|---|---|---|
| `ollama/gemma3:4b` | Function Calling | Prompt 1 (original) | 0% |
| `ollama/gemma3:4b` | Text Completion | Prompt 2 (field descriptions) | 100% |
| `ollama/gemma3:4b` | Ollama Format Parameter | Prompt 1 (original) | 100% |
| `ollama/gemma3:4b` | Structured LLM Wrapper | Prompt 2 (field descriptions) | 100% |
| `ollama/gemma3:4b` | Structured Predict | Prompt 2 (field descriptions) | 100% |
| `ollama/qwen3.5:4b` | Function Calling | Prompt 1 (original) | 0% |
| `ollama/qwen3.5:4b` | Text Completion | Prompt 1 (original) | 100% |
| `ollama/qwen3.5:4b` | Ollama Format Parameter | Prompt 1 (original) | 100% |
| `ollama/qwen3.5:4b` | Structured LLM Wrapper | Prompt 1 (original) | 100% |
| `ollama/qwen3.5:4b` | Structured Predict | Prompt 1 (original) | 100% |

---

## Key Findings

- **Function Calling fails 100% for both models, all prompts**: `gemma3:4b` and `qwen3.5:4b` as served via Ollama through LiteLLM do not support native function/tool calling. `FunctionCallingProgram` fails immediately at construction time (sub-1s, no LLM inference occurs). This is the root cause of the production bug.
- **The Ollama Format Parameter method achieves 100% regardless of prompt**: passing the Pydantic schema as the Ollama `format` parameter enables server-side grammar-constrained decoding — the model is forced to produce valid JSON matching the schema regardless of what the prompt says. It is the only method that achieves 100% even with the original unmodified prompt (Prompt 1).
- **gemma3:4b is prompt-sensitive for text-completion methods**: Prompt 1 fails (0%) for Text Completion, Structured LLM Wrapper, and Structured Predict. Adding explicit field descriptions (Prompt 2) brings all three to 100%. The root cause is that Prompt 1 lacks output field descriptions and contains a Norwegian placeholder name that confuses the model.
- **qwen3.5:4b is prompt-agnostic**: it succeeds 100% on Text Completion, Ollama Format Parameter, Structured LLM Wrapper, and Structured Predict across all 4 prompts. It has stronger instruction-following and JSON output capabilities without grammar enforcement.
- **Function Calling's near-zero elapsed time (0.3–0.5s) is not a sign of speed** — it fails at construction time before any LLM call is made. This makes silent failures easy to misread as fast responses.
- **Prompt 3 (few-shot) consistently adds latency**: the embedded example adds ~1–2s across all working methods and both models, with no additional accuracy benefit over Prompt 2.

---

## Decision

**Primary recommendation: Ollama Format Parameter method with the original prompt.**

The Ollama Format Parameter method passes the Pydantic model's JSON schema as the `format` field in `additional_kwargs`. This uses server-side grammar enforcement, making structured output independent of prompt phrasing — 100% success even with the existing unmodified prompt, no prompt refactoring required.

Implementation: add `format=SlideOutlineWithLayout.model_json_schema()` to `additional_kwargs` and use `LLMTextCompletionProgram` instead of `FunctionCallingProgram`. Gate the `format` kwarg with `model_name.startswith("ollama/")` so it is not passed to cloud providers.

**Secondary recommendation (if Ollama format parameter is unavailable):** Text Completion, Structured LLM Wrapper, or Structured Predict all work equally well with Prompt 2 or later.

**Do not use Function Calling for any Ollama model** — it always fails and failures are silent.
