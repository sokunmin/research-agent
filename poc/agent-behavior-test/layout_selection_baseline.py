"""
Layout Name Comprehension Test v2
===================================
Extended version of layout_name_test.py that tests THREE models:
  1. ollama/gemma3:4b          (local baseline)
  2. ollama/ministral-3:14b-cloud  (cloud, no think mode)
  3. ollama/gpt-oss:20b-cloud      (cloud, think mode always on)

Method: LLMTextCompletionProgram (METHOD_B)
N_RUNS: 3 per (model × slide_type)
Execution: SEQUENTIAL ONLY — no asyncio.gather (Ollama does not support parallel)

NOTE ON gemma3:4b RESULTS:
  If layout_name_test_results.json exists and its slide test cases match exactly
  (same labels, same expected layouts), we load gemma3:4b results from that file
  instead of re-running to save time. The check is strict: label set and expected
  layout sets must both match. If any mismatch, we re-run.

NOTE ON CLOUD MODEL CONFIG:
  Model names and additional_kwargs are taken EXACTLY from test_cloud_models.py.
  - ministral-3:14b-cloud → ollama/ministral-3:14b-cloud, no additional_kwargs
  - gpt-oss:20b-cloud     → ollama/gpt-oss:20b-cloud, no additional_kwargs
  Both are accessed via Ollama's cloud routing (no local GPU required).
  The provider prefix is "ollama/" (same as local models).
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from agent_workflows.schemas import SlideOutlineWithLayout
from llama_index.llms.litellm import LiteLLM
from llama_index.core.program import LLMTextCompletionProgram
from utils.tools import get_all_layouts_info

# ── Config ─────────────────────────────────────────────────────────────────────

TEMPLATE_PATH = str(
    Path(__file__).parent.parent.parent / "assets" / "template-en.pptx"
)

# Models to test — config taken EXACTLY from test_cloud_models.py:
#   - "ollama/" prefix is the litellm provider prefix for local Ollama models
#     (cloud models also use this prefix; Ollama proxies to upstream cloud)
#   - additional_kwargs: empty dict means no extra_body / think suppression
#     (for gpt-oss:20b-cloud, think=False is ignored per test_cloud_models.md,
#     so we do not attempt to suppress thinking — accept always-on think mode)
MODELS = [
    {
        "name": "ollama/gemma3:4b",
        "additional_kwargs": {},
        "label": "gemma3:4b",
    },
    {
        "name": "ollama/ministral-3:14b-cloud",
        "additional_kwargs": {},
        "label": "ministral-3:14b-cloud",
    },
    {
        "name": "ollama/gpt-oss:20b-cloud",
        "additional_kwargs": {},
        "label": "gpt-oss:20b-cloud",
    },
]

N_RUNS = 3  # runs per (model × slide_type)

# ── Load real layout info from template-en.pptx ────────────────────────────────
# Layout names are NEVER hardcoded — always read from the template file.

def _load_layouts():
    raw = get_all_layouts_info(TEMPLATE_PATH)
    simplified = []
    for l in raw:
        simplified.append({
            "layout_name": l["layout_name"],
            "placeholders": [
                {
                    "index": p["index"],
                    "font_size": p["font_size"],
                    "auto_size": p["auto_size"],
                }
                for p in l["placeholders"]
            ],
        })
    return simplified

AVAILABLE_LAYOUTS = _load_layouts()
AVAILABLE_LAYOUT_NAMES = [l["layout_name"] for l in AVAILABLE_LAYOUTS]
VALID_LAYOUT_NAMES = set(AVAILABLE_LAYOUT_NAMES)

# ── Test cases: 6 representative slide types ──────────────────────────────────
# These are IDENTICAL to layout_name_test.py — do not change them.
# (gemma3:4b result loading depends on exact match of labels + expected sets.)

SLIDE_TEST_CASES = [
    {
        "label": "cover/title_slide",
        "slide": {
            "title": "Attention Is All You Need",
            "content": "A Research Presentation\nPresented by: John Smith",
        },
        "expected": {"TITLE_SLIDE"},
        "description": "Cover/title slide — should pick TITLE_SLIDE",
    },
    {
        "label": "academic_content",
        "slide": {
            "title": "Transformer Architecture",
            "content": (
                "* Key Approach: Self-attention mechanism replacing recurrence\n"
                "* Multi-head attention with positional encoding\n"
                "* Encoder-decoder architecture\n"
                "* Outperforms RNN/CNN baselines on translation tasks"
            ),
        },
        "expected": {"TITLE_AND_BODY", "項目符號"},
        "description": "Regular academic content slide — should pick TITLE_AND_BODY or 項目符號",
    },
    {
        "label": "section_header",
        "slide": {
            "title": "Chapter 2: Methodology",
            "content": "",
        },
        "expected": {"SECTION_HEADER_CENTER", "SECTION_HEADER_TOP"},
        "description": "Section header / chapter transition — should pick SECTION_HEADER_CENTER or SECTION_HEADER_TOP",
    },
    {
        "label": "bullet_list",
        "slide": {
            "title": "Key Findings",
            "content": (
                "* 15% improvement in BLEU score over baseline\n"
                "* 3x faster training convergence\n"
                "* Reduced memory footprint by 40%\n"
                "* Better generalisation on out-of-domain data"
            ),
        },
        "expected": {"項目符號", "TITLE_AND_BODY"},
        "description": "Bullet list only — should pick 項目符號 or TITLE_AND_BODY",
    },
    {
        "label": "closing_slide",
        "slide": {
            "title": "Thank You",
            "content": "Questions and Discussion\nContact: research@example.com",
        },
        "expected": {"TITLE_SLIDE", "SECTION_HEADER_CENTER"},
        "description": "Thank you / closing slide — should pick TITLE_SLIDE or SECTION_HEADER_CENTER",
    },
    {
        "label": "quote_slide",
        "slide": {
            "title": "Inspiration",
            "content": (
                '"The measure of intelligence is the ability to change."\n'
                "— Albert Einstein"
            ),
        },
        "expected": {"QUOTE"},
        "description": "Quote slide — should pick QUOTE",
    },
]

# ── Prompt (identical to layout_name_test.py — AUGMENT_LAYOUT_PMT) ────────────

PROMPT_TEMPLATE = """
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
- layout_name: the exact name string of the chosen layout (must match one of the available layout names exactly)
- idx_title_placeholder: the numeric index (as a string) of the title placeholder in the chosen layout
- idx_content_placeholder: the numeric index (as a string) of the content placeholder in the chosen layout
"""

# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_llm(model_cfg: dict) -> LiteLLM:
    llm_kwargs = dict(model=model_cfg["name"], temperature=0.1, max_tokens=2048)
    additional_kwargs = dict(model_cfg.get("additional_kwargs", {}))
    if additional_kwargs:
        llm_kwargs["additional_kwargs"] = additional_kwargs
    return LiteLLM(**llm_kwargs)


# ── METHOD_B: LLMTextCompletionProgram ────────────────────────────────────────

async def run_method_b(model_cfg: dict, slide_outline: dict, expected_layouts: set) -> dict:
    llm = _make_llm(model_cfg)
    t_start = time.perf_counter()
    try:
        program = LLMTextCompletionProgram.from_defaults(
            llm=llm,
            output_cls=SlideOutlineWithLayout,
            prompt_template_str=PROMPT_TEMPLATE,
            verbose=False,
        )
        response = await program.acall(
            slide_content=json.dumps(slide_outline),
            available_layout_names=json.dumps(AVAILABLE_LAYOUT_NAMES),
            available_layouts=json.dumps(AVAILABLE_LAYOUTS, indent=2),
        )
        elapsed = time.perf_counter() - t_start

        if not isinstance(response, SlideOutlineWithLayout):
            return {
                "success": False,
                "layout_chosen": None,
                "layout_valid": False,
                "layout_appropriate": False,
                "elapsed_s": round(elapsed, 1),
                "error": f"Unexpected type: {type(response)}",
            }

        layout_chosen = response.layout_name
        layout_valid = layout_chosen in VALID_LAYOUT_NAMES
        layout_appropriate = layout_chosen in expected_layouts

        return {
            "success": True,
            "layout_chosen": layout_chosen,
            "layout_valid": layout_valid,
            "layout_appropriate": layout_appropriate,
            "elapsed_s": round(elapsed, 1),
            "error": None,
        }

    except Exception as e:
        elapsed = time.perf_counter() - t_start
        return {
            "success": False,
            "layout_chosen": None,
            "layout_valid": False,
            "layout_appropriate": False,
            "elapsed_s": round(elapsed, 1),
            "error": str(e)[:400],
        }


# ── gemma3:4b result loading from previous run ────────────────────────────────

def _try_load_gemma3_results() -> dict | None:
    """
    Attempt to load gemma3:4b results from layout_name_test_results.json.
    Returns a dict {label: [run_dicts]} if:
      - The file exists
      - The model field is "ollama/gemma3:4b"
      - n_runs == N_RUNS (3)
      - All SLIDE_TEST_CASES labels are present
      - Expected layout sets match exactly
    Returns None if any condition fails (will trigger a fresh run).
    """
    json_path = Path(__file__).parent / "layout_name_test_results.json"
    if not json_path.exists():
        return None

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    if data.get("model") != "ollama/gemma3:4b":
        print("  [gemma3:4b] Skipping cached results: model mismatch")
        return None
    if data.get("n_runs") != N_RUNS:
        print(f"  [gemma3:4b] Skipping cached results: n_runs mismatch ({data.get('n_runs')} vs {N_RUNS})")
        return None

    # Build expected sets from current SLIDE_TEST_CASES
    current_expected = {tc["label"]: tc["expected"] for tc in SLIDE_TEST_CASES}

    # Verify all labels present and expected sets match
    summary = data.get("summary", [])
    cached_expected = {row["label"]: set(row["expected_layouts"]) for row in summary}

    for label, expected in current_expected.items():
        if label not in cached_expected:
            print(f"  [gemma3:4b] Skipping cached results: missing label '{label}'")
            return None
        if cached_expected[label] != expected:
            print(f"  [gemma3:4b] Skipping cached results: expected set mismatch for '{label}'")
            return None

    raw = data.get("raw_results", {})
    # Verify all labels have correct number of runs
    for label in current_expected:
        if label not in raw or len(raw[label]) != N_RUNS:
            print(f"  [gemma3:4b] Skipping cached results: incomplete runs for '{label}'")
            return None

    print("  [gemma3:4b] Loaded cached results from layout_name_test_results.json (slide cases match exactly)")
    return raw


# ── Per-model test runner ──────────────────────────────────────────────────────

async def run_model(model_cfg: dict, preloaded_results: dict | None = None) -> dict:
    """
    Run all SLIDE_TEST_CASES N_RUNS times for a single model.
    If preloaded_results is provided (gemma3:4b only), skip inference.
    Returns {label: [run_dicts]}.
    """
    model_name = model_cfg["name"]
    model_label = model_cfg["label"]

    if preloaded_results is not None:
        print(f"\n  [{model_label}] Using cached results (no inference needed)")
        return preloaded_results

    all_results = {}
    total_calls = len(SLIDE_TEST_CASES) * N_RUNS
    call_n = 0

    for test_case in SLIDE_TEST_CASES:
        label = test_case["label"]
        slide = test_case["slide"]
        expected = test_case["expected"]
        description = test_case["description"]

        print(f"\n  [{model_label}] [{label}]  {description}")
        print(f"  [{model_label}] Expected layout(s): {expected}")
        all_results[label] = []

        for run_idx in range(N_RUNS):
            call_n += 1
            print(
                f"    run {run_idx+1}/{N_RUNS}  ({call_n}/{total_calls})",
                end=" ", flush=True,
            )
            result = await run_method_b(model_cfg, slide, expected)
            result["run_idx"] = run_idx
            result["label"] = label
            all_results[label].append(result)

            if result["success"]:
                mark = "OK" if result["layout_appropriate"] else "WRONG"
                chosen = result["layout_chosen"]
                print(f"-> {mark}  chosen={chosen!r}  ({result['elapsed_s']}s)")
            else:
                err_preview = result["error"][:80] if result["error"] else "unknown"
                print(f"-> FAIL  err={err_preview}  ({result['elapsed_s']}s)")

    return all_results


# ── Summary table for a single model ──────────────────────────────────────────

def _print_model_summary(model_label: str, all_results: dict) -> list:
    """Print per-model results table. Returns summary_rows list."""
    print(f"\n\n{'='*80}")
    print(f"  RESULTS SUMMARY  (model: {model_label})")
    print(f"{'='*80}")
    header = (
        f"  {'Label':<22} {'Expected':<36} {'Chosen layouts (per run)':<36}"
        f"  {'Succ':>5} {'Appr':>5} {'AvgS':>6}"
    )
    print(header)
    print(f"  {'-'*115}")

    summary_rows = []
    for test_case in SLIDE_TEST_CASES:
        label = test_case["label"]
        expected = test_case["expected"]
        runs = all_results[label]

        n = len(runs)
        n_success = sum(1 for r in runs if r["success"])
        n_appropriate = sum(1 for r in runs if r["layout_appropriate"])
        n_elapsed = [r["elapsed_s"] for r in runs if r["success"]]
        avg_elapsed = round(sum(n_elapsed) / len(n_elapsed), 1) if n_elapsed else 0.0

        chosen_list = [
            r["layout_chosen"] if r["layout_chosen"] else "FAIL"
            for r in runs
        ]
        chosen_str = ", ".join(chosen_list)
        expected_str = "/".join(sorted(expected))
        success_rate = f"{n_success}/{n}"
        appr_rate = f"{n_appropriate}/{n}"

        print(
            f"  {label:<22} {expected_str:<36} {chosen_str:<36}"
            f"  {success_rate:>5} {appr_rate:>5} {avg_elapsed:>6}"
        )

        summary_rows.append({
            "label": label,
            "description": test_case["description"],
            "expected_layouts": sorted(expected),
            "chosen_layouts": chosen_list,
            "success_rate": f"{n_success}/{n}",
            "appropriate_rate": f"{n_appropriate}/{n}",
            "avg_elapsed_s": avg_elapsed,
        })

    print(f"{'='*80}")

    # Per-model findings
    total_appropriate = sum(
        sum(1 for r in all_results[tc["label"]] if r["layout_appropriate"])
        for tc in SLIDE_TEST_CASES
    )
    total_success = sum(
        sum(1 for r in all_results[tc["label"]] if r["success"])
        for tc in SLIDE_TEST_CASES
    )
    total_runs = len(SLIDE_TEST_CASES) * N_RUNS

    print(f"  Overall success rate:     {total_success}/{total_runs}")
    print(f"  Overall appropriate rate: {total_appropriate}/{total_runs}")
    print()

    for test_case in SLIDE_TEST_CASES:
        label = test_case["label"]
        runs = all_results[label]
        n_appropriate = sum(1 for r in runs if r["layout_appropriate"])
        chosen_unique = set(r["layout_chosen"] for r in runs if r["layout_chosen"])
        if n_appropriate == N_RUNS:
            verdict = "CORRECT (all runs)"
        elif n_appropriate > 0:
            verdict = f"PARTIAL ({n_appropriate}/{N_RUNS} runs correct)"
        else:
            verdict = f"INCORRECT — chose {chosen_unique}"
        print(f"  {label:<22}: {verdict}")

    return summary_rows


# ── Cross-model comparison table ───────────────────────────────────────────────

def _print_cross_model_comparison(model_results: list):
    """
    model_results: list of {model_label, all_results}
    """
    print(f"\n\n{'='*80}")
    print(f"  CROSS-MODEL COMPARISON")
    print(f"{'='*80}")
    header = (
        f"  {'Model':<30} {'Overall Succ':>14} {'Overall Appr':>14} {'Avg Elapsed':>13}"
    )
    print(header)
    print(f"  {'-'*75}")

    for item in model_results:
        label = item["model_label"]
        all_results = item["all_results"]
        total_runs = len(SLIDE_TEST_CASES) * N_RUNS
        total_success = sum(
            sum(1 for r in all_results[tc["label"]] if r["success"])
            for tc in SLIDE_TEST_CASES
        )
        total_appropriate = sum(
            sum(1 for r in all_results[tc["label"]] if r["layout_appropriate"])
            for tc in SLIDE_TEST_CASES
        )
        all_elapsed = [
            r["elapsed_s"]
            for tc in SLIDE_TEST_CASES
            for r in all_results[tc["label"]]
            if r["success"]
        ]
        avg_elapsed = round(sum(all_elapsed) / len(all_elapsed), 1) if all_elapsed else 0.0

        succ_str = f"{total_success}/{total_runs}"
        appr_str = f"{total_appropriate}/{total_runs}"
        elapsed_str = f"{avg_elapsed}s"

        print(
            f"  {label:<30} {succ_str:>14} {appr_str:>14} {elapsed_str:>13}"
        )

    print(f"{'='*80}\n")


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    output_dir = Path(__file__).parent

    print(f"\n{'='*80}")
    print(f"  Layout Name Comprehension Test v2")
    print(f"  Template: template-en.pptx")
    print(f"  Layouts:  {AVAILABLE_LAYOUT_NAMES}")
    print(f"  N_RUNS:   {N_RUNS} per (model × slide_type)")
    print(f"  Models:   {[m['label'] for m in MODELS]}")
    print(f"  ALL EXECUTION IS SEQUENTIAL")
    print(f"{'='*80}\n")

    # Try to load gemma3:4b cached results
    gemma3_cached = _try_load_gemma3_results()

    all_model_results = []   # list of {model_label, all_results, summary_rows}
    all_model_summaries = {}  # model_label -> summary_rows

    for model_cfg in MODELS:
        model_label = model_cfg["label"]
        model_name = model_cfg["name"]

        print(f"\n{'='*80}")
        print(f"  Running model: {model_name}  (label: {model_label})")
        print(f"{'='*80}")

        preloaded = gemma3_cached if model_label == "gemma3:4b" else None
        all_results = await run_model(model_cfg, preloaded_results=preloaded)

        summary_rows = _print_model_summary(model_label, all_results)
        all_model_results.append({
            "model_label": model_label,
            "all_results": all_results,
            "summary_rows": summary_rows,
        })
        all_model_summaries[model_label] = summary_rows

    # Cross-model comparison
    _print_cross_model_comparison(all_model_results)

    # ── Save results to JSON ───────────────────────────────────────────────────

    output_data = {
        "n_runs": N_RUNS,
        "template": TEMPLATE_PATH,
        "available_layout_names": AVAILABLE_LAYOUT_NAMES,
        "models": [],
    }

    for item in all_model_results:
        model_label = item["model_label"]
        model_cfg = next(m for m in MODELS if m["label"] == model_label)
        total_runs = len(SLIDE_TEST_CASES) * N_RUNS
        all_results = item["all_results"]

        total_success = sum(
            sum(1 for r in all_results[tc["label"]] if r["success"])
            for tc in SLIDE_TEST_CASES
        )
        total_appropriate = sum(
            sum(1 for r in all_results[tc["label"]] if r["layout_appropriate"])
            for tc in SLIDE_TEST_CASES
        )
        all_elapsed = [
            r["elapsed_s"]
            for tc in SLIDE_TEST_CASES
            for r in all_results[tc["label"]]
            if r["success"]
        ]
        avg_elapsed = round(sum(all_elapsed) / len(all_elapsed), 1) if all_elapsed else 0.0

        output_data["models"].append({
            "model_name": model_cfg["name"],
            "model_label": model_label,
            "additional_kwargs": model_cfg["additional_kwargs"],
            "overall_success_rate": f"{total_success}/{total_runs}",
            "overall_appropriate_rate": f"{total_appropriate}/{total_runs}",
            "avg_elapsed_s": avg_elapsed,
            "summary": item["summary_rows"],
            "raw_results": all_results,
        })

    json_path = output_dir / "layout_name_test_v2_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"  Results saved to: {json_path}")
    print(f"\n{'='*80}")
    print("  DONE")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
