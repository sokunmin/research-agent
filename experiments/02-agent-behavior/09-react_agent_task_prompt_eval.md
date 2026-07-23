# Experiment 9 — ReAct Agent: Task Prompt Engineering for PPTX Code Generation

## Task Context

lz-chen's ReActAgent used GPT-4o to write python-pptx code at runtime. Exp 8 swapped in a
local 4B model and fixed a tool-invocation failure — the model wrote correct-looking code
but never called the tool to execute it. This experiment picks up from there: assuming the
tool IS called, is the code the model writes actually correct? A code audit of lz-chen's
task prompt (`SLIDE_GEN_PMT`) found it described required python-pptx patterns in prose
only, with no code examples. This experiment identifies which task prompt gets a local 4B
model to write correct python-pptx code — specifically the layout lookup pattern, null
guards, and save path.

This experiment targets **Step 6 — PPTX Rendering** (original ReActAgent approach) from the
system architecture (README → System Architecture).

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

A **PPTX layout** is a slide template that defines which placeholder areas exist on a slide — title bar, body text region, photo region, or nothing at all. The layouts with no text placeholders (`THREE_PHOTO`, `FULL_PHOTO`, `BLANK`) are exactly what this experiment's null-guard test case targets.

![PPTX Layout Groups](imgs/pptx_layout_groups.svg)

Step 6 — PPTX Rendering (detail, original ReActAgent approach)

```
Step 6 — PPTX Rendering (detail)
lz-chen's original tool and prompt names; this experiment substitutes a Docker-based
execution tool (tested as `run_code` throughout this report) because Azure access was unavailable.
This experiment tests `SLIDE_GEN_PMT` via direct LLM completion, not the live ReAct loop shown below —
see Experiment Setup for the static-analysis method.
────────────────────────────────────────────────────────────────────────────────
 slide_outlines.json + PPTX template
       │
       ▼
 ┌─── EXPERIMENT TARGET ──────────────────────────────────────────────────────────────┐
 │                                                                                    │
 │  ① [slide_gen]                                                                    │
 │  ┌─── Original (lz-chen) ────────────────┬─── My Implementation ──────────────┐    │
 │  │ ReActAgent · Azure GPT-4o             │ ReActAgent · local 4B LLM (Ollama) │    │
 │  │ SLIDE_GEN_PMT                         │ SLIDE_GEN_PMT (P0–P3 tested)       │    │
 │  │ Tools: code_interpreter, list_files,  │ Tools: run_code, list_files,       │    │
 │  │   upload_file, get_all_layout         │   upload_file, get_all_layout      │    │
 │  └───────────────────────────────────────┴────────────────────────────────────┘    │
 │       │                                                                            │
 │       ▼  paper_summaries.pptx                                                      │
 └────────────────────────────────────────────────────────────────────────────────────┘
       │
       ▼
 paper_summaries.pptx
```

**Variable names defined here:**
- `SLIDE_GEN_PMT` — the system prompt telling the agent what python-pptx code to write: which files to load, which API patterns to use, where to save output. This is the prompt under test.
- `REACT_PROMPT_SUFFIX` — the ReAct format control prompt (Thought/Action/Observation loop structure, termination instructions) that the pipeline appends to `SLIDE_GEN_PMT` when running inside the live agent. This experiment tests `SLIDE_GEN_PMT` via direct LLM completion instead of the ReAct loop, so `REACT_PROMPT_SUFFIX` is not part of the prompts evaluated here — it is tested separately in Exp 10.

---

## Summary

- **Problem:** lz-chen's task prompt (`SLIDE_GEN_PMT`) described required python-pptx patterns in prose only, with no code examples — a code audit traced this to three recurring bugs: the model picks the wrong slide layout (some layouts, like photo-only slides, have no title or content fields at all), writes to those missing fields without checking first and crashes, and saves the file with no directory prefix.
- **Solution:** Four prompt variants, each adding one more code example, were tested on two models via static code analysis to isolate prompt quality from execution noise.
- **Result:** Adding two code examples raised correctness from 8.3% to 100% on both models — but a partial fix briefly made things worse, since the model copies a code example's omissions as faithfully as its content. The validated prompt was never deployed; the ReActAgent route was replaced before integration.

---

## Experiment Setup

### Models

