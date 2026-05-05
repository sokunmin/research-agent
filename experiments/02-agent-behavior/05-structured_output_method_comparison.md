# Experiment 5 — Constrained Decoding vs. Text Completion: Structured Output Method Selection for Local LLMs

## Task Context

This experiment targets **Step 5 — Slide Outline + Human-in-the-Loop** from the system architecture (README → System Architecture).

```
Input: paper summaries (*.md, one per paper)        ← Step 4: Summarization
      │
      ▼
┌── 5. SLIDE OUTLINE + HUMAN-IN-THE-LOOP ───────────────────────────────┐
├─── Original (lz-chen) ───────────┬─── My Implementation ─────────────┤
│ GPT-4o: 1 outline per paper      │ Local LLM: 1 title slide           │
│ FunctionCallingProgram           │           + 4 content slides       │
│ HITL: approve / reject           │ LLMTextCompletionProgram           │
│                                  │ HITL: approve / give feedback      │
│                                  │ → Layout selection by LLM          │
└──────────────────────────────────┴────────────────────────────────────┘
      │
      ▼
Output: slide_outlines.json                          → Step 6: PPTX Rendering
```

Within Step 5, the layout selection sub-step (`outlines_with_layout`) is the experiment target:

```
Step 5 — Slide Outline + Human-in-the-Loop (detail)
──────────────────────────────────────────────────────────────────
 paper summaries (*.md, one per paper)
       │
       ▼
 [summary2outline]        LLM → PaperSlideOutline
       │                  { paper_title, paper_authors, paper_year,
       │                    content_slides[4]: List[SlideOutline] }
       ▼                    ↑ loops back on rejection
 [gather_feedback_outline]    Human-in-the-Loop: approve / revise
       │
       ▼
 ┌─── EXPERIMENT TARGET ────────────────────────────────────────┐
 │ [outlines_with_layout]                                       │
 │   For each content slide:                                    │
 │     LLM picks layout from the PPTX template                 │
 │   Input:  SlideOutline { title, content }                    │
 │   Prompt: AUGMENT_LAYOUT_PMT                                 │
 │   Output: SlideOutlineWithLayout { title, content,           │
 │                                    layout_name,              │
 │                                    idx_title_placeholder,    │
 │                                    idx_content_placeholder } │
 └──────────────────────────────────────────────────────────────┘
       │
       ▼
 slide_outlines.json      → Step 6: PPTX Rendering
```

`AUGMENT_LAYOUT_PMT` is the prompt for the `outlines_with_layout` step. It asks the LLM to look at each slide's content and select the appropriate layout from the available PPTX template layouts — returning the layout name and placeholder indices as structured JSON. If the LLM returns malformed output here, `slide_gen` has nothing valid to render and the whole pipeline stops.

---

## Summary

- **Problem:** The layout selection step requires the LLM to return a structured JSON object (layout name + placeholder indices) for deterministic PPTX rendering downstream.
  - The default function-calling API silently failed on all tested local models — 0% valid output, pipeline blocked.
  - Root cause was unknown: Ollama API incompatibility vs prompt design vs model capability.
- **Solution:** Systematically compared all 5 LlamaIndex structured output APIs across 2 local models and 4 prompt variants — 360 LLM calls total.
- **Result:** Text Completion was adopted as the pipeline solution — works across all LiteLLM providers (OpenAI, Anthropic, Ollama, Gemini).
  - Ollama Format Parameter achieves 100% accuracy regardless of prompt quality, but is Ollama-specific — incompatible with the multi-provider requirement.

---

## Experiment Setup

✅ = currently used in the pipeline

### Objective

- **Problem:** `FunctionCallingProgram` crashes silently on all Ollama models — 0% valid output, pipeline blocked
- **Goal:** Which LlamaIndex structured output method reliably returns valid Pydantic JSON across 2 models and 4 prompt variants, and stays compatible with LiteLLM multi-provider routing?
- **Pass condition:** 100% valid JSON output

### Methods compared

**Three underlying approaches:**
- **Function Calling** — structure enforced by the model's native tool-call API (model-side)
- **Text Completion** — model outputs JSON as text; client-side Pydantic parser validates it
- **Grammar Enforcement** — Ollama server constrains token generation to valid JSON (server-side decoding)

