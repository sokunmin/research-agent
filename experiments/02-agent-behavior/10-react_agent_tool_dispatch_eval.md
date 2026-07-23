# Experiment 10 — ReAct Agent: Conversation-Format Instructions and Error Handling

## Task Context

This experiment targets Step 6 — PPTX Rendering (README → System Architecture), specifically the original ReActAgent-based approach that predates the current deterministic renderer. This is the third of three experiments diagnosing that approach (Exp 8 → Exp 9 → Exp 10): Exp 8 established `gemma3:4b` as the model and fixed whether the ReAct loop invoked its tools at all; Exp 9 fixed the task prompt (`SLIDE_GEN_PMT`) so the model writes correct python-pptx code. This experiment targets the remaining failure layer: the separate instructions that tell the agent how to format its replies and when to stop.

Step 6 is the first step where a rendered PPTX file is produced. If the agent loops infinitely, produces wrong code, or never emits `Answer:`, the entire presentation pipeline halts with no output.

Step 6 — PPTX Rendering (detail, original ReActAgent approach)

```
Step 6 — PPTX Rendering (detail)
────────────────────────────────────────────────────────────────────────────
 slide_outlines.json + PPTX template
       │
       ▼
 ┌─── EXPERIMENT TARGET: REACT_PROMPT_SUFFIX (6 variants tested) ────────┐
 │                                                                       │
 │  ┌─── System prompt (sent once, at the start) ─────────────────────┐  │
 │  │ SLIDE_GEN_PMT (fixed, Exp 9) + REACT_PROMPT_SUFFIX (under test) │  │
 │  └─────────────────────────────────────────────────────────────────┘  │
 │       │                                                               │
 │       ▼                                                               │
 │  ┌─── Tools available to the LLM ──────────────────────────────────┐  │
 │  │ run_code, list_files, upload_file                               │  │
 │  │ Dispatched to a mock sandbox: regex-checks the code,            │  │
 │  │ returns a canned response — no real Docker execution            │  │
 │  └─────────────────────────────────────────────────────────────────┘  │
 │       │                                                               │
 │       ▼                                                               │
 │  ┌─── LLM turn — must match this exact reply format ───────────────┐  │
 │  │ Thought: I need to run the code to generate the slide deck      │  │
 │  │ Action: run_code                                                │  │
 │  │ Action Input: {"code": "prs = Presentation(...) ..."}           │  │
 │  └─────────────────────────────────────────────────────────────────┘  │
 │       │                                                               │
 │       ▼                                                               │
 │  ┌─── LLM reads the tool's response ───────────────────────────────┐  │
 │  │ → loops again, or emits: Answer: Done. ...has been saved.       │  │
 │  └─────────────────────────────────────────────────────────────────┘  │
 │       │                                                               │
 │       ▼                                                               │
 │  ┌─── Normal path (P0–P4) ─────────────────────────────────────────┐  │
 │  │ Code is correct — does the loop end cleanly?                    │  │
 │  │ → terminated% / format_viol%                                    │  │
 │  └─────────────────────────────────────────────────────────────────┘  │
 │                                                                       │
 │  ┌─── Error-handling path (P4 vs P5) ───────────────────────────────┐ │
 │  │ ┌─ Persistent error ─────────────────────┬─ Missing dependency ─┐│ │
 │  │ │ Attempt (1/3) failed. + error message  │ import pptx →        ││ │
 │  │ │ Attempt (2/3) failed. + error message  │ ModuleNotFoundError  ││ │
 │  │ │ Attempt (3/3) failed. LIMIT REACHED.   │                      ││ │
 │  │ │   + error message                      │ → does the model     ││ │
 │  │ │ → does the model give up gracefully,   │   self-heal by       ││ │
 │  │ │   instead of retrying forever?         │   installing it?     ││ │
 │  │ └────────────────────────────────────────┴──────────────────────┘│ │
 │  └──────────────────────────────────────────────────────────────────┘ │
 │                                                                       │
 └───────────────────────────────────────────────────────────────────────┘
       │
       ▼
 paper_summaries.pptx (normal path)  /  Answer: task failed (error path)
```

---

## Summary

