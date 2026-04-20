"""
Agent Behavior Test: SLIDE_MODIFICATION_PMT prompt comparison
=============================================================
Tests whether gemma3:4b correctly follows the modify_slides task:
  ✅ Expected: call run_code() → load existing PPTX → apply fixes → save new file → confirm
  ❌ Bug: describe modifications as text / ask questions / no tool calls

Compares two prompts:
  Prompt A — current SLIDE_MODIFICATION_PMT (5-step prose, no CRITICAL guards)
  Prompt B — improved version modeled after the updated SLIDE_GEN_PMT style
               (explicit CRITICAL: MUST use run_code, clear completion condition)

Model tested: ollama/gemma3:4b (confirmed best ReAct performer from rounds 1+2)
User message: mirrors real modify_slides.py invocation (latest pptx path + feedback + save path)
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))
from prompts.prompts import SLIDE_MODIFICATION_PMT, REACT_PROMPT_SUFFIX

from llama_index.llms.litellm import LiteLLM
from llama_index.core.agent.workflow import ReActAgent
from llama_index.core.tools import FunctionTool
from llama_index.core import PromptTemplate


# ── Prompt B: improved version (same style as new SLIDE_GEN_PMT) ───────────────

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

# ── Mock state ─────────────────────────────────────────────────────────────────

class ToolCallLog:
    def __init__(self):
        self.calls: list[dict] = []

    def record(self, tool_name: str, **kwargs):
        self.calls.append({"tool": tool_name, **kwargs})

    def names(self) -> list[str]:
        return [c["tool"] for c in self.calls]


# ── Mock tools (same signatures as real LlmSandboxToolSpec + get_all_layout) ───

MODIFIED_FNAME = "paper_summaries_v1.pptx"

def make_tools(log: ToolCallLog) -> list[FunctionTool]:

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
        # Code ran but didn't save the expected file
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


# ── Mock input: mirrors real modify_slides invocation ──────────────────────────

SLIDE_PPTX_PATH   = "/sandbox/paper_summaries.pptx"
MODIFIED_PPTX_PATH = MODIFIED_FNAME

# mirrors ev.model_dump() from SlideValidationEvent
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

# Exact same user message format as slide_gen.py modify_slides step
USER_MESSAGE = (
    f"The latest version of the slide deck is at `{SLIDE_PPTX_PATH}`.\n"
    f"The feedback is: '{json.dumps(MOCK_FEEDBACK)}'\n"
    f"Save the modified slide deck as `{MODIFIED_PPTX_PATH}`."
)


# ── Single prompt test ─────────────────────────────────────────────────────────

async def run_test(prompt_label: str, system_prompt_body: str) -> dict:
    log = ToolCallLog()
    tools = make_tools(log)

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
        response = await agent.run(USER_MESSAGE)
        final_answer = str(response)
        error = None
    except Exception as e:
        final_answer = ""
        error = str(e)
    elapsed_s = time.perf_counter() - t_start

    tool_names = log.names()
    run_code_calls = [c for c in log.calls if c["tool"] == "run_code"]

    return {
        "prompt_label":              prompt_label,
        "error":                     error,
        "elapsed_s":                 round(elapsed_s, 1),
        "tool_call_sequence":        tool_names,
        "run_code_called":           "run_code" in tool_names,
        "run_code_count":            tool_names.count("run_code"),
        "list_files_count":          tool_names.count("list_files"),
        "any_run_code_saves_modified": any(c.get("saves_modified") for c in run_code_calls),
        "final_answer_has_question": "?" in final_answer[-300:],
        "final_answer_tail":         final_answer[-400:].strip(),
        "all_tool_calls":            log.calls,
    }


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    tests = [
        ("Prompt A (current SLIDE_MODIFICATION_PMT)", SLIDE_MODIFICATION_PMT),
        ("Prompt B (improved, CRITICAL guards)",       SLIDE_MODIFICATION_PMT_V2),
    ]

    results = []
    for label, prompt_body in tests:
        print(f"\n{'='*70}")
        print(f"  TESTING: {label}")
        print(f"{'='*70}\n")
        result = await run_test(label, prompt_body)
        results.append(result)

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

    # ── Comparison table ───────────────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print("  COMPARISON SUMMARY  (model: gemma3:4b)")
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
        line = f"  {label:<{label_col}}" + "".join(f"{fmt(v):<{val_col}}" for v in values)
        print(line)

    row("Elapsed time (s)",              *[r["elapsed_s"]                   for r in results])
    row("run_code() called",             *[r["run_code_called"]             for r in results])
    row("run_code() call count",         *[r["run_code_count"]              for r in results])
    row("list_files() call count",       *[r["list_files_count"]            for r in results])
    row("Code saves modified file",      *[r["any_run_code_saves_modified"] for r in results])
    row("Final answer asks question",    *[r["final_answer_has_question"]   for r in results])
    row("Error",                         *[r["error"] or "none"             for r in results])

    print(f"\n  Tool call sequences:")
    for r in results:
        print(f"    {r['prompt_label']}: {r['tool_call_sequence']}")

    # ── Interpretation ─────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  INTERPRETATION")
    print(f"{'='*70}")

    n_called   = sum(1 for r in results if r["run_code_called"])
    n_saves    = sum(1 for r in results if r["any_run_code_saves_modified"])
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


if __name__ == "__main__":
    asyncio.run(main())
