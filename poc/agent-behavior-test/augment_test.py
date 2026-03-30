"""
Agent Behavior Test: outlines_with_layout FunctionCallingProgram prompt comparison
===================================================================================
Tests whether LLMs correctly produce SlideOutlineWithLayout via FunctionCallingProgram.
  ✅ Expected: valid SlideOutlineWithLayout — all 5 required fields correctly populated
  ❌ Bug:     wraps output in {"properties": {...}} → Pydantic validation failure
              (observed in production log 2026-03-27)

Compares 4 prompt variants of AUGMENT_LAYOUT_PMT:
  Prompt 1 — current (verbatim AUGMENT_LAYOUT_PMT from prompts.py)
  Prompt 2 — typo fixes + explicit field descriptions
  Prompt 3 — typo fixes + field descriptions + few-shot example
  Prompt 4 — Round-2 principle applied: explicit no-wrap directive + value-level instruction
              (based on finding that unambiguous output-format instructions fix gemma3:4b)

Models:  ollama/gemma3:4b, ollama/qwen3.5:4b
Runs:    N_RUNS per (model × prompt × slide_outline) combination
Metric:  success rate, layout validity, placeholder index validity, avg latency
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from agent_workflows.schemas import SlideOutlineWithLayout
from llama_index.llms.litellm import LiteLLM
from llama_index.core.program import FunctionCallingProgram

# ── Config ────────────────────────────────────────────────────────────────────

MODELS = [
    {
        "name":               "ollama/gemma3:4b",
        "additional_kwargs":  {},
    },
    {
        "name":               "ollama/qwen3.5:4b",
        "additional_kwargs":  {"extra_body": {"think": False}},
    },
]

N_RUNS = 3   # runs per (model × prompt × slide_outline); total = 2 × 4 × 3 × 3 = 72 LLM calls

# ── Mock available layouts (mirrors real template structure) ──────────────────

AVAILABLE_LAYOUTS = [
    {
        "layout_name": "Title and Content",
        "placeholders": [
            {"index": 0, "name": "Title 1",              "font_size": 32.0, "auto_size": None},
            {"index": 1, "name": "Content Placeholder 2","font_size": None, "auto_size": "TEXT_TO_FIT_SHAPE"},
        ],
    },
    {
        "layout_name": "Title Slide",
        "placeholders": [
            {"index": 0, "name": "Title 1",   "font_size": 44.0, "auto_size": None},
            {"index": 1, "name": "Subtitle 2","font_size": 28.0, "auto_size": "SHAPE_TO_FIT_TEXT"},
        ],
    },
    {
        "layout_name": "Section Header",
        "placeholders": [
            {"index": 0, "name": "Title 1", "font_size": 36.0, "auto_size": None},
        ],
    },
    {
        "layout_name": "Blank",
        "placeholders": [],
    },
]

AVAILABLE_LAYOUT_NAMES = [layout["layout_name"] for layout in AVAILABLE_LAYOUTS]
VALID_LAYOUT_NAMES     = set(AVAILABLE_LAYOUT_NAMES)

# ── Test cases: 3 representative slide types ──────────────────────────────────

SLIDE_OUTLINES = [
    {   # regular academic content slide
        "title": "Attention Is All You Need",
        "content": (
            "* Key Approach: Transformer using self-attention, no recurrence\n"
            "* Key Components: Multi-head attention, positional encoding, encoder-decoder\n"
            "* Training: Adam optimizer, warmup schedule\n"
            "* Conclusion: Outperforms RNN/CNN baselines on translation tasks"
        ),
    },
    {   # agenda / overview slide
        "title": "Agenda",
        "content": "1. Introduction\n2. Methodology\n3. Experimental Results\n4. Conclusion",
    },
    {   # closing slide
        "title": "Thank You",
        "content": "Questions and Discussion\nContact: research@example.com",
    },
]

# ── Prompt 1: current AUGMENT_LAYOUT_PMT (verbatim) ──────────────────────────

PROMPT_1 = """
You are an AI that selects slide layout from a template for the slide text given.
You will receive a page content with title and main text.
Your task is to select the appropriate layout and information such as index of the placeholder for the page
 based on what type of the content it is (e.g. is it topic overview/agenda,
 or actual content, or thank you message).
