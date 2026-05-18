# Experiment 10 — ReAct Agent: How a Prompt Example Key Breaks Tool Dispatch in 4B Models

## Task Context

This experiment targets Step 6 — PPTX Rendering (README → System Architecture), specifically the original ReActAgent-based approach that predates the current deterministic renderer. This is the third in a three-part diagnostic chain (Exp 7 → Exp 8 → Exp 9). Exp 7 established gemma3:4b as the model. Exp 8 fixed the task prompt (`SLIDE_GEN_PMT`) to achieve 100% code generation correctness. This experiment targets the remaining failure layer: tool dispatch mechanics controlled by `REACT_PROMPT_SUFFIX`.

```
Input: slide_outlines.json (List[SlideOutlineWithLayout])    ← Step 5: outlines_with_layout
      │
      ▼
┌── 6. PPTX RENDERING ──────────────────────────────────────────────────────────────┐
├─── Original (lz-chen) ───────────────────┬─── My Implementation ──────────────────┤
│ ReActAgent + Docker sandbox              │ PptxRenderer (deterministic)           │
│ LLM writes python-pptx code at runtime  │ JSON → PPTX directly, no LLM          │
│ Agent runs code via run_code tool        │ No sandbox, no loop                   │
└──────────────────────────────────────────┴────────────────────────────────────────┘
      │
      ▼
Output: paper_summaries.pptx                                 → Step 7: validate_slides
```

Step 6 is the first step where a rendered PPTX file is produced. If the agent loops infinitely, produces wrong code, or never emits `Answer:`, the entire presentation pipeline halts with no output.

**Variable names defined here:**
- `SLIDE_GEN_PMT` — task instruction: what files to load, what python-pptx patterns to use, where to save output
- `REACT_PROMPT_SUFFIX` — ReAct format control: Thought/Action/Observation loop structure, termination instructions
- `system_prompt = SLIDE_GEN_PMT + REACT_PROMPT_SUFFIX`
- `run_code(code: str)` — tool that executes Python in the Docker sandbox
- `list_files(remote_dir: str)` — tool that lists sandbox directory contents
- `MockSandbox` — deterministic sandbox used in this experiment: correct code → success + file created; wrong code → realistic error string
- `CodeEvaluator` — regex checker for 4 code correctness criteria applied to the first `run_code` argument

Step 6 — PPTX Rendering (detail, original ReActAgent approach)

