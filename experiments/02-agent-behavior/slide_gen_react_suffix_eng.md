# ReAct Agent: How a Prompt Example Key Breaks Tool Dispatch in 4B Models

**Date:** 2026-04-07  
**Script:** `experiments/02-agent-behavior/slide_gen_react_suffix_eng.py`  
**Hardware:** MacBook M1 16 GB — all models run locally via Ollama

---

## Background

A LlamaIndex `ReActAgent`'s system prompt has two parts:

```
system_prompt = [task prompt] + [ReAct format template]
```

The **task prompt** tells the agent what to do — what files exist, which `python-pptx` patterns to use, where to save output. The **ReAct format template** tells it *how* to respond — how to structure the Thought / Action / Observation loop, and when to wrap up with a final `Answer:`.

The previous experiment fixed the task prompt and selected `gemma3:4b` as the most viable local model. But even with those fixes, early pipeline test logs still showed failures that had nothing to do with code quality:

- The agent called `run_code` 20+ times with the same code — stuck in a loop
- It reported "The error persists" right after `run_code` returned success — hallucinated failure
- It never emitted an `Answer:` and the workflow timed out

These pointed at the format template, not the task prompt. This experiment figures out what exactly in the template was causing this.

---

## Setup

To isolate the template's effect, I called the LLM directly via LiteLLM — bypassing LlamaIndex entirely. If the model fails to follow the format, it's the prompt causing it, not any framework scaffolding.

I also used a **mock sandbox** instead of real Docker execution. The mock gives deterministic responses: generate correct code → file confirmed; use the wrong argument key → get a realistic `AttributeError` back (same error text as Docker would return). This removes execution variability so any failure is traceable to the prompt alone.

**Models:**

| | Model | Size |
|---|---|---|
| `gemma3:4b` | `ollama/gemma3:4b` | 4B, local |
| `ministral-3:14b` | `ollama/ministral-3:14b-cloud` | 14B, cloud-hosted via Ollama |

**Config:** 3 runs per variant · 10 max turns · temperature 0

**What I tracked:**

| Metric | What it means |
|---|---|
| Completed % | The agent finished with a valid `Answer:` before running out of turns |
| Avg turns | Average number of LLM calls per run |
| format_viol % | The agent output something the ReAct loop couldn't parse at all — neither a valid `Action:` line nor `Answer:` |

---

## Variants Tested

All variants keep the task prompt constant. Only the format template changes.

**Experiment A — fixing loop and termination behavior (4 variants):**

| Variant | What changed |
|---|---|
| P0 — baseline | The original format template, verbatim. Contains `"keep repeating the above format until you have enough information"` and `"The answer MUST contain a sequence of bullet points"`. |
| P1 — termination guard | P0 + an explicit rule: once `list_files` confirms the output file exists, emit `Answer:` immediately and stop. |
| P2 — simplified | Replaced "keep repeating" with "use the minimum tool calls needed". Removed the bullet-point requirement from `Answer:`. |
| P3 — combined | P2 changes + P1's termination guard applied together. |

**Experiment B — fixing the root cause (1 variant):**

| Variant | What changed |
|---|---|
| P4 — example key fix | P2 with the format example updated to use tool-specific key names. See below. |

---

## What Was Actually Breaking It

While debugging P2 — where `gemma3:4b` dispatched 8 tool calls but all of them failed — I inspected the raw model outputs turn by turn. Every single call looked like this:

```
Action Input: {"input": "import json\nfrom pptx import Presentation\n..."}
```

The `run_code` tool expects `code` as the argument name. But the model was passing `"input"` every time. The tool handler does `kwargs.get("code", "")` — so it always got an empty string, the code never ran, and the mock sandbox returned an `AttributeError` on every turn. The model saw the same error, retried with more code, got the same error again, and eventually broke the format entirely.

Tracing it back: the format template had this generic example of how to format a tool call:

```
(e.g. {"input": "hello world", "num_beams": 5})
```

The model was copying `"input"` straight from that example — it never read the tool description that says the parameter is called `code`.