For content slides, make sure to
 - choose a layout that has content placeholder (also referred to as 'Plassholder for innhold')
 after the title placeholder
 - choose the content placeholder that is large enough for the text content

The following layout are available: {available_layout_names} with their detailed information:
{available_layouts}

Here is the slide content:
{slide_content}
"""

# ── Prompt 2: typo fix + explicit field descriptions ─────────────────────────
# Changes:
#   - "Plassholder for innhold" → "content placeholder" (Norwegian removed)
#   - Added explicit definition of each output field

PROMPT_2 = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and main text body.

Select the layout and placeholder indices based on the content type
(e.g. agenda/overview, regular content, title slide, or closing/thank-you slide).

For content slides:
 - choose a layout that has a content placeholder after the title placeholder
 - choose the content placeholder that is large enough for the text

The following layouts are available: {available_layout_names} with their detailed information:
{available_layouts}

Here is the slide content:
{slide_content}

Output the following fields:
- title: the slide title text (copy verbatim from input)
- content: the slide body text (copy verbatim from input)
- layout_name: the exact name string of the chosen layout (must match one of the available layout names)
- idx_title_placeholder: the numeric index (as a string) of the title placeholder in the chosen layout
- idx_content_placeholder: the numeric index (as a string) of the content placeholder in the chosen layout
"""

# ── Prompt 3: typo fix + field descriptions + few-shot example ───────────────
# Adds a worked example showing exactly the expected output format.
# Uses plain-text example format to avoid Python string escaping conflicts.

PROMPT_3 = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and main text body.

Select the layout and placeholder indices based on the content type
(e.g. agenda/overview, regular content, title slide, or closing/thank-you slide).

For content slides:
 - choose a layout that has a content placeholder after the title placeholder
 - choose the content placeholder that is large enough for the text

The following layouts are available: {available_layout_names} with their detailed information:
{available_layouts}

--- Example ---
Slide content:
  title: "Deep Learning for NLP"
  content: "* Recurrent Networks\n* Transformers\n* BERT pre-training"

Expected output:
  title:                    "Deep Learning for NLP"
  content:                  "* Recurrent Networks\n* Transformers\n* BERT pre-training"
  layout_name:              "Title and Content"
  idx_title_placeholder:    "0"
  idx_content_placeholder:  "1"
--- End Example ---

Here is the slide content:
{slide_content}

Output the following fields:
- title: the slide title text (copy verbatim from input)
- content: the slide body text (copy verbatim from input)
- layout_name: the exact name string of the chosen layout (must match one of the available layout names)
- idx_title_placeholder: the numeric index (as a string) of the title placeholder in the chosen layout
- idx_content_placeholder: the numeric index (as a string) of the content placeholder in the chosen layout
"""

# ── Prompt 4: Round-2 principle — explicit no-wrap + value-level instruction ─
# Based on results.md Round 2 finding: gemma3:4b responds well to unambiguous,
# explicit instruction about exactly what NOT to do. Here we directly address
# the "properties wrapping" failure mode observed in production.

PROMPT_4 = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and main text body.

Select the layout and placeholder indices based on the content type
(e.g. agenda/overview, regular content, title slide, or closing/thank-you slide).

For content slides:
 - choose a layout that has a content placeholder after the title placeholder
 - choose the content placeholder that is large enough for the text

The following layouts are available: {available_layout_names} with their detailed information:
{available_layouts}

Here is the slide content:
{slide_content}

CRITICAL: Provide the ACTUAL VALUES for each field — not a schema, not a description.
Do NOT wrap your answer inside a "properties" key or any JSON Schema structure.
Do NOT output field definitions or type annotations. Output concrete values only.

Required fields (fill each with the real value, not a placeholder):
- title:                   copy the title string from the slide content above
- content:                 copy the content string from the slide content above
- layout_name:             the exact layout name string chosen from the available list
- idx_title_placeholder:   the string form of the integer index for the title placeholder
- idx_content_placeholder: the string form of the integer index for the content placeholder
"""

