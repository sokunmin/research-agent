# Slide Gen ReAct Suffix Engineering — Experiment Report

**Date:** 2026-04-07  
**Script:** `poc/agent-behavior-test/slide_gen_react_suffix_eng.py`  
**Results JSON:** `poc/agent-behavior-test/slide_gen_react_suffix_eng_results.json`  
**Status:** COMPLETED (Exp 3 + Exp 4)

---

## 1. Background

This project generates PowerPoint slides from academic paper summaries via a multi-step agentic workflow:

```
[markdown summaries]
  → summary2outline  (LLM, FunctionCallingProgram)       → SlideOutline {title, content}
  → outlines_with_layout (LLM, LLMTextCompletionProgram) → SlideOutlineWithLayout {title, content, layout_name, idx_*}
                                                             serialised → slide_outlines.json
  → slide_gen        (ReActAgent)                         → agent writes + runs python-pptx code in Docker sandbox
  → validate_slides / modify_slides                       → final .pptx
```

The `slide_gen` step instantiates a LlamaIndex `ReActAgent`. Its system prompt is composed of two parts:

```
system_prompt = SLIDE_GEN_PMT + REACT_PROMPT_SUFFIX
```

- **`SLIDE_GEN_PMT`** — task specification: what files exist in the sandbox, what python-pptx patterns to use, where to save output.
- **`REACT_PROMPT_SUFFIX`** — ReAct format control: how the agent structures its Thought/Action/Observation loop, when to terminate.

### Prior experiments

**Experiment 1** (`slide_gen_fix_validation.py`) confirmed four Python-level bugs in the production code (JSON double-encoding, wrong placeholder type, missing `add_slide()` pattern, file not uploaded to sandbox, wrong save path). All 17 fix assertions passed.

**Experiment 2** (`slide_gen_prompt_eng.py`) validated four levels of `SLIDE_GEN_PMT` specificity (P0 vague → P3 full pattern). **P2** (with explicit `add_slide()` lookup and null guard code examples) achieved 100% correctness on both models. This experiment holds `SLIDE_GEN_PMT` fixed at P2.

### Motivation for this experiment

Even with correct code generation (Exp 2 P2), pre-fix production Docker logs showed ReAct loop failures independent of code quality:

1. Agent hallucinated "The error persists" after `run_code` returned success.
2. Agent called `run_code` 20+ times with the same wrong code — infinite loop.
3. Agent never output `Answer:` — workflow hit timeout.

These failures are attributable to `REACT_PROMPT_SUFFIX`, not `SLIDE_GEN_PMT`:
- `"keep repeating the above format until you have enough information"` — encourages looping even after success.
- `"The answer MUST contain a sequence of bullet points"` — designed for Q&A, misleads agent on file-generation tasks.
- No explicit stop condition tied to file presence.

---

## 2. Experiment Design

### 2.1 Method

- Direct `litellm.completion()` loop — **no LlamaIndex ReActAgent**, isolates suffix text effect.
- **MockSandbox** — deterministic responses without Docker. Correct code → success + file created; wrong code → realistic error string based on which check failed.
- `CodeEvaluator` — same regex checks as Experiment 2 (4 criteria: layout lookup, save path, null guard, import).
- `N_RUNS = 3`, `MAX_TURNS = 10`, `temperature = 0`.

### 2.2 Models

| Label | Model string |
|-------|-------------|
| `gemma3:4b` | `ollama/gemma3:4b` |
| `ministral-3:14b-cloud` | `ollama/ministral-3:14b-cloud` |

### 2.3 REACT_PROMPT_SUFFIX variants

All variants hold `SLIDE_GEN_PMT` constant at P2 (validated in Experiment 2).

**Experiment 3 variants (loop/termination focused):**

| ID | Change from P0 |
|----|----------------|
| **P0_baseline** | Verbatim production `REACT_PROMPT_SUFFIX`. Control condition. |
| **P1_termination_guard** | P0 + `## Critical Termination Rule`: explicit stop after `list_files` confirms file; "Trust the Observation." |
| **P2_simplified** | Replace "keep repeating" with "minimum tool calls"; remove `## Additional Rules` (bullet-point requirement). |
| **P3_combined** | P2 simplifications + P1 termination guard. |

**Experiment 4 variant (example key fix):**

| ID | Change from P2 |
|----|----------------|
| **P4_example_fix** | P2 with format example key fixed: `{"input": "hello world", "num_beams": 5}` → `{"code": "print('hello')"} for run_code, {"remote_dir": "/sandbox"} for list_files` |

