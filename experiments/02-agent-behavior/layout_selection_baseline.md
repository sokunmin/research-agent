# Slide Layout Selection Baseline — LLM Comprehension Test

**Date:** 2026-03-29

---

## Background & Motivation

When the research agent converts an academic paper outline into a PowerPoint, it must assign a layout to each slide — for example, a cover slide should use `TITLE_SLIDE`, a chapter divider should use `SECTION_HEADER_CENTER`, and a quote should use `QUOTE`. The template contains 12 distinct layouts. If a model always defaults to `TITLE_AND_BODY` (the generic content layout) for every slide, the resulting deck looks visually uniform: every slide becomes a plain title-plus-body content slide, missing proper cover slides, section breaks, quote cards, and closing slides.

This experiment measured whether three LLMs can correctly select the right layout given only the slide's title and body text. The results form the baseline that the follow-on prompt engineering experiment (`layout_selection_prompt_eng.md`) was designed to improve.

---

## Experiment Setup

**Method:** LlamaIndex `LLMTextCompletionProgram` — sends the prompt as text and parses the model's response into a `SlideOutlineWithLayout` Pydantic object. Does not use native function/tool calling, so it works for models that do not support the tool-calls API.

**Template:** 12 layouts read dynamically from `assets/template-en.pptx` (including `TITLE_SLIDE`, `TITLE_AND_BODY`, `QUOTE`, `SECTION_HEADER_CENTER`, `SECTION_HEADER_TOP`, `Bullet Points`, and 6 photo/visual layouts).

**Models tested:**

| Model | Parameters | Provider |
|-------|-----------|---------|
| `gemma3:4b` | 4B | Local Ollama (M1) |
| `ministral-3:14b-cloud` | 14B | Ollama → Mistral cloud |
| `gpt-oss:20b-cloud` | 20B | Ollama → OpenAI cloud |

**Slide types tested (6 total):**

| Slide Type | Expected Layout(s) |
|---|---|
| Cover / title slide | `TITLE_SLIDE` |
| Academic content (4 bullet points) | `TITLE_AND_BODY` or `Bullet Points` |
| Section header (empty body) | `SECTION_HEADER_CENTER` or `SECTION_HEADER_TOP` |
| Bullet list | `Bullet Points` or `TITLE_AND_BODY` |
| Closing / thank-you slide | `TITLE_SLIDE` or `SECTION_HEADER_CENTER` |
| Quote with attribution | `QUOTE` |

**Run configuration:** 3 runs per (model × slide type) at temperature 0.1, max_tokens 2048. Sequential execution only (Ollama does not support parallel inference). Total: 3 models × 6 slide types × 3 runs = **54 inferences**.

---

## Results

### gemma3:4b (local, 4B parameters)

| Slide Type | Expected Layout(s) | Run 1 | Run 2 | Run 3 | Appropriate Rate | Avg Elapsed |
|---|---|---|---|---|---|---|
| Cover / title slide | `TITLE_SLIDE` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 9.7s |
| Academic content | `TITLE_AND_BODY` / `Bullet Points` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 9.0s |
| Section header | `SECTION_HEADER_CENTER` / `SECTION_HEADER_TOP` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 7.9s |
| Bullet list | `TITLE_AND_BODY` / `Bullet Points` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 9.1s |
| Closing slide | `TITLE_SLIDE` / `SECTION_HEADER_CENTER` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 8.2s |
| Quote slide | `QUOTE` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 8.7s |

**Overall parse success rate:** 18/18 (100%)
**Overall appropriate rate:** 6/18 (33.3%)
**Avg elapsed per call:** 8.8s

### ministral-3:14b-cloud (cloud, 14B parameters)

| Slide Type | Expected Layout(s) | Run 1 | Run 2 | Run 3 | Appropriate Rate | Avg Elapsed |
|---|---|---|---|---|---|---|
| Cover / title slide | `TITLE_SLIDE` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 3.3s |
| Academic content | `TITLE_AND_BODY` / `Bullet Points` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 3.1s |
| Section header | `SECTION_HEADER_CENTER` / `SECTION_HEADER_TOP` | `SECTION_HEADER_TOP` | `SECTION_HEADER_TOP` | `SECTION_HEADER_TOP` | 3/3 | 2.5s |
| Bullet list | `TITLE_AND_BODY` / `Bullet Points` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 2.8s |
| Closing slide | `TITLE_SLIDE` / `SECTION_HEADER_CENTER` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 2.7s |
| Quote slide | `QUOTE` | `QUOTE` | `QUOTE` | `QUOTE` | 3/3 | 2.7s |