```
Step 6 — PPTX Rendering (detail)
──────────────────────────────────────────────────────────────────
 slide_outlines.json + PPTX template
       │
       ▼
 ┌─── EXPERIMENT TARGET ──────────────────────────────────────────┐
 │                                                                │
 │  ① [slide_gen]   ← REACT_PROMPT_SUFFIX under test             │
 │     ReActAgent · SLIDE_GEN_PMT (P2, fixed)                    │
 │     REACT_PROMPT_SUFFIX: 6 variants (P0–P5)                    │
 │     Tools: run_code, list_files, upload_file                   │
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

- **Problem:** In the original slide generation step, even after the task prompt was validated at P2 level, the ReAct loop itself failed independently of code quality.
  - Pre-fix logs: the agent called the code execution tool 20+ times without terminating, hallucinated errors after successful runs, and never emitted a termination signal.
  - Root cause: the format suffix template — not the task prompt.
- **Solution:** A direct LLM call loop with MockSandbox (no Docker, deterministic) — isolates the suffix text effect from Docker variability.
  - 5 normal-path suffix variants + 2 error-path variants across 2 models, N=3 runs, MAX_TURNS=10.
  - CodeEvaluator with 4 regex checks independently verified code correctness on the first tool call.
- **Result:** Correcting the format example key to match the tool's actual argument name — a one-line change — eliminated all failures for gemma3:4b (0% → 100% task completion, 100% → 0% format violation) with no regression for ministral.
  - The error-path findings (gemma3:4b fails under persistent errors regardless of suffix) were the final evidence confirming the switch to deterministic rendering.

---

## Experiment Setup

No ✅ markers apply to this experiment — the ReActAgent step was superseded before any prompt variant was integrated into the pipeline. See Pipeline Integration Status.

**Objective:**
- **Problem:** lz-chen's `REACT_PROMPT_SUFFIX` (P0_baseline) caused `format_viol% = 100%` for gemma3:4b — the agent violated the ReAct format at turn 1 before dispatching any tool. Pre-fork Docker logs also showed infinite `run_code` retry loops independent of code quality.
- **Goal:** Identify which element of `REACT_PROMPT_SUFFIX` controls reliable loop termination and correct tool dispatch for both test models, using MockSandbox to isolate the suffix effect from Docker variability.
- **Pass condition:** `terminated% = 100%` and `format_viol% = 0%` for both models across all 3 runs.

**Method:**
- Direct `litellm.completion()` loop (no LlamaIndex ReActAgent wrapper) — isolates suffix text effect
- MockSandbox: deterministic; correct code → success + file created; wrong code → realistic `AttributeError`
- CodeEvaluator: 4 regex checks applied to the first `run_code` call's code argument (layout lookup, save path, null guard, import)
- `SLIDE_GEN_PMT` held constant at P2 (validated in a prior experiment to produce correct code when the tool receives it)

**Models:**

| Label | Model string |
|---|---|
| gemma3:4b | ollama/gemma3:4b |
| ministral-3:14b-cloud | ollama/ministral-3:14b-cloud |

**Normal-path suffix variants (suffix engineering and example key fix):**

*Prompt text for each variant — the sections that differ across variants are annotated inline:*

<details>
<summary><strong>P0_baseline</strong> — lz-chen's original REACT_PROMPT_SUFFIX (verbatim)</summary>

````text
## Tools
You have access to a wide variety of tools. You are responsible for using
the tools in any sequence you deem appropriate to complete the task at hand.
This may require breaking the task into subtasks and using different tools
to complete each subtask.

You have access to the following tools:
{tool_desc}

## Output Format
To answer the question, please use the following format.

```
Thought: I need to use a tool to help me answer the question.
Action: tool name (one of {tool_names}) if using a tool.
Action Input: the input to the tool, in a JSON format representing the kwargs
              (e.g. {"input": "hello world", "num_beams": 5})
```

Please ALWAYS start with a Thought.

Please use a valid JSON format for the Action Input. Do NOT do this {'input': 'hello world', 'num_beams': 5}.

If this format is used, the user will respond in the following format:

```
Observation: tool response
```

You should keep repeating the above format until you have enough information
to answer the question without using any more tools. At that point, you MUST respond
in the one of the following two formats:

```
Thought: I can answer without using any more tools.
Answer: [your answer here]
```

```
Thought: I cannot answer the question with the provided tools.
Answer: Sorry, I cannot answer your query.
```

## Additional Rules
- The answer MUST contain a sequence of bullet points that explain how you arrived at the answer.
  This can include aspects of the previous conversation history.
- You MUST obey the function signature of each tool. Do NOT pass in no arguments if the function expects arguments.

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
````

</details>

<details>
<summary><strong>P1_termination_guard</strong> — P0 + explicit stop rule after file confirmed</summary>

````text
## Tools / ## Output Format / ## Additional Rules
(identical to P0 — example key still: {"input": "hello world", "num_beams": 5}
 loop instruction still: "You should keep repeating the above format")

## Critical Termination Rule        ← ADDED vs P0
Once list_files confirms that `paper_summaries.pptx` exists in `/sandbox/`,
you MUST IMMEDIATELY output the following and STOP:
  Thought: The file has been confirmed. Task is complete.
  Answer: Done. paper_summaries.pptx has been saved.
Do NOT call any more tools after this confirmation.
Do NOT re-run the code. Do NOT call list_files again.
Trust the Observation. If it says the file exists, it exists.

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
````

</details>

<details>
<summary><strong>P2_simplified</strong> — removed competing instruction + tighter loop wording</summary>

````text
## Tools
(identical to P0)

## Output Format
To answer the question, please use the following format.

```
Thought: I need to use a tool to help me answer the question.
Action: tool name (one of {tool_names}) if using a tool.
Action Input: the input to the tool, in a JSON format representing the kwargs
              (e.g. {"input": "hello world", "num_beams": 5})   ← example key still wrong: "input"