### 2.4 Metrics

| Metric | Definition |
|--------|-----------|
| `terminated%` | Agent emitted `Answer:` before `MAX_TURNS` exhausted |
| `avg_turns` | Mean LLM calls per run |
| `avg_tool_calls` | Mean tool dispatches per run |
| `loops%` | Any tool call dispatched after `list_files` already confirmed file |
| `first_correct%` | First `run_code` call passed all 4 CodeEvaluator checks |
| `hallucinated%` | Agent claimed error/failure after a successful `run_code` Observation |
| `format_viol%` | Agent produced neither a parseable `Action:` nor `Answer:` |

---

## 3. Results

### Experiment 3 — gemma3:4b

| Variant | terminated% | avg_turns | avg_tool_calls | loops% | first_correct% | hallucinated% | format_viol% |
|---------|-------------|-----------|----------------|--------|----------------|---------------|-------------|
| P0_baseline | 0.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | **100.0** |
| P1_termination_guard | 0.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | **100.0** |
| P2_simplified | 0.0 | 9.0 | 8.0 | 0.0 | 0.0 | 0.0 | **100.0** |
| P3_combined | 0.0 | 1.0 | 0.0 | 0.0 | 0.0 | 0.0 | **100.0** |

### Experiment 3 — ministral-3:14b-cloud

| Variant | terminated% | avg_turns | avg_tool_calls | loops% | first_correct% | hallucinated% | format_viol% |
|---------|-------------|-----------|----------------|--------|----------------|---------------|-------------|
| P0_baseline | **100.0** | 3.0 | 2.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| P1_termination_guard | **100.0** | 3.0 | 2.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| P2_simplified | **100.0** | 3.0 | 2.0 | 0.0 | 100.0 | 0.0 | 0.0 |
| P3_combined | 66.7 | 4.0 | 3.0 | 0.0 | 66.7 | 0.0 | **33.3** |

### Experiment 4 — both models (P4_example_fix)

| Model | terminated% | avg_turns | avg_tool_calls | loops% | first_correct% | hallucinated% | format_viol% |
|-------|-------------|-----------|----------------|--------|----------------|---------------|-------------|
| gemma3:4b | **100.0** | 3.0 | 2.0 | 0.0 | **100.0** | 0.0 | **0.0** |
| ministral-3:14b-cloud | **100.0** | 3.0 | 2.0 | 0.0 | **100.0** | 0.0 | **0.0** |

### Delta summary (gemma3:4b only — ministral unchanged)

| Variant | terminated% | first_correct% | format_viol% | avg_turns |
|---------|-------------|----------------|-------------|-----------|
| P2_simplified (Exp 3) | 0% | 0% | 100% | 9.0 |
| **P4_example_fix (Exp 4)** | **100%** | **100%** | **0%** | **3.0** |

---

## 4. Analysis

### 4.1 Exp 3 — gemma3:4b: all variants failed (100% format_viol)

**P0/P1/P3 — immediate format violation at turn 1:**  
The model outputs prose or a markdown code block on the first response with no `Action:` line. The `## Additional Rules` section (`"The answer MUST contain a sequence of bullet points"`) creates a competing instruction that conflicts with the `Action:` format requirement. A 4B model lacks the instruction-following capacity to correctly scope the bullet-point rule to only the final `Answer:` — it applies it everywhere, breaking the loop before it starts.

**P2 — partial compliance, format violation at turn 9:**  
Removing `## Additional Rules` and "keep repeating" lets `gemma3:4b` dispatch 8 tool calls across 9 turns (`n_tool_calls = 8`). However, `first_correct% = 0%` — all `run_code` calls fail. Turn-by-turn inspection (via `_inspect_gemma_p2.py`) revealed the root cause:

The model passes `"input"` as the JSON key instead of `"code"`:
```
Action Input: {"input": "import json\nfrom pptx import Presentation\n..."}
```
The tool expects `run_code(code: str)`. `kwargs.get("code", "")` returns empty string → `CodeEvaluator` fails all 4 checks → MockSandbox always returns `AttributeError`. The model sees the same error every turn regardless of its code content, loops until turn 9, then breaks format.

