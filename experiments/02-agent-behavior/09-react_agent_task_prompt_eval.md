# Experiment 9 — ReAct Agent: Task Prompt Engineering for PPTX Code Generation

## Task Context

This experiment targets **Step 6 — PPTX Rendering** (original ReActAgent approach) from the system architecture (README → System Architecture). This experiment is the second in a three-part diagnostic chain (Exp 7 → Exp 8 → Exp 9): Exp 7 established gemma3:4b as the model but found the agent wrote invalid python-pptx code at 8.3% overall correctness — this experiment targets that failure by fixing the task prompt (`SLIDE_GEN_PMT`). The original author used GPT-4o in a ReActAgent loop to generate python-pptx code at runtime. This experiment identifies which task prompt (`SLIDE_GEN_PMT`) gets a local 4B model to write correct python-pptx code — specifically the layout lookup pattern, null guards, and save path.

```
Input: slide_outlines.json + PPTX template       ← Step 5: Slide Outline + HITL
      │
      ▼
┌── 6. PPTX RENDERING ──────────────────────────────────────────────────┐
├─── Original (lz-chen) ────────────────┬─── My Implementation ─────────┤
│ ReActAgent (GPT-4o)                   │ ReActAgent (local 4B LLM)     │
│ → writes python-pptx code             │ → writes python-pptx code     │
│ → executes in Azure sandbox           │ → executes in Docker sandbox  │
└───────────────────────────────────────┴───────────────────────────────┘
      │
      ▼
Output: paper_summaries.pptx                      → Step 7: Slide Validation & Fix
```

Step 6 is the first step where a rendered PPTX file is produced. If the agent writes invalid python-pptx code, the sandbox execution fails, nothing is saved to `/sandbox/`, and the pipeline stalls with no output.

**Variable names defined here:**
- `SLIDE_GEN_PMT` — the system prompt telling the agent what python-pptx code to write: which files to load, which API patterns to use, where to save output. This is the prompt under test.
- `REACT_PROMPT_SUFFIX` — the ReAct format control prompt: Thought/Action/Observation loop structure, termination instructions. This is held constant and is tested separately in Exp 9.
- `system_prompt = SLIDE_GEN_PMT + REACT_PROMPT_SUFFIX`

Step 6 — PPTX Rendering (detail, original ReActAgent approach)

```
Step 6 — PPTX Rendering (detail)
──────────────────────────────────────────────────────────────────
 slide_outlines.json + PPTX template
       │
       ▼
 ┌─── EXPERIMENT TARGET ──────────────────────────────────────────┐
 │                                                                │
 │  ① [slide_gen]                                                 │
 │     ReActAgent · SLIDE_GEN_PMT (P0–P3 variants under test)    │
 │     REACT_PROMPT_SUFFIX: held constant                        │
 │     Tools: run_code, list_files, upload_file, get_all_layout   │
 │       │                                                        │
 │       ▼  paper_summaries.pptx                                  │
 │  ② [validate_slides]   VLM per slide image  ◄───────────────┐ │
 │       │                                                      │ │
 │       ├─ all OK ────────────────── stop: final.pptx ✓        │ │
 │       │                                                      │ │
 │       └─ issues found AND n_retry < 2                        │ │
 │              │                                               │ │
 │              ▼                                               │ │
 │  ③ [modify_slides]                                           │ │
 │     ReActAgent · SLIDE_MODIFICATION_PMT                      │ │
 │     saves paper_summaries_v{n_retry}.pptx                    │ │
 │              │                                               │ │
 │              └───────────────────────────────────────────────┘ │
 │                    (up to 2 retries; n_retry ≥ 2 → ✗)          │
 │                                                                │
 └────────────────────────────────────────────────────────────────┘
       │
       ▼
 paper_summaries.pptx
```

---

## Summary

- **Problem:** lz-chen's task prompt produced three recurring code errors that caused sandbox failures on every run — 8.3% overall correctness across both models:
  - Wrong layout selection pattern causes AttributeError — the prompt describes what to do but gives no code example, so models default to passing a string name directly
  - Missing null guard causes TypeError — the prompt says to skip null placeholder indices but gives no code pattern, so models omit the check when data has no null values
  - Wrong save path — the prompt provides only a filename without directory prefix