```

Please ALWAYS start with a Thought.

Please use a valid JSON format for the Action Input. Do NOT do this {'input': 'hello world', 'num_beams': 5}.

If this format is used, the user will respond in the following format:

```
Observation: tool response
```

Use the minimum number of tool calls needed. Stop as soon as the goal is achieved.  ← CHANGED vs P0
At that point, you MUST respond in the one of the following two formats:

```
Thought: I can answer without using any more tools.
Answer: [your answer here]
```

```
Thought: I cannot answer the question with the provided tools.
Answer: Sorry, I cannot answer your query.
```

## Additional Rules     ← REMOVED vs P0 (entire section gone)

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
````

</details>

<details>
<summary><strong>P3_combined</strong> — P2 simplifications + P1 termination guard</summary>

````text
## Tools / ## Output Format
(same as P2 — "minimum tool calls" wording, example key still: {"input": "hello world", "num_beams": 5})

## Additional Rules     ← REMOVED (same as P2)

## Critical Termination Rule        ← ADDED (same as P1)
Once list_files confirms that `paper_summaries.pptx` exists in `/sandbox/`,
you MUST IMMEDIATELY output the following and STOP:
  Thought: The file has been confirmed. Task is complete.
  Answer: Done. paper_summaries.pptx has been saved.
Do NOT call any more tools after this confirmation.
Do NOT re-run the code. Do NOT call list_files again.
Trust the Observation. If it says the file exists, it exists.

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
````

</details>

<details>
<summary><strong>P4_example_fix</strong> — P2 + corrected example key</summary>

````text
## Tools
(identical to P0)

## Output Format
To answer the question, please use the following format.

```
Thought: I need to use a tool to help me answer the question.
Action: tool name (one of {tool_names}) if using a tool.
Action Input: the input to the tool, in a JSON format representing the kwargs
              (e.g. {"code": "print('hello')"} for run_code,
                    {"remote_dir": "/sandbox"} for list_files)   ← CHANGED vs P2: key matches tool signature
```

Please ALWAYS start with a Thought.

Please use a valid JSON format for the Action Input. Do NOT do this {'input': 'hello world', 'num_beams': 5}.

If this format is used, the user will respond in the following format:

```
Observation: tool response
```

Use the minimum number of tool calls needed. Stop as soon as the goal is achieved.  ← same as P2

## Additional Rules     ← REMOVED (same as P2)

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
````

</details>

| ID | Description | Key changes from P0_baseline |
|---|---|---|
| P0_baseline | lz-chen's original suffix (verbatim) | Control — no changes |
| P1_termination_guard | P0 + explicit stop after `list_files` confirms file | Added `## Critical Termination Rule`; example key and `## Additional Rules` unchanged |
| P2_simplified | Removed `## Additional Rules`; "keep repeating" → "minimum tool calls" | Removes competing instruction; example key still `{"input": "hello world", "num_beams": 5}` |
| P3_combined | P2 + P1's `## Critical Termination Rule` | Both simplification and explicit stop rule |
| P4_example_fix | P2 + corrected example key | Example changed to `{"code": "print('hello')"} for run_code, {"remote_dir": "/sandbox"} for list_files` |

**Error-path suffix variants (error behavior sub-experiment):**