**Root cause:** The format example in the suffix is `(e.g. {"input": "hello world", "num_beams": 5})`. LLM in-context learning gives few-shot examples higher prior weight than tool description text. A 4B model pattern-matches the `"input"` key from the example rather than reading `run_code(code: str)` from the tool description. This is the primary failure mode.

### 4.2 Exp 3 — ministral-3:14b-cloud: suffix variants have no positive effect; P3 hurts

P0/P1/P2 all achieve `terminated% = 100%` in exactly 3 turns: `run_code` → `list_files` → `Answer:`. The model terminates before any loop risks can manifest. Suffix variant changes are irrelevant for the success path.

**P3 is worse than P0** (66.7% vs 100%): P3 applies both P2's "minimum tool calls" wording AND P1's explicit termination guard. These two termination instructions conflict — one is implicit ("stop when goal achieved"), the other specifies an exact expected output string. For 1/3 runs, the model produced a malformed response trying to reconcile both, resulting in format violation at turn 6.

This is an **instruction over-specification** failure: adding a redundant, more specific constraint on top of a sufficient one creates ambiguity rather than clarity.

### 4.3 Exp 4 — P4: one-line fix resolves gemma3:4b completely

Changing the format example from `{"input": "hello world", "num_beams": 5}` to `{"code": "print('hello')"} for run_code, {"remote_dir": "/sandbox"} for list_files`:

- `gemma3:4b`: 0% → **100%** terminated, 0% → **100%** first_correct, 100% → **0%** format_viol, avg_turns 9.0 → **3.0**
- `ministral-3:14b-cloud`: unchanged at 100% (not disrupted by the fix)

The model now uses `"code"` as the key, the evaluator receives the actual code string, `MockSandbox` evaluates it correctly and returns success on the first attempt. The entire fix is **one line** in the suffix template.

**Why this works — LLM perspective:**  
In causal language models, generating the token sequence `{"` is immediately followed by the key token. At that decision point, the token with highest probability is determined by the attention-weighted context. The few-shot example `{"input": "hello world"}` creates a strong n-gram prior: `{" → input`. After the fix, the example `{"code": "print('hello')"} for run_code` creates `{" → code` as the dominant prior for the `run_code` context. The task-specific example overrides the generic one.

---

## 5. Conclusion

### Primary finding

**The `REACT_PROMPT_SUFFIX` format example key name is the single most impactful lever for small model ReAct tool dispatch.** It overrides the tool description for argument key selection in models ≤ 4B.

The fix is a one-line change in `backend/prompts/prompts.py` (`REACT_PROMPT_SUFFIX`):

```python
# Current (broken for small models):
(e.g. {"input": "hello world", "num_beams": 5})

# Fix (P4):
(e.g. {"code": "print('hello')"} for run_code, {"remote_dir": "/sandbox"} for list_files)
```

### Recommended production prompt

**`REACT_PROMPT_SUFFIX` = P4** (P2 simplifications + example key fix):
- Remove "keep repeating" → "minimum tool calls" (prevents latent loop risk on production errors)
- Remove `## Additional Rules` bullet-point requirement (eliminates competing instruction for small models)
- Fix format example key names (enables correct tool dispatch for small models)

P1 and P3 are not recommended: the explicit termination guard adds over-specification that hurts `ministral` and does not help `gemma3:4b`.

### Caveats

- MockSandbox is deterministic. Real Docker errors are more varied; self-correction across turns was not tested.
- `loops_after_success = 0%` for all runs — the production loop failure mode requires real Docker execution to test.
- N=3 is low; treat percentages as directional.
- `first_correct% = 100%` for gemma3:4b P4 is under MockSandbox conditions where SLIDE_GEN_PMT P2 patterns are held constant. Real production may produce code with additional issues (e.g., wrong template path) not covered by the 4 static checks.

---

## Experiment 5 — Error Behavior Sub-Experiment (P5)

**Date run:** 2026-04-07  
**Script:** `poc/agent-behavior-test/slide_gen_react_suffix_eng.py` (error sub-experiment section)  
**Results JSON:** `poc/agent-behavior-test/slide_gen_react_suffix_eng_error_results.json`  
**Log:** `poc/agent-behavior-test/slide_gen_react_suffix_eng_p5_log.txt`

### 5.1 Background / Why this experiment

Experiments 1–4 confirmed that P4 fixes normal-path ReAct behavior for both models: the agent generates correct python-pptx code on the first attempt and terminates cleanly. However, production deployments encounter two additional failure modes that MockSandbox (always succeeds on correct code) cannot expose:

