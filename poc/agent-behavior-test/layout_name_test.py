"""
Layout Name Comprehension Test
================================
Tests whether gemma3:4b (via Ollama) correctly selects the right layout
for given slide content, using the NEW English layout names from template-en.pptx.

Method: METHOD_B (LLMTextCompletionProgram) — the target migration method.
Model:  ollama/gemma3:4b
N_RUNS: 3 per slide type (sequential execution only)
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

MODEL = {
    "name": "ollama/gemma3:4b",
    "additional_kwargs": {},
}

N_RUNS = 3  # runs per slide type

# ── Load real layout info from template-en.pptx ────────────────────────────────

def _load_layouts():
    raw = get_all_layouts_info(TEMPLATE_PATH)
    # Strip to only the fields relevant for prompting (keep it concise for small model)
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
# Each entry has: title, content, expected_layout (acceptable set), label

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

# ── Prompt (AUGMENT_LAYOUT_PMT from prompts.py) ────────────────────────────────

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

def _make_llm() -> LiteLLM:
    model_cfg = MODEL
    llm_kwargs = dict(model=model_cfg["name"], temperature=0.1, max_tokens=2048)
    additional_kwargs = dict(model_cfg.get("additional_kwargs", {}))
    if additional_kwargs:
        llm_kwargs["additional_kwargs"] = additional_kwargs
    return LiteLLM(**llm_kwargs)


def _valid_int_str(val) -> bool:
    try:
        int(val)
        return True
    except (ValueError, TypeError):
        return False


# ── METHOD_B: LLMTextCompletionProgram ────────────────────────────────────────

async def run_method_b(slide_outline: dict, expected_layouts: set) -> dict:
    llm = _make_llm()
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


# ── Main ───────────────────────────────────────────────────────────────────────

async def main():
    output_dir = Path(__file__).parent

    print(f"\n{'='*80}")
    print(f"  Layout Name Comprehension Test")
    print(f"  Model:    {MODEL['name']}")
    print(f"  Template: template-en.pptx")
    print(f"  Layouts:  {AVAILABLE_LAYOUT_NAMES}")
    print(f"  N_RUNS:   {N_RUNS} per slide type")
    print(f"  ALL EXECUTION IS SEQUENTIAL")
    print(f"{'='*80}\n")

    all_results = {}  # label -> list of run dicts

    total_calls = len(SLIDE_TEST_CASES) * N_RUNS
    call_n = 0

    for test_case in SLIDE_TEST_CASES:
        label = test_case["label"]
        slide = test_case["slide"]
        expected = test_case["expected"]
        description = test_case["description"]

        print(f"\n  [{label}]  {description}")
        print(f"  Expected layout(s): {expected}")
        all_results[label] = []

        for run_idx in range(N_RUNS):
            call_n += 1
            print(
                f"    run {run_idx+1}/{N_RUNS}  ({call_n}/{total_calls})",
                end=" ", flush=True,
            )
            result = await run_method_b(slide, expected)
            result["run_idx"] = run_idx
            result["label"] = label
            all_results[label].append(result)

            if result["success"]:
                mark = "OK" if result["layout_appropriate"] else "WRONG"
                chosen = result["layout_chosen"]
                print(f"-> {mark}  chosen={chosen!r}  ({result['elapsed_s']}s)")
            else:
                print(f"-> FAIL  err={result['error'][:80] if result['error'] else 'unknown'}  ({result['elapsed_s']}s)")

    # ── Print summary table ────────────────────────────────────────────────────

    print(f"\n\n{'='*80}")
    print(f"  RESULTS SUMMARY  (model: {MODEL['name']})")
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

    print(f"{'='*80}\n")

    # ── Findings analysis ──────────────────────────────────────────────────────

    print("  FINDINGS:")
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

    print()

    # ── Save results to JSON ───────────────────────────────────────────────────

    output_json = {
        "model": MODEL["name"],
        "template": TEMPLATE_PATH,
        "available_layout_names": AVAILABLE_LAYOUT_NAMES,
        "n_runs": N_RUNS,
        "summary": summary_rows,
        "raw_results": all_results,
    }

    json_path = output_dir / "layout_name_test_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_json, f, indent=2, ensure_ascii=False)

    print(f"  Results saved to: {json_path}")
    print(f"\n{'='*80}")
    print("  DONE")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    asyncio.run(main())