| ID | Description |
|---|---|
| P4_example_fix | Normal-path winner; used as control for error scenarios |
| P5_stop_on_failure | P4 + `## Critical Stop Rule`: emit `Answer:` immediately on seeing "LIMIT REACHED" in any Observation |

**Metrics:**

| Metric | Definition | Notes |
|---|---|---|
| `terminated%` | Agent emitted `Answer:` before MAX_TURNS exhausted | Primary — 100% = clean loop exit |
| `format_viol%` | Agent produced neither parseable `Action:` nor `Answer:` | Primary — 0% = format compliance |
| `first_correct%` | First `run_code` call passed all 4 CodeEvaluator checks | 100% = no wasted retry turns |
| `avg_turns` | Mean LLM calls per run (capped at MAX_TURNS) | Efficiency |
| `avg_tool_calls` | Mean tool dispatches per run | Efficiency |
| `loops%` | Any tool call dispatched after `list_files` already confirmed file | Loop detection |
| `hallucinated%` | Agent's response contained failure keywords (`error`, `fail`, `not found`, `invalid`, `wrong`) in the turn immediately after a successful `run_code` Observation | Hallucination detection (keyword match) |

**CodeEvaluator checks (all 4 must pass for `first_correct% = 100%`):**

| Check | What it verifies |
|---|---|
| `layout_lookup_correct` | Code uses `slide_layouts` name comparison and `add_slide(variable)` |
| `save_path_correct` | Code calls `prs.save()` with `/sandbox/` path |
| `null_guard_correct` | Code checks `idx is not None` before `slide.placeholders[idx]` |
| `import_correct` | Code imports `Presentation` from `pptx` |

**Error sub-experiment sandboxes:**

| Sandbox | Behavior |
|---|---|
| `PersistentErrorSandbox` | Every `run_code` returns `AttributeError` + attempt counter. Appends "LIMIT REACHED" at attempt 3. `list_files` always returns "(no files in /sandbox)". |
| `ModuleNotFoundSandbox` | `import pptx` without install → `ModuleNotFoundError`. `!pip install` → `SyntaxError`. `pip install` or `subprocess` pip → success + sets `_pptx_installed = True`. Subsequent slide code → unconditional success. |

**Run parameters:** N=3, MAX_TURNS=10, temperature=0. N=3 is intentional for a resource-constrained environment (MacBook M1, local inference): if a model fails 2/3 runs at small N, additional runs won't change the direction. The goal is a fast failure signal, not statistical precision.

---

## Full Experimental Results

### Suffix engineering — P0 through P3 variants

- **Purpose:** Establish the baseline and measure whether loop instruction changes (removing `## Additional Rules`, changing termination wording) resolve the failure without touching the example key
- **Expected:** At least one variant achieves `terminated% = 100%` and `format_viol% = 0%` for both models

#### gemma3:4b

| Variant | terminated% | avg_turns | avg_tool_calls | loops% | first_correct% | hallucinated% | format_viol% |
|---|---|---|---|---|---|---|---|
| P0_baseline | 0.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 |
| P1_termination_guard | 0.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 |
| P2_simplified | 0.0 | 9.0 | 8.0 | 0.0 | 0.0 | 0.0 | 100.0 |
| P3_combined | 0.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 |

- P0/P1/P3: `avg_tool_calls = 0.0` — the model never dispatches a single tool call; format violation fires at turn 1 with prose or a markdown code block.
- P2: `avg_tool_calls = 8.0` — model dispatches tools but `first_correct% = 0%`. The format example `{"input": "hello world"}` causes the model to pass `"input"` as the JSON key. `run_code(code: str)`: `kwargs.get("code", "")` returns empty string → all 4 CodeEvaluator checks fail → MockSandbox always returns `AttributeError`. After 8 identical failed calls the model breaks format at turn 9.

#### ministral-3:14b-cloud