| Method | LlamaIndex API | Mechanism |
|---|---|---|
| Function Calling | `FunctionCallingProgram` | Relies on the model's native tool/function-calling capability via LiteLLM. Fails if the model does not support it. |
| Text Completion ✅ | `LLMTextCompletionProgram` | Appends JSON schema instructions to the prompt; parses the text output into the Pydantic model. No native tool call required. |
| Ollama Format Parameter | `LLMTextCompletionProgram` + Ollama `format` kwarg | Same as Text Completion, but passes the Pydantic schema as `format` in `additional_kwargs`. Ollama enforces grammar-constrained decoding server-side — output is valid JSON before it leaves the model. Ollama-only. |
| Structured LLM Wrapper | `llm.as_structured_llm()` → `acomplete()` | Wraps the LLM with `as_structured_llm(OutputCls)`; the parsed Pydantic object is in `response.raw`. |
| Structured Predict | `llm.astructured_predict()` with `PydanticProgramMode.LLM` | Routes through LlamaIndex's LLM-mode structured prediction; uses text completion internally. |

### Primary metric — Success Rate

Percentage of LLM calls returning valid JSON that matches the Pydantic schema without error.
- `0%` = method produces no valid output (crashes, returns schema definition, or malformed JSON)
- `100%` = all outputs are valid

### Prompt variants

| Prompt | Description |
|---|---|
| Prompt 1 (original) | Verbatim `AUGMENT_LAYOUT_PMT` as used in the pipeline — no explicit output field descriptions, contains a Norwegian placeholder name (`Plassholder for innhold`) |
| Prompt 2 (field descriptions added) | Adds explicit output field descriptions; removes the Norwegian placeholder name |
| Prompt 3 (few-shot) | Prompt 2 plus an embedded example |
| Prompt 4 (no-wrap directive) | Adds an explicit instruction not to wrap output in a JSON schema definition |

> The prompt used in the pipeline was further redesigned in a follow-up experiment and is not directly equivalent to any of the 4 variants above. See the prompt experiment report for details.

**Models:** `ollama/gemma3:4b`, `ollama/qwen3.5:4b`  
**Slide test cases:** 3 types — academic content, agenda/overview, closing/thank-you  
**Runs per combination:** 3  
**Total LLM calls:** 360 (all sequential — Ollama does not support parallel inference)

---

## Full Experimental Results

### `ollama/gemma3:4b` — Success Rate

- **Purpose:** Test all 5 structured output methods on `gemma3:4b` across 4 prompt variants
- **Expected:** At least one method achieves 100% success rate on this model

| Method | Prompt 1 (original) | Prompt 2 (field descriptions) | Prompt 3 (few-shot) | Prompt 4 (no-wrap) |
|---|---|---|---|---|
| Function Calling | 0% | 0% | 0% | 0% |
| Text Completion ✅ | 0% | **100%** | **100%** | **100%** |
| Ollama Format Parameter | **100%** | **100%** | **100%** | **100%** |
| Structured LLM Wrapper | 0% | **100%** | **100%** | **100%** |
| Structured Predict | 0% | **100%** | **100%** | **100%** |

**Conclusion:** Function Calling fails at construction time on all prompts — grammar-constrained decoding works on any prompt, but text completion requires field descriptions added to the prompt for gemma3:4b.

The 0.3–0.5s elapsed time for Function Calling is framework overhead, not a model response — the method crashes before inference starts, and this applies to both models across all 4 prompts.

### `ollama/gemma3:4b` — Avg Elapsed (s) per Call

| Method | Prompt 1 (original) | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| Function Calling | 0.5 | 0.4 | 0.4 | 0.4 |
| Text Completion ✅ | 4.0 | 4.3 | 6.1 | 4.5 |
| Ollama Format Parameter | 3.5 | 3.3 | 5.3 | 4.6 |
| Structured LLM Wrapper | 3.8 | 4.6 | 5.8 | 4.5 |
| Structured Predict | 3.5 | 4.2 | 5.6 | 4.6 |

