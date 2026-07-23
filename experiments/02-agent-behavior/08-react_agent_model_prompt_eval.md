# Experiment 8 — ReAct Agent: Model and Prompt Selection for PPTX Rendering

## Task Context

This experiment targets **Step 6 — PPTX Rendering** (original ReAct approach) from the system architecture (README → System Architecture).

lz-chen's original renders slides through a ReActAgent bound to Azure GPT-4o. The model writes python-pptx code as free text, and the agent executes it in an Azure sandbox. This experiment tests whether the same ReAct loop holds up when the model is swapped for a local, ~4B-parameter class run through Ollama on an M1 MacBook. It is the first of three experiments — Exp 8 → Exp 9 → Exp 10 — that progressively test this ReActAgent approach, motivating its eventual replacement by deterministic rendering.

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
lz-chen's original tool and prompt names; this experiment substitutes `llm-sandbox`'s equivalent
execution tool (tested as `run_code` throughout this report) because Azure access was unavailable.
──────────────────────────────────────────────────────────────────────────────────────
 slide_outlines.json + PPTX template
       │
       ▼
 ┌─── EXPERIMENT TARGET ──────────────────────────────────────────────────────────────┐
 │                                                                                    │
 │  ① [slide_gen]                                                                    │
 │  ┌─── Original (lz-chen) ────────────────┬─── My Implementation ──────────────┐    │
 │  │ ReActAgent · Azure GPT-4o             │ ReActAgent · local 4B LLM (Ollama) │    │
 │  │ SLIDE_GEN_PMT · max_iterations=50     │ SLIDE_GEN_PMT · max_iterations=50  │    │
 │  │ Tools: code_interpreter, list_files,  │ Tools: run_code, list_files,       │    │
 │  │   upload_file, get_all_layout         │   upload_file, get_all_layout      │    │
 │  │ Sandbox: Azure managed container      │ Sandbox: llm-sandbox (Docker)      │    │
 │  └───────────────────────────────────────┴────────────────────────────────────┘    │
 │       │                                                                            │
 │       ▼  paper_summaries.pptx                                                      │
 │  ② [validate_slides]   VLM per slide image  ◄──────────────────────────────────┐  │
 │       │                                                                         │  │
 │       ├─ all OK ──────────────────────────────────── stop: final.pptx ✓         │  │
 │       │                                                                         │  │
 │       └─ issues found AND n_retry < 2                                           │  │
 │              │                                                                  │  │
 │              ▼                                                                  │  │
 │  ③ [modify_slides]                                                             │  │
 │  ┌─── Original (lz-chen) ────────────────┬─── My Implementation ──────────────┐ │  │
 │  │ ReActAgent · Azure GPT-4o             │ ReActAgent · local 4B LLM (Ollama) │ │  │
 │  │ SLIDE_MODIFICATION_PMT                │ SLIDE_MODIFICATION_PMT             │ │  │
 │  │ max_iterations=50                     │ max_iterations=50                  │ │  │
 │  │ Sandbox: Azure managed container      │ Sandbox: llm-sandbox (Docker)      │ │  │
 │  └───────────────────────────────────────┴────────────────────────────────────┘ │  │
 │     saves paper_summaries_v{n_retry}.pptx                                       │  │
 │              │                                                                  │  │
 │              └──────────────────────────────────────────────────────────────────┘  │
 │                    (up to 2 retries; n_retry ≥ 2 → ✗)                              │
 │                                                                                    │
 └────────────────────────────────────────────────────────────────────────────────────┘
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

<details>
<summary><strong>`slide_gen` — internal ReAct loop</strong> (expand for a turn-by-turn walkthrough)</summary>

```
Input: user message = "example outline item in JSON is {...}, generate a slide deck"
Tools available: run_code, list_files, upload_file, get_all_layout

┌─ Turn 1 ─────────────────────────────────────────────────────────────┐
│ Thought: I need to write python-pptx code and execute it              │
│ Action: run_code                                                       │
│ Action Input: {"code": "prs = Presentation(...); ... prs.save(...)"}  │
│        ▼ tool actually executes the code (mock: checks for prs.save())│
│ Observation: "Execution successful. Files created:                    │
│               /sandbox/paper_summaries.pptx"                          │
└────────────────────────────────────────────────────────────────────┘
┌─ Turn 2 (some models add this verification step) ───────────────────┐
│ Thought: I should confirm the file exists                             │
│ Action: list_files                                                     │
│ Observation: ["pptx-template.pptx", "slide_outlines.json",             │
│               "paper_summaries.pptx"]                                  │
└────────────────────────────────────────────────────────────────────┘
┌─ Final turn ──────────────────────────────────────────────────────────┐
│ Answer: "Done. paper_summaries.pptx has been saved."                   │
└────────────────────────────────────────────────────────────────────┘

Failure mode: if the model outputs code as Answer text instead of an
Action: run_code line, the tool never executes — 0 calls, no PPTX file
is ever produced, even though the code itself may be correct.
```

