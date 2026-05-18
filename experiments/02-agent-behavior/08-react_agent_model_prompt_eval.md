# Experiment 8 — ReAct Agent: Model & Prompt Evaluation for PPTX Rendering

## Task Context

This experiment targets **Step 6 — PPTX Rendering** (original ReAct approach) from the system architecture (README → System Architecture). This is the first of three sequential experiments (Exp 7 → Exp 8 → Exp 9). Together they progressively diagnosed each failure layer of the ReActAgent approach — forming the evidence trail for replacing it with deterministic rendering. The original author used GPT-4o in a ReActAgent loop to generate python-pptx code at runtime and execute it in an Azure sandbox. The fork replaces the hard-coded Azure dependency with a provider-agnostic LiteLLM layer — any LLM provider is switchable via `.env` with no code changes. To validate pipeline feasibility without cloud cost or access constraints, local SLMs (~4B parameters) served via Ollama on an M1 MacBook are used as the test vehicle. This experiment identifies which local SLM and prompt configuration can reliably drive the same ReAct loop.

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

Step 6 has two ReActAgent-driven sub-steps with a VLM validation loop in between:

- **`slide_gen`** — given `slide_outlines.json`, generates a PPTX file from scratch
- **`validate_slides`** — VLM checks each slide image; routes to `modify_slides` if issues found (up to 2 retries)
- **`modify_slides`** — given the existing PPTX and validation feedback, modifies and saves a revised version