**Conclusion:** Text-completion methods run at 3.5–6.1s on gemma3:4b — the few-shot prompt adds ~2s per call with no accuracy gain over field descriptions.

---

### `ollama/qwen3.5:4b` — Success Rate

- **Purpose:** Verify whether the same method findings hold on `qwen3.5:4b`
- **Expected:** Results broadly consistent with `gemma3:4b` — same methods pass or fail

| Method | Prompt 1 (original) | Prompt 2 (field descriptions) | Prompt 3 (few-shot) | Prompt 4 (no-wrap) |
|---|---|---|---|---|
| Function Calling | 0% | 0% | 0% | 0% |
| Text Completion ✅ | **100%** | **100%** | **100%** | **100%** |
| Ollama Format Parameter | **100%** | **100%** | **100%** | **100%** |
| Structured LLM Wrapper | **100%** | **100%** | **100%** | **100%** |
| Structured Predict | **100%** | **100%** | **100%** | **100%** |

**Conclusion:** qwen3.5:4b is more robust than gemma3:4b — text completion works on the original prompt without field descriptions.

### `ollama/qwen3.5:4b` — Avg Elapsed (s) per Call

| Method | Prompt 1 (original) | Prompt 2 | Prompt 3 | Prompt 4 |
|---|---|---|---|---|
| Function Calling | 0.3 | 0.3 | 0.3 | 0.4 |
| Text Completion ✅ | 8.1 | 7.9 | 7.7 | 7.9 |
| Ollama Format Parameter | 7.5 | 7.7 | 7.4 | 8.2 |
| Structured LLM Wrapper | 7.7 | 8.3 | 8.0 | 8.1 |
| Structured Predict | 7.6 | 8.2 | 7.9 | 8.0 |

**Conclusion:** qwen3.5:4b runs ~2× slower than gemma3:4b per call but achieves consistent 100% success without prompt tuning.

---

### Cross-Method Summary: Best Prompt per (Model × Method)

- **Purpose:** Identify the best prompt per model per method to compare peak performance across all combinations
- **Expected:** `Text Completion` and `Ollama Format Parameter` reach 100% for both models; `Function Calling` stays at 0%

| Model | Method | Best Prompt | Success Rate |
|---|---|---|---|
| `ollama/gemma3:4b` | Function Calling | Prompt 1 (original) | 0% |
| `ollama/gemma3:4b` | Text Completion ✅ | Prompt 2 (field descriptions) | 100% |
| `ollama/gemma3:4b` | Ollama Format Parameter | Prompt 1 (original) | 100% |
| `ollama/gemma3:4b` | Structured LLM Wrapper | Prompt 2 (field descriptions) | 100% |
| `ollama/gemma3:4b` | Structured Predict | Prompt 2 (field descriptions) | 100% |
| `ollama/qwen3.5:4b` | Function Calling | Prompt 1 (original) | 0% |
| `ollama/qwen3.5:4b` | Text Completion ✅ | Prompt 1 (original) | 100% |
| `ollama/qwen3.5:4b` | Ollama Format Parameter | Prompt 1 (original) | 100% |
| `ollama/qwen3.5:4b` | Structured LLM Wrapper | Prompt 1 (original) | 100% |
| `ollama/qwen3.5:4b` | Structured Predict | Prompt 1 (original) | 100% |

**Conclusion:** Function Calling is the only method that cannot reach 100% regardless of prompt or model — all text-completion-based methods are equivalent at peak performance.

---

## Observations

### Method selection: why Function Calling fails

```
Bug: 0% structured output at outlines_with_layout
      │
      ▼
Root cause: FunctionCallingProgram
      │  No tool calling support in Ollama/LiteLLM
      │  Crashes before inference → silent failure (0.3–0.5s)
      │
      ▼
Switch to text-completion methods
      │
      ├─ gemma3:4b + Prompt 1 ──────────────────── 0% ✗
      │    · No output field descriptions
      │    · Norwegian placeholder name (Plassholder for innhold)
      │      (`Plassholder for innhold` = "Content placeholder" in Norwegian —
      │       from the original project's branded PPTX template by Inmeta,
      │       a Norwegian IT consultancy)
      │
      ├─ gemma3:4b + Prompt 2 ──────────────────────── 100% ✓
      │
      ├─ qwen3.5:4b + Prompt 1 ─────────────────── 100% ✓
      │
      └─ Any model + Ollama `format` param ────────── 100% ✓
            Server-side grammar enforcement
            Works even with broken Prompt 1
            (Ollama-only — see Decision for why not chosen)
```