# ── Helpers ───────────────────────────────────────────────────────────────────

def _valid_int_str(val: str) -> bool:
    try:
        int(val)
        return True
    except (ValueError, TypeError):
        return False


def _detect_properties_wrap(err: str) -> bool:
    """Heuristic: error message suggests the {"properties": ...} wrapping pattern."""
    return (
        "'properties'" in err
        or '"properties"' in err
        or ("Field required" in err and "input_value=" in err)
    )


# ── Single LLM call ───────────────────────────────────────────────────────────

async def run_single(prompt_template: str, slide_outline: dict, model_cfg: dict) -> dict:
    """Run a single FunctionCallingProgram call for the given model config."""
    model_name = model_cfg["name"]
    additional_kwargs = model_cfg.get("additional_kwargs", {})

    # Construct LiteLLM with optional additional_kwargs
    llm_kwargs = dict(model=model_name, temperature=0.1, max_tokens=2048)
    if additional_kwargs:
        llm_kwargs["additional_kwargs"] = additional_kwargs
    llm = LiteLLM(**llm_kwargs)

    t_start = time.perf_counter()
    try:
        # Catch capability errors at program construction level
        try:
            program = FunctionCallingProgram.from_defaults(
                llm=llm,
                output_cls=SlideOutlineWithLayout,
                prompt_template_str=prompt_template,
                verbose=False,
            )
        except (ValueError, Exception) as cap_err:
            elapsed = time.perf_counter() - t_start
            err_str = str(cap_err)
            return {
                "success":                False,
                "layout_valid":           False,
                "idx_title_valid":        False,
                "idx_content_valid":      False,
                "title_copied":           False,
                "layout_chosen":          None,
                "elapsed_s":              round(elapsed, 1),
                "error":                  err_str[:300],
                "properties_wrap":        False,
                "capability_error":       True,
            }

        response = await program.acall(
            slide_content=json.dumps(slide_outline),
            available_layout_names=json.dumps(AVAILABLE_LAYOUT_NAMES),
            available_layouts=json.dumps(AVAILABLE_LAYOUTS, indent=2),
            description="Data model for the slide page outline with layout",
        )
        elapsed = time.perf_counter() - t_start

        success = isinstance(response, SlideOutlineWithLayout)
        layout_valid      = response.layout_name in VALID_LAYOUT_NAMES if success else False
        idx_title_valid   = _valid_int_str(response.idx_title_placeholder)   if success else False
        idx_content_valid = _valid_int_str(response.idx_content_placeholder) if success else False
        title_copied      = (response.title == slide_outline["title"])        if success else False

        return {
            "success":                success,
            "layout_valid":           layout_valid,
            "idx_title_valid":        idx_title_valid,
            "idx_content_valid":      idx_content_valid,
            "title_copied":           title_copied,
            "layout_chosen":          response.layout_name if success else None,
            "elapsed_s":              round(elapsed, 1),
            "error":                  None,
            "properties_wrap":        False,
            "capability_error":       False,
        }

    except Exception as e:
        elapsed = time.perf_counter() - t_start
        err_str = str(e)
        return {
            "success":                False,
            "layout_valid":           False,
            "idx_title_valid":        False,
            "idx_content_valid":      False,
            "title_copied":           False,
            "layout_chosen":          None,
            "elapsed_s":              round(elapsed, 1),
            "error":                  err_str[:300],
            "properties_wrap":        _detect_properties_wrap(err_str),
            "capability_error":       False,
        }


# ── Per-prompt test runner ────────────────────────────────────────────────────

