# Slide Layout Selection — Prompt Engineering to Fix Baseline Failures

**Date:** 2026-03-29

---

## Background & Motivation

The baseline experiment (`layout_selection_baseline.md`) showed that all three tested models universally fail to select the correct layout for cover slides and closing slides — every model chose `TITLE_AND_BODY` for these slide types across all runs (0/9 each). The root cause identified was prompt design: the baseline prompt gives generic instructions with no explicit routing rules for distinguishing slide roles.

This experiment tested 4 prompt engineering strategies specifically designed to fix these failures. The same 3 models and 6 slide types from the baseline were used, making results directly comparable. The key question: can prompt design alone bring even the weakest local 4B model to 100% accuracy, eliminating the need for larger or cloud models?

---

## Experiment Setup

**Method:** LlamaIndex `LLMTextCompletionProgram` for all models and all prompts (same as the baseline). Native function/tool calling explicitly excluded — it fails for all Ollama models.

**Models tested:** Same as baseline — `gemma3:4b` (local 4B), `ministral-3:14b-cloud` (cloud 14B), `gpt-oss:20b-cloud` (cloud 20B, think mode always on).

**Run configuration:** 3 runs per (model × prompt × slide type) at temperature 0.1, max_tokens 2048. Sequential execution only. Total: 3 models × 4 prompts × 6 slide types × 3 runs = **216 inferences**.

**Slide types tested:** Identical to baseline — cover/title slide, academic content, section header, bullet list, closing slide, quote slide.

### Prompt Strategies Tested (4 total)

**1. Decision-Tree Routing**
A two-step explicit dispatch: Step 1 classifies the slide into one of 5 roles (quote slide, section break, closing slide, title cover, content slide) using if/then rules. Step 2 maps the role to the correct layout name. Hypothesis: explicit routing rules will fix the universal cover/closing slide failures.

**2. Negative Examples** *(the recommended production prompt)*
Explicit "USE X when" positive rules combined with "DO NOT use TITLE_AND_BODY for" negative constraints. Directly counters the dominant failure mode (TITLE_AND_BODY bias) without requiring multi-step reasoning. Hypothesis: negative constraints are the most direct way to break the bias without hallucination risk.

**3. Chain-of-Thought**
Asks the model to classify the slide type first (cover, section_break, closing, quote, content), then select the layout, then verify the choice exists in the available list. Hypothesis: making reasoning explicit gives models a chance to self-correct before outputting the final layout.

**4. Minimal Layout List**
Provides only the 6 core text layouts (instead of all 12) with explicit English role descriptions. Eliminates the 6 photo/visual layouts that are irrelevant for academic text slides and adds semantic grounding for non-English layout names. Hypothesis: a smaller, well-described layout list reduces decision noise.

---

## Results

### gemma3:4b (local, 4B parameters)
**Baseline (from layout_selection_baseline.md):** 6/18 (33.3%)

| Prompt | cover/title | academic | section header | bullet list | closing | quote | Overall | Avg Elapsed |
|---|---|---|---|---|---|---|---|---|
| Decision-Tree Routing | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **15/18** | 11.7s |
| Negative Examples | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 11.6s |
| Chain-of-Thought | 3/3 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 | **12/18** | 11.7s |
| Minimal Layout List | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 | 3/3 | **12/18** | 11.3s |

**Failure details:**
- Decision-Tree Routing failure: the model returned `TITLE_COVER` (the role label from Step 1) as the `layout_name` instead of `TITLE_SLIDE`. The 4B model collapsed the two-step classify-then-map chain by outputting the intermediate label as the final answer.
- Chain-of-Thought failure: the model chose `CONTENT_WITH_PHOTO` for academic_content and bullet_list slides (6/6 runs). The CoT prompt's "content" slide type label was confused with the `CONTENT_WITH_PHOTO` layout name — a name collision between CoT vocabulary and layout names.
- Minimal Layout List failure: with only 6 layouts and no negative examples, the model chose `TITLE_SLIDE` for section_header (all 3 runs), conflating "no body text" with "title slide."

### ministral-3:14b-cloud (cloud, 14B parameters)
**Baseline (from layout_selection_baseline.md):** 12/18 (66.7%)

| Prompt | cover/title | academic | section header | bullet list | closing | quote | Overall | Avg Elapsed |
|---|---|---|---|---|---|---|---|---|
| Decision-Tree Routing | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.9s |
| Negative Examples | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.1s |
| Chain-of-Thought | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.0s |
| Minimal Layout List | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 1.9s |

All 4 prompts achieved perfect 18/18. The Minimal Layout List prompt produced the fastest latency (1.9s avg) due to the shorter token count.