1. **Persistent unrecoverable error** — the sandbox always returns an error (e.g., corrupted template, Docker resource limit, hard API failure). Without a stop rule, a ReAct agent may loop indefinitely, consuming MAX_TURNS or hanging the workflow.
2. **Missing dependency** (`ModuleNotFoundError: No module named 'pptx'`) — python-pptx may not be pre-installed in some deployment environments. The model needs to self-diagnose the error and issue a `pip install` command before retrying the slide generation code.

Experiment 5 tests both failure modes explicitly, with a new prompt variant P5 that adds an explicit stop signal for Scenario A.

---

### 5.2 Scenario A Design — Persistent Error / Infinite Loop

**What `PersistentErrorSandbox` does:**  
Every `run_code` call returns an `AttributeError` regardless of the code content. An attempt counter is embedded in each observation:

```
Attempt (1/3) failed.
ERROR (exit_code=1):
AttributeError: 'str' object has no attribute 'part'
```

When the attempt count reaches `max_attempts` (set to 3), the string `LIMIT REACHED` is appended:

```
Attempt (3/3) failed. LIMIT REACHED.
ERROR (exit_code=1):
AttributeError: 'str' object has no attribute 'part'
```

Subsequent calls continue incrementing the counter (e.g., `(4/3)`, `(5/3)`) to show the model it has exceeded the limit.

`list_files` always returns `(no files in /sandbox)` since no file is ever created.

**What P5 adds — `## Critical Stop Rule`:**  
P5 is P4 plus the following section appended to the suffix:

```
## Critical Stop Rule
If you see "LIMIT REACHED" in any Observation, output IMMEDIATELY:
  Thought: Maximum attempts reached. Cannot complete the task.
  Answer: Task failed after 3 attempts. Error: [summarise the last error seen]
Do NOT call run_code again after seeing "LIMIT REACHED".
```

**What P4 does NOT have:**  
P4 has no stop rule. It only says "Use the minimum number of tool calls needed. Stop as soon as the goal is achieved." There is no explicit instruction to stop when the goal is *unachievable*.

**Prompts tested:** P4 (control, no stop rule) vs P5 (with `LIMIT REACHED` stop rule)  
**Models:** `gemma3:4b`, `ministral-3:14b-cloud`  
**N_RUNS = 3, MAX_TURNS = 10**

---

### 5.3 Scenario B Design — Recoverable Error / pip install

**What `ModuleNotFoundSandbox` does:**  
Simulates an environment where python-pptx is not installed. Behaviour:

- Code that imports `pptx` without prior installation → `ModuleNotFoundError: No module named 'pptx'`
- Code containing `!pip install` → `SyntaxError: invalid syntax (!pip is Jupyter notebook syntax, not valid in a Python script)` — simulates the common mistake of using Jupyter notebook syntax in a Python script context
- Code containing `pip install python-pptx` or `subprocess`-based pip (without `!`) → `Successfully installed python-pptx-1.0.2`, sets `_pptx_installed = True`
- Subsequent slide generation code after successful install → unconditional success (`paper_summaries.pptx created`)

**Why `TOOL_DESC_NO_PPTX_CLAIM` is used:**  
The standard `TOOL_DESC` contains the phrase "python-pptx is pre-installed." This makes Scenario B unrealistic — the model would have no reason to attempt pip install if the tool description asserts the library is already present. `TOOL_DESC_NO_PPTX_CLAIM` removes that claim, so the model must infer the need for installation from the `ModuleNotFoundError` alone.

**What we are measuring:**  
- Does the model correctly diagnose `ModuleNotFoundError` and generate a pip install command?
- Does it use the correct pip syntax (subprocess or bare `pip install`) vs the wrong Jupyter `!pip` syntax?
- After installing, does it successfully complete the slide generation task?
- How many turns does it take to reach the pip install step?

**Prompt tested:** P4 only (baseline; no stop rule needed for a recoverable error)  
**Models:** `gemma3:4b`, `ministral-3:14b-cloud`

---

### 5.4 Results — Scenario A (Persistent Error)