- **Solution:** 4 prompt variants (P0 through P3), each adding one code pattern incrementally, tested across 2 models and 2 test cases via static analysis — 48 LLM calls total. Static analysis (regex) was chosen to isolate LLM output quality from sandbox execution noise and ReAct loop variability.
- **Result:** The prompt with explicit layout lookup and null guard patterns achieves 100% overall correctness on both models and both test cases. The key non-obvious finding: adding the layout pattern alone causes gemma3:4b to drop null guards to 0% on data with no null values — the model mimics the style of the provided code example, including its omissions. The validated prompt was not deployed; the ReActAgent was replaced by deterministic rendering before integration.

---

## Experiment Setup

> This experiment's approach was superseded by deterministic rendering — no ✅ applies. See Pipeline Integration Status. A later experiment (Exp 9) validated the `REACT_PROMPT_SUFFIX` independently; that experiment is also superseded for the same reason.

### Objective

- **Baseline:** lz-chen's `SLIDE_GEN_PMT` (P0_vague) is the control condition — vague text instructions, no explicit python-pptx code patterns. It achieves 8.3% overall correctness on local models, establishing the reference point for measuring prompt improvement.
- **Goal:** Identify the minimal set of explicit code patterns to add to `SLIDE_GEN_PMT` that achieves 100% code correctness on both models across both test cases
- **Pass condition:** `overall% = 100%` for both models on both test cases (all 4 static analysis checks pass)

### Models

| Label | Model string | Type |
|---|---|---|
| gemma3:4b | ollama/gemma3:4b | Local, 4B |
| ministral-3:14b-cloud | ollama/ministral-3:14b-cloud | Cloud via Ollama routing |

**LLM call:** `litellm.completion()` — plain text output, no structured output parsing, no ReAct loop. The LLM is asked to generate python-pptx code directly; the code string is then evaluated statically.

### Prompt Variants

All variants share the same preamble (task description, template path, slide data). The requirements section differs incrementally:

| ID | What is added vs previous |
|---|---|
| **P0** `P0_vague` | Text-only requirements, no python-pptx code examples. lz-chen's original prompt (with the save path bug isolated: `/sandbox/` prefix pre-fixed to remove one confound). |
| **P1** `P1_layout_pattern` | P0 + explicit `add_slide` lookup pattern: `layout = next(l for l in prs.slide_layouts if l.name == item['layout_name'])` |
| **P2** `P2_null_guard` | P1 + explicit null guard pattern: `if item['idx_title_placeholder'] is not None: slide.placeholders[...]` |
| **P3** `P3_full_pattern` | P2 + prepended `Required imports: from pptx import Presentation` block |

<details>
<summary><strong>P0</strong> — <code>P0_vague</code>: text-only requirements, no python-pptx code examples (lz-chen baseline with save path pre-fixed)</summary>

````text
You are a Python code generator.
Write complete, executable Python code to create a PowerPoint slide deck
from the given data using the python-pptx library.

OUTPUT FORMAT: Python code ONLY. No explanations. No markdown code fences (no ```).

Template path: /sandbox/pptx-template.pptx
Slide data (JSON list of slide outline objects):
{slide_data}

Requirements:
- Load the template from /sandbox/pptx-template.pptx using Presentation()
- Loop over all items in the slide data; create one slide per item
- Match each slide to its layout by layout_name from the JSON
- Fill the title using idx_title_placeholder index, content using idx_content_placeholder index
- If idx_title_placeholder is null, do NOT attempt to fill a title placeholder for that slide
- If idx_content_placeholder is null, do NOT attempt to fill a content placeholder for that slide
- Save the final file as /sandbox/paper_summaries.pptx using prs.save()
````

</details>

<details>
<summary><strong>P1</strong> — <code>P1_layout_pattern</code>: P0 + explicit <code>add_slide</code> layout lookup pattern</summary>

````text
You are a Python code generator.
Write complete, executable Python code to create a PowerPoint slide deck
from the given data using the python-pptx library.

OUTPUT FORMAT: Python code ONLY. No explanations. No markdown code fences (no ```).

Template path: /sandbox/pptx-template.pptx
Slide data (JSON list of slide outline objects):
{slide_data}