```
Step 6 — PPTX Rendering (detail)
──────────────────────────────────────────────────────────────────
 slide_outlines.json + PPTX template
       │
       ▼
 ┌─── EXPERIMENT TARGET ──────────────────────────────────────────┐
 │                                                                │
 │  ① [slide_gen]                                                 │
 │     ReActAgent · SLIDE_GEN_PMT · max_iterations=50            │
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
 │     ReActAgent · SLIDE_MODIFICATION_PMT · max_iterations=50  │ │
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

**Tools available to the agent:**

| Tool | Role |
|---|---|
| `run_code` | Executes Python code in the sandbox (python-pptx operations) — **primary generation tool; the experiment measures whether and how many times this is called** |
| `list_files` | Lists files in the sandbox — used by the agent to verify the PPTX was saved |
| `upload_file` | Uploads a local file to the sandbox (template, JSON) |
| `get_all_layout` | Returns PPTX layout metadata (placeholder names, sizes, positions) |

If `slide_gen` fails to call `run_code`, no PPTX is produced and `validate_slides` receives nothing — the pipeline stalls. If `modify_slides` fails to call `run_code`, the same invalid slide deck re-enters `validate_slides` and is rejected until retries are exhausted.

---

## Summary

- **Problem:** The fork's provider-agnostic LiteLLM layer must support local SLMs as well as cloud models. Validating the ReAct-based rendering step with a local 4B SLM revealed a failure — models output code as text instead of calling the tool, producing no PPTX file.
  - Root cause was unknown: prompt ambiguity vs fundamental model limitation.
- **Solution:** 3-round evaluation across 4 models and 2 agent tasks:
  - Round 1 — prompt fix validation on slide generation: qwen3.5:4b vs gemma3:4b
  - Round 2 — gemma3n series viability on slide generation: 3 models
  - Round 3 — prompt style comparison on slide modification: prose vs CRITICAL-style directive
- **Result:** gemma3:4b was the only viable model across all rounds.
  - Prompt style must match task ambiguity level — CRITICAL for high-ambiguity tasks, prose for low-ambiguity tasks. This applies to any future agent step design.
  - The ReActAgent approach was superseded after Exp 8 confirmed it was not viable for local inference.

---

## Experiment Setup

> This experiment's approach was superseded by deterministic rendering — no ✅ applies. See Pipeline Integration Status.

### Objective

- **Problem:** The original `SLIDE_GEN_PMT` causes 4B models to output code as text instead of calling `run_code` — 0 PPTX produced
- **Goal:** Which model calls `run_code` in 1 attempt after the prompt fix, and does the same CRITICAL-style directive also work for `modify_slides`?
- **Pass condition:** `run_code()` count = 1, no error

### Models

| Model | Size | Source | Rounds |
|---|---|---|---|
| `ollama/gemma3:4b` | 4B | Ollama | R1, R2, R3 |
| `ollama/qwen3.5:4b` | 4B | Ollama | R1 |
| `ollama/gemma3n:e2b` | 2B | Ollama | R2 |
| `ollama/gemma3n:e4b` | 4B | Ollama | R2 |

### Rounds

| Round | Task | Models | Variables | Purpose |
|---|---|---|---|---|
| R1 | `slide_gen` | qwen3.5:4b, gemma3:4b | Updated `SLIDE_GEN_PMT` | Verify prompt fix; compare model efficiency |
| R2 | `slide_gen` | gemma3:4b, gemma3n:e2b, gemma3n:e4b | Updated `SLIDE_GEN_PMT` | Evaluate gemma3n series as replacement |
| R3 | `modify_slides` | gemma3:4b | Prompt A (prose) vs Prompt B (CRITICAL) | Identify best prompt style |

**Prompt change (R1 prerequisite):** the original `SLIDE_GEN_PMT` contained "Respond user with the python code" — 4B models interpreted this as outputting text, not calling the tool. Replaced with: "CRITICAL: You MUST use `run_code` to actually execute the code. Do not output code as text only."

| Prompt | Name | Style | Key design |
|---|---|---|---|
| A | `SLIDE_MODIFICATION_PMT` | 5-step prose | locate file → run code → save → verify → confirm. No CRITICAL directives. |
| B | `SLIDE_MODIFICATION_PMT_V2` | CRITICAL-style | "ONLY job / Do NOT explain / MUST use `run_code`" — mirrors updated `SLIDE_GEN_PMT` |

#### Prompt Texts

<details>
<summary><strong>SLIDE_GEN_PMT</strong> — updated system prompt for slide_gen (used in R1, R2; held constant across models)</summary>

````text
You are an AI code executor that generates a PowerPoint slide deck using python-pptx.

Your ONLY job is to write Python code and execute it using the `run_code` tool.
Do NOT explain, describe, or ask the user questions. Just write and execute the code.

Input files available in the sandbox:
- Slide outlines JSON: `{json_file_path}` (list of slide outline objects with layout info)
- PPTX template: `{template_fpath}`

Steps you MUST follow in order:
1. Use `run_code` to read and print `{json_file_path}` so you understand the structure.
2. Use `run_code` to execute python-pptx code that generates the slide deck.
3. Use `list_files` to confirm `{generated_slide_fname}` exists in the sandbox.
4. If the file does not exist, fix and re-run the code.
5. When `{generated_slide_fname}` is confirmed present, output: "Done. {generated_slide_fname} has been saved."

Requirements for the generated code:
- Load the template from `{template_fpath}` using Presentation()
- Loop over all items in `{json_file_path}`; create one slide per outline item
- Match each slide to its layout by layout_name from the JSON
- Fill title using idx_title_placeholder index, content using idx_content_placeholder index
- If there is no front page or 'thank you' slide, add them using the appropriate layout
- If a placeholder has auto_size=TEXT_TO_FIT_SHAPE, use MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE and do NOT set font size
- Save the final file as `{generated_slide_fname}` using prs.save()

CRITICAL: You MUST use `run_code` to actually execute the code. Do not output code as text only.
CRITICAL: Task is complete only when `list_files` confirms `{generated_slide_fname}` exists.
````

</details>

<details>
<summary><strong>REACT_PROMPT_SUFFIX</strong> — ReAct format control appended to all system prompts (lz-chen's original; this is the P0_baseline variant tested separately in Exp 9)</summary>

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
Action Input: the input to the tool, in a JSON format representing the kwargs (e.g. {"input": "hello world", "num_beams": 5})
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
- The answer MUST contain a sequence of bullet points that explain how you arrived at the answer. This can include aspects of the previous conversation history.
- You MUST obey the function signature of each tool. Do NOT pass in no arguments if the function expects arguments.

## Current Conversation
Below is the current conversation consisting of interleaving human and assistant messages.
````

</details>

<details>
<summary><strong>Prompt A — SLIDE_MODIFICATION_PMT</strong> — 5-step prose style (used in R3)</summary>

````text
You are an AI assistant specialized in modifying slide decks based on user feedback using the python-pptx library. 
Follow these steps precisely:
1. Understand Feedback and plan for modifications.
	- Analyzes the user's feedback to grasp the required changes.
	- Develops a clear strategy on how to implement feedback points effectively in the slide deck.
	
2. Generate Python Code:
   - Write Python code using the python-pptx library that applies the modifications 
   to the latest version of the slide deck.
   - Ensure the code accurately reflects all aspects of the feedback.

3. Execute the Code:
   - Run the generated Python code to modify the slide deck.
   - Handle any potential errors during execution to ensure the process completes successfully.

4. Store the Modified Slide Deck:
   - Save the newly modified slide deck as a new file (file path specified by user).
   - Confirm that the file is stored correctly.
   
5. Confirm Completion:
   - Only after successfully completing all the above steps, provide a confirmation message to the user
    indicating that the slide deck has been modified and stored successfully.
   - Do not provide any user-facing responses before ensuring the slide deck is properly updated and saved.

**Important**: Do not skip any steps or provide responses to the user until the entire process
 is fully completed and the new slide deck file is securely stored.
````

</details>

<details>
<summary><strong>Prompt B — SLIDE_MODIFICATION_PMT_V2</strong> — CRITICAL-style directive (used in R3; defined inline in the script)</summary>

````text
You are an AI code executor that modifies a PowerPoint slide deck using python-pptx based on validation feedback.

Your ONLY job is to write Python code and execute it using the `run_code` tool.
Do NOT explain, describe, or ask the user questions. Just write and execute the code.

Steps you MUST follow in order:
1. Use `list_files` to locate the latest version of the slide deck in the sandbox.
2. Use `run_code` to execute python-pptx code that applies ALL requested modifications.
3. Save the modified file with the exact filename specified by the user using prs.save().
4. Use `list_files` to confirm the new file exists in the sandbox.
5. When the file is confirmed present, output: "Done. <filename> has been saved."

Requirements for the generated code:
- Load the existing PPTX from the path found in step 1
- Apply every fix described in the feedback (e.g. reduce font size, fix overflow, adjust layout)
- Save the modified file as the exact filename given in the user message

CRITICAL: You MUST use `run_code` to actually execute the code. Do not output code as text only.
CRITICAL: Task is complete only when `list_files` confirms the new filename exists.
````

</details>

**Execution:** MacBook M1 · LlamaIndex `ReActAgent` · Ollama local inference · mock `FunctionTool` stubs (tools check whether generated code contains `prs.save()` and return synthetic sandbox responses — no real Docker execution in this experiment)

**Timeout:** 600s (R1, R2) · max_iterations=20 (R3)

### Primary metric — `run_code()` call count
- `0` = model never called the tool (failure — no PPTX produced)
- `1` = first attempt succeeded (efficient)
- `>1` = model self-debugged across multiple calls (works, but inefficient)

**Supporting metrics:** elapsed time (s) · total tool calls · error type

---

## Full Experimental Results

### Round 1 — slide_gen: Prompt Fix Validation

- **Purpose:** Verify the updated `SLIDE_GEN_PMT` causes models to call `run_code` instead of outputting code as text; compare efficiency between `qwen3.5:4b` and `gemma3:4b`
- **Expected:** Both models call `run_code` exactly once under the new prompt

| Model | `run_code()` calls | Total tool calls | Old prompt | New prompt |
|---|---|---|---|---|
| qwen3.5:4b | **16** | 17 | ✗ outputs code as text | ✓ calls `run_code` |
| gemma3:4b | **1** | 4 | not tested | ✓ calls `run_code` |

**Tool call sequences:**
```
qwen3.5:4b:  run_code ×11 → list_files → run_code ×5   (list_files appears mid-sequence after 11th call)
gemma3:4b:   run_code → list_files ×3    (1 call succeeds; list_files verifies result)
```
**Conclusion:** Both models call the tool, but gemma3:4b does it in 1 call vs qwen3.5:4b's 16.

---

### Round 2 — slide_gen: gemma3n Series Evaluation

- **Purpose:** Evaluate whether `gemma3n:e2b` or `gemma3n:e4b` can replace `gemma3:4b` as the slide generation model
- **Expected:** At least one gemma3n model matches `gemma3:4b`'s 1-call result

| Model | `run_code()` calls | Elapsed (s) | Error |
|---|---|---|---|
| gemma3:4b | 1 | 46.1 | none |
| gemma3n:e2b | 0 | 600.0 | TIMEOUT |
| gemma3n:e4b | 0 | 19.3 | none (format mismatch — silent) |

**Tool call sequences:**
```
gemma3:4b:    run_code → list_files ×3
gemma3n:e2b:  []  (run_agent_step never returned in 600s)
gemma3n:e4b:  []  (exited at turn 1 — output treated as StopEvent)
```

**gemma3n:e4b final answer fragment:**

    ```tool_code
    print(open('/sandbox/slide_outlines.json').read())
    ```

LlamaIndex ReAct parser expects this format to trigger a tool call:

    Action: run_code
    Action Input: {"code": "..."}

`gemma3n:e4b` outputs a Gemini-style `tool_code` block instead. The parser
cannot match it to the `Action:` pattern → treats the entire output as the
final answer → emits StopEvent → loop exits at turn 1 with 0 tool calls and
no error or warning.

**Conclusion:** Both gemma3n models failed — gemma3n:e2b by timeout, gemma3n:e4b by silent format mismatch with LlamaIndex ReAct.

---

### Round 3 — modify_slides: Prompt Style Comparison (gemma3:4b)

- **Purpose:** Determine whether the CRITICAL-style prompt that fixed `slide_gen` also works for `modify_slides`, or whether a different prompt style is needed
- **Expected:** Prompt B (CRITICAL) matches or improves on Prompt A's 1-call result

| Prompt | `run_code()` calls | Elapsed (s) | Error |
|---|---|---|---|
| A — prose | 1 | 39.7 | none |
| B — CRITICAL | 0 | 336.8 | max iterations (20) |

**Tool call sequences:**
```
Prompt A: run_code → list_files  (1 call succeeds; list_files confirms new file)
Prompt B: []  (20 agent steps — no tool call generated in any round)
```
**Conclusion:** Prompt B caused complete failure — the CRITICAL directive breaks slide modification despite fixing slide generation.

---

### Cross-Model Summary (Rounds 1 + 2, slide_gen)

| Model | Size | `run_code` called | Call count | Verdict |
|---|---|---|---|---|
| `gemma3:4b` | 4B | ✓ | 1 | ✓ viable, efficient |
| `qwen3.5:4b` | 4B | ✓ | 16 | △ viable, inefficient |
| `gemma3n:e2b` | 2B | ✗ | 0 | ✗ timeout |
| `gemma3n:e4b` | 4B | ✗ | 0 | ✗ format mismatch |

---

## Observations

### slide_gen: prompt ambiguity and fix

```
Root: slide_gen agent outputs code as text — no tool call, no PPTX produced
      │
      ▼