- **Problem:** Even after the task prompt was validated to produce correct code, the ReAct loop itself failed independently of code quality — the agent called the code execution tool repeatedly without terminating, hallucinated errors after successful runs, and never emitted a termination signal. The root cause was the separate reply-format instructions, not the task prompt.
- **Solution:** Several versions of those reply-format instructions were tested on two models via a direct LLM call loop with a mock sandbox, isolating their effect from Docker variability.
- **Result:** Correcting a single format example key to match the tool's actual argument name eliminated all failures for the smaller model, with no regression on the larger one. A separate error-path test then showed the smaller model still couldn't reliably follow the ReAct format once real errors occurred — the final evidence behind replacing the whole ReActAgent route with deterministic rendering.

---

## Experiment Setup

**Variables:**

| Name | Role |
|---|---|
| `SLIDE_GEN_PMT` | The task instructions — what files to load, what code patterns to use, where to save output. Held constant at the version validated in Exp 9. |
| `run_code` | Sandbox tool that executes Python code and returns the result. |
| `list_files` | Sandbox tool that lists files in a sandbox directory. |

<details>
<summary>Full text of <code>SLIDE_GEN_PMT</code> (held constant across this experiment)</summary>

````text
You are an AI code executor that generates a PowerPoint slide deck using python-pptx.

Your ONLY job is to write Python code and execute it using the `run_code` tool.
Do NOT explain, describe, or ask the user questions. Just write and execute the code.

Input files already available in the sandbox:
- Slide outlines JSON: `/sandbox/slide_outlines.json` (list of slide outline dicts)
- PPTX template: `/sandbox/pptx-template.pptx`

Steps you MUST follow in order:
1. Use `run_code` to execute python-pptx code that generates the slide deck.
2. Use `list_files` to confirm `paper_summaries.pptx` exists in /sandbox/.
3. If the file does not exist, fix and re-run the code.
4. When `paper_summaries.pptx` is confirmed present, output: "Done. paper_summaries.pptx has been saved."

Requirements for the generated code:
- Load the template from `/sandbox/pptx-template.pptx` using Presentation()
- Load slide data from `/sandbox/slide_outlines.json` using json.load()
- Loop over all items; create one slide per item
- python-pptx layout lookup (add_slide requires a SlideLayout object, NOT a string or int):
    layout = next((l for l in prs.slide_layouts if l.name == item['layout_name']), prs.slide_layouts[0])
    slide  = prs.slides.add_slide(layout)
- Placeholder fill with null guard (idx values may be None for visual-only layouts):
    if item['idx_title_placeholder'] is not None:
        slide.placeholders[item['idx_title_placeholder']].text = item['title']
    if item['idx_content_placeholder'] is not None:
        slide.placeholders[item['idx_content_placeholder']].text = item['content']
- If a placeholder has auto_size=TEXT_TO_FIT_SHAPE, use MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE and do NOT set font size
- If there is no front page or 'thank you' slide, add them using the appropriate layout
- Save the final file as `/sandbox/paper_summaries.pptx` using prs.save()

CRITICAL: You MUST use `run_code` to actually execute the code. Do not output code as text only.
CRITICAL: Task is complete only when `list_files` confirms `paper_summaries.pptx` exists.
````

</details>

**Code correctness checks (same as Exp 9):**

| Check | Measures |
|---|---|
| `layout_lookup_correct` | The model looks up the matching layout object by name, instead of passing a layout name or index directly |
| `null_guard_correct` | The code guards against a null placeholder index before writing to it |
| `save_path_correct` | The output file is saved to the expected sandbox directory |
| `import_correct` | The required library import is present |

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
  └────────────────────────────────────────────────────┘
      │
      ▼
  ┌─ Check B: contains ".add_slide(variable)"? ────────┐
  │  slide = prs.slides.add_slide(layout)              │  ✓ yes (layout is a variable)
  └────────────────────────────────────────────────────┘
      │
      ▼
  ┌─ Check C: contains a ".name ==" comparison? ───────┐
  │  if l.name == item['layout_name']                  │  ✓ yes
  └────────────────────────────────────────────────────┘
      │
      ▼
  ┌─ Check D: does add_slide("string") or add_slide(number) appear? ─┐
  │  (does not appear)                                               │  ✓ no → good
  └──────────────────────────────────────────────────────────────────┘
      │
      ▼
  A✓ + B✓ + C✓ + D(absent) ──▶ ✅ PASS

