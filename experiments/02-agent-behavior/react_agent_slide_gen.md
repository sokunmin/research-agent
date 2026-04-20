# ReAct Agent: Model & Prompt Evaluation for Slide Generation

**Date:** 2026-03-27  
**Script:** `experiments/02-agent-behavior/react_agent_slide_gen.py`  
**Hardware:** MacBook M1 16 GB — all models run locally via Ollama

---

## Background

The slide generation pipeline originally used a LlamaIndex `ReActAgent` driven by GPT-4o for two steps:

- **Slide generation** (`slide_gen`): given a JSON file of slide outlines, the agent writes and executes `python-pptx` code to produce a PPTX file from scratch
- **Slide modification** (`modify_slides`): given an existing PPTX and visual validation feedback, the agent loads the file, applies corrections, and saves a new version

The agent had four tools: `run_code` (execute Python in a sandbox), `list_files` (confirm the output file exists), `upload_file` (add a file to the sandbox), and `get_all_layout` (query PPTX layout metadata from the template).

After switching from GPT-4o to local Ollama models, slide generation broke: models started outputting Python code as plain text instead of calling `run_code`. No file was ever produced.

This set of experiments answers two questions:
1. Is the failure a prompt problem (fixable) or a fundamental model capability gap?
2. Does the prompt fix that works for slide generation also work for slide modification?

---

## Setup

**Method:** LlamaIndex `ReActAgent` with mock tool responses — no real sandbox execution. The mock gives deterministic feedback: code that includes `prs.save()` gets a success response; code that doesn't gets a warning. This isolates agent behavior from execution-side variability.

**Temperature:** 0.1 · **Timeout:** 600s · **N_RUNS:** 1 per model or prompt variant

**Task 1 — Model comparison for slide generation:**  
`gemma3:4b` and `qwen3.5:4b` were compared first (Round 1); `gemma3n:e2b` and `gemma3n:e4b` were tested separately against `gemma3:4b` (Round 2). Same prompt, same mock setup, same task input across both rounds. All results are combined here as a model comparison.

**Task 2 — Prompt comparison for slide modification:**  
Model fixed to `gemma3:4b` (selected from Task 1). Two prompt strategies compared, 1 run each.

**Metrics:** task completion · `run_code()` call count · tool call sequence · elapsed time

---

## Prompt Strategies (Task 2)

**Prompt A — Structured prose**  
5 numbered steps in natural language: (1) use `list_files` to find the existing PPTX, (2) read the validation feedback, (3) load the file with `python-pptx`, (4) apply all corrections, (5) save with the specified filename and confirm with `list_files`.

**Prompt B — CRITICAL directive**  
The same approach that fixed slide generation: `CRITICAL: You MUST use run_code to actually execute the code. Do not output code as text only.` Applied directly to the modification task.

---

## Results

### Task 1 — Model Comparison for Slide Generation

| Model | Size | Completed | `run_code()` calls | Issue |
|---|---|---|---|---|
| gemma3:4b | 4B | ✅ | **1** | — |
| qwen3.5:4b | 4B | ✅ | 16 | 15 failed attempts before eventual success |
| gemma3n:e2b | 2B | ❌ | 0 | Timed out at 600s without dispatching any tool |
| gemma3n:e4b | 4B | ❌ | 0 | Outputs Gemini-style `tool_code` blocks — incompatible format |

**Tool call sequences:**

`gemma3:4b`: `run_code → list_files → list_files → list_files`  
One successful execution on the first try, followed by three `list_files` confirmations.

`qwen3.5:4b`: 16× `run_code` before eventually succeeding — repeatedly self-corrected import errors, wrong placeholder indices, and missing `prs.save()` calls.

`gemma3n:e4b`: Produces a Gemini-native `tool_code` block at turn 1. LlamaIndex's ReAct parser doesn't recognise this format, so the loop exits immediately with no execution and no error message. Completely silent without logging raw model output.

### Task 2 — Prompt Comparison for Slide Modification (gemma3:4b)

| Prompt | Completed | `run_code()` calls | Issue |
|---|---|---|---|
| Prompt A — structured prose | ✅ | 2 | — |
| Prompt B — CRITICAL directive | ❌ | 0 | Looped for 20 rounds, zero tool calls |

Prompt B — the exact approach that fixed slide generation — caused a complete breakdown on the modification task. With `CRITICAL: you MUST call run_code immediately` in the prompt, the model looped for 20 rounds without calling a single tool. The directive seems to conflict with the multi-step inspect → load → fix → save workflow: the model couldn't decide when the "right moment" to call `run_code` was, and got stuck.

---

## Key Findings

**1. The original failure was a prompt problem, not a model capability gap.**  
The old phrasing — *"Respond user with the python code"* — led models to treat the task as a text output job rather than a tool execution job. Adding an explicit action directive fixed `gemma3:4b` immediately. The model understood the task; it just misread the output instruction.

**2. A fix for one task can break another.**  
The CRITICAL directive that resolved slide generation completely broke slide modification. Each agent step needs its own independently designed prompt — reusing a "working" prompt across different tasks isn't safe and can cause regressions.

**3. Model format incompatibility can be completely silent.**  
`gemma3n:e4b` doesn't fail with bad output — it fails invisibly. It produces a Gemini-specific `tool_code` format that LlamaIndex's ReAct parser can't parse, so the loop exits at turn 1 with no error signal. Without logging raw model outputs on every turn, there's no indication anything went wrong.

---

## What I Did Next

In isolation, `gemma3:4b` with task-specific prompts completed both tasks reliably. But when I integrated the ReActAgent into the actual project pipeline, a different problem emerged: the python-pptx code the model generated was unreliable in practice. Not every run — but often enough to matter. Wrong placeholder indices, missing `prs.save()` calls, code that executed cleanly but produced an empty or broken PPTX. This happened with both small and large models.

It wasn't a prompt problem I could fix. The model's ability to write correct `python-pptx` code against my specific template was just too inconsistent to depend on.

So I replaced the approach: the LLM now outputs a structured JSON object describing each slide's content, and a deterministic Python renderer handles all the PPTX construction. The ReActAgent evaluation here was still worth doing — it's the evidence that I systematically tested the original approach before deciding to replace it.