Requirements:
- Load the template from /sandbox/pptx-template.pptx using Presentation()
- Loop over all items in the slide data; create one slide per item
- Match each slide to its layout by layout_name from the JSON
- Fill the title using idx_title_placeholder index, content using idx_content_placeholder index
- If idx_title_placeholder is null, do NOT attempt to fill a title placeholder for that slide
- If idx_content_placeholder is null, do NOT attempt to fill a content placeholder for that slide
- Save the final file as /sandbox/paper_summaries.pptx using prs.save()

python-pptx layout lookup (add_slide requires a SlideLayout object, NOT a string):
    layout = next(l for l in prs.slide_layouts if l.name == item['layout_name'])
    slide  = prs.slides.add_slide(layout)
````

</details>

<details>
<summary><strong>P2</strong> — <code>P2_null_guard</code>: P1 + explicit null guard pattern for idx fields</summary>

````text
You are a Python code generator.
Write complete, executable Python code to create a PowerPoint slide deck
from the given data using the python-pptx library.

OUTPUT FORMAT: Python code ONLY. No explanations. No markdown code fences (no ```).

Template path: /sandbox/pptx-template.pptx
Slide data (JSON list of slide outline objects):
{slide_data}

Requirements:
- Load the template from /sandbox/pptx-template.pptx using Presentation()
- Loop over all items in the slide data; create one slide per item
- Match each slide to its layout by layout_name from the JSON
- Fill the title using idx_title_placeholder index, content using idx_content_placeholder index
- If idx_title_placeholder is null, do NOT attempt to fill a title placeholder for that slide
- If idx_content_placeholder is null, do NOT attempt to fill a content placeholder for that slide
- Save the final file as /sandbox/paper_summaries.pptx using prs.save()

python-pptx layout lookup (add_slide requires a SlideLayout object, NOT a string):
    layout = next(l for l in prs.slide_layouts if l.name == item['layout_name'])
    slide  = prs.slides.add_slide(layout)

Placeholder fill with null guard (idx values may be None for visual-only layouts):
    if item['idx_title_placeholder'] is not None:
        slide.placeholders[item['idx_title_placeholder']].text = item['title']
    if item['idx_content_placeholder'] is not None:
        slide.placeholders[item['idx_content_placeholder']].text = item['content']
````

</details>

<details>
<summary><strong>P3</strong> — <code>P3_full_pattern</code>: P2 + prepended Required imports block</summary>

````text
You are a Python code generator.
Write complete, executable Python code to create a PowerPoint slide deck
from the given data using the python-pptx library.

OUTPUT FORMAT: Python code ONLY. No explanations. No markdown code fences (no ```).

Template path: /sandbox/pptx-template.pptx
Slide data (JSON list of slide outline objects):
{slide_data}

Required imports:
    from pptx import Presentation

Requirements:
- Load the template from /sandbox/pptx-template.pptx using Presentation()
- Loop over all items in the slide data; create one slide per item
- Match each slide to its layout by layout_name from the JSON
- Fill the title using idx_title_placeholder index, content using idx_content_placeholder index
- If idx_title_placeholder is null, do NOT attempt to fill a title placeholder for that slide
- If idx_content_placeholder is null, do NOT attempt to fill a content placeholder for that slide
- Save the final file as /sandbox/paper_summaries.pptx using prs.save()

python-pptx layout lookup (add_slide requires a SlideLayout object, NOT a string):
    layout = next(l for l in prs.slide_layouts if l.name == item['layout_name'])
    slide  = prs.slides.add_slide(layout)

Placeholder fill with null guard (idx values may be None for visual-only layouts):
    if item['idx_title_placeholder'] is not None:
        slide.placeholders[item['idx_title_placeholder']].text = item['title']
    if item['idx_content_placeholder'] is not None:
        slide.placeholders[item['idx_content_placeholder']].text = item['content']
````

</details>

### Test Cases

| ID | Description | Null idx values? |
|---|---|---|
| **TC1** `TC1_standard` | 3 slides: TITLE_SLIDE, TITLE_AND_BODY, TITLE_SLIDE. All `idx_title/content_placeholder` are integers (0 or 1). | No |
| **TC2** `TC2_with_nulls` | 5 slides including one FULL_PHOTO with `idx_title_placeholder: null, idx_content_placeholder: null`. | Yes |