| Variant | terminated% | avg_turns | avg_tool_calls | loops% | first_correct% | hallucinated% | format_viol% |
|---|---|---|---|---|---|---|---|
| P0_baseline | 100.0 | 3.0 | 2.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| P1_termination_guard | 100.0 | 3.0 | 2.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| P2_simplified | 100.0 | 3.0 | 2.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| P3_combined | 66.7 | 4.0 | 3.0 | 0.0 | 66.7 | 0.0 | 33.3 |

- P0/P1/P2: `terminated% = 100%` in exactly 3 turns — `run_code` → `list_files` → `Answer:`. Ministral reads the tool parameter description (`code: str`) correctly despite the wrong example key; `first_correct% = 100%`.
- P3: `terminated% = 66.7%`, `format_viol% = 33.3%`. Adding the `## Critical Termination Rule` on top of P2's "minimum tool calls" creates two competing termination signals. 1/3 runs produces a malformed response at turn 6.

**Conclusion:** No P0–P3 variant achieves the pass condition for gemma3:4b — the wrong example key keeps first_correct% at 0% even when tool dispatch is unblocked, and P3 introduces a regression in ministral.

### Example key fix — P4 variant

- **Purpose:** Test whether correcting the format example key from `{"input": "hello world"}` to `{"code": "print('hello')"}` resolves gemma3:4b without regressing ministral
- **Expected:** Both models reach `terminated% = 100%`, `format_viol% = 0%`

| Model | terminated% | avg_turns | avg_tool_calls | loops% | first_correct% | hallucinated% | format_viol% |
|---|---|---|---|---|---|---|---|
| gemma3:4b | 100.0 | 3.0 | 2.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| ministral-3:14b-cloud | 100.0 | 3.0 | 2.0 | 0.0 | 100.0 | 0.0 | 0.0 |

**Conclusion:** P4 meets the pass condition for both models — correcting the example key alone resolves all gemma3:4b failures with no regression in ministral.

### Delta summary (gemma3:4b only — ministral unchanged by P4)

| Variant | terminated% | first_correct% | format_viol% | avg_turns |
|---|---|---|---|---|
| P2_simplified | 0% | 0% | 100% | 9.0 |
| P4_example_fix | 100% | 100% | 0% | 3.0 |

**Conclusion:** Correcting the example key moves gemma3:4b from complete failure to the same performance profile as ministral — a single-line change with no regressions.

### Error behavior sub-experiment — Scenario A: Persistent Error

- **Purpose:** Test whether models avoid infinite loops when every `run_code` returns a persistent unrecoverable error. P5 adds a `## Critical Stop Rule` keyed on the "LIMIT REACHED" signal appended to the Observation at attempt 3.
- **Expected:** Models emit `Answer:` with a failure message after 3 failed attempts; `gave_up_correctly% = 100%`, `format_viol% = 0%`.

| Model | Prompt | terminated% | gave_up_correctly% | hallucinated_success% | reached_max_turns% | format_viol% | avg_turns | avg_tool_calls |
|---|---|---|---|---|---|---|---|---|
| gemma3:4b | P4 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 10.0 | 9.0 |
| gemma3:4b | P5 | 0.0 | 0.0 | 0.0 | 0.0 | 100.0 | 1.0 | 0.0 |
| ministral-3:14b-cloud | P4 | 33.3 | 33.3 | 0.0 | 0.0 | 33.3 | 3.0 | 2.3 |
| ministral-3:14b-cloud | P5 | 100.0 | 100.0 | 0.0 | 0.0 | 0.0 | 3.0 | 2.0 |

Note: `reached_max_turns% = 0%` for all conditions. gemma3:4b P4 ran 9 tool calls and broke via format violation at turn 10 — it did not exhaust MAX_TURNS without any exit. In the pipeline with a higher MAX_TURNS limit this pattern would approach an infinite loop.