</details>

<details>
<summary><strong>`modify_slides` — internal ReAct loop</strong> (expand for a turn-by-turn walkthrough)</summary>

```
Input: user message = "latest deck is at /sandbox/paper_summaries.pptx,
  feedback: {slide_idx:2 text overflow, slide_idx:4 title cut off},
  save as paper_summaries_v1.pptx"
Tools available: same as slide_gen

┌─ Turn 1 ─────────────────────────────────────────────────────────────┐
│ Thought: confirm the existing file first                              │
│ Action: list_files                                                     │
│ Observation: ["pptx-template.pptx", "slide_outlines.json",             │
│               "paper_summaries.pptx"]                                  │
└────────────────────────────────────────────────────────────────────┘
┌─ Turn 2 ─────────────────────────────────────────────────────────────┐
│ Thought: apply the feedback — shrink font on slide 2, widen title      │
│          box on slide 4                                                │
│ Action: run_code                                                       │
│ Action Input: {"code": "prs = Presentation('paper_summaries.pptx');    │
│   ... prs.save('paper_summaries_v1.pptx')"}                           │
│ Observation: "Execution successful. Files created:                    │
│               /sandbox/paper_summaries_v1.pptx"                       │
└────────────────────────────────────────────────────────────────────┘
┌─ Final turn ──────────────────────────────────────────────────────────┐
│ Answer: "Done. paper_summaries_v1.pptx has been saved."                │
└────────────────────────────────────────────────────────────────────┘

Failure mode: if the model's output is neither a valid Action: line nor
an Answer: line, the loop repeats without progress until it hits the
iteration/timeout limit — this is what happens with Prompt B in
Sub-exp 3 below.
```

</details>

---

## Summary

- **Problem:** lz-chen's original drives PPTX generation through a ReActAgent loop bound to Azure GPT-4o, where the model writes python-pptx code as free-form text and the agent parses it into tool calls. Nothing in that design indicates whether the same loop, prompts, and tool-parsing behavior hold when the underlying model is a class smaller than GPT-4o.
- **Solution:** An ablation tests four local Ollama models across both ReAct sub-steps — slide generation and slide modification — isolating model choice from prompt style as separate variables.
  - Part A — model comparison for slide generation across four candidate models
  - Part B — prompt style comparison for slide modification using the strongest candidate from Part A
- **Result:** `gemma3:4b` is the only model that completes both sub-steps in a single tool call; the directive-style prompt that fixes slide generation breaks slide modification completely, 0 tool calls against a working 1-call baseline.

---

## Experiment Setup

> This experiment's approach was superseded by deterministic rendering — no ✅ applies. See Pipeline Integration Status.

### Sub-Experiments

| Sub-exp | Name | Task | Models | Variables | Purpose |
|---|---|---|---|---|---|
| Sub-exp 1 | Tool-Call Fix Verification | `slide_gen` | `qwen3.5:4b`, `gemma3:4b` | Updated `SLIDE_GEN_PMT` | Verify prompt fix; compare model efficiency |
| Sub-exp 2 | gemma3n Series Evaluation | `slide_gen` | `gemma3:4b`, `gemma3n:e2b`, `gemma3n:e4b` | Updated `SLIDE_GEN_PMT` | Evaluate gemma3n series as replacement |
| Sub-exp 3 | Prompt Generalization Test | `modify_slides` | `gemma3:4b` | Prompt A (baseline) vs Prompt B (CRITICAL) | Identify best prompt style |

**Problem (motivating Sub-exp 1):** lz-chen's original `SLIDE_GEN_PMT` says "Respond user with the python code that generates the slide deck" — phrasing that reads as an instruction to write the code into the answer text, not to execute it via a tool. 4B models followed this literally: they produced correct code but never called `run_code`, so no PPTX file was ever created.

**Fix:** Replaced with an explicit tool-call directive: "CRITICAL: You MUST use `run_code` to actually execute the code. Do not output code as text only."

### Shared ReAct Configuration

| Parameter | Value |
|---|---|
| Agent framework | LlamaIndex `ReActAgent` |
| Inference | Ollama local inference (M1 MacBook) |
| Sandbox representation | Mock `FunctionTool` stubs — tools check whether generated code contains `prs.save()` and return synthetic sandbox responses; no real Docker execution in this experiment |
| Temperature | 0.1 |
| Max tokens | 4096 |
| Timeout | 600s (Sub-exp 1, Sub-exp 2) |
| Max iterations | 20 (Sub-exp 3) |