async def run_prompt_test(prompt_label: str, prompt_template: str, model_cfg: dict) -> dict:
    model_name = model_cfg["name"]
    all_runs = []
    capability_error_detected = False

    for slide in SLIDE_OUTLINES:
        slide_label = slide["title"]
        for run_idx in range(N_RUNS):
            print(
                f"  [{model_name}][{prompt_label}] slide={slide_label!r:30s} run={run_idx+1}/{N_RUNS}",
                end=" ", flush=True,
            )

            # If we already know this model can't build the program, skip remaining runs
            if capability_error_detected:
                result = {
                    "success": False, "layout_valid": False,
                    "idx_title_valid": False, "idx_content_valid": False,
                    "title_copied": False, "layout_chosen": None,
                    "elapsed_s": 0.0, "error": "capability_error (skipped)",
                    "properties_wrap": False, "capability_error": True,
                    "slide_title": slide_label, "run_idx": run_idx,
                }
                all_runs.append(result)
                print("→ ⛔ cap_err (skipped)")
                continue

            result = await run_single(prompt_template, slide, model_cfg)
            result["slide_title"] = slide_label
            result["run_idx"]     = run_idx
            all_runs.append(result)

            if result.get("capability_error"):
                capability_error_detected = True
                mark = "⛔ cap_err"
            elif result["success"]:
                mark = "✅"
            elif result["properties_wrap"]:
                mark = "⚠️  wrap"
            else:
                mark = "❌"
            print(f"→ {mark} ({result['elapsed_s']}s)")

    n          = len(all_runs)
    success_n  = sum(1 for r in all_runs if r["success"])
    wrap_n     = sum(1 for r in all_runs if r["properties_wrap"])
    cap_err_n  = sum(1 for r in all_runs if r.get("capability_error"))

    return {
        "prompt_label":          prompt_label,
        "model_name":            model_name,
        "total_runs":            n,
        "success_count":         success_n,
        "success_rate":          success_n / n,
        "layout_valid_rate":     sum(1 for r in all_runs if r["layout_valid"])    / n,
        "idx_valid_rate":        sum(1 for r in all_runs if r["idx_title_valid"] and r["idx_content_valid"]) / n,
        "title_copied_rate":     sum(1 for r in all_runs if r["title_copied"])    / n,
        "avg_elapsed_s":         round(sum(r["elapsed_s"] for r in all_runs) / n, 1),
        "properties_wrap_count": wrap_n,
        "capability_error_count":cap_err_n,
        "capability_error_all":  cap_err_n == n,
        "raw_runs":              all_runs,
    }


# ── Print per-model comparison table ─────────────────────────────────────────

