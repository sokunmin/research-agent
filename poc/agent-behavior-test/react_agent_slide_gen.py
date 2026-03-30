"""
Agent Behavior Test: SLIDE_GEN_PMT prompt interpretation
=========================================================
Tests whether models correctly follow the updated SLIDE_GEN_PMT prompt:
  ✅ Expected: call run_code() → execute python-pptx code → confirm file exists
  ❌ Bug: describe code as text / ask user questions / loop without converging

Runs sequentially: gemma3:4b → gemma3n:e2b → gemma3n:e4b
Uses identical prompts, tools, and user message as the real slide_gen step.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

# Use actual prompts from backend (no modifications)
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))
from prompts.prompts import SLIDE_GEN_PMT, REACT_PROMPT_SUFFIX

from llama_index.llms.litellm import LiteLLM
from llama_index.core.agent.workflow import ReActAgent
from llama_index.core.tools import FunctionTool
from llama_index.core import PromptTemplate


# ── Mock state ─────────────────────────────────────────────────────────────────

class ToolCallLog:
    def __init__(self):
        self.calls: list[dict] = []

    def record(self, tool_name: str, **kwargs):
        self.calls.append({"tool": tool_name, **kwargs})

    def names(self) -> list[str]:
        return [c["tool"] for c in self.calls]


# ── Mock tools (same signatures as real LlmSandboxToolSpec + get_all_layout) ──

def make_tools(log: ToolCallLog) -> list[FunctionTool]:

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
        FunctionTool.from_defaults(fn=run_code,    name="run_code"),
        FunctionTool.from_defaults(fn=list_files,  name="list_files"),
        FunctionTool.from_defaults(fn=upload_file, name="upload_file"),
        FunctionTool.from_defaults(fn=get_all_layout, name="get_all_layout"),
    ]


# ── Outline fixture (same structure as real slide_outlines.json items) ─────────

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


# ── Single model test ──────────────────────────────────────────────────────────

async def run_test(model: str) -> dict:
    log = ToolCallLog()
    tools = make_tools(log)

    # Exact same prompt construction as slide_gen.py:390-398
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

    # Exact same user message as slide_gen.py:404-406
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


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    models = [
        "ollama/gemma3:4b",
        "ollama/gemma3n:e2b",
        "ollama/gemma3n:e4b",
    ]

    results = []
    for model in models:
        print(f"\n{'='*70}")
        print(f"  TESTING: {model}")
        print(f"{'='*70}\n")
        result = await run_test(model)
        results.append(result)

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

    # ── Comparison table ───────────────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print("  COMPARISON SUMMARY")
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
        line = f"  {label:<{label_col}}" + "".join(f"{fmt(v):<{val_col}}" for v in values)
        print(line)

    row("Elapsed time (s)",           *[r["elapsed_s"]                for r in results])
    row("run_code() called",          *[r["run_code_called"]          for r in results])
    row("run_code() call count",      *[r["run_code_count"]           for r in results])
    row("Code actually saves pptx",   *[r["any_run_code_saves_pptx"]  for r in results])
    row("Final answer asks question", *[r["final_answer_has_question"] for r in results])
    row("Error",                      *[r["error"] or "none"          for r in results])

    print(f"\n  Tool call sequences:")
    for r in results:
        print(f"    {r['model'].replace('ollama/', '')}: {r['tool_call_sequence']}")

    # ── Interpretation ─────────────────────────────────────────────────────────
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


if __name__ == "__main__":
    asyncio.run(main())