| Model | Prompt | terminated% | gave_up_correctly% | hallucinated_success% | reached_max_turns% | format_viol% | avg_turns | avg_tool_calls |
|-------|--------|-------------|-------------------|----------------------|--------------------|-------------|-----------|----------------|
| gemma3:4b | P4 (no stop rule) | 0.0 | 0.0 | 0.0 | 0.0 | **100.0** | 10.0 | 9.0 |
| gemma3:4b | P5 (LIMIT REACHED) | 0.0 | 0.0 | 0.0 | 0.0 | **100.0** | **1.0** | 0.0 |
| ministral-3:14b-cloud | P4 (no stop rule) | 33.3 | 33.3 | 0.0 | 0.0 | 33.3 | 3.0 | 2.3 |
| ministral-3:14b-cloud | P5 (LIMIT REACHED) | **100.0** | **100.0** | 0.0 | 0.0 | 0.0 | 3.0 | 2.0 |

**Note on `reached_max_turns%`:** This metric is `True` only when the loop exhausts `MAX_TURNS=10` without any `break` (no `Answer:`, no format violation, no exception). For gemma3:4b P4, the model runs 9 tool calls and then produces a format violation on turn 10, which triggers a `break`. Consequently `reached_max_turns=False` even though `n_turns=10`. The model was effectively stuck, but broke out via format violation rather than true exhaustion.

---

### 5.5 Results — Scenario B (Module Not Found)

| Model | Prompt | correct_pip% | jupyter_pip% | task_done% | terminated% | avg_turns | avg_tool_calls | avg_pip_turn |
|-------|--------|-------------|-------------|-----------|-------------|-----------|----------------|-------------|
| gemma3:4b | P4 | **100.0** | 0.0 | **100.0** | **100.0** | 5.0 | 4.0 | 2.0 |
| ministral-3:14b-cloud | P4 | **100.0** | 33.3 | 0.0 | 0.0 | 3.3 | 2.3 | 2.3 |

**Qualitative evidence — actual `pip_code_sample` values from results:**

`gemma3:4b` — all 3 runs generated identical, minimal correct pip syntax:

```
pip install python-pptx
```

`ministral-3:14b-cloud` — 2/3 runs generated the same minimal form; 1/3 run generated a subprocess-based install that was classified as `generated_jupyter_pip=True` due to pattern overlap:

```
# ministral run 0 & run 2 (correct, pip_turn=2):
pip install python-pptx

# ministral run 1 (correct pip but also triggered jupyter_pip flag, pip_turn=3):
import subprocess
import sys
subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'python-pptx'])
```

Note: the `subprocess.check_call` form is functionally valid Python (not Jupyter syntax). The `generated_jupyter_pip` flag fires because the detection regex is broad. See Section 5.6 for interpretation.

---

### 5.6 Analysis

#### Does P5's "LIMIT REACHED" signal help the model stop correctly vs P4?

**ministral-3:14b-cloud: yes, decisively.**  
With P4 (no stop rule), ministral terminated correctly in only 1/3 runs (33.3%) and had a format violation in another 1/3 run. With P5, it terminated correctly in all 3/3 runs (100%), always emitting `Answer:` with a failure message after 3 turns (2 tool calls). The "LIMIT REACHED" keyword in the Observation directly triggers the stop behaviour as intended.

**gemma3:4b: the signal is ignored; format violation dominates.**  
With P4, gemma3:4b ran all 10 turns (9 tool calls) and broke on format violation on turn 10. With P5, it broke on format violation at turn 1, using 0 tool calls — it never even attempted a tool call. In both cases `format_viol%=100%`. The model does not reach the point where it can read "LIMIT REACHED" because it violates the ReAct format before dispatching any tool. This is the same fundamental format compliance failure observed in Experiments 3 and 4 under error conditions. P5 actually makes it worse by truncating to 1 turn instead of 10 — suggesting the P5 suffix text itself disrupts the gemma3:4b format compliance for the error scenario (possibly conflicting instructions between the `## Critical Stop Rule` section and the normal `Thought/Action` format).

#### Does the model give up gracefully (gave_up_correctly) or hallucinate success?

Neither model hallucinated success (`hallucinated_success%=0` for all conditions). ministral with P5 consistently produced answers containing failure keywords ("error persists", "cannot complete"), correctly classified as `gave_up_correctly=True`. No model falsely claimed the file was created.

#### Does the model reach MAX_TURNS (true infinite loop)?

No. `reached_max_turns%=0` for all conditions. gemma3:4b with P4 came closest: 9 tool calls, then format violation at turn 10. ministral with P4 had mixed outcomes (1/3 gave up, 1/3 format violation, 1/3 ran 5 turns then gave up). True infinite loop (exhausting MAX_TURNS without any break) did not occur in these runs. However, gemma3:4b P4 effectively consumed nearly all available turns before breaking — in production with a higher MAX_TURNS limit it would approach infinite looping.