TC2 specifically tests whether the LLM handles `None`-valued idx fields (visual-only layouts). TC1 tests whether null guards are written defensively even when the data doesn't force them — which turns out to be the most discriminating condition (see Observations).

### Evaluation Checks (Static Analysis)

Four boolean checks per generated code string. The method is static analysis (regex), not execution. This isolates LLM output quality from sandbox execution variability and ReAct loop behavior.

| Check | Measures | Primary signal? |
|---|---|---|
| `layout_lookup_correct` | `slide_layouts` iterated + `add_slide(variable)` + `.name ==` comparison. Rejects `add_slide("string")` and `add_slide(0)`. | **Yes** |
| `null_guard_correct` | `is not None` check AND `placeholders[` both present in code. | **Yes** |
| `save_path_correct` | `prs.save()` target starts with `/sandbox/` or is a relative path. Rejects `/app/`, `/root/`. | Low (expected ~100% after P0 save fix) |
| `import_correct` | `from pptx import Presentation` present. | Sanity only |

**`overall%`** = 1 only if all 4 checks pass. This is the primary metric.

**Known limitations of static analysis:**
- `layout_lookup_correct`: inline `add_slide(next(...))` is a false negative — the two-step pattern is required.
- `null_guard_correct`: co-presence check only — does not verify structural wrapping. An unrelated `is not None` elsewhere in the code causes a false positive.
- `save_path_correct` / `import_correct`: low discriminating power between prompt variants; these are sanity signals.

**Run parameters:** N=3 per (model × prompt × test_case). Total: 4 prompts × 2 models × 2 test cases × 3 runs = **48 LLM calls**. N=3 is intentional for a resource-constrained environment (MacBook M1, local inference): if a model fails 2/3 runs at small N, additional runs won't change the direction.

---

## Full Experimental Results

### Full Summary Table

- **Purpose:** Measure per-check and overall correctness across all prompt variants, models, and test cases
- **Expected:** P2 or later achieves `overall% = 100%` for both models on both test cases

**MODEL: gemma3:4b**

| prompt | test_case | N | layout% | save% | null% | import% | overall% |
|---|---|---|---|---|---|---|---|
| P0_vague | TC1_standard | 3 | 0.0 | 33.3 | 100.0 | 100.0 | 0.0 |
| P0_vague | TC2_with_nulls | 3 | 0.0 | 100.0 | 100.0 | 100.0 | 0.0 |
| P1_layout_pattern | TC1_standard | 3 | 100.0 | 100.0 | 0.0 | 100.0 | 0.0 |
| P1_layout_pattern | TC2_with_nulls | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P2_null_guard | TC1_standard | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P2_null_guard | TC2_with_nulls | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P3_full_pattern | TC1_standard | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P3_full_pattern | TC2_with_nulls | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

**MODEL: ministral-3:14b-cloud**

| prompt | test_case | N | layout% | save% | null% | import% | overall% |
|---|---|---|---|---|---|---|---|
| P0_vague | TC1_standard | 3 | 33.3 | 100.0 | 100.0 | 100.0 | 33.3 |
| P0_vague | TC2_with_nulls | 3 | 0.0 | 100.0 | 66.7 | 100.0 | 0.0 |
| P1_layout_pattern | TC1_standard | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P1_layout_pattern | TC2_with_nulls | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P2_null_guard | TC1_standard | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P2_null_guard | TC2_with_nulls | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P3_full_pattern | TC1_standard | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P3_full_pattern | TC2_with_nulls | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

**Conclusion:** Both models reach 100% overall at the two-pattern prompt — the critical non-obvious failure is that adding the layout pattern alone causes the 4B model to drop null guards entirely on data with no null values.

### Failure Breakdown (aggregated across both models and both test cases)

| prompt | layout | save | null | import | N |
|---|---|---|---|---|---|
| P0_vague | 91.7 | 16.7 | 8.3 | 0.0 | 12 |
| P1_layout_pattern | 0.0 | 0.0 | 25.0 | 0.0 | 12 |
| P2_null_guard | 0.0 | 0.0 | 0.0 | 0.0 | 12 |
| P3_full_pattern | 0.0 | 0.0 | 0.0 | 0.0 | 12 |