### gpt-oss:20b-cloud (cloud, 20B parameters, think mode always on)
**Baseline (from layout_selection_baseline.md):** 10/18 (55.6%)

| Prompt | cover/title | academic | section header | bullet list | closing | quote | Overall | Avg Elapsed |
|---|---|---|---|---|---|---|---|---|
| Decision-Tree Routing | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.8s |
| Negative Examples | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.8s |
| Chain-of-Thought | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.7s |
| Minimal Layout List | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 1/3 | **16/18** | 2.8s |

**Minimal Layout List failure:** quote_slide run 2 was a parse failure ("Could not extract json string from output") and run 3 chose `TITLE_AND_BODY`. The shorter minimal-layout prompt may have provided insufficient anchoring tokens for this model's always-on think mode, causing occasional output format corruption.

### Cross-Model Summary

| Model | Prompt | Appropriate Rate | Parse Success | Avg Elapsed |
|---|---|---|---|---|
| `gemma3:4b` | Decision-Tree Routing | 15/18 | 18/18 | 11.7s |
| `gemma3:4b` | Negative Examples | **18/18** | 18/18 | 11.6s |
| `gemma3:4b` | Chain-of-Thought | 12/18 | 18/18 | 11.7s |
| `gemma3:4b` | Minimal Layout List | 12/18 | 18/18 | 11.3s |
| `ministral-3:14b-cloud` | Decision-Tree Routing | **18/18** | 18/18 | 2.9s |
| `ministral-3:14b-cloud` | Negative Examples | **18/18** | 18/18 | 2.1s |
| `ministral-3:14b-cloud` | Chain-of-Thought | **18/18** | 18/18 | 2.0s |
| `ministral-3:14b-cloud` | Minimal Layout List | **18/18** | 18/18 | 1.9s |
| `gpt-oss:20b-cloud` | Decision-Tree Routing | **18/18** | 18/18 | 2.8s |
| `gpt-oss:20b-cloud` | Negative Examples | **18/18** | 18/18 | 2.8s |
| `gpt-oss:20b-cloud` | Chain-of-Thought | **18/18** | 18/18 | 2.7s |
| `gpt-oss:20b-cloud` | Minimal Layout List | 16/18 | 17/18 | 2.8s |

**Improvement over baseline:**

| Model | Baseline | Best this experiment | Improvement |
|---|---|---|---|
| `gemma3:4b` | 6/18 (33.3%) | 18/18 (100%) with Negative Examples | +67 percentage points |
| `ministral-3:14b-cloud` | 12/18 (66.7%) | 18/18 (100%) with any prompt | +33 percentage points |
| `gpt-oss:20b-cloud` | 10/18 (55.6%) | 18/18 (100%) with Decision-Tree/Negative/Chain-of-Thought | +44 percentage points |

---

## Key Findings

- **The Negative Examples prompt achieves 100% for all three models**, including the weakest local 4B model. It is the only prompt that works universally across all model sizes.
- **Small models (4B) require negative constraints**: `gemma3:4b` achieves 100% only with the Negative Examples prompt. Multi-step prompts (Decision-Tree Routing, Chain-of-Thought) trigger hallucinations or name collisions. Minimal context causes regressions on slide types that were previously correct.
- **Larger models are more robust**: `ministral-3:14b-cloud` achieves 100% on all 4 prompt strategies. It can correctly interpret multiple reasoning styles, whereas `gemma3:4b` has no tolerance for suboptimal prompt design.
- **The Minimal Layout List prompt is the only strategy that fails** — for `gpt-oss:20b-cloud` on the quote slide (1 parse failure + 1 wrong choice), likely because the shorter prompt destabilizes structured output parsing under always-on think mode.
- **Prompt quality matters more than model size for small models**: with the right prompt, a local 4B model can match the accuracy of a cloud 14B or 20B model.

---

## Decision

**The Negative Examples prompt is adopted for production** as the `AUGMENT_LAYOUT_PMT` replacement in `backend/prompts/prompts.py`.

Rationale: it is the only prompt achieving 18/18 on `gemma3:4b` (the weakest supported model), achieves 18/18 on both cloud models, uses no multi-step reasoning (eliminating hallucination of intermediate labels), and the explicit USE/DO NOT rules are straightforward to maintain and extend.

**Recommended model + prompt combinations for production:**

| Priority | Model | Prompt | Appropriate Rate | Avg Latency |
|---|---|---|---|---|
| Primary | `ollama/ministral-3:14b-cloud` | Negative Examples | 18/18 | 2.1s |
| Fallback | `ollama/gpt-oss:20b-cloud` | Negative Examples | 18/18 | 2.8s |
| Local-only / offline | `ollama/gemma3:4b` | Negative Examples | 18/18 | 11.6s |