| Label | Model string | Type |
|---|---|---|
| `gemma3:4b` | `ollama/gemma3:4b` | Local, 4B |
| `ministral-3:14b-cloud` | `ollama/ministral-3:14b-cloud` | Cloud via Ollama routing |

**LLM call:** `litellm.completion()` at `temperature=0.1` — plain text output, no structured output parsing, no ReAct loop. The LLM is asked to generate python-pptx code directly; the code string is then evaluated statically.

### Prompt Variants

All variants share the same preamble (task description, template path, slide data). The requirements section differs incrementally:

| Name | Key Design |
|---|---|
| `P0_baseline` | Text-only instructions only — no code example for layout selection or null handling. (The save-path instruction is already correct here.) |
| `P1_layout_pattern` | Adds one code example: how to correctly look up the matching layout object by name. |
| `P2_null_guard` | Adds a second code example on top of `P1_layout_pattern`: how to skip a placeholder when its index is null. |
| `P3_full_pattern` | Adds one more line on top of `P2_null_guard`: a required-imports statement. |

<details>
<summary><code>P0_baseline</code>: text-only requirements, no python-pptx code examples (lz-chen's original prompt, save path already correct)</summary>

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
<summary><code>P1_layout_pattern</code>: `P0_baseline` + explicit layout lookup pattern</summary>

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
<summary><code>P2_null_guard</code>: `P1_layout_pattern` + explicit null guard pattern for idx fields</summary>

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
<summary><code>P3_full_pattern</code>: `P2_null_guard` + prepended Required imports block</summary>

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

| Name | Description | Null idx values? |
|---|---|---|
| `TC1_standard` | 3 slides: TITLE_SLIDE, TITLE_AND_BODY, TITLE_SLIDE. All `idx_title/content_placeholder` are integers (0 or 1). | No |
| `TC2_with_nulls` | 5 slides including one FULL_PHOTO with `idx_title_placeholder: null, idx_content_placeholder: null`. | Yes |

<details>
<summary><code>TC1_standard</code> — input JSON (3 slides, no null idx values)</summary>

```json
[
  {
    "title": "Attention Is All You Need",
    "content": "A Research Presentation\nPresented by: John Smith",
    "layout_name": "TITLE_SLIDE",
    "idx_title_placeholder": 0,
    "idx_content_placeholder": 1
  },
  {
    "title": "Key Approach",
    "content": "* Transformer architecture using self-attention\n* Eliminates recurrence entirely",
    "layout_name": "TITLE_AND_BODY",
    "idx_title_placeholder": 0,
    "idx_content_placeholder": 1
  },
  {
    "title": "Thank You",
    "content": "Q&A",
    "layout_name": "TITLE_SLIDE",
    "idx_title_placeholder": 0,
    "idx_content_placeholder": 1
  }
]
```

</details>

<details>
<summary><code>TC2_with_nulls</code> — input JSON (5 slides, one FULL_PHOTO with null idx values)</summary>

```json
[
  {
    "title": "Attention Is All You Need",
    "content": "A Research Presentation\nPresented by: John Smith",
    "layout_name": "TITLE_SLIDE",
    "idx_title_placeholder": 0,
    "idx_content_placeholder": 1
  },
  {
    "title": "Model Architecture",
    "content": "* Multi-head attention\n* Positional encoding\n* Feed-forward layers",
    "layout_name": "BULLET_LIST",
    "idx_title_placeholder": 0,
    "idx_content_placeholder": 1
  },
  {
    "title": "",
    "content": "",
    "layout_name": "FULL_PHOTO",
    "idx_title_placeholder": null,
    "idx_content_placeholder": null
  },
  {
    "title": "Results",
    "content": "* BLEU score: 41.0 on WMT 2014 En-De\n* Outperforms all previous SOTA",
    "layout_name": "TITLE_AND_BODY",
    "idx_title_placeholder": 0,
    "idx_content_placeholder": 1
  },
  {
    "title": "Thank You",
    "content": "Q&A",
    "layout_name": "TITLE_SLIDE",
    "idx_title_placeholder": 0,
    "idx_content_placeholder": 1
  }
]
```

</details>

`TC2_with_nulls` specifically tests whether the LLM handles `None`-valued idx fields (visual-only layouts). `TC1_standard` tests whether null guards are written defensively even when the data doesn't force them — which turns out to be the most discriminating condition (see Observations).

### Evaluation Checks (Static Analysis)

Four boolean checks are run against the generated code string via regex — not execution — to isolate LLM output quality from sandbox and ReAct loop variability.

| Check | Measures | Primary signal? |
|---|---|---|
| `layout_lookup_correct` | The model looks up the matching layout object by name, instead of passing a layout name or index directly. | **Yes** |
| `null_guard_correct` | The code guards against a null placeholder index before writing to it. | **Yes** |
| `save_path_correct` | The output file is saved to the expected sandbox directory, not an arbitrary system path. | Low — the correct path is already given in every variant's text instructions |
| `import_correct` | The required library import is present. | Sanity only |

<details>
<summary>How each check works — regex walkthrough with pass/fail examples</summary>

```
┌─────────────────────────────────────────────────────────────────────┐
│  1. layout_lookup_correct — did the code look up the layout          │
│     correctly?                                                       │
└─────────────────────────────────────────────────────────────────────┘

generated code string
      │
      ▼
  ┌─ Check A: contains "slide_layouts"? ───────────────┐
  │  layout = next(l for l in prs.slide_layouts...)    │  ✓ yes
  └─────────────────────────────────────────────────────┘
      │
      ▼
  ┌─ Check B: contains ".add_slide(variable)"? ────────┐
  │  slide = prs.slides.add_slide(layout)              │  ✓ yes (layout is a variable)
  └─────────────────────────────────────────────────────┘
      │
      ▼
  ┌─ Check C: contains a ".name ==" comparison? ───────┐
  │  if l.name == item['layout_name']                  │  ✓ yes
  └─────────────────────────────────────────────────────┘
      │
      ▼
  ┌─ Check D: does add_slide("string") or add_slide(number) appear? ─┐
  │  (does not appear)                                               │  ✓ no → good
  └───────────────────────────────────────────────────────────────────┘
      │
      ▼
  A✓ + B✓ + C✓ + D(absent) ──▶ ✅ PASS

Counter-example:
  slide = prs.slides.add_slide("TITLE_AND_BODY")
        │
        ▼
  Hits check D (string passed directly) ──▶ ❌ FAIL


┌─────────────────────────────────────────────────────────────────────┐
│  2. null_guard_correct — is there a null check before writing?       │
└─────────────────────────────────────────────────────────────────────┘

generated code string
      │
      ├─ Contains the string "is not None"? ──── ✓/✗
      │
      └─ Contains the string "placeholders["? ── ✓/✗
      │
      ▼
   Both must be present in the code

✅ PASS example:
  if item['idx_title_placeholder'] is not None:      ← "is not None" present
      slide.placeholders[...] = item['title']         ← "placeholders[" present

❌ FAIL example:
  slide.placeholders[item['idx_title_placeholder']].text = item['title']
                     ↑
              "is not None" never appears anywhere in the code


┌─────────────────────────────────────────────────────────────────────┐
│  3. save_path_correct — was the file saved to the right path?        │
└─────────────────────────────────────────────────────────────────────┘

  What is passed into prs.save(...)?
      │
      ├─ A hardcoded string path?
      │     │
      │     ├─ Starts with "/sandbox/"? ────────────▶ ✅ PASS
      │     ├─ Not "/"-prefixed (relative path)? ────▶ ✅ PASS
      │     └─ Some other absolute path (e.g. /app/)? ▶ ❌ FAIL
      │
      └─ A variable, e.g. prs.save(output_path)?
            │
            └─ ✅ PASS

Examples:
  prs.save('/sandbox/paper_summaries.pptx')   → starts with /sandbox/ → ✅ PASS
  prs.save('/app/output.pptx')                → absolute path, not /sandbox/ → ❌ FAIL
  prs.save('paper_summaries.pptx')            → relative path → ✅ PASS


┌─────────────────────────────────────────────────────────────────────┐
│  4. import_correct — is the required import present?                 │
└─────────────────────────────────────────────────────────────────────┘

  Does the code contain either of these lines?
      │
      ├─ "from pptx import Presentation" ──┐
      │                                     ├── either one present ──▶ ✅ PASS
      └─ "import pptx" ─────────────────────┘
                                             neither present ──▶ ❌ FAIL

(This check nearly always passes — it's the most common first line in any python-pptx tutorial.)


┌─────────────────────────────────────────────────────────────────────┐
│  overall% — all 4 checks must pass for this generation to count as    │
│  fully correct                                                        │
└─────────────────────────────────────────────────────────────────────┘

  layout✓ + null_guard✓ + save_path✓ + import✓  ──▶ overall = 1 (pass)
  any single ✗                                    ──▶ overall = 0 (fail)
```

</details>

**`overall%`** = 1 only if all 4 checks pass. This is the primary metric.

**Run parameters:**
- N=3 per (model × prompt × test_case)
- Total: 4 prompts × 2 models × 2 test cases × 3 runs = **48 LLM calls**
- N=3 is intentional for a resource-constrained environment (MacBook M1, local inference) — if a model fails 2/3 runs at small N, additional runs won't change the direction

---

## Full Experimental Results

### Full Summary Table

- **Purpose:** Measure per-check and overall correctness across all prompt variants, models, and test cases
- **Expected:** `P2_null_guard` or later achieves `overall% = 100%` for both models on both test cases

**MODEL: `gemma3:4b`**

| prompt | test_case | N | layout% | save% | null% | import% | overall% |
|---|---|---|---|---|---|---|---|
| P0_baseline | TC1_standard | 3 | 0.0 | 33.3 | 100.0 | 100.0 | 0.0 |
| P0_baseline | TC2_with_nulls | 3 | 0.0 | 100.0 | 100.0 | 100.0 | 0.0 |
| P1_layout_pattern | TC1_standard | 3 | 100.0 | 100.0 | 0.0 | 100.0 | 0.0 |
| P1_layout_pattern | TC2_with_nulls | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P2_null_guard | TC1_standard | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P2_null_guard | TC2_with_nulls | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P3_full_pattern | TC1_standard | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |
| P3_full_pattern | TC2_with_nulls | 3 | 100.0 | 100.0 | 100.0 | 100.0 | 100.0 |

**MODEL: `ministral-3:14b-cloud`**

| prompt | test_case | N | layout% | save% | null% | import% | overall% |
|---|---|---|---|---|---|---|---|
| P0_baseline | TC1_standard | 3 | 33.3 | 100.0 | 100.0 | 100.0 | 33.3 |
| P0_baseline | TC2_with_nulls | 3 | 0.0 | 100.0 | 66.7 | 100.0 | 0.0 |
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
| P0_baseline | 91.7 | 16.7 | 8.3 | 0.0 | 12 |
| P1_layout_pattern | 0.0 | 0.0 | 25.0 | 0.0 | 12 |
| P2_null_guard | 0.0 | 0.0 | 0.0 | 0.0 | 12 |
| P3_full_pattern | 0.0 | 0.0 | 0.0 | 0.0 | 12 |

**Conclusion:** The null guard failure at the layout-only prompt is concentrated entirely in the 4B model on non-null data — the same model writes null guards correctly when actual null values are present in the data.

---

## Observations

### Does a text-only instruction fix the layout lookup API misuse?

No — both models default to the wrong API pattern until the prompt includes an explicit lookup pattern, regardless of model size (`gemma3:4b` and `ministral-3:14b-cloud` both go from 0–33% to 100% correctness with the same fix).

### Why does adding the layout pattern alone break the null guard?

A model mimics the style of a partial code example, including what it omits — `gemma3:4b`'s null guard correctness drops from 100% to 0% once a layout example with no null guard is added, recovering only when the test data itself contains null values.

---

## Decision

### Which `SLIDE_GEN_PMT` variant was applied?

`P2_null_guard` (layout lookup + null guard) was chosen by Occam's razor — it matches `P3_full_pattern`'s 100% accuracy without the redundant import-fix tokens, and outperforms `P1_layout_pattern`, which fixes layout selection but introduces the null guard regression.

The validated prompt was never integrated. The ReActAgent approach was replaced before deployment. See Pipeline Integration Status.

---

## Pipeline Integration Status 🚫 SUPERSEDED

The validated prompt was never deployed — `PptxRenderer` replaced the ReActAgent with deterministic rendering from schema-validated JSON after markdown formatting broke on the sandbox path and Exp 10 found the decisive tool-dispatch failure (confirmed 2026-04-15); the key transferable lesson is that a partial code example gets mimicked including its omissions, a risk for any prompt-guided code generation step.