**Conclusion:** P5 resolves ministral's error-path termination (33.3% → 100% gave_up_correctly) — gemma3:4b fails under both suffixes due to format violation, requiring a code-level guard rather than a prompt fix.

### Error behavior sub-experiment — Scenario B: Missing Dependency

- **Purpose:** Test whether models self-diagnose `ModuleNotFoundError: No module named 'pptx'`, generate a correct pip install command, and then complete slide generation. `TOOL_DESC_NO_PPTX_CLAIM` is used (removes the "python-pptx is pre-installed" claim from the tool description).
- **Expected:** Model issues correct pip syntax at an early turn, then completes the task; `task_done% = 100%`.

| Model | Prompt | correct_pip% | jupyter_pip% | task_done% | terminated% | avg_turns | avg_tool_calls | avg_pip_turn |
|---|---|---|---|---|---|---|---|---|
| gemma3:4b | P4 | 100.0 | 0.0 | 100.0 | 100.0 | 5.0 | 4.0 | 2.0 |
| ministral-3:14b-cloud | P4 | 100.0 | 33.3 | 0.0 | 0.0 | 3.3 | 2.3 | 2.3 |

Note on ministral `jupyter_pip% = 33.3%`: 1/3 runs generated `subprocess.check_call([sys.executable, '-m', 'pip', ...])` — functionally valid Python, not Jupyter `!pip` syntax. The detection regex fired a false positive. True `!pip` was not generated by either model. The subprocess form was accepted by the sandbox as a correct install.

**Conclusion:** gemma3:4b fully recovers after self-installing the missing dependency — ministral diagnoses and installs correctly but does not complete slide generation within the turn budget.

---

## Observations

### Format violation root cause and the P2 partial fix

```
P0 → gemma3:4b format_viol% = 100%, avg_tool_calls = 0.0
      │
      ▼
Root cause: ## Additional Rules contains a competing instruction
  "The answer MUST contain a sequence of bullet points that explain
   how you arrived at the answer."
      │  This instruction is scoped to the final Answer: in a Q&A context.
      │  A 4B model cannot scope it — applies bullet-point format everywhere.
      │  → First response is bullet-point prose, not a Thought/Action: line.
      │  → Loop driver receives no parseable Action: → format_viol = True.
      │
      ├─ P1 (adds ## Critical Termination Rule on top of P0)
      │    No change: ## Additional Rules still present.
      │    Format violation still fires at turn 1 before any tool dispatch.
      │    avg_turns = 1.0, avg_tool_calls = 0.0 — identical to P0.
      │
      └─ P2 (removes ## Additional Rules, "keep repeating" → "minimum tool calls")
           Competing instruction removed.
           → gemma3:4b now dispatches tools: avg_tool_calls = 8.0
           → BUT first_correct% = 0%, format_viol% = 100% at turn 9
                 │
                 ▼
           Why first_correct% = 0%?
             Format example still: {"input": "hello world", "num_beams": 5}
             Model generates: Action Input: {"input": "<code>"}
             run_code(code: str): kwargs.get("code", "") → ""
             CodeEvaluator receives empty string → all 4 checks fail
             MockSandbox returns AttributeError every call
             → 8 identical failed calls → format violation at turn 9
```

**Conclusion:** Removing the competing instruction is necessary but not sufficient — P2 unblocks tool dispatch but the wrong example key causes every tool call to pass an empty argument.
P2 unblocks tool dispatch for gemma3:4b but does not fix the key name. The model iterates 8 times seeing the same error. The wrong key produces an empty code argument on every call — the loop is structurally non-self-correcting for this failure mode.

### P4 — one-line fix resolves the key problem