def print_model_table(model_results: list, model_name: str):
    label_col  = 36
    val_col    = 14
    short_names = ["Prompt 1", "Prompt 2", "Prompt 3", "Prompt 4"]

    print(f"\n{'='*72}")
    print(f"  MODEL: {model_name}")
    print(f"{'='*72}")

    header = f"  {'Metric':<{label_col}}" + "".join(f"{n:<{val_col}}" for n in short_names)
    print(header)
    print(f"  {'-'*(label_col + val_col * len(model_results))}")

    def fmt_rate(v: float) -> str:
        return f"{v:.0%}"

    rows = [
        ("Success rate",               "success_rate",          fmt_rate),
        ("Layout valid rate",          "layout_valid_rate",     fmt_rate),
        ("Both idx valid rate",        "idx_valid_rate",        fmt_rate),
        ("Avg elapsed (s)",            "avg_elapsed_s",         str),
        ("'properties'-wrap errors",   "properties_wrap_count", str),
        ("Capability errors",          "capability_error_count",str),
    ]
    for row_label, key, fmtfn in rows:
        vals = [fmtfn(r[key]) for r in model_results]
        line = f"  {row_label:<{label_col}}" + "".join(f"{v:<{val_col}}" for v in vals)
        print(line)

    # Per-slide breakdown
    print(f"\n  Per-slide success ({N_RUNS} runs per prompt):")
    for slide in SLIDE_OUTLINES:
        stitle = slide["title"]
        row_vals = []
        for r in model_results:
            slide_runs = [x for x in r["raw_runs"] if x["slide_title"] == stitle]
            n_ok = sum(1 for x in slide_runs if x["success"])
            row_vals.append(f"{n_ok}/{len(slide_runs)}")
        line = f"  {stitle!r:<{label_col}}" + "".join(f"{v:<{val_col}}" for v in row_vals)
        print(line)


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    prompts = [
        ("Prompt 1 (current)",                  PROMPT_1),
        ("Prompt 2 (typo fix + field desc)",    PROMPT_2),
        ("Prompt 3 (+ few-shot)",               PROMPT_3),
        ("Prompt 4 (Round2 no-wrap directive)", PROMPT_4),
    ]

    total_calls = len(MODELS) * len(prompts) * len(SLIDE_OUTLINES) * N_RUNS
    print(f"\n{'='*72}")
    print(f"  outlines_with_layout — FunctionCallingProgram Prompt Comparison")
    print(f"  Models: {', '.join(m['name'] for m in MODELS)}")
    print(f"  Slide types: {len(SLIDE_OUTLINES)}  |  Runs per combo: {N_RUNS}  |  Total LLM calls (max): {total_calls}")
    print(f"{'='*72}\n")

    # results grouped by model: { model_name: [result_p1, result_p2, result_p3, result_p4] }
    all_model_results = {}

    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        print(f"\n{'#'*72}")
        print(f"# Testing model: {model_name}")
        print(f"{'#'*72}")
        model_results = []
        for label, prompt in prompts:
            print(f"\n── Running: {label} ──")
            result = await run_prompt_test(label, prompt, model_cfg)
            model_results.append(result)
        all_model_results[model_name] = model_results

    # ── Per-model comparison tables ───────────────────────────────────────────
    print(f"\n\n{'='*72}")
    print("  COMPARISON SUMMARY (per model)")
    print(f"{'='*72}")

    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        print_model_table(all_model_results[model_name], model_name)

    # ── Cross-model best combo ────────────────────────────────────────────────
    print(f"\n\n{'='*72}")
    print("  CROSS-MODEL BEST COMBINATION")
    print(f"{'='*72}")

    all_results_flat = [r for results in all_model_results.values() for r in results]
    sorted_by_success = sorted(all_results_flat, key=lambda r: r["success_rate"], reverse=True)

    print(f"  {'Model':<28} {'Prompt':<38} {'Success':>8}")
    print(f"  {'-'*76}")
    for r in sorted_by_success:
        print(f"  {r['model_name']:<28} {r['prompt_label']:<38} {r['success_rate']:>7.0%}")

    # ── Interpretation ────────────────────────────────────────────────────────
    print(f"\n{'='*72}")
    print("  INTERPRETATION")
    print(f"{'='*72}")

    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        model_results = all_model_results[model_name]

        cap_all = all(r["capability_error_all"] for r in model_results)
        if cap_all:
            print(f"\n  {model_name}: FunctionCallingProgram capability error on all prompts.")
            print(f"    → Model does NOT support native function calling via LiteLLM.")
            continue

        sorted_r = sorted(model_results, key=lambda r: r["success_rate"], reverse=True)
        best  = sorted_r[0]
        worst = sorted_r[-1]
        print(f"\n  {model_name}:")
        print(f"    Best prompt : {best['prompt_label']}  ({best['success_rate']:.0%})")
        print(f"    Worst prompt: {worst['prompt_label']} ({worst['success_rate']:.0%})")

        wrap_total = sum(r["properties_wrap_count"] for r in model_results)
        if wrap_total > 0:
            print(f"    'properties'-wrapping errors detected ({wrap_total} total).")
        else:
            print(f"    No 'properties'-wrapping errors detected.")

        p1 = model_results[0]
        for idx in (1, 2, 3):
            r     = model_results[idx]
            delta = r["success_rate"] - p1["success_rate"]
            sign  = "+" if delta >= 0 else ""
            print(f"    {r['prompt_label']} vs Prompt 1: {sign}{delta:.0%} success rate")

    print()
    return all_model_results


if __name__ == "__main__":
    asyncio.run(main())
