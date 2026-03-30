# ReAct Agent Model Selection for Slide Generation

**Date:** 2026-03-27

---

## Background & Motivation

The slide generation pipeline uses a LlamaIndex ReAct Agent to write and execute Python (python-pptx) inside a Docker sandbox. An early production failure was observed: the agent produced Python code as plain text in its reply instead of invoking the `run_code` tool, so no actual PowerPoint file was created. This experiment investigated whether the failure was caused by prompt ambiguity or a fundamental model limitation, and identified which 4B-scale local model is best suited for this task.

Four models available through Ollama were tested: `qwen3.5:4b`, `gemma3:4b`, `gemma3n:e2b`, and `gemma3n:e4b`. All experiments ran on a MacBook M1 with local inference — model size and latency are directly constrained by on-device hardware.

---

## Experiment Setup

Three rounds of testing covered the two core agent tasks:

- **Slide generation** (`slide_gen`): given a `slide_outlines.json` file, generate a PPTX from scratch using python-pptx
- **Slide modification** (`modify_slides`): given an existing PPTX and validation feedback, load, modify, and save a new version

The agent has 4 tools: `run_code`, `list_files`, `upload_file`, `get_all_layout`.

| Parameter | Value |
|-----------|-------|
| Agent framework | LlamaIndex ReAct Agent |
| Sandbox | Docker container |
| PPTX library | python-pptx |
| Timeout | 600 seconds (Round 2) / max_iterations limit (Round 3) |
| Models tested | qwen3.5:4b, gemma3:4b, gemma3n:e2b, gemma3n:e4b |

Metrics recorded per run: task completion, `run_code` call count, `list_files` call count, whether generated code contains `prs.save()`, whether errors occurred, total tool call count, elapsed time.

---

## Results

### Round 1 — Slide Generation: qwen3.5:4b vs gemma3:4b

Both models were tested under the corrected prompt that explicitly requires using `run_code` (the old prompt said "Respond user with the python code", which 4B models interpreted as "write code in the reply text").

| Metric | qwen3.5:4b | gemma3:4b |
|--------|-----------|-----------|
| Task completed | Yes | Yes |
| `run_code()` called | Yes | Yes |
| `run_code()` call count | 16 | 1 |
| Generated code contains `prs.save()` | Yes | Yes |
| `list_files()` call count | 1 | 3 |
| Final answer contains a question | No | No |
| Errors occurred | None | None |
| Total tool call count | 17 | 4 |

**qwen3.5:4b tool call sequence:**
`run_code × 16 → list_files` (iterative debugging across 16 attempts before success)

**gemma3:4b tool call sequence:**
`run_code → list_files → list_files → list_files` (1 call succeeded; subsequent calls verified output)

**Efficiency comparison:**

| Metric | qwen3.5:4b | gemma3:4b | Ratio |
|--------|-----------|-----------|-------|
| Total tool calls | 17 | 4 | 4.25× |
| `run_code` call count | 16 | 1 | 16.0× |

### Round 2 — Slide Generation: gemma3n Series vs gemma3:4b

| Metric | gemma3:4b | gemma3n:e2b | gemma3n:e4b |
|--------|-----------|-------------|-------------|
| Elapsed time (s) | 46.1 | 600.0 (timeout) | 19.3 |
| `run_code()` called | Yes | No | No |
| `run_code()` call count | 1 | 0 | 0 |
| Code contains `prs.save()` | Yes | No | No |
| Errors occurred | None | TIMEOUT | None (but ineffective) |
| Total tool call count | 4 | 0 | 0 |
| ReAct compatibility | Excellent | Incompatible | Incompatible |

**gemma3n:e2b** timed out at 600 seconds with zero tool calls — the model stalled inside `run_agent_step` and never produced a parseable ReAct response.

**gemma3n:e4b** responded in 19.3s but invoked no tools. It output a `tool_code` block — a Google Gemini-specific function call format — which is incompatible with the `Action:/Observation:` format required by LlamaIndex ReAct. The workflow treated the raw output as the final answer and terminated.

### Round 3 — Slide Modification: Prompt Style Comparison (gemma3:4b)

Two prompt styles for the `modify_slides` task were compared:

- **Prose format** (current): 5-step sequential instructions, no coercive language
- **Directive format**: mirrors the `slide_gen` prompt — adds "CRITICAL: You MUST use run_code", "ONLY job", explicit completion conditions

| Metric | Prose format (current) | Directive format |
|--------|----------------------|------------------|
| Elapsed time (s) | 39.7 | 336.8 (hit max iterations) |
| `run_code()` called | Yes | No |
| `run_code()` call count | 1 | 0 |
| `list_files()` call count | 1 | 0 |
| Code saves modified file | Yes | No |
| Errors occurred | None | Max iterations (20) |
| Total tool call count | 2 | 0 |

Tool call sequences:
- Prose format: `run_code → list_files` (succeeded on first call)
- Directive format: no tool calls across 20 rounds (infinite loop)

---

## Key Findings

- **gemma3:4b is the clear winner**: it completes both `slide_gen` and `modify_slides` in a single `run_code` call with clean execution and no errors.
- **qwen3.5:4b works but is highly inefficient**: it required 16 `run_code` calls to complete the same slide generation task that gemma3:4b finished in 1 call (16× more code execution attempts).
- **gemma3n:e2b is unusable**: it timed out at 600 seconds without producing a single tool call.
- **gemma3n:e4b is format-incompatible**: it outputs Gemini-style `tool_code` blocks instead of the `Action:` format required by LlamaIndex ReAct, causing immediate workflow termination.
- **The original production failure was prompt ambiguity**, not a model capability issue: changing "Respond user with the python code" to an explicit tool invocation instruction fixed both models.
- **Prompt style is task-dependent**: the directive-style `CRITICAL` prompt that works for `slide_gen` causes a complete failure (20-round loop, 0 tool calls) for `modify_slides`. The two tasks require different prompt strategies and should not be unified.

---

## Decision

**gemma3:4b is adopted as the ReAct agent model** for both `slide_gen` and `modify_slides`. The gemma3n series is not suitable under the current Ollama + LlamaIndex ReAct architecture.

The two prompts remain deliberately different: `slide_gen` uses explicit directive-style language ("CRITICAL: MUST use run_code") to override the model's text-generation prior; `modify_slides` uses a 5-step prose format because the concrete feedback content already provides a sufficient action signal. Applying the directive style to `modify_slides` harms performance and must not be done.