Counter-example:
  slide = prs.slides.add_slide("TITLE_AND_BODY")
        │
        ▼
  Hits check D (string passed directly) ──▶ ❌ FAIL


┌─────────────────────────────────────────────────────────────────────┐
│  2. null_guard_correct — is there a null check before writing?      │
└─────────────────────────────────────────────────────────────────────┘

generated code string
      │
      ├─ Contains the string "is not None"? ──── ✓/✗
      │
      ├─ Contains the string "placeholders["? ── ✓/✗
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
│  3. save_path_correct — was the file saved to the right path?       │
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
│  4. import_correct — is the required import present?               │
└─────────────────────────────────────────────────────────────────────┘

  Does the code contain either of these lines?
      │
      ├─ "from pptx import Presentation" ──┐
      │                                    ├── either one present ──▶ ✅ PASS
      └─ "import pptx" ────────────────────┘
                                             neither present ──▶ ❌ FAIL

(This check nearly always passes — it's the most common first line in any python-pptx tutorial.)


┌─────────────────────────────────────────────────────────────────────┐
│  overall% — all 4 checks must pass for this generation to count as  │
│  fully correct                                                      │
└─────────────────────────────────────────────────────────────────────┘

  layout✓ + null_guard✓ + save_path✓ + import✓  ──▶ overall = 1 (pass)
  any single ✗                                    ──▶ overall = 0 (fail)
```

</details>

**Models:**

| Label | Model string |
|---|---|
| `gemma3:4b` | `ollama/gemma3:4b` |
| `ministral-3:14b-cloud` | `ollama/ministral-3:14b-cloud` |

**Reply-format instruction variants (normal path):**

| Name | What it does differently |
|---|---|
| `P0_baseline` | The original, unchanged instructions — includes a competing rule that tells the model to write bullet-point explanations, plus a vague "keep going" instruction with no clear stop condition. |
| `P1_termination_guard` | Adds one explicit rule: stop as soon as the output file is confirmed to exist. |
| `P2_simplified` | Removes the competing bullet-point rule, and replaces "keep going" with "use the fewest tool calls possible." |
| `P3_combined` | Combines `P2_simplified`'s simplification with `P1_termination_guard`'s explicit stop instruction. |
| `P4_example_fix` | Takes `P2_simplified` and fixes the one concrete bug: the example shown to the model used the wrong argument name for the code-execution tool. |

**Reply-format instruction variants (error handling):**

| Name | What it does differently |
|---|---|
| `P4_example_fix` | The normal-path winner, used unchanged as the control condition for these error tests. |
| `P5_stop_on_failure` | Adds one more rule: if the sandbox reports the retry limit has been reached, stop immediately and report failure instead of trying again. |

**Run parameters:** N=3, MAX_TURNS=10, temperature=0. N=3 is intentional for a resource-constrained environment (MacBook M1, local inference): if a model fails 2/3 runs at small N, additional runs won't change the direction. The goal is a fast failure signal, not statistical precision.

---

## Full Experimental Results

### Which reply-format instruction variant gets both models to finish cleanly?

- **Purpose:** Compare all 5 reply-format instruction variants across both models, 3 runs each
- **Expected:** At least one variant reaches a clean finish on both models every time

| Variant | `gemma3:4b` | `ministral-3:14b-cloud` |
|---|:---:|:---:|
| `P0_baseline` | ❌ 0/3 | ✅ 3/3 |
| `P1_termination_guard` | ❌ 0/3 | ✅ 3/3 |
| `P2_simplified` | ❌ 0/3 | ✅ 3/3 |
| `P3_combined` | ❌ 0/3 | ⚠️ 2/3 |
| `P4_example_fix` | ✅ 3/3 | ✅ 3/3 |

✅ = finished cleanly every run. ⚠️ = finished cleanly some runs. ❌ = never finished cleanly.

**Conclusion:** Only `P4_example_fix` gets a clean finish from both models every time — everything before it either fails outright on the smaller model or, in one case, destabilizes the larger one.

### Does an explicit "give up" instruction help under persistent errors?

- **Purpose:** Test whether models correctly give up, rather than retry forever, when every code execution attempt returns the same unrecoverable error
- **Expected:** The give-up instruction raises correct, graceful failure reporting for both models

| Variant | `gemma3:4b` | `ministral-3:14b-cloud` |
|---|:---:|:---:|
| `P4_example_fix` (no give-up rule) | ❌ 0/3 | ⚠️ 1/3 |
| `P5_stop_on_failure` | ❌ 0/3 | ✅ 3/3 |

✅ = gave up correctly every run. ⚠️ = gave up correctly some runs. ❌ = never gave up correctly (broke reply format instead).

**Conclusion:** The give-up instruction works for the larger model but doesn't help the smaller one — which breaks its reply format even faster once the instruction is added.

### Can the models recover from a missing dependency?

- **Purpose:** Test whether models self-diagnose a missing-package error, install it, and complete the task
- **Expected:** Model installs the dependency and finishes the task

| Variant | `gemma3:4b` | `ministral-3:14b-cloud` |
|---|:---:|:---:|
| `P4_example_fix` | ✅ 3/3 completed | ❌ 0/3 completed |

Both models diagnose and install the missing package correctly every time — the difference is only in finishing afterward.

**Conclusion:** The smaller model follows through to a finished file every time; the larger model installs the dependency correctly but runs out of turns before finishing.

### How predictable is the tool-call cost of this rendering stage?

- **Purpose:** Compare how many tool calls the same rendering stage takes once fixed, versus when an error occurs
- **Expected:** If the architecture is reliable, tool-call counts should stay close to the fixed baseline regardless of condition

| Condition | Model | Tool calls per run |
|---|---|---|
| Normal path | both models | 2 — baseline |
| Persistent execution error | `gemma3:4b` | 9 |
| Persistent execution error | `ministral-3:14b-cloud` | 2.3 |
| Current pipeline (deterministic renderer) | — | 0 |

**Conclusion:** Once fixed, the normal path costs 2 tool calls — but a persistent error alone can push that up to 4.5x for the smaller model, with no guarantee of ever finishing. The deterministic renderer that replaced this stage needs zero calls regardless of condition.

---

## Observations

### How predictable is the cost of generating code with an LLM in a loop?

Not predictable at all — the same rendering task can take anywhere from 2 to 17 tool calls depending on the model and whether errors occur, and swapping to a different model narrows this range but doesn't eliminate it.
- `qwen3.5:4b` needed 16 tool calls to do what `gemma3:4b` did in 1 (Exp 8); in this experiment, a persistent execution error alone pushed `gemma3:4b`'s call count up to 9, with no clean exit.

### Does an explicit give-up instruction help a model recognize an unrecoverable error?

For the larger model, yes — for the smaller model, no amount of prompting helps once errors start.
- `ministral-3:14b-cloud`: the give-up instruction, keyed on a "limit reached" signal, raises correct graceful termination from 33.3% to 100%.
- `gemma3:4b`: fails to follow the ReAct format under error conditions with or without the give-up instruction — the variant with it breaks format at turn 1 instead of turn 10, before ever reaching the signal it was designed to detect.

---

## Decision

### Why was the entire ReActAgent approach abandoned after three experiments?

Exp 8 through Exp 10 fixed tool invocation, code correctness, and conversation format one layer at a time — each layer was solvable with prompt engineering. But two problems remained that no prompt fix or model swap could close: generating code with an LLM in a loop has an unpredictable retry cost (the same rendering task ranged from 2 to 17 tool calls depending on model and error conditions), and even the more reliable model still couldn't guarantee a clean recovery under every error condition. That's why the whole ReActAgent-plus-sandbox approach was replaced rather than patched further.

---

## Pipeline Integration Status 🚫 SUPERSEDED

The validated fix was never deployed. The agent-writes-code-and-runs-it-in-a-sandbox approach was replaced with a deterministic renderer: the LLM still produces the slide content and layout choices as JSON, but a fixed piece of code — not the LLM — turns that JSON into the final PPTX file, with no sandbox and no runtime code generation. This removes the entire class of failures this experiment series investigated (wrong code, stuck loops, broken formatting), and separately fixed a rendering bug the sandbox approach couldn't avoid (LLM-generated bullet text losing its formatting once written directly to PPTX).