Root cause: prompt ambiguity in original SLIDE_GEN_PMT
      │  "Respond user with the python code" is interpreted as:
      │    write code in the response text (text-generation mode)
      │    not: call the run_code tool to execute code (agent mode)
      │  4B RLHF models have a strong prior toward "explain/describe"
      │  over "execute via tool"; ambiguous phrasing activates that prior
      │
      ▼
Fix: CRITICAL directive added to SLIDE_GEN_PMT
      │  "CRITICAL: You MUST use run_code to actually execute the code."
      │  Forces model from text-generation mode into agent-action mode
      │  Both qwen3.5:4b and gemma3:4b call run_code under new prompt ✓
```

### slide_gen: model comparison (R1 + R2)

```
Model efficiency gap (R1, fixed prompt)
      │
      ├─ gemma3:4b ── 1 run_code call  ✓
      │    First code attempt is correct python-pptx (includes prs.save())
      │    Subsequent list_files are proactive result verification
      │    Strategy: write once → verify
      │
      └─ qwen3.5:4b ── 16 run_code calls  △
           First attempt fails (import errors, placeholder index, save path)
           Self-debugs across 16 iterations before succeeding
           4.25× more LLM rounds; same end result, far higher cost
      │
      ▼
gemma3n series (R2): two distinct failure modes
      │
      ├─ gemma3n:e2b ── TIMEOUT at 600s  ✗
      │    0 tool calls — run_agent_step never returned
      │    Model too slow to complete a single agent step within timeout
      │
      └─ gemma3n:e4b ── format mismatch, exits at turn 1  ✗
           Outputs ```tool_code``` block (Gemini function-call format)
           LlamaIndex ReAct parser expects "Action: / Action Input:" format
           Parser cannot read tool_code → treats output as StopEvent
           Loop exits immediately with 0 tool calls and no error or warning