**Conclusion:** The null guard failure at the layout-only prompt is concentrated entirely in the 4B model on non-null data — the same model writes null guards correctly when actual null values are present in the data.

---

## Observations

### Prompt text vs code pattern (P0 → P1)

```
P0_vague baseline
      │  layout% = 0% for gemma3:4b, 16.7% for ministral (across TC1+TC2)
      │  Text instruction: "match each slide to its layout by layout_name"
      │  Both models default to add_slide("TITLE_AND_BODY") or add_slide(int)
      │  → AttributeError in sandbox execution on every call
      │
      ▼
P1: add explicit two-line lookup pattern
      │  layout = next(l for l in prs.slide_layouts if l.name == item['layout_name'])
      │  slide  = prs.slides.add_slide(layout)
      │
      ▼
layout% → 100% for both models, both test cases
```

**Conclusion:** Text instructions alone are insufficient for non-obvious API patterns — both models default to the most common training distribution form when no code example is provided.
- Both models pass a string name directly to the layout selection call. That form appears frequently in simple tutorials.
- The two-step pattern (assign layout to variable, then pass it to the add_slide call) requires an explicit code example to trigger.
- This is not model-size-specific. Even the 14B model fails at layout lookup without an explicit code pattern. The failure is an API knowledge gap, not a reasoning gap.

### Null guard regression (P1 → P2)

This is the most important finding in the experiment. Adding a code example can make model behavior worse, not better.

```
P0 → gemma3:4b writes null guards on both TC1 and TC2 without any code example
      │  Text instruction: "if null, do NOT fill"
      │  null% = 100% for both test cases under text-only prompt
      │
      ▼
P1: layout code pattern is introduced — but WITHOUT null guard code pattern
      │
      ├─ TC2 (data has None values): null% = 100%  ✓
      │    Model sees None in the actual slide data → defensive instinct activates
      │
      └─ TC1 (data has no None values): null% = 0%  ✗
           Model mimics the style of the provided layout code example
           The layout example contains no null guards
           With no None in the data to trigger defensive instinct,
           the code style example becomes the dominant signal
           → model writes code without null guards
           → would cause TypeError at runtime on any layout with null idx
      │
      ▼
P2: explicit null guard code pattern added alongside layout pattern
      │  if item['idx_title_placeholder'] is not None:
      │      slide.placeholders[item['idx_title_placeholder']].text = item['title']
      │
      ▼
null% → 100% for both models, both test cases
```

**Conclusion:** A model mimics the style of provided code examples — including what they omit.
- When the only code example is the layout lookup block, gemma3:4b treats any omission in that example as a style signal. The layout block has no null guards. So the model omits null guards too — even when the text instruction says to guard.
- The test case with null values recovers. Seeing actual null values in the data overrides the code style signal.
- The standard test case does not recover. The data contains no null values, so the code style example remains the dominant signal.
- This means a prompt with a partial code example can be worse than a text-only prompt for the omitted pattern.
- The 14B model result reinforces this. Even with actual null values in the data and a text instruction saying to guard, one out of three runs omitted the null guard. Adding an explicit null guard pattern stabilizes the result. For smaller and mid-size models, code examples enforce the output contract more reliably than text instructions.

### P3 Occam's Razor

```
P2 → P3: prepend "Required imports: from pptx import Presentation"
      │
      ▼
No measurable change: overall% = 100% for both models, both test cases
      │
      │  import% = 100% at P0 for both models — already saturated
      │  P(generate "from pptx import Presentation" | task = "write python-pptx code") ≈ 1.0
      │  Adding the import to the prompt does not shift the posterior
      │
      ▼
P3 adds tokens that contribute no signal and introduce two theoretical risks:
      1. Attention dilution: each additional prompt token competes for
         attention weight on the tokens that actually matter (layout and null guard patterns)
         For 4B models, effective context per token is finite
      2. Position shift: prepending changes the left-context of every downstream token
         P2 order: PREAMBLE → requirements → layout code → null guard code
         P3 order: imports → PREAMBLE → requirements → layout code → null guard code
         Theoretical risk: format drift in small models sensitive to prompt ordering
```