### Models Compared

| Model | Size | Source | Sub-exp |
|---|---|---|---|
| `ollama/gemma3:4b` | 4B | Ollama | Sub-exp 1, Sub-exp 2, Sub-exp 3 |
| `ollama/qwen3.5:4b` | 4B | Ollama | Sub-exp 1 |
| `ollama/gemma3n:e2b` | 2B | Ollama | Sub-exp 2 |
| `ollama/gemma3n:e4b` | 4B | Ollama | Sub-exp 2 |

| Prompt | Name | Style | Key design |
|---|---|---|---|
| A (baseline) | `SLIDE_MODIFICATION_PMT` | 5-step prose | lz-chen's original prompt, verbatim — locate file → run code → save → verify → confirm. No CRITICAL directives. |
| B | `SLIDE_MODIFICATION_PMT_V2` | CRITICAL-style | "ONLY job / Do NOT explain / MUST use `run_code`" — mirrors updated `SLIDE_GEN_PMT` |

#### Prompt Texts

<details>
<summary><strong>SLIDE_GEN_PMT (original — baseline)</strong> — lz-chen's unmodified prompt; the "Respond user with the python code" phrasing is the root cause fixed below</summary>

````text
You are an AI that generate slide deck from a given slide outlines and uses the
 template file provided. Write python-pptx code for generating the slide deck by loop over the slide 
 outlines provided.
You will be provided with a json file `{json_file_path}` that contains a list of slide outlines
 and layout to use from the template.
The template file is located at `{template_fpath}`.
If you can't find those files at remote location, you need to upload them.
Respond user with the python code that generates the slide deck.

Requirement:
- If there is no front page or 'thank you' page, create them by using the related layout template in the
 layout information provided, DO NOT assume the index of the layout for them
- If the placeholder chosen has text auto_size set to TEXT_TO_FIT_SHAPE, make sure to set the
 text to fit the shape (use MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE) and DO NOT set a font size
- One slide page per outline item that you are given, fill in all the title and content you are given
- Use layout and text box index according to what is given in each of the slide content item 
- Vary the content layout of the slides to make the presentation engaging
- Generate the python code before you try to execute it
- Save the final slide pptx file with name `{generated_slide_fname}`
````

</details>