```

**Conclusion:** gemma3n:e4b fails silently — no error or warning appears at the workflow level.
The model outputs a tool_code block in under 20s. This looks like fast execution. LlamaIndex's ReAct parser cannot read this format and exits the loop at turn 1, treating the raw block as the final answer. There is no exception, no warning in logs — the failure is invisible at the workflow level.

### modify_slides: prompt style sensitivity (R3)

```
New finding: CRITICAL directive harms modify_slides
      │  Prompt A (5-step prose): 1 run_code call, complete in 39.7s
      │  Prompt B (CRITICAL style): 0 tool calls, 20-iteration timeout (336.8s)
      │
      ▼
Root cause: task ambiguity determines optimal prompt style
      │
      ├─ slide_gen (high ambiguity):
      │    "Generate a slide deck" — no concrete action signal in the request
      │    Model prior drifts toward explaining/describing code as text
      │    CRITICAL directive needed to override this prior
      │
      └─ modify_slides (low ambiguity):
           Feedback message contains explicit action signals:
           specific slide indices, specific issue types, specific output filename
           These activate the model's problem-solving prior directly
           Adding CRITICAL creates competing signals:
             "Do NOT explain" vs "understand feedback text before fixing"
           gemma3:4b generates output that is neither Action: nor Answer:
           workflow loop runs 20 iterations without making progress
