"""
Agent Behavior Test: ReAct Agent for Slide Generation & Modification
=====================================================================
Tests two ReAct Agent tasks used in the PPTX generation pipeline:

  Task 1 — slide_gen (Rounds 1+2):
    Tests whether models correctly follow SLIDE_GEN_PMT to call run_code()
    and generate a PPTX file from slide_outlines.json.
    Models: gemma3:4b, gemma3n:e2b, gemma3n:e4b

  Task 2 — modify_slides (Round 3):
    Tests whether gemma3:4b correctly follows SLIDE_MODIFICATION_PMT.
    Compares two prompts: current (Prompt A) vs improved CRITICAL-style (Prompt B).
    Model: gemma3:4b (confirmed best ReAct performer from Rounds 1+2)

Experiment report: react_agent_slide_gen.md

Run from project root:
    micromamba run -n py3.12 python poc/agent-behavior-test/react_agent_slide_gen.py

Prerequisite: Ollama must be running locally and OLLAMA_API_BASE set in .env.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from prompts.prompts import SLIDE_GEN_PMT, REACT_PROMPT_SUFFIX, SLIDE_MODIFICATION_PMT

from llama_index.llms.litellm import LiteLLM
from llama_index.core.agent.workflow import ReActAgent
from llama_index.core.tools import FunctionTool
from llama_index.core import PromptTemplate


# ══════════════════════════════════════════════════════════════════════════════
# Prompt B for modify_slides (improved, CRITICAL-guard style)
# ══════════════════════════════════════════════════════════════════════════════

SLIDE_MODIFICATION_PMT_V2 = """
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
"""


# ══════════════════════════════════════════════════════════════════════════════
# Shared helper
# ══════════════════════════════════════════════════════════════════════════════

class ToolCallLog:
    def __init__(self):
        self.calls: list[dict] = []

    def record(self, tool_name: str, **kwargs):
        self.calls.append({"tool": tool_name, **kwargs})

    def names(self) -> list[str]:
        return [c["tool"] for c in self.calls]


# ══════════════════════════════════════════════════════════════════════════════
# Task 1 — slide_gen (Rounds 1+2)
# ══════════════════════════════════════════════════════════════════════════════

def make_tools_slide_gen(log: ToolCallLog) -> list[FunctionTool]:
    """Mock tools for slide_gen: sandbox starts empty (no existing pptx)."""

    def run_code(code: str) -> str:
        """Execute Python code in the sandbox environment."""
        saves_pptx = "prs.save" in code or ".save(" in code
        log.record("run_code", code_len=len(code), saves_pptx=saves_pptx,
                   code_snippet=code[:300])
        if saves_pptx:
            return (
                "Execution successful.\n"
                "stdout: (no output)\n"
                "Files created: /sandbox/paper_summaries.pptx"
            )
        return (
            "Execution successful.\n"
            "stdout: (no output)\n"
            "WARNING: paper_summaries.pptx was NOT found in /sandbox/. "
            "Make sure your code calls prs.save('paper_summaries.pptx')."
        )

    def list_files() -> str:
        """List all files currently in the sandbox."""
        log.record("list_files")
        pptx_saved = any(c.get("saves_pptx") for c in log.calls if c["tool"] == "run_code")
        files = ["pptx-template.pptx", "slide_outlines.json"]
        if pptx_saved:
            files.append("paper_summaries.pptx")
        return json.dumps(files)

    def upload_file(local_file_path: str) -> str:
        """Upload a local file to the sandbox."""
        log.record("upload_file", path=local_file_path)
        return f"Uploaded {local_file_path} → /sandbox/{Path(local_file_path).name}"

    def get_all_layout() -> str:
        """Get all slide layout information from the PPTX template."""
        log.record("get_all_layout")
        return json.dumps([
            {
                "layout_name": "Title and Content",
                "placeholders": [
                    {"index": 0, "name": "Title 1",
                     "font_size": 32.0, "auto_size": None,
                     "left": 457200, "top": 274638, "width": 8229600, "height": 1143000},
                    {"index": 1, "name": "Content Placeholder 2",
                     "font_size": None, "auto_size": "TEXT_TO_FIT_SHAPE",
                     "left": 457200, "top": 1600200, "width": 8229600, "height": 4525963},
                ],
                "number_of_shapes": 3,
                "has_background": True,
            },
            {
                "layout_name": "Title Slide",
                "placeholders": [
                    {"index": 0, "name": "Title 1",
                     "font_size": 44.0, "auto_size": None,
                     "left": 457200, "top": 1600200, "width": 8229600, "height": 1143000},
                    {"index": 1, "name": "Subtitle 2",
                     "font_size": 28.0, "auto_size": "SHAPE_TO_FIT_TEXT",
                     "left": 457200, "top": 2971800, "width": 8229600, "height": 1143000},
                ],
                "number_of_shapes": 2,
                "has_background": True,
            },
        ])

    return [
        FunctionTool.from_defaults(fn=run_code,       name="run_code"),
        FunctionTool.from_defaults(fn=list_files,     name="list_files"),
        FunctionTool.from_defaults(fn=upload_file,    name="upload_file"),
        FunctionTool.from_defaults(fn=get_all_layout, name="get_all_layout"),
    ]


# Outline fixture (same structure as real slide_outlines.json items)
OUTLINE_EXAMPLE = {
    "title": "Attention Is All You Need",
    "content": (
        "* Key Approach: Transformer using self-attention, no recurrence\n"
        "* Key Components: Multi-head attention, positional encoding, encoder-decoder\n"
        "* Training: Adam optimizer, label smoothing, warmup schedule\n"
        "* Dataset: WMT 2014 English-German / English-French\n"
        "* Evaluation: BLEU score, achieves 28.4 on EN-DE\n"
        "* Conclusion: Attention-only model outperforms RNN/CNN baselines"
    ),
    "layout_name": "Title and Content",
    "idx_title_placeholder": "0",
    "idx_content_placeholder": "1",
}


async def run_slide_gen_test(model: str) -> dict:
    log = ToolCallLog()
    tools = make_tools_slide_gen(log)

    # Exact same prompt construction as slide_gen.py
    system_prompt = (
        SLIDE_GEN_PMT.format(
            json_file_path="/sandbox/slide_outlines.json",
            template_fpath="/sandbox/pptx-template.pptx",
            generated_slide_fname="paper_summaries.pptx",
        )
        + REACT_PROMPT_SUFFIX
    )

    # extra_body think=False only applies to qwen3 models
    extra = {"extra_body": {"think": False}} if "qwen3" in model else {}
    llm = LiteLLM(
        model=model,
        temperature=0.1,
        max_tokens=4096,
        additional_kwargs=extra,
    )

    agent = ReActAgent(tools=tools, llm=llm, verbose=True, timeout=600)
    agent.update_prompts({"react_header": PromptTemplate(system_prompt)})

    # Exact same user message as slide_gen step
    user_message = (
        f"An example of outline item in json is {json.dumps(OUTLINE_EXAMPLE)},"
        f" generate a slide deck"
    )

    t_start = time.perf_counter()
    try:
        response = await agent.run(user_message)
        final_answer = str(response)
        error = None
    except Exception as e:
        final_answer = ""
        error = str(e)
    elapsed_s = time.perf_counter() - t_start

    tool_names = log.names()
    run_code_calls = [c for c in log.calls if c["tool"] == "run_code"]

    return {
        "model":                   model,
        "error":                   error,
        "elapsed_s":               round(elapsed_s, 1),
        "tool_call_sequence":      tool_names,
        "run_code_called":         "run_code" in tool_names,
        "run_code_count":          tool_names.count("run_code"),
        "any_run_code_saves_pptx": any(c.get("saves_pptx") for c in run_code_calls),
        "final_answer_has_question": "?" in final_answer[-300:],
        "final_answer_tail":       final_answer[-400:].strip(),
        "all_tool_calls":          log.calls,
    }


def print_slide_gen_results(results: list[dict]) -> None:
    print(f"\n\n{'='*70}")
    print("  TASK 1 — slide_gen: COMPARISON SUMMARY")
    print(f"{'='*70}")

    label_col = 32
    val_col   = 18
    short_names = [r["model"].replace("ollama/", "") for r in results]

    header = f"  {'Metric':<{label_col}}" + "".join(f"{n:<{val_col}}" for n in short_names)
    print(header)
    print(f"  {'-' * (label_col + val_col * len(results))}")

    def fmt(v) -> str:
        if v is True:  return "✅"
        if v is False: return "❌"
        return str(v)

    def row(label: str, *values):
        print(f"  {label:<{label_col}}" + "".join(f"{fmt(v):<{val_col}}" for v in values))

    row("Elapsed time (s)",           *[r["elapsed_s"]                for r in results])
    row("run_code() called",          *[r["run_code_called"]          for r in results])
    row("run_code() call count",      *[r["run_code_count"]           for r in results])
    row("Code actually saves pptx",   *[r["any_run_code_saves_pptx"]  for r in results])
    row("Final answer asks question", *[r["final_answer_has_question"] for r in results])
    row("Error",                      *[r["error"] or "none"          for r in results])

    print(f"\n  Tool call sequences:")
    for r in results:
        print(f"    {r['model'].replace('ollama/', '')}: {r['tool_call_sequence']}")

    print(f"\n{'='*70}")
    print("  INTERPRETATION")
    print(f"{'='*70}")

    n_called     = sum(1 for r in results if r["run_code_called"])
    n_saves_pptx = sum(1 for r in results if r["any_run_code_saves_pptx"])
    called_names  = [r["model"].replace("ollama/", "") for r in results if r["run_code_called"]]
    skipped_names = [r["model"].replace("ollama/", "") for r in results if not r["run_code_called"]]

    if n_called == 0:
        print("  → NO model called run_code().")
        print("    Likely a PROMPT issue: the prompt does not clearly instruct")
        print("    the agent to execute code. All models interpret the task")
        print("    as 'describe/output code as text', not 'execute via tool'.")
    elif n_called == len(results):
        print("  → ALL models called run_code().")
        if n_saves_pptx == len(results):
            print("    All generated code that saves the pptx. Prompt is clear.")
        else:
            no_save = [r["model"].replace("ollama/", "") for r in results if not r["any_run_code_saves_pptx"]]
            print(f"    Called run_code() but pptx save missing in: {no_save}")
            print("    Prompt may need to reinforce the output filename requirement.")
    else:
        print(f"  → MIXED results:")
        print(f"    Called run_code()  : {called_names}")
        print(f"    Did NOT call it    : {skipped_names}")
        print("    Suggests a MODEL CAPABILITY difference between these models.")
        print("    Models that skipped run_code() may lack ReAct instruction-following ability.")


# ══════════════════════════════════════════════════════════════════════════════
# Task 2 — modify_slides (Round 3)
# ══════════════════════════════════════════════════════════════════════════════

MODIFIED_FNAME = "paper_summaries_v1.pptx"


def make_tools_modify(log: ToolCallLog) -> list[FunctionTool]:
    """Mock tools for modify_slides: sandbox already contains the original pptx."""

    def run_code(code: str) -> str:
        """Execute Python code in the sandbox environment."""
        saves_modified = MODIFIED_FNAME in code and (".save(" in code or "prs.save" in code)
        log.record("run_code", code_len=len(code), saves_modified=saves_modified,
                   code_snippet=code[:300])
        if saves_modified:
            return (
                "Execution successful.\n"
                "stdout: (no output)\n"
                f"Files created: /sandbox/{MODIFIED_FNAME}"
            )
        return (
            "Execution successful.\n"
            "stdout: (no output)\n"
            f"WARNING: {MODIFIED_FNAME} was NOT found in /sandbox/. "
            f"Make sure your code calls prs.save('{MODIFIED_FNAME}')."
        )

    def list_files() -> str:
        """List all files currently in the sandbox."""
        log.record("list_files")
        saved = any(c.get("saves_modified") for c in log.calls if c["tool"] == "run_code")
        files = ["pptx-template.pptx", "slide_outlines.json", "paper_summaries.pptx"]
        if saved:
            files.append(MODIFIED_FNAME)
        return json.dumps(files)

    def upload_file(local_file_path: str) -> str:
        """Upload a local file to the sandbox."""
        log.record("upload_file", path=local_file_path)
        return f"Uploaded {local_file_path} → /sandbox/{Path(local_file_path).name}"

    def get_all_layout() -> str:
        """Get all slide layout information from the PPTX template."""
        log.record("get_all_layout")
        return json.dumps([
            {
                "layout_name": "Title and Content",
                "placeholders": [
                    {"index": 0, "name": "Title 1",
                     "font_size": 32.0, "auto_size": None,
                     "left": 457200, "top": 274638, "width": 8229600, "height": 1143000},
                    {"index": 1, "name": "Content Placeholder 2",
                     "font_size": None, "auto_size": "TEXT_TO_FIT_SHAPE",
                     "left": 457200, "top": 1600200, "width": 8229600, "height": 4525963},
                ],
                "number_of_shapes": 3,
                "has_background": True,
            },
        ])

    return [
        FunctionTool.from_defaults(fn=run_code,       name="run_code"),
        FunctionTool.from_defaults(fn=list_files,     name="list_files"),
        FunctionTool.from_defaults(fn=upload_file,    name="upload_file"),
        FunctionTool.from_defaults(fn=get_all_layout, name="get_all_layout"),
    ]


# Mock input: mirrors real modify_slides invocation
SLIDE_PPTX_PATH    = "/sandbox/paper_summaries.pptx"
MODIFIED_PPTX_PATH = MODIFIED_FNAME

MOCK_FEEDBACK = {
    "results": [
        {
            "slide_idx": 2,
            "suggestion_to_fix": (
                "Text in content placeholder is overflowing the text box. "
                "Reduce font size to 14pt or smaller."
            ),
        },
        {
            "slide_idx": 4,
            "suggestion_to_fix": (
                "Title text is cut off at the right edge. "
                "Increase title placeholder width or reduce font size to 24pt."
            ),
        },
    ]
}

MODIFY_USER_MESSAGE = (
    f"The latest version of the slide deck is at `{SLIDE_PPTX_PATH}`.\n"
    f"The feedback is: '{json.dumps(MOCK_FEEDBACK)}'\n"
    f"Save the modified slide deck as `{MODIFIED_PPTX_PATH}`."
)


async def run_modify_test(prompt_label: str, system_prompt_body: str) -> dict:
    log = ToolCallLog()
    tools = make_tools_modify(log)

    system_prompt = system_prompt_body + REACT_PROMPT_SUFFIX

    llm = LiteLLM(
        model="ollama/gemma3:4b",
        temperature=0.1,
        max_tokens=4096,
    )

    agent = ReActAgent(tools=tools, llm=llm, verbose=True, timeout=600)
    agent.update_prompts({"react_header": PromptTemplate(system_prompt)})

    t_start = time.perf_counter()
    try:
        response = await agent.run(MODIFY_USER_MESSAGE)
        final_answer = str(response)
        error = None
    except Exception as e:
        final_answer = ""
        error = str(e)
    elapsed_s = time.perf_counter() - t_start

    tool_names = log.names()
    run_code_calls = [c for c in log.calls if c["tool"] == "run_code"]

    return {
        "prompt_label":                prompt_label,
        "error":                       error,
        "elapsed_s":                   round(elapsed_s, 1),
        "tool_call_sequence":          tool_names,
        "run_code_called":             "run_code" in tool_names,
        "run_code_count":              tool_names.count("run_code"),
        "list_files_count":            tool_names.count("list_files"),
        "any_run_code_saves_modified": any(c.get("saves_modified") for c in run_code_calls),
        "final_answer_has_question":   "?" in final_answer[-300:],
        "final_answer_tail":           final_answer[-400:].strip(),
        "all_tool_calls":              log.calls,
    }


def print_modify_results(results: list[dict]) -> None:
    print(f"\n\n{'='*70}")
    print("  TASK 2 — modify_slides: COMPARISON SUMMARY  (model: gemma3:4b)")
    print(f"{'='*70}")

    label_col = 32
    val_col   = 36
    short_names = ["Prompt A (current)", "Prompt B (improved)"]

    header = f"  {'Metric':<{label_col}}" + "".join(f"{n:<{val_col}}" for n in short_names)
    print(header)
    print(f"  {'-' * (label_col + val_col * len(results))}")

    def fmt(v) -> str:
        if v is True:  return "✅"
        if v is False: return "❌"
        return str(v)

    def row(label: str, *values):
        print(f"  {label:<{label_col}}" + "".join(f"{fmt(v):<{val_col}}" for v in values))

    row("Elapsed time (s)",           *[r["elapsed_s"]                   for r in results])
    row("run_code() called",          *[r["run_code_called"]             for r in results])
    row("run_code() call count",      *[r["run_code_count"]              for r in results])
    row("list_files() call count",    *[r["list_files_count"]            for r in results])
    row("Code saves modified file",   *[r["any_run_code_saves_modified"] for r in results])
    row("Final answer asks question", *[r["final_answer_has_question"]   for r in results])
    row("Error",                      *[r["error"] or "none"             for r in results])

    print(f"\n  Tool call sequences:")
    for r in results:
        print(f"    {r['prompt_label']}: {r['tool_call_sequence']}")

    print(f"\n{'='*70}")
    print("  INTERPRETATION")
    print(f"{'='*70}")

    n_called = sum(1 for r in results if r["run_code_called"])
    n_saves  = sum(1 for r in results if r["any_run_code_saves_modified"])
    called_labels  = [r["prompt_label"] for r in results if r["run_code_called"]]
    skipped_labels = [r["prompt_label"] for r in results if not r["run_code_called"]]

    if n_called == 0:
        print("  → NEITHER prompt caused the model to call run_code().")
        print("    Both prompts fail to instruct the model to execute code.")
        print("    SLIDE_MODIFICATION_PMT needs CRITICAL guards like the new SLIDE_GEN_PMT.")
    elif n_called == len(results):
        print("  → BOTH prompts caused the model to call run_code().")
        if n_saves == len(results):
            print("    Both produced code that saves the modified file.")
            counts = [r["run_code_count"] for r in results]
            if counts[1] < counts[0]:
                print(f"    Prompt B is more efficient: {counts[1]} vs {counts[0]} run_code() calls.")
            elif counts[0] == counts[1]:
                print(f"    Both needed {counts[0]} run_code() calls — efficiency is equal.")
            else:
                print(f"    Prompt A is more efficient: {counts[0]} vs {counts[1]} run_code() calls (unexpected).")
        else:
            no_save = [r["prompt_label"] for r in results if not r["any_run_code_saves_modified"]]
            print(f"    run_code() called but modified file not saved for: {no_save}")
    else:
        print(f"  → MIXED results:")
        print(f"    Called run_code(): {called_labels}")
        print(f"    Did NOT call it  : {skipped_labels}")
        print("    Prompt B likely fixes the issue present in Prompt A.")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    # ── Task 1: slide_gen (Rounds 1+2) ────────────────────────────────────────
    slide_gen_models = [
        "ollama/gemma3:4b",
        "ollama/gemma3n:e2b",
        "ollama/gemma3n:e4b",
    ]

    print(f"\n{'='*70}")
    print("  TASK 1 — slide_gen: Testing SLIDE_GEN_PMT across models")
    print(f"  Models: {[m.replace('ollama/', '') for m in slide_gen_models]}")
    print(f"{'='*70}")

    slide_gen_results = []
    for model in slide_gen_models:
        print(f"\n{'='*70}")
        print(f"  TESTING: {model}")
        print(f"{'='*70}\n")
        result = await run_slide_gen_test(model)
        slide_gen_results.append(result)

        print(f"\n── Raw result for {model} ──")
        print(f"  Elapsed time       : {result['elapsed_s']}s")
        print(f"  Tool call sequence : {result['tool_call_sequence']}")
        print(f"  run_code() called  : {result['run_code_called']}")
        print(f"  run_code() count   : {result['run_code_count']}")
        print(f"  Code saves pptx    : {result['any_run_code_saves_pptx']}")
        print(f"  Final answer has ? : {result['final_answer_has_question']}")
        if result["error"]:
            print(f"  ERROR              : {result['error']}")
        print(f"  Final answer tail  :\n    {result['final_answer_tail'][:300]}")

    print_slide_gen_results(slide_gen_results)

    # ── Task 2: modify_slides (Round 3) ───────────────────────────────────────
    modify_tests = [
        ("Prompt A (current SLIDE_MODIFICATION_PMT)", SLIDE_MODIFICATION_PMT),
        ("Prompt B (improved, CRITICAL guards)",       SLIDE_MODIFICATION_PMT_V2),
    ]

    print(f"\n\n{'='*70}")
    print("  TASK 2 — modify_slides: Testing Prompt A vs B (model: gemma3:4b)")
    print(f"{'='*70}")

    modify_results = []
    for label, prompt_body in modify_tests:
        print(f"\n{'='*70}")
        print(f"  TESTING: {label}")
        print(f"{'='*70}\n")
        result = await run_modify_test(label, prompt_body)
        modify_results.append(result)

        print(f"\n── Raw result: {label} ──")
        print(f"  Elapsed time          : {result['elapsed_s']}s")
        print(f"  Tool call sequence    : {result['tool_call_sequence']}")
        print(f"  run_code() called     : {result['run_code_called']}")
        print(f"  run_code() count      : {result['run_code_count']}")
        print(f"  list_files() count    : {result['list_files_count']}")
        print(f"  Code saves v1 file    : {result['any_run_code_saves_modified']}")
        print(f"  Final answer has ?    : {result['final_answer_has_question']}")
        if result["error"]:
            print(f"  ERROR                 : {result['error']}")
        print(f"  Final answer tail     :\n    {result['final_answer_tail'][:400]}")

    print_modify_results(modify_results)


if __name__ == "__main__":
    asyncio.run(main())