**Conclusion:** The minimal prompt is preferred — the import block adds tokens that shift no output distribution and fail every test for redundancy.
- The import block fails all three Occam's Razor tests: omitting it doesn't degrade output, adding it could interfere, and it solves no problem the two-pattern prompt can't.
- The import statement is already saturated in the training distribution of any model trained on Python code. Redundant tokens are never neutral — they dilute attention and shift token positions.

### Prompt variant comparison tree

```
SLIDE_GEN_PMT variants (sorted by overall% high → low)
[✓ = 100% overall  △ = partial  ✗ = failed]
      │
      ├─ P2_null_guard ── 100% ✓  ← chosen
      │    Both models, both test cases
      │    Minimal prompt that achieves the target
      │
      ├─ P3_full_pattern ── 100% ✓
      │    Same result as P2, adds import block with no benefit
      │    Theoretical attention dilution and position shift risk
      │    Not chosen: fails Occam's Razor
      │
      ├─ P1_layout_pattern ── 75.0% △
      │    layout% fixed to 100%; null% = 0% for gemma3:4b TC1
      │    Null guard regression for data with no None values
      │
      └─ P0_vague (lz-chen baseline, control) ── 8.3%
           layout% = 8.3% (models guess add_slide("string"))
           save% = 83.3% (models omit /sandbox/ prefix)
           8.3% overall — baseline reference on local models
```

The two-pattern and three-pattern prompts are tied at 100%. The two-pattern prompt is kept — it is shorter and introduces no theoretical risks.

---

## Decision

```
Decision: Which SLIDE_GEN_PMT variant to apply?
      │
      ├── P0_vague (lz-chen original, control)
      │     ✗ layout% = 8.3% — models guess wrong API
      │     ✗ save% = 83.3% — wrong path on gemma3:4b
      │     → BASELINE: reference point for measuring prompt improvement
      │
      ├── P1_layout_pattern
      │     ✓ layout% = 100%
      │     ✗ null% = 0% for gemma3:4b TC1 — null guard regression
      │     → REJECTED: partial fix, introduces new failure mode
      │
      ├── P2_null_guard
      │     ✓ overall% = 100% for both models, both test cases
      │     ✓ Minimal prompt — no redundant tokens
      │     → CHOSEN: minimal sufficient prompt
      │
      └── P3_full_pattern
            ✓ overall% = 100% — same as P2
            △ Adds import block with no measurable benefit
            △ Attention dilution and position shift risk for small models
            → NOT CHOSEN: redundant tokens, fails Occam's Razor
```

The two-pattern prompt is the minimal sufficient prompt. It adds two explicit code blocks after the existing requirements text: the layout lookup pattern and the null guard pattern. Both models were validated on this prompt. If model behavior changes with a different LLM, the layout-only prompt is the correct intermediate — it fixes the layout selection failure without introducing null guard regression.

The validated prompt was never integrated. The ReActAgent approach was replaced before deployment. See Pipeline Integration Status.

---

## Pipeline Integration Status 🚫 SUPERSEDED

### What replaced it

- `PptxRenderer` renders PPTX directly from schema-validated `slide_outlines.json` — no LLM, no Docker sandbox, no ReAct loop.
- LLM now outputs structured JSON only; the renderer constructs the PPTX deterministically.
- Eliminates all layout lookup, null guard, save path, and loop failure modes investigated in this experiment.

### Why the decision was made

- python-pptx has no markdown parser — LLM-generated bullet text collapsed into a single paragraph and literal `*` characters appeared on slides (confirmed 2026-04-15).
- Docker sandbox added latency and infrastructure dependency on top of non-deterministic code generation.

### Transferable findings

- **Code example style mimicry:** A partial code example causes a model to mimic the style of that example — including its omissions. A layout code example without null guards causes the model to omit null guards even when the text instruction says to guard. This applies to any agent step where code generation is guided by partial examples.
- **Text instructions are insufficient for non-obvious API patterns:** Both a 4B and a 14B model fail to use the correct layout selection pattern from text description alone. Explicit code patterns are required for library APIs that don't match the most common training distribution form.
- **Minimal prompt principle:** Every token added to a prompt that does not shift the output distribution is a potential source of attention dilution and position sensitivity — especially for models ≤ 4B. Validate each addition against a measurable failure before including it.