This makes sense once you think about how token generation works. When the model generates `{"`, the very next token it needs to pick is the key name. At that moment, the in-context example is the strongest signal — the model has already seen `{"input"` in context, so it writes `{"input"` again. A 4B model doesn't have the capacity to reason "this example is just illustrative; the actual tool spec says the key is `code`". A 14B model can — which is why `ministral-3:14b` was unaffected throughout.

**The fix was one line:**

```python
# Before — generic placeholder, wrong key for run_code:
(e.g. {"input": "hello world", "num_beams": 5})

# After — tool-specific examples:
(e.g. {"code": "print('hello')"} for run_code, {"remote_dir": "/sandbox"} for list_files)
```

---

## Results

### Experiment A — Loop / Termination Variants

**gemma3:4b:**

| Variant | Completed | Avg turns | format_viol % | Notes |
|---|---|---|---|---|
| P0 — baseline | 0% | 1.0 | 100% | Bullet-point rule conflicts with `Action:` format; fails at turn 1 |
| P1 — termination guard | 0% | 1.0 | 100% | Same root cause; guard has no effect |
| P2 — simplified | 0% | 9.0 | 100% | 8 tool calls dispatched — all with wrong `"input"` key |
| P3 — combined | 0% | 1.0 | 100% | Two conflicting stop conditions break the loop immediately |

All four variants failed for `gemma3:4b`. But P2 was the useful one: removing the conflicting instructions finally let the model try dispatching tools. Those 8 failed calls are what revealed the wrong key name — without P2, I'd have just seen turn-1 failures and never traced it this far.

**ministral-3:14b:**

| Variant | Completed | Avg turns | format_viol % | Notes |
|---|---|---|---|---|
| P0 — baseline | 100% | 3.0 | 0% | — |
| P1 — termination guard | 100% | 3.0 | 0% | — |
| P2 — simplified | 100% | 3.0 | 0% | — |
| P3 — combined | 67% | 4.0 | 33% | Adding a second stop rule on top of one that already worked caused 1/3 runs to produce malformed output |

The 14B model worked fine across P0–P2 because it correctly reads the tool description and uses `"code"` as the key. P3 actually hurt it: the termination guard was redundant since P0 already worked, and stacking two stop conditions created ambiguity for 1 in 3 runs.

### Experiment B — Example Key Fix (P4)

| Model | P2 (before) | P4 (after) | Change |
|---|---|---|---|
| gemma3:4b — completed | 0% | **100%** | +100pp |
| gemma3:4b — avg turns | 9.0 | **3.0** | −67% |
| gemma3:4b — format_viol % | 100% | **0%** | −100pp |
| ministral-3:14b — completed | 100% | 100% | unchanged |

One line changed. `gemma3:4b` went from completely broken to 100% in 3 clean turns. The 14B model was unaffected in either direction.

---

## Key Takeaway

**For small models (≤ 4B), the key name in a format example overrides the tool's own parameter description.**

The model picks up argument key names from the example, not from reading the tool spec. If the example says `{"input": ...}` and the tool expects `code`, the model will use `input` — every time, regardless of what the description says.

Larger models don't have this problem. They can treat the example as illustrative and read the actual spec correctly. The fix isn't more explanation — it's just matching the example to reality.

---

## What I Did Next

P4 fixed the tool dispatch problem — `gemma3:4b` could now call tools correctly in these isolated tests. But when I integrated the ReActAgent into the full project pipeline, a different problem surfaced: the python-pptx code the model generated was unreliable in practice. Not on every run, but often enough — wrong placeholder indices, missing `prs.save()` calls, code that executed without errors but produced an empty or visually broken PPTX. This happened across model sizes, not just with 4B models.

Unlike the format issues fixed here, this wasn't something addressable with more prompt tuning. The model's ability to write correct `python-pptx` code against the specific template was just too inconsistent to depend on.

So I changed the architecture: instead of having the LLM write and run Python at runtime, it now outputs a structured JSON object describing the slide content, and a deterministic Python renderer handles all the PPTX construction. P4 was the right fix for the format template problem — but it was the code generation reliability that led me to rethink the whole approach.