<details>
<summary><strong>SLIDE_GEN_PMT (fixed — used in this experiment)</strong> — updated system prompt for `slide_gen` (used in Sub-exp 1, Sub-exp 2; held constant across models)</summary>

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
<summary><strong>REACT_PROMPT_SUFFIX (original — baseline)</strong> — ReAct format control appended to all system prompts (lz-chen's original; this is the P0_baseline variant tested separately in Exp 10)</summary>

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
<summary><strong>Prompt A — SLIDE_MODIFICATION_PMT (original — baseline)</strong> — lz-chen's unmodified prompt, verbatim; 5-step prose style (used in Sub-exp 3)</summary>

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
<summary><strong>Prompt B — SLIDE_MODIFICATION_PMT_V2</strong> — CRITICAL-style directive (used in Sub-exp 3; defined inline in the script)</summary>

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

### Metrics

**Primary metric — `run_code()` call count**
- `0` = model never called the tool (failure — no PPTX produced)
- `1` = first attempt succeeded (efficient)
- `>1` = model self-debugged across multiple calls (works, but inefficient)

**Supporting metrics:** elapsed time (s) · total tool calls · error type

---

## Full Experimental Results

### Sub-exp 1 — `slide_gen`: Tool-Call Fix Verification

- **Purpose:** Verify the updated `SLIDE_GEN_PMT` causes models to call `run_code` instead of outputting code as text; compare efficiency between `qwen3.5:4b` and `gemma3:4b`
- **Expected:** Both models call `run_code` exactly once under the new prompt

| Model | `run_code()` calls | Total tool calls | Old prompt | New prompt |
|---|---|---|---|---|
| `qwen3.5:4b` | 16 | 17 | ✗ outputs code as text | ✓ calls `run_code` |
| `gemma3:4b` | **1** | **4** | not tested | ✓ calls `run_code` |

**Tool call sequences:**
```
qwen3.5:4b:  run_code ×11 → list_files → run_code ×5   (list_files appears mid-sequence after 11th call)
gemma3:4b:   run_code → list_files ×3    (1 call succeeds; list_files verifies result)
```
**Conclusion:** Both models recover from the original text-output failure once the prompt explicitly names the tool, but the fix does not make them equally efficient.

---

### Sub-exp 2 — `slide_gen`: gemma3n Series Evaluation

- **Purpose:** Evaluate whether `gemma3n:e2b` or `gemma3n:e4b` can replace `gemma3:4b` as the slide generation model
- **Expected:** At least one gemma3n model matches `gemma3:4b`'s 1-call result

| Model | `run_code()` calls | Elapsed (s) | Error |
|---|---|---|---|
| `gemma3:4b` | **1** | **46.1** | none |
| `gemma3n:e2b` | 0 | 600.0 | TIMEOUT |
| `gemma3n:e4b` | 0 | 19.3 | none (format mismatch — silent) |

**Tool call sequences:**
```
gemma3:4b:    run_code → list_files ×3
gemma3n:e2b:  []  (run_agent_step never returned in 600s)
gemma3n:e4b:  []  (exited at turn 1 — output treated as StopEvent)
```

**`gemma3n:e4b` final answer fragment:**

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

**Conclusion:** Neither gemma3n variant reaches a single tool call, closing off the smaller-parameter path as a substitute for `gemma3:4b`.

---

### Sub-exp 3 — `modify_slides`: Prompt Generalization Test (`gemma3:4b`)

Sub-exp 1 fixed `slide_gen` by adding an explicit CRITICAL-style directive ("You MUST use `run_code`") to the prompt. This sub-experiment tests whether the same directive style also works for a different task — `modify_slides`, which edits an already-generated slide deck based on feedback (e.g., shrink an overflowing font on one slide, widen a cut-off title on another) instead of generating one from scratch. The model is fixed to `gemma3:4b`, the winner from Sub-exp 1/2.

- **Purpose:** Determine whether the CRITICAL-style prompt that fixed `slide_gen` also works for `modify_slides`, or whether a different prompt style is needed
- **Expected:** Prompt B (CRITICAL) matches or improves on Prompt A's 1-call result

| Prompt | `run_code()` calls | Elapsed (s) | Error |
|---|---|---|---|
| A — prose (baseline) | **1** | **39.7** | none |
| B — CRITICAL (rewrite) | 0 | 336.8 | max iterations (20) |

**Tool call sequences:**
```
Prompt A: run_code → list_files  (1 call succeeds; list_files confirms new file)
Prompt B: []  (20 agent steps — no tool call generated in any round)
```
**Conclusion:** The same directive that fixed slide generation makes slide modification fail completely, showing the two sub-steps need independently tuned prompts.

---

### Cross-Model Summary (Sub-exp 1 + 2, `slide_gen`)

| Model | Size | `run_code` called | Call count | Verdict |
|---|---|---|---|---|
| `gemma3:4b` | 4B | ✓ | 1 | ✓ viable, efficient |
| `qwen3.5:4b` | 4B | ✓ | 16 | △ viable, inefficient |
| `gemma3n:e2b` | 2B | ✗ | 0 | ✗ timeout |
| `gemma3n:e4b` | 4B | ✗ | 0 | ✗ format mismatch |

---

## Observations

### Why do both gemma3n variants fail to produce a single tool call?

`gemma3n:e2b` stalls before completing a single agent step, and `gemma3n:e4b` exits after one turn because it outputs a Gemini-style `tool_code` block that LlamaIndex's ReAct parser can't match to the `Action:` format — neither failure raises an exception or warning.

- `gemma3n:e2b` times out after 600s with 0 tool calls.
- `gemma3n:e4b` exits after 19.3s, also with 0 tool calls.

### Why does the directive-style prompt that fixed slide generation break slide modification?

Slide modification's feedback message already supplies explicit action signals — specific slide indices, issue descriptions, and an output filename — so adding directive constraints on top creates competing signals `gemma3:4b` can't resolve into either an `Action:` or `Answer:` line.

- Prompt A (5-step prose) completes `modify_slides` in 1 `run_code` call, 39.7s.
- Prompt B (CRITICAL-style) produces 0 tool calls after 20 iterations, timing out at 336.8s.

---

## Decision

### Which model for ReAct-based slide generation?

`gemma3:4b` is selected — it is the only tested model that reaches a working PPTX in a single tool call, with a stable repeat result.

- `gemma3:4b`: 1 `run_code` call in both the initial run and the repeat run (46.1s elapsed on repeat).

### Which prompt style for slide modification?

`Prompt A` — the existing 5-step prose format — is selected over the CRITICAL-style rewrite for its higher reliability on this sub-step.

- Prompt A: 1 `run_code` call, 39.7s.

---

## Pipeline Integration Status 🚫 SUPERSEDED

ReActAgent-driven `slide_gen`/`modify_slides` were replaced by a deterministic `PptxRenderer` (schema-validated JSON in, no runtime code generation or sandbox). Exp 9 refined the task prompt further. Exp 10 then found prompt engineering alone couldn't fix a persistent-error loop failure under real error conditions. The transferable lesson — that prompt style must match task ambiguity — still applies to future agent step design.