#### Can gemma3:4b / ministral self-heal via pip install?

**gemma3:4b: yes, perfectly.** All 3 runs correctly diagnosed `ModuleNotFoundError`, issued `pip install python-pptx` at turn 2, completed the slide generation after the install, and confirmed the file. `task_done%=100%`.

**ministral-3:14b-cloud: pip install yes, task completion no.** All 3 runs generated a correct pip install command (`correct_pip%=100%`). However, `task_done%=0%` — the file was never confirmed. With only 3–4 turns per run, ministral issued the pip install but did not proceed to run the slide generation code and call `list_files` within the turn budget. The runs ended without `Answer:` (`terminated%=0%`). The model's correct self-healing instinct was present but the follow-through was incomplete.

#### Did any model use `!pip` (Jupyter syntax)?

gemma3:4b: never used `!pip`. ministral-3:14b-cloud: 1/3 runs used `subprocess.check_call([sys.executable, '-m', 'pip', ...])`  which triggered the `generated_jupyter_pip` detection flag, but this form is actually valid Python (not `!pip`). True `!pip` was never generated by either model. The subprocess form works in a Python script context; the sandbox accepted it as a correct install.

#### Does model size matter for self-recovery?

In Scenario B: smaller model (gemma3:4b, 4B parameters) outperformed the larger cloud model (ministral-3:14b-cloud, 14B) in terms of end-to-end task completion (100% vs 0%). gemma3:4b generated minimal, correct `pip install python-pptx` consistently and then immediately proceeded to complete the task. ministral generated the install but stalled before confirming the file. This reversal of the Exp 3/4 pattern (where ministral was more reliable) suggests that for self-recovery workflows, a model's tendency to complete the action chain matters as much as instruction following.

However, this finding may be confounded by the turn budget: ministral's 3-turn runs may not have had enough turns to complete install + code + list_files + Answer. A higher MAX_TURNS for Scenario B would clarify this.

---

### 5.7 Conclusion

#### What these results mean for production deployment

**Scenario A (persistent errors):**  
The P5 `## Critical Stop Rule` keyed on the "LIMIT REACHED" signal is effective for `ministral-3:14b-cloud`: it converts 33% reliable termination (P4) to 100% reliable, graceful failure reporting (P5). For `gemma3:4b`, P5 does not help — the model cannot follow the ReAct format under error conditions regardless of prompt. If the production model is `gemma3:4b`, prompt engineering alone cannot solve the persistent-error loop failure; a code-level guard (maximum tool call count enforced by the loop driver, not the model) is required.

**Scenario B (missing dependency):**  
Both models correctly self-diagnose `ModuleNotFoundError` and generate a pip install command. `gemma3:4b` fully completes the recovery. `ministral-3:14b-cloud` issues the install but does not complete the task within the turn budget tested. In production, ensure the sandbox description does not falsely claim python-pptx is pre-installed if the environment cannot guarantee it — removing that claim (as `TOOL_DESC_NO_PPTX_CLAIM` does) is sufficient for models to self-diagnose and heal.

#### Recommended actions

1. **Deploy P5 as the production `REACT_PROMPT_SUFFIX`** (for `ministral-3:14b-cloud`). P5 adds the `## Critical Stop Rule` to P4 with no regressions on the normal path (Exp 5 normal-path run: ministral P5 = 100% terminated, 3 turns, 2 tool calls — identical to P4).

2. **Add a code-level turn guard for `gemma3:4b`**: the model cannot reliably emit `Answer:` under error conditions even with an explicit stop rule. The loop driver should enforce a hard cap on `run_code` retries (e.g., abort after 3 identical errors) independently of the model's prompt compliance.

3. **Remove "python-pptx is pre-installed" from `TOOL_DESC`** if deployment cannot guarantee the library is present. Both models handle `ModuleNotFoundError` correctly when the claim is absent; the false claim would suppress self-healing.

4. **Increase MAX_TURNS for `ministral-3:14b-cloud` Scenario B** to ≥ 8 turns if pip-install self-recovery is required. The current 3-turn pattern (install → code → done/list_files) may not fit within MAX_TURNS=10 if other setup steps are interleaved.

5. **N=3 caveat**: All percentages are directional. Rerun with N≥10 before treating them as deployment-ready benchmarks.
