"""
Agent Behavior Test v2: outlines_with_layout — Method Comparison
=================================================================
Tests whether LLMs correctly produce SlideOutlineWithLayout via 5 different methods:

  METHOD_A: FunctionCallingProgram (original baseline)
  METHOD_B: LLMTextCompletionProgram
  METHOD_C: Ollama `format` param — JSON schema in additional_kwargs (Ollama only)
  METHOD_D: llm.as_structured_llm() — wrap llm, call sllm.acomplete(formatted_prompt)
  METHOD_E: llm.astructured_predict() with PydanticProgramMode.LLM

Same 4 prompts × 2 models from augment_test.py.
N_RUNS = 3 per (model × prompt × method × slide) combination.
Total = 2 models × 4 prompts × 5 methods × 3 slides × 3 runs = 360 LLM calls.

ALL execution is SEQUENTIAL — Ollama does not support parallel requests.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from agent_workflows.schemas import SlideOutlineWithLayout
from llama_index.llms.litellm import LiteLLM
from llama_index.core.program import FunctionCallingProgram, LLMTextCompletionProgram
from llama_index.core import PromptTemplate
from llama_index.core.llms.llm import PydanticProgramMode

# ── Config ────────────────────────────────────────────────────────────────────

MODELS = [
    {
        "name":               "ollama/gemma3:4b",
        "additional_kwargs":  {},
        "is_ollama":          True,
    },
    {
        "name":               "ollama/qwen3.5:4b",
        "additional_kwargs":  {"extra_body": {"think": False}},
        "is_ollama":          True,
    },
]

N_RUNS = 3  # runs per (model × prompt × method × slide)

METHODS = ["METHOD_A", "METHOD_B", "METHOD_C", "METHOD_D", "METHOD_E"]

# ── Mock available layouts (mirrors real template structure) ──────────────────

AVAILABLE_LAYOUTS = [
    {
        "layout_name": "Title and Content",
        "placeholders": [
            {"index": 0, "name": "Title 1",               "font_size": 32.0, "auto_size": None},
            {"index": 1, "name": "Content Placeholder 2", "font_size": None, "auto_size": "TEXT_TO_FIT_SHAPE"},
        ],
    },
    {
        "layout_name": "Title Slide",
        "placeholders": [
            {"index": 0, "name": "Title 1",    "font_size": 44.0, "auto_size": None},
            {"index": 1, "name": "Subtitle 2", "font_size": 28.0, "auto_size": "SHAPE_TO_FIT_TEXT"},
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
  content: "* Recurrent Networks\\n* Transformers\\n* BERT pre-training"

Expected output:
  title:                    "Deep Learning for NLP"
  content:                  "* Recurrent Networks\\n* Transformers\\n* BERT pre-training"
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

PROMPTS = [
    ("Prompt 1 (current)",                  PROMPT_1),
    ("Prompt 2 (typo fix + field desc)",    PROMPT_2),
    ("Prompt 3 (+ few-shot)",               PROMPT_3),
    ("Prompt 4 (Round2 no-wrap directive)", PROMPT_4),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _valid_int_str(val) -> bool:
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


def _detect_capability_error(err: str) -> bool:
    """Heuristic: model does not support function calling."""
    lower = err.lower()
    return (
        "does not support" in lower
        or "function call" in lower
        or "tool_call" in lower
        or "not support" in lower
    )


def _make_llm(model_cfg: dict, extra_format_kwarg: dict = None) -> LiteLLM:
    """Construct a LiteLLM instance from model config."""
    model_name = model_cfg["name"]
    additional_kwargs = dict(model_cfg.get("additional_kwargs", {}))
    if extra_format_kwarg:
        additional_kwargs.update(extra_format_kwarg)
    llm_kwargs = dict(model=model_name, temperature=0.1, max_tokens=2048)
    if additional_kwargs:
        llm_kwargs["additional_kwargs"] = additional_kwargs
    return LiteLLM(**llm_kwargs)


def _build_empty_failure(elapsed: float, err_str: str, properties_wrap: bool,
                          capability_error: bool, skipped: bool = False) -> dict:
    return {
        "success":            False,
        "layout_valid":       False,
        "idx_title_valid":    False,
        "idx_content_valid":  False,
        "title_copied":       False,
        "layout_chosen":      None,
        "elapsed_s":          round(elapsed, 1),
        "error":              err_str[:400] if err_str else None,
        "properties_wrap":    properties_wrap,
        "capability_error":   capability_error,
        "skipped":            skipped,
    }


def _build_success(response: SlideOutlineWithLayout, elapsed: float,
                   slide_outline: dict) -> dict:
    layout_valid      = response.layout_name in VALID_LAYOUT_NAMES
    idx_title_valid   = _valid_int_str(response.idx_title_placeholder)
    idx_content_valid = _valid_int_str(response.idx_content_placeholder)
    title_copied      = (response.title == slide_outline["title"])
    return {
        "success":            True,
        "layout_valid":       layout_valid,
        "idx_title_valid":    idx_title_valid,
        "idx_content_valid":  idx_content_valid,
        "title_copied":       title_copied,
        "layout_chosen":      response.layout_name,
        "elapsed_s":          round(elapsed, 1),
        "error":              None,
        "properties_wrap":    False,
        "capability_error":   False,
        "skipped":            False,
    }


# ── METHOD_A: FunctionCallingProgram ─────────────────────────────────────────

async def run_method_a(prompt_template: str, slide_outline: dict, model_cfg: dict) -> dict:
    llm = _make_llm(model_cfg)
    t_start = time.perf_counter()
    try:
        try:
            program = FunctionCallingProgram.from_defaults(
                llm=llm,
                output_cls=SlideOutlineWithLayout,
                prompt_template_str=prompt_template,
                verbose=False,
            )
        except Exception as cap_err:
            elapsed = time.perf_counter() - t_start
            err_str = str(cap_err)
            return _build_empty_failure(elapsed, err_str, False, True)

        response = await program.acall(
            slide_content=json.dumps(slide_outline),
            available_layout_names=json.dumps(AVAILABLE_LAYOUT_NAMES),
            available_layouts=json.dumps(AVAILABLE_LAYOUTS, indent=2),
            description="Data model for the slide page outline with layout",
        )
        elapsed = time.perf_counter() - t_start
        if isinstance(response, SlideOutlineWithLayout):
            return _build_success(response, elapsed, slide_outline)
        else:
            return _build_empty_failure(elapsed, f"Unexpected type: {type(response)}", False, False)

    except Exception as e:
        elapsed = time.perf_counter() - t_start
        err_str = str(e)
        return _build_empty_failure(
            elapsed, err_str,
            _detect_properties_wrap(err_str),
            _detect_capability_error(err_str),
        )


# ── METHOD_B: LLMTextCompletionProgram ───────────────────────────────────────

async def run_method_b(prompt_template: str, slide_outline: dict, model_cfg: dict) -> dict:
    llm = _make_llm(model_cfg)
    t_start = time.perf_counter()
    try:
        program = LLMTextCompletionProgram.from_defaults(
            llm=llm,
            output_cls=SlideOutlineWithLayout,
            prompt_template_str=prompt_template,
            verbose=False,
        )
        response = await program.acall(
            slide_content=json.dumps(slide_outline),
            available_layout_names=json.dumps(AVAILABLE_LAYOUT_NAMES),
            available_layouts=json.dumps(AVAILABLE_LAYOUTS, indent=2),
        )
        elapsed = time.perf_counter() - t_start
        if isinstance(response, SlideOutlineWithLayout):
            return _build_success(response, elapsed, slide_outline)
        else:
            return _build_empty_failure(elapsed, f"Unexpected type: {type(response)}", False, False)

    except Exception as e:
        elapsed = time.perf_counter() - t_start
        err_str = str(e)
        return _build_empty_failure(
            elapsed, err_str,
            _detect_properties_wrap(err_str),
            _detect_capability_error(err_str),
        )


# ── METHOD_C: Ollama format param ─────────────────────────────────────────────

async def run_method_c(prompt_template: str, slide_outline: dict, model_cfg: dict) -> dict:
    """
    Pass SlideOutlineWithLayout.model_json_schema() as `format` in additional_kwargs.
    Only works for Ollama models. For non-Ollama, skip with a note.
    """
    if not model_cfg.get("is_ollama", False):
        return _build_empty_failure(
            0.0,
            "METHOD_C: Skipped — Ollama format param only supported for Ollama models",
            False, False, skipped=True,
        )

    schema = SlideOutlineWithLayout.model_json_schema()
    # Merge with existing additional_kwargs, adding format
    base_kwargs = dict(model_cfg.get("additional_kwargs", {}))
    base_kwargs["format"] = schema

    llm = _make_llm(model_cfg, extra_format_kwarg={"format": schema})
    t_start = time.perf_counter()
    try:
        program = LLMTextCompletionProgram.from_defaults(
            llm=llm,
            output_cls=SlideOutlineWithLayout,
            prompt_template_str=prompt_template,
            verbose=False,
        )
        response = await program.acall(
            slide_content=json.dumps(slide_outline),
            available_layout_names=json.dumps(AVAILABLE_LAYOUT_NAMES),
            available_layouts=json.dumps(AVAILABLE_LAYOUTS, indent=2),
        )
        elapsed = time.perf_counter() - t_start
        if isinstance(response, SlideOutlineWithLayout):
            return _build_success(response, elapsed, slide_outline)
        else:
            return _build_empty_failure(elapsed, f"Unexpected type: {type(response)}", False, False)

    except Exception as e:
        elapsed = time.perf_counter() - t_start
        err_str = str(e)
        return _build_empty_failure(
            elapsed, err_str,
            _detect_properties_wrap(err_str),
            _detect_capability_error(err_str),
        )


# ── METHOD_D: llm.as_structured_llm() ────────────────────────────────────────

async def run_method_d(prompt_template: str, slide_outline: dict, model_cfg: dict) -> dict:
    """
    Wrap llm via as_structured_llm(), manually format the prompt string,
    call sllm.acomplete(formatted_prompt), result is response.raw.
    """
    llm = _make_llm(model_cfg)
    t_start = time.perf_counter()
    try:
        sllm = llm.as_structured_llm(SlideOutlineWithLayout)
        formatted_prompt = prompt_template.format(
            slide_content=json.dumps(slide_outline),
            available_layout_names=json.dumps(AVAILABLE_LAYOUT_NAMES),
            available_layouts=json.dumps(AVAILABLE_LAYOUTS, indent=2),
        )
        response = await sllm.acomplete(formatted_prompt)
        elapsed = time.perf_counter() - t_start
        raw = response.raw
        if isinstance(raw, SlideOutlineWithLayout):
            return _build_success(raw, elapsed, slide_outline)
        else:
            # Try to parse if it's a dict or something else
            err_str = f"response.raw type={type(raw)}, value={str(raw)[:200]}"
            return _build_empty_failure(elapsed, err_str, False, False)

    except Exception as e:
        elapsed = time.perf_counter() - t_start
        err_str = str(e)
        return _build_empty_failure(
            elapsed, err_str,
            _detect_properties_wrap(err_str),
            _detect_capability_error(err_str),
        )


# ── METHOD_E: llm.astructured_predict() ──────────────────────────────────────

async def run_method_e(prompt_template: str, slide_outline: dict, model_cfg: dict) -> dict:
    """
    Set pydantic_program_mode=PydanticProgramMode.LLM on the LLM instance,
    then call llm.astructured_predict(SlideOutlineWithLayout, prompt=PromptTemplate(...), **kwargs).
    """
    llm = _make_llm(model_cfg)
    llm.pydantic_program_mode = PydanticProgramMode.LLM
    t_start = time.perf_counter()
    try:
        response = await llm.astructured_predict(
            SlideOutlineWithLayout,
            prompt=PromptTemplate(prompt_template),
            slide_content=json.dumps(slide_outline),
            available_layout_names=json.dumps(AVAILABLE_LAYOUT_NAMES),
            available_layouts=json.dumps(AVAILABLE_LAYOUTS, indent=2),
        )
        elapsed = time.perf_counter() - t_start
        if isinstance(response, SlideOutlineWithLayout):
            return _build_success(response, elapsed, slide_outline)
        else:
            return _build_empty_failure(elapsed, f"Unexpected type: {type(response)}", False, False)

    except Exception as e:
        elapsed = time.perf_counter() - t_start
        err_str = str(e)
        return _build_empty_failure(
            elapsed, err_str,
            _detect_properties_wrap(err_str),
            _detect_capability_error(err_str),
        )


# ── Method dispatcher ─────────────────────────────────────────────────────────

METHOD_RUNNERS = {
    "METHOD_A": run_method_a,
    "METHOD_B": run_method_b,
    "METHOD_C": run_method_c,
    "METHOD_D": run_method_d,
    "METHOD_E": run_method_e,
}


# ── Per-method-prompt-slide runner ────────────────────────────────────────────

async def run_all_combinations(model_cfg: dict) -> dict:
    """
    For a given model, run ALL methods × prompts × slides × N_RUNS sequentially.
    Returns: { (method, prompt_label, slide_title): [result, ...] }
    """
    model_name = model_cfg["name"]
    results = {}  # key=(method, prompt_label, slide_title) -> list of result dicts

    total_methods = len(METHODS)
    total_prompts = len(PROMPTS)
    total_slides  = len(SLIDE_OUTLINES)
    total_runs    = total_methods * total_prompts * total_slides * N_RUNS
    call_n        = 0

    for method in METHODS:
        runner = METHOD_RUNNERS[method]
        for p_label, prompt_template in PROMPTS:
            for slide in SLIDE_OUTLINES:
                slide_title = slide["title"]
                key = (method, p_label, slide_title)
                results[key] = []

                for run_idx in range(N_RUNS):
                    call_n += 1
                    print(
                        f"  [{model_name}][{method}][{p_label}] "
                        f"slide={slide_title!r:30s} run={run_idx+1}/{N_RUNS} "
                        f"({call_n}/{total_runs})",
                        end=" ", flush=True,
                    )

                    result = await runner(prompt_template, slide, model_cfg)
                    result["method"]      = method
                    result["slide_title"] = slide_title
                    result["run_idx"]     = run_idx
                    results[key].append(result)

                    if result.get("skipped"):
                        mark = "-- skip"
                    elif result.get("capability_error"):
                        mark = "cap_err"
                    elif result["success"]:
                        mark = "OK"
                    elif result["properties_wrap"]:
                        mark = "WRAP"
                    else:
                        mark = "FAIL"
                    print(f"-> {mark} ({result['elapsed_s']}s)")

    return results


# ── Aggregate metrics ─────────────────────────────────────────────────────────

def aggregate(runs: list) -> dict:
    """Compute summary metrics for a list of run result dicts."""
    n = len(runs)
    if n == 0:
        return {
            "n": 0, "success_rate": 0.0, "layout_valid_rate": 0.0,
            "idx_valid_rate": 0.0, "avg_elapsed_s": 0.0,
            "properties_wrap_count": 0, "capability_error_count": 0,
            "skip_count": 0,
        }
    non_skipped = [r for r in runs if not r.get("skipped")]
    n_ns = len(non_skipped)
    return {
        "n":                      n,
        "success_rate":           sum(1 for r in runs if r["success"]) / n,
        "layout_valid_rate":      sum(1 for r in runs if r["layout_valid"]) / n,
        "idx_valid_rate":         sum(1 for r in runs if r["idx_title_valid"] and r["idx_content_valid"]) / n,
        "avg_elapsed_s":          round(sum(r["elapsed_s"] for r in non_skipped) / n_ns, 1) if n_ns else 0.0,
        "properties_wrap_count":  sum(1 for r in runs if r["properties_wrap"]),
        "capability_error_count": sum(1 for r in runs if r.get("capability_error")),
        "skip_count":             sum(1 for r in runs if r.get("skipped")),
    }


# ── Print model summary table ─────────────────────────────────────────────────

def print_model_tables(model_name: str, results: dict, prompts_list: list):
    """
    Print a table: rows=methods, columns=prompts, value=success_rate.
    Also print avg_elapsed_s and per-slide breakdown.
    """
    prompt_labels = [p[0] for p in prompts_list]
    col_w = 14

    print(f"\n{'='*90}")
    print(f"  MODEL: {model_name}")
    print(f"{'='*90}")

    # SUCCESS RATE TABLE
    print(f"\n  Success Rate (rows=methods, cols=prompts):")
    header = f"  {'Method':<12}" + "".join(f"{pl[:col_w]:<{col_w}}" for pl in prompt_labels)
    print(header)
    print(f"  {'-'*(12 + col_w * len(prompt_labels))}")
    for method in METHODS:
        row_vals = []
        for p_label, _ in prompts_list:
            # All slides combined
            all_runs = []
            for slide in SLIDE_OUTLINES:
                key = (method, p_label, slide["title"])
                all_runs.extend(results.get(key, []))
            agg = aggregate(all_runs)
            if agg["skip_count"] == len(all_runs) and len(all_runs) > 0:
                row_vals.append("SKIP")
            else:
                row_vals.append(f"{agg['success_rate']:.0%}")
        print(f"  {method:<12}" + "".join(f"{v:<{col_w}}" for v in row_vals))

    # AVG ELAPSED TABLE
    print(f"\n  Avg Elapsed (s) (rows=methods, cols=prompts):")
    print(header)
    print(f"  {'-'*(12 + col_w * len(prompt_labels))}")
    for method in METHODS:
        row_vals = []
        for p_label, _ in prompts_list:
            all_runs = []
            for slide in SLIDE_OUTLINES:
                key = (method, p_label, slide["title"])
                all_runs.extend(results.get(key, []))
            agg = aggregate(all_runs)
            if agg["skip_count"] == len(all_runs) and len(all_runs) > 0:
                row_vals.append("SKIP")
            else:
                row_vals.append(str(agg["avg_elapsed_s"]))
        print(f"  {method:<12}" + "".join(f"{v:<{col_w}}" for v in row_vals))

    # PER-SLIDE BREAKDOWN (per method, best prompt only)
    print(f"\n  Per-slide success breakdown (all prompts combined, {N_RUNS} runs each):")
    slide_header = f"  {'Method':<12}{'Prompt':<38}" + "".join(
        f"{s['title'][:12]:<14}" for s in SLIDE_OUTLINES
    )
    print(slide_header)
    print(f"  {'-'*(12 + 38 + 14 * len(SLIDE_OUTLINES))}")
    for method in METHODS:
        for p_label, _ in prompts_list:
            slide_vals = []
            for slide in SLIDE_OUTLINES:
                key = (method, p_label, slide["title"])
                runs = results.get(key, [])
                if not runs:
                    slide_vals.append("N/A")
                elif runs[0].get("skipped"):
                    slide_vals.append("SKIP")
                else:
                    n_ok = sum(1 for r in runs if r["success"])
                    slide_vals.append(f"{n_ok}/{len(runs)}")
            print(f"  {method:<12}{p_label:<38}" + "".join(f"{v:<14}" for v in slide_vals))


# ── Cross-method summary table ────────────────────────────────────────────────

def print_cross_method_summary(all_model_results: dict, prompts_list: list):
    """Print model × method × best_prompt -> success_rate."""
    print(f"\n\n{'='*90}")
    print("  CROSS-METHOD SUMMARY: model x method x best_prompt -> success_rate")
    print(f"{'='*90}")
    print(f"  {'Model':<28} {'Method':<12} {'BestPrompt':<38} {'SuccessRate':>12}")
    print(f"  {'-'*92}")

    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        results = all_model_results[model_name]

        for method in METHODS:
            best_rate   = -1.0
            best_prompt = ""
            for p_label, _ in prompts_list:
                all_runs = []
                for slide in SLIDE_OUTLINES:
                    key = (method, p_label, slide["title"])
                    all_runs.extend(results.get(key, []))
                agg = aggregate(all_runs)
                if agg["success_rate"] > best_rate:
                    best_rate   = agg["success_rate"]
                    best_prompt = p_label

            if best_rate < 0:
                rate_str = "N/A"
            elif all(
                results.get((method, p_label, slide["title"]), [{}])[0].get("skipped")
                for p_label, _ in prompts_list
                for slide in SLIDE_OUTLINES
            ):
                rate_str = "SKIP"
            else:
                rate_str = f"{best_rate:.0%}"

            print(f"  {model_name:<28} {method:<12} {best_prompt:<38} {rate_str:>12}")
        print()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main():
    total_calls = len(MODELS) * len(PROMPTS) * len(METHODS) * len(SLIDE_OUTLINES) * N_RUNS
    print(f"\n{'='*90}")
    print(f"  outlines_with_layout — Method Comparison (v2)")
    print(f"  Models:  {', '.join(m['name'] for m in MODELS)}")
    print(f"  Methods: {', '.join(METHODS)}")
    print(f"  Prompts: {len(PROMPTS)}  |  Slides: {len(SLIDE_OUTLINES)}  |  N_RUNS: {N_RUNS}")
    print(f"  Total LLM calls (max): {total_calls}")
    print(f"  ALL EXECUTION IS SEQUENTIAL")
    print(f"{'='*90}\n")

    all_model_results = {}  # model_name -> results dict

    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        print(f"\n{'#'*90}")
        print(f"# Testing model: {model_name}")
        print(f"{'#'*90}")

        results = await run_all_combinations(model_cfg)
        all_model_results[model_name] = results

    # ── Print tables per model ─────────────────────────────────────────────────
    print(f"\n\n{'='*90}")
    print("  COMPARISON TABLES")
    print(f"{'='*90}")

    for model_cfg in MODELS:
        model_name = model_cfg["name"]
        print_model_tables(model_name, all_model_results[model_name], PROMPTS)

    # ── Cross-method summary ───────────────────────────────────────────────────
    print_cross_method_summary(all_model_results, PROMPTS)

    # ── Save raw results as JSON ───────────────────────────────────────────────
    output_dir = Path(__file__).parent
    raw_json_path = output_dir / "augment_results_raw.json"

    # Convert tuple keys to strings for JSON serialization
    serializable = {}
    for model_name, results in all_model_results.items():
        serializable[model_name] = {}
        for (method, p_label, slide_title), runs in results.items():
            key_str = f"{method}|{p_label}|{slide_title}"
            serializable[model_name][key_str] = runs

    with open(raw_json_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False)
    print(f"\n  Raw results saved to: {raw_json_path}")

    print(f"\n{'='*90}")
    print("  DONE")
    print(f"{'='*90}\n")

    return all_model_results


if __name__ == "__main__":
    asyncio.run(main())