**Overall parse success rate:** 18/18 (100%)
**Overall appropriate rate:** 12/18 (66.7%)
**Avg elapsed per call:** 2.8s

### gpt-oss:20b-cloud (cloud, 20B parameters, think mode always on)

| Slide Type | Expected Layout(s) | Run 1 | Run 2 | Run 3 | Appropriate Rate | Avg Elapsed |
|---|---|---|---|---|---|---|
| Cover / title slide | `TITLE_SLIDE` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 2.1s |
| Academic content | `TITLE_AND_BODY` / `Bullet Points` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 2.5s |
| Section header | `SECTION_HEADER_CENTER` / `SECTION_HEADER_TOP` | `TITLE_AND_BODY` | `SECTION_HEADER_TOP` | `SECTION_HEADER_TOP` | 2/3 | 3.2s |
| Bullet list | `TITLE_AND_BODY` / `Bullet Points` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 2.0s |
| Closing slide | `TITLE_SLIDE` / `SECTION_HEADER_CENTER` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 3.1s |
| Quote slide | `QUOTE` | `TITLE_AND_BODY` | `QUOTE` | `QUOTE` | 2/3 | 2.3s |

**Overall parse success rate:** 18/18 (100%)
**Overall appropriate rate:** 10/18 (55.6%)
**Avg elapsed per call:** 2.5s

### Cross-Model Summary

| Model | Parameters | Provider | Parse Success | Appropriate Rate | Avg Elapsed |
|---|---|---|---|---|---|
| `gemma3:4b` | 4B | Local Ollama | 18/18 (100%) | 6/18 (33.3%) | 8.8s |
| `gpt-oss:20b-cloud` | 20B | Ollama → cloud | 18/18 (100%) | 10/18 (55.6%) | 2.5s |
| `ministral-3:14b-cloud` | 14B | Ollama → cloud | 18/18 (100%) | 12/18 (66.7%) | 2.8s |

**Slide-type breakdown (appropriate rate per model):**

| Slide Type | gemma3:4b | ministral-3:14b-cloud | gpt-oss:20b-cloud |
|---|---|---|---|
| Cover / title slide | 0/3 | 0/3 | 0/3 |
| Academic content | 3/3 | 3/3 | 3/3 |
| Section header | 0/3 | 3/3 | 2/3 |
| Bullet list | 3/3 | 3/3 | 3/3 |
| Closing slide | 0/3 | 0/3 | 0/3 |
| Quote slide | 0/3 | 3/3 | 2/3 |
| **Total** | **6/18** | **12/18** | **10/18** |

**TITLE_AND_BODY bias analysis:**

| Model | TITLE_AND_BODY chosen (out of 18 runs) | Appropriate uses | Inappropriate uses |
|---|---|---|---|
| `gemma3:4b` | 18/18 (100%) | 6 | 12 |
| `ministral-3:14b-cloud` | 9/18 (50%) | 6 | 3 |
| `gpt-oss:20b-cloud` | 11/18 (61%) | 6 | 5 |

---

## Key Findings

- **All models parse 100% of responses successfully** — the structured output method works reliably. The problem is layout *selection*, not output parsing.
- **`gemma3:4b` has extreme TITLE_AND_BODY bias**: it chose `TITLE_AND_BODY` for every single one of its 18 runs, regardless of slide type. It has essentially no layout discrimination capability beyond identifying content slides.
- **Cover/title slide and closing slide fail universally**: all 3 models chose `TITLE_AND_BODY` for these two slide types across all 9 total runs (0/9 each). The slide's semantic role ("this is the opening slide") is not sufficiently conveyed to the models by the current prompt.
- **The 14B model outperforms the 20B model** (66.7% vs 55.6%), showing that raw parameter count is not the sole determinant. `ministral-3:14b-cloud` is more consistent: its results are either 0/3 or 3/3 with no partial scores, while `gpt-oss:20b-cloud` shows instability on section_header and quote_slide (2/3 each).
- **The failure mode is always the same**: when models get a slide wrong, they always fall back to `TITLE_AND_BODY`. There is no variety in errors.

---

## Decision

`ministral-3:14b-cloud` is the strongest candidate among the three models based on appropriate rate (66.7%) and consistency. However, the universal failure on cover/title and closing slides (0/9 across all models) is a prompt engineering problem, not a model capability problem.

This result directly motivated the follow-on experiment in `layout_selection_prompt_eng.md`, which tested 4 prompt engineering strategies specifically designed to fix these failures. The baseline results from this file (6/18, 10/18, 12/18) are the reference points used to measure improvement in that experiment.