```
P2 → gemma3:4b dispatches tools but first_correct% = 0% due to wrong key "input"
      │
      ▼
Root cause: n-gram prior from the format example overrides the tool signature
  Example: {"input": "hello world", "num_beams": 5}
      │
      │  In a causal language model, generating the token sequence '{"'
      │  is immediately followed by the key token. The few-shot example
      │  gives '{"' → 'input' a strong prior at that decision point.
      │  A 4B model pattern-matches the example key rather than reading
      │  "code: str" from the tool description text — which appears
      │  earlier in the context and receives lower attention weight
      │  at the moment of key generation.
      │
      ▼
P4: example changed to {"code": "print('hello')"} for run_code
  → '{"' → 'code' becomes the dominant prior for the run_code context
  → First run_code call passes all 4 CodeEvaluator checks
  → MockSandbox returns success → model calls list_files → Answer:
  → gemma3:4b: terminated% 0% → 100%, format_viol% 100% → 0%,
               first_correct% 0% → 100%, avg_turns 9.0 → 3.0
  → ministral: unchanged at 100% (14B reads tool signature regardless of example)
```

**Conclusion:** The fix is a single-line change to the format example key.
P4 is P2 with only the example key name changed. Ministral (14B) reads the tool parameter description correctly under both the old and new example. This confirms that key sensitivity is specific to smaller models.

### P3 — instruction over-specification causes regression in ministral

P3 combines P2's "minimum tool calls" wording with P1's explicit `## Critical Termination Rule`. Ministral terminates cleanly in 3 turns under P0/P1/P2 with no ambiguity. P3 introduces two competing termination signals: one implicit ("stop when goal is achieved"), one specifying an exact expected output string. For 1/3 runs, ministral attempts to reconcile both and produces a malformed response at turn 6 (`format_viol% = 33.3%`). A more specific redundant constraint added on top of a sufficient one creates ambiguity rather than precision.

### Error scenarios — gemma3:4b cannot follow ReAct format under any error condition

```
Scenario A: PersistentErrorSandbox — every run_code returns AttributeError
      │
      ├─ gemma3:4b P4 (no stop rule)
      │    Normal path: terminated% = 100%, avg_tool_calls = 2.0
      │    Error path:  format_viol% = 100%, avg_tool_calls = 9.0, avg_turns = 10.0
      │    → Under persistent error, model loops 9 tool calls then breaks format
      │    → Production with higher MAX_TURNS would approach infinite loop
      │
      ├─ gemma3:4b P5 (## Critical Stop Rule on "LIMIT REACHED")
      │    format_viol% = 100%, avg_tool_calls = 0.0, avg_turns = 1.0
      │    → P5 text itself disrupts format compliance before any tool dispatch
      │    → Model produces 0 tool calls — breaks at turn 1 worse than P4
      │    → Prompt engineering cannot solve persistent-error behavior for 4B models
      │
      ├─ ministral P4 (no stop rule)
      │    terminated% = 33.3%, gave_up_correctly% = 33.3%, format_viol% = 33.3%
      │    → Inconsistent: 1/3 graceful exit, 1/3 format violation, 1/3 mixed
      │
      └─ ministral P5 (## Critical Stop Rule)
           terminated% = 100%, gave_up_correctly% = 100%, format_viol% = 0%
           avg_turns = 3.0, avg_tool_calls = 2.0
           → "LIMIT REACHED" keyword directly triggers Answer: with failure message
           → Efficiency identical to normal path — no overhead from stop rule
```

**Conclusion:** gemma3:4b's format compliance is conditional on the success path — P5 worsens first-turn behavior in error scenarios, requiring a code-level guard rather than a prompt fix.
A code-level guard — enforcing a hard abort after N identical errors in the loop driver, independently of the model — is required for gemma3:4b on the error path.

### Scenario B — smaller model outperforms larger on self-recovery

Both models correctly diagnose `ModuleNotFoundError` and issue `pip install python-pptx` at turn 2 (`correct_pip% = 100%`). The recovery paths diverge after the install:

- gemma3:4b proceeds immediately to slide generation, calls `list_files`, confirms the file, and emits `Answer:` — `task_done% = 100%` in 5 turns.
- ministral issues the install but does not complete slide generation within the 3.3-turn average — `task_done% = 0%`, `terminated% = 0%`.