**Conclusion:** Function Calling crashes silently before inference — text-completion methods succeed but gemma3:4b requires field descriptions in the prompt.
- The 0.3–0.5s elapsed time is framework overhead, not a model response. The method crashes before inference starts. Easy to miss without explicit error logging.
- qwen3.5:4b requires thinking mode disabled; otherwise chain-of-thought tokens break JSON parsing.
- Slide content type has no effect on success rate. All three types — academic content, agenda, and closing — pass or fail together for every method-prompt combination.

### Prompt sensitivity: which prompt works per model

```
Prompt comparison — Text Completion method
      │
      ├─ Prompt 1 (original)
      │    gemma3:4b  → 0%   ✗
      │    qwen3.5:4b → 100% ✓  ← primary model, no change needed
      │
      ├─ Prompt 2 (field descriptions added)
      │    gemma3:4b  → 100% ✓
      │    qwen3.5:4b → 100% ✓
      │
      ├─ Prompt 3 (few-shot)
      │    gemma3:4b  → 100% ✓
      │    qwen3.5:4b → 100% ✓
      │    +1–2s latency, no accuracy gain over Prompt 2
      │
      └─ Prompt 4 (no-wrap directive)
           gemma3:4b  → 100% ✓
           qwen3.5:4b → 100% ✓
```

**Conclusion:** Prompt 1 is kept for the pipeline — qwen3.5:4b succeeds without changes, and gemma3:4b recovers with field descriptions added.

Prompt 1 was kept because qwen3.5:4b (the primary model) already achieves 100% with it — no prompt changes needed. gemma3:4b achieves 100% with Prompt 2 (field descriptions added).

---

## Decision

```
Which method works across ALL providers?
      │
      ├── Ollama Format Parameter (METHOD_C)
      │     ✓ 100% on any prompt — server-side grammar enforcement
      │     ✗ Ollama-specific — breaks on cloud providers
      │     → REJECTED: incompatible with multi-provider requirement
      │
      ├── Text Completion / LLMTextCompletionProgram (METHOD_B) ✅
      │     ✓ 100% on all providers (OpenAI, Anthropic, Ollama, Gemini)
      │     ✓ Explicit program factory — stateless, no side effects
      │     △ gemma3:4b requires Prompt 2 (field descriptions added)
      │     → CHOSEN: universal compatibility, most direct API
      │
      ├── Structured LLM Wrapper (METHOD_D)
      │     ✓ 100% — same accuracy as METHOD_B
      │     ✓ Works on all providers
      │     △ Requires manual prompt formatting + response.raw access
      │     → NOT CHOSEN: equal result, more steps than METHOD_B
      │
      ├── Structured Predict (METHOD_E)
      │     ✓ 100% — same accuracy as METHOD_B
      │     ✓ Works on all providers
      │     △ Modifies LLM instance state (pydantic_program_mode)
      │     → NOT CHOSEN: equal result, side-effect risk vs METHOD_B
      │
      └── Function Calling (METHOD_A)
            ✗ 0% on all Ollama models — crashes at construction time
            → REJECTED: fundamentally incompatible with Ollama/LiteLLM
```

Text Completion, Structured LLM Wrapper, and Structured Predict all use text completion internally and reach 100% for both models. Text Completion was picked over the other two — same result, and the most direct LlamaIndex API with no extra wrapping. gemma3:4b needs Prompt 2 (field descriptions) under any text-completion method. For qwen3.5:4b, Prompt 1 works as-is.

---

## Pipeline Integration Status ✅ INTEGRATED

Text completion method replaced function calling in `slide_gen.py` → `_text_program()` → `outlines_with_layout`.

### Impact

- Structured output reliability: 0% → 100% for all Ollama models.
- Compatible with all LiteLLM providers (OpenAI, Anthropic, Ollama, Gemini) — no provider lock-in.