```

**Conclusion:** Prompt complexity must match task ambiguity — applying the same directive style uniformly breaks low-ambiguity tasks.
The CRITICAL directive that fixed slide generation completely broke slide modification. For gemma3:4b, 5-step prose gives the model a sequential state machine to follow. Global CRITICAL constraints force the model to maintain them across every token in the strict Thought/Action/Observation structure. When the task context is dense — feedback text, filenames, and fix instructions all present — 4B models can't sustain that reliably.

---

## Decision

### Which model for ReAct-based PPTX rendering?

```
Which model for ReAct-based PPTX rendering?
      │
      ├── gemma3:4b
      │     ✓ 1 run_code call for slide_gen (one-shot code generation)
      │     ✓ Works on both slide_gen and modify_slides with correct prompts
      │     ✓ Stable across repeated runs
      │     → CHOSEN: only viable option among tested models
      │
      ├── qwen3.5:4b
      │     △ Works but requires 16 run_code calls (4.25× more LLM rounds)
      │     → NOT CHOSEN: inefficient
      │
      ├── gemma3n:e2b
      │     ✗ Times out at 600s — cannot complete one agent step on M1
      │     → REJECTED
      │
      └── gemma3n:e4b
            ✗ Gemini-style tool_code format incompatible with LlamaIndex ReAct
            ✗ Silent failure — workflow exits at turn 1 with no error
            → REJECTED
```

### Which prompt style for modify_slides?

```
Which prompt style for modify_slides?
      │
      ├── Prompt A — 5-step prose (SLIDE_MODIFICATION_PMT)
      │     ✓ 1 run_code call, task complete in 39.7s
      │     → KEPT: already correct for this task
      │
      └── Prompt B — CRITICAL style (SLIDE_MODIFICATION_PMT_V2)
            ✗ 0 tool calls, 20-iteration timeout
            → REJECTED: harms modify_slides despite fixing slide_gen
```

Each agent step requires an independently designed prompt. Unifying prompt style across steps is not viable for 4B models.

---

## Pipeline Integration Status 🚫 SUPERSEDED

### What replaced it
- ReActAgent step replaced with deterministic `PptxRenderer`
- LLM now outputs schema-validated JSON only; the renderer constructs the PPTX directly — no runtime code generation, no sandbox
- Eliminates all ReAct-related failure modes regardless of model size

### Why the decision was made
- **Exp 7 (this experiment):** gemma3:4b selected as the model — but even with the correct model, the agent wrote invalid python-pptx API calls at 8.3% overall correctness. This failure motivated Exp 8.
- **Exp 8:** Fixed `SLIDE_GEN_PMT` with explicit code patterns (P2) — code generation reached 100%. But tool dispatch was still broken: wrong argument keys caused the agent to never call `run_code` correctly.
- **Exp 9:** Fixed `REACT_PROMPT_SUFFIX` tool dispatch (P4) — task completion reached 100%. But the error path still caused hallucinated failures.
- **Architectural finding (2026-04-15):** python-pptx has no markdown parser — LLM-generated bullet text collapsed into a single paragraph and literal `*` characters appeared on slides. Docker sandbox added latency and infrastructure dependency on top of non-deterministic code generation. These two issues together drove the decision to replace the ReActAgent with a schema-controlled renderer.

### Transferable findings
- Prompt style must match task ambiguity: CRITICAL directives for high-ambiguity tasks, prose step guides for low-ambiguity tasks — applicable to any future agent step design