This reversal of the normal-path pattern (where ministral is more reliable) may be confounded by turn budget: ministral's 3-turn pattern on the normal path leaves little slack for an extra install step. A higher MAX_TURNS for this scenario would clarify whether this is a model capability gap or a budget constraint.

---

## Decision

### Which REACT_PROMPT_SUFFIX for the normal slide generation path?

```
Decision: Which suffix enables reliable ReAct tool dispatch for slide_gen?
      │
      ├── P0_baseline (lz-chen's original, verbatim)
      │     ✗ ## Additional Rules blocks gemma3:4b format compliance at turn 1
      │     ✗ "keep repeating" encourages looping even after success
      │     → REJECTED
      │
      ├── P1_termination_guard (P0 + explicit file-confirmed stop rule)
      │     ✗ ## Additional Rules unchanged — same format violation as P0
      │     ✗ Adds over-specification on top of a broken baseline
      │     → REJECTED
      │
      ├── P2_simplified (removed ## Additional Rules + "keep repeating")
      │     ✓ Unblocks gemma3:4b tool dispatch
      │     ✗ Wrong example key "input" → first_correct% = 0% for gemma3:4b
      │     → REJECTED (necessary first step; insufficient alone)
      │
      ├── P3_combined (P2 + P1 termination guard)
      │     ✗ Competing termination signals regress ministral (33.3% format_viol)
      │     ✗ Same key failure as P2 for gemma3:4b
      │     → REJECTED
      │
      └── P4_example_fix (P2 + corrected example key)
            ✓ terminated% = 100%, format_viol% = 0% for both models
            ✓ first_correct% = 100% — no wasted retry turns
            ✓ avg_turns = 3.0 for both models
            △ Does not help gemma3:4b under persistent error conditions
            → CHOSEN: one-line fix, no regressions on either model
```

### Which suffix for persistent error handling?

```
Decision: Which suffix when run_code returns unrecoverable errors?
      │
      ├── P4 (no stop rule)
      │     ✗ ministral: 33.3% reliable termination, 33.3% format_viol — insufficient
      │     ✗ gemma3:4b: format violation regardless — prompt cannot solve this
      │     → INSUFFICIENT for ministral
      │
      └── P5 (P4 + ## Critical Stop Rule keyed on "LIMIT REACHED")
            ✓ ministral: 100% gave_up_correctly, 0% format_viol
            ✗ gemma3:4b: format violation at turn 1 — worse than P4
            → USE P5 for ministral; gemma3:4b requires code-level guard
```

For gemma3:4b on the error path, a code-level turn guard — aborting after N consecutive identical errors in the loop driver, not relying on the model to emit a termination signal — is required regardless of suffix choice.

---

## Pipeline Integration Status 🚫 SUPERSEDED

### What replaced it
- The deterministic renderer (`PptxRenderer`) renders PPTX directly from the JSON outline using python-pptx — no LLM, no Docker sandbox, no ReAct loop.
- Eliminates the entire class of loop, termination, and format-compliance failures this experiment investigated.

### Why the decision was made
- python-pptx has no markdown parser — LLM-generated bullet text collapsed into a single paragraph and literal `*` characters appeared on slides.
- Docker sandbox added latency and infrastructure dependency on top of non-deterministic code generation.

### Transferable findings
- **Example key sensitivity:** For models ≤ 4B, the argument key name in the format example has stronger influence on tool call key selection than the tool's parameter description. Task-specific examples must exactly match actual tool argument names.
- **Keyword-triggered stop rule:** The P5 `## Critical Stop Rule` keyed on "LIMIT REACHED" converts inconsistent termination (33.3%) to graceful failure reporting (100%) for ministral-3:14b-cloud — validated in the error-path sub-experiment.
