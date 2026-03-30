"""
Layout Prompt Engineering Test
================================
Tests 4 prompt engineering strategies for slide layout selection across 3 models.
Builds on layout_name_test_v2.py which showed that cover/title_slide and closing_slide
fail universally across all models with the baseline prompt.

Models:
  1. ollama/gemma3:4b         (local, 4B — worst in previous test)
  2. ollama/ministral-3:14b-cloud  (best in previous test, 12/18)
  3. ollama/gpt-oss:20b-cloud      (second best, 10/18)
  Note: groq models are skipped because the .env uses ollama-based models for this task
        and the cloud models are accessed via Ollama's cloud routing.

Method: LLMTextCompletionProgram ONLY (FunctionCallingProgram fails for Ollama models,
        confirmed in augment-results.md).

Execution: SEQUENTIAL ONLY — no asyncio.gather (Ollama does not support parallel).

N_RUNS = 3 per (model × prompt × slide_type) combination.
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from dotenv import load_dotenv
load_dotenv('/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/.env')

from agent_workflows.schemas import SlideOutlineWithLayout
from llama_index.llms.litellm import LiteLLM
from llama_index.core.program import LLMTextCompletionProgram
from utils.tools import get_all_layouts_info

# ── Config ─────────────────────────────────────────────────────────────────────

TEMPLATE_PATH = str(
    Path(__file__).parent.parent.parent / "assets" / "template-en.pptx"
)

# Models — config taken from layout_name_test_v2.py and test_cloud_models.py.
# Cloud models accessed via Ollama's transparent cloud routing (ollama/ prefix).
MODELS = [
    {
        "name": "ollama/gemma3:4b",
        "additional_kwargs": {},
        "label": "gemma3:4b",
        "provider": "ollama",
    },
    {
        "name": "ollama/ministral-3:14b-cloud",
        "additional_kwargs": {},
        "label": "ministral-3:14b-cloud",
        "provider": "ollama",
    },
    {
        "name": "ollama/gpt-oss:20b-cloud",
        "additional_kwargs": {},
        "label": "gpt-oss:20b-cloud",
        "provider": "ollama",
    },
]

N_RUNS = 3  # runs per (model × prompt × slide_type)

# ── Load layout info from template-en.pptx ────────────────────────────────────

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

# ── Slide test cases (identical to layout_name_test_v2.py) ───────────────────

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
        "expected": {"TITLE_AND_BODY", "Bullet Points"},
        "description": "Regular academic content slide — should pick TITLE_AND_BODY or Bullet Points",
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
        "expected": {"Bullet Points", "TITLE_AND_BODY"},
        "description": "Bullet list only — should pick Bullet Points or TITLE_AND_BODY",
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

# ── Prompt Variants ────────────────────────────────────────────────────────────
#
# All 4 prompts test meaningfully different strategies.
# The baseline prompt (layout_name_test_v2.py PROMPT_TEMPLATE) has already been tested.
# We do NOT duplicate the baseline here — all 4 variants are new strategies.
#
# Strategy summary:
#   PROMPT_1: Decision-tree / explicit routing — step-by-step "if/then" dispatch rules
#   PROMPT_2: Negative examples — explicitly tells model what NOT to pick for each slide type
#   PROMPT_3: Chain-of-thought — ask model to reason about slide role before selecting layout
#   PROMPT_4: Minimal layout list + descriptions — reduce to 6 core layouts with English role descriptions

# ── PROMPT_1: Decision-tree routing ───────────────────────────────────────────
# Rationale: The baseline prompt gives a generic instruction. Models fail cover/title
# and closing slides because they lack explicit routing rules. A decision tree forces
# the model to match slide characteristics to layout before picking.
# Hypothesis: Explicit if/then rules will fix cover_slide and closing_slide failures.

PROMPT_1_DECISION_TREE = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and body text.

STEP 1 — Identify the slide role using this decision tree:
  A. If the slide body is a direct quote with an attribution line (e.g. "— Author Name")
     → role = QUOTE_SLIDE
  B. Else if the slide title starts with "Chapter", "Section", "Part", or the body is empty or nearly empty (< 10 characters)
     → role = SECTION_BREAK
  C. Else if the slide title is "Thank You", "Conclusion", "Q&A", "Questions", "Contact", or the content is a short closing message (contact info, acknowledgements)
     → role = CLOSING_SLIDE
  D. Else if the slide has a subtitle line like "Presented by:", "A Research Presentation", or "Author:" in the body and no bullet points
     → role = TITLE_COVER
  E. Else if the slide body contains bullet points (* or -)
     → role = CONTENT_SLIDE
  F. Else
     → role = CONTENT_SLIDE

STEP 2 — Select layout based on role:
  - role = QUOTE_SLIDE     → use layout: QUOTE
  - role = SECTION_BREAK   → use layout: SECTION_HEADER_CENTER or SECTION_HEADER_TOP
  - role = CLOSING_SLIDE   → use layout: TITLE_SLIDE or SECTION_HEADER_CENTER
  - role = TITLE_COVER     → use layout: TITLE_SLIDE
  - role = CONTENT_SLIDE   → use layout: TITLE_AND_BODY or Bullet Points

The following layouts are available: {available_layout_names}
Layout details:
{available_layouts}

Slide content to classify:
{slide_content}

Output the following fields:
- title: the slide title text (copy verbatim from input)
- content: the slide body text (copy verbatim from input)
- layout_name: the exact name string of the chosen layout (must match one of the available layout names exactly)
- idx_title_placeholder: the numeric index (as a string) of the title placeholder in the chosen layout
- idx_content_placeholder: the numeric index (as a string) of the content placeholder in the chosen layout
"""

# ── PROMPT_2: Negative examples ───────────────────────────────────────────────
# Rationale: Models exhibit TITLE_AND_BODY bias. Explicit "do NOT use X for Y"
# instructions may break the default bias without requiring complex routing logic.
# Hypothesis: Negative constraints reduce inappropriate TITLE_AND_BODY choices.

PROMPT_2_NEGATIVE_EXAMPLES = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and main text body.

LAYOUT SELECTION RULES — follow these exactly:

USE TITLE_SLIDE when:
  - The slide is the opening/cover slide of the presentation
  - The body contains author name, institution, or "Presented by:" lines
  - The slide is a closing/thank-you slide ("Thank You", "Q&A", "Questions")

USE SECTION_HEADER_CENTER or SECTION_HEADER_TOP when:
  - The body is empty or very short (no bullet points)
  - The title begins with "Chapter", "Section", "Part", or similar division markers

USE QUOTE when:
  - The body contains a direct quotation with attribution (e.g. "— Author Name")
  - The main content is a single sentence or short paragraph presented as a quote

USE TITLE_AND_BODY or Bullet Points when:
  - The slide contains multiple bullet points (* or -)
  - The body is substantive academic or technical content

DO NOT use TITLE_AND_BODY for:
  - Opening cover slides with author attribution
  - Chapter/section transition slides with empty or minimal body
  - Closing/thank-you slides
  - Slides whose body is a quoted sentence with attribution line

The following layouts are available: {available_layout_names}
Layout details:
{available_layouts}

Slide content:
{slide_content}

Output the following fields:
- title: the slide title text (copy verbatim from input)
- content: the slide body text (copy verbatim from input)
- layout_name: the exact name string of the chosen layout (must match one of the available layout names exactly)
- idx_title_placeholder: the numeric index (as a string) of the title placeholder in the chosen layout
- idx_content_placeholder: the numeric index (as a string) of the content placeholder in the chosen layout
"""

# ── PROMPT_3: Chain-of-thought ────────────────────────────────────────────────
# Rationale: Previous prompts ask for the answer directly. Chain-of-thought asks the
# model to explicitly classify the slide type before selecting a layout, making
# reasoning explicit and giving models a chance to self-correct.
# Hypothesis: CoT reasoning improves accuracy on ambiguous slides (cover, closing).

PROMPT_3_CHAIN_OF_THOUGHT = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and body text.

Before selecting a layout, REASON STEP BY STEP:

1. What type of slide is this? Choose one:
   - "cover": the opening/title page of a presentation (has author attribution, institution, or "Presented by")
   - "section_break": a chapter or section divider (body is empty or only has a subtitle/tagline, no bullets)
   - "closing": a thank-you, Q&A, or conclusion slide
   - "quote": body is a quoted sentence with attribution (e.g. "— Einstein")
   - "content": a slide with substantial bullet-point content

2. Based on the slide type, which layout is most appropriate?
   - cover      → TITLE_SLIDE
   - section_break → SECTION_HEADER_CENTER or SECTION_HEADER_TOP
   - closing    → TITLE_SLIDE or SECTION_HEADER_CENTER
   - quote      → QUOTE
   - content    → TITLE_AND_BODY or Bullet Points

3. Confirm: does the chosen layout exist in the available layout list below?

The following layouts are available: {available_layout_names}
Layout details:
{available_layouts}

Slide content:
{slide_content}

Output the following fields:
- title: the slide title text (copy verbatim from input)
- content: the slide body text (copy verbatim from input)
- layout_name: the exact name string of the chosen layout (must match one of the available layout names exactly)
- idx_title_placeholder: the numeric index (as a string) of the title placeholder in the chosen layout
- idx_content_placeholder: the numeric index (as a string) of the content placeholder in the chosen layout
"""

# ── PROMPT_4: Minimal layout list with role descriptions ─────────────────────
# Rationale: All 12 layouts overwhelm the model with irrelevant options. Photo layouts,
# full-photo, and blank are almost never correct for text slides. Providing only the
# 6 text-relevant layouts with clear English role descriptions reduces the search space.
# Chinese layout names ("Bullet Points", "Blank") are renamed to English descriptions to avoid
# the disambiguation problem noted in layout_name_test.md §8.3.
# Hypothesis: Smaller, clearly described layout list improves selection accuracy.
#
# NOTE: We still pass the full available_layout_names for the validity check,
# but the prompt narrative focuses on the 6 most relevant layouts.

PROMPT_4_MINIMAL_LAYOUT = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and body text.

AVAILABLE TEXT LAYOUTS (choose from these 6 for text slides):

1. TITLE_SLIDE
   Role: Opening cover slide OR closing thank-you slide.
   Use when: The slide is the first or last slide of the presentation,
             body has author/institution info, or title is "Thank You" / "Conclusion".

2. TITLE_AND_BODY
   Role: Standard academic or technical content slide.
   Use when: The slide has a title and multiple paragraphs or bullet points of body text.

3. Bullet Points  (bullet list layout)
   Role: Bullet-point content slide — similar to TITLE_AND_BODY but optimized for lists.
   Use when: The body is a list of bullet points (* or -).

4. SECTION_HEADER_CENTER
   Role: Section divider centered on slide. No body content area.
   Use when: The slide marks the start of a new section/chapter with empty or very short body.

5. SECTION_HEADER_TOP
   Role: Section divider with title at top. No body content area.
   Use when: Same as SECTION_HEADER_CENTER — chapter/section transition with minimal body.

6. QUOTE
   Role: Large-format quote display.
   Use when: The body is a quotation sentence with attribution (e.g. "— Author Name").

For photo-heavy or decorative content, other layouts exist but are not listed here.

The full list of available layouts (for reference): {available_layout_names}
Full layout technical details:
{available_layouts}

Slide content:
{slide_content}

Output the following fields:
- title: the slide title text (copy verbatim from input)
- content: the slide body text (copy verbatim from input)
- layout_name: the exact name string of the chosen layout (must match one of the available layout names exactly)
- idx_title_placeholder: the numeric index (as a string) of the title placeholder in the chosen layout
- idx_content_placeholder: the numeric index (as a string) of the content placeholder in the chosen layout
"""

# ── Prompt registry ────────────────────────────────────────────────────────────

PROMPTS = [
    {
        "id": "P1_decision_tree",
        "label": "Decision-Tree Routing",
        "template": PROMPT_1_DECISION_TREE,
        "description": "Explicit if/then decision tree: classify slide role → pick layout",
        "rationale": "Baseline prompt has no routing rules. Explicit dispatch may fix cover/closing failures.",
    },
    {
        "id": "P2_negative_examples",
        "label": "Negative Examples",
        "template": PROMPT_2_NEGATIVE_EXAMPLES,
        "description": "Explicit 'DO NOT use TITLE_AND_BODY for X' constraints",
        "rationale": "All models show TITLE_AND_BODY bias. Explicit negative constraints aim to break that default.",
    },
    {
        "id": "P3_chain_of_thought",
        "label": "Chain-of-Thought",
        "template": PROMPT_3_CHAIN_OF_THOUGHT,
        "description": "Ask model to classify slide type explicitly before selecting layout",
        "rationale": "Making reasoning explicit via CoT steps may improve accuracy on ambiguous slides.",
    },
    {
        "id": "P4_minimal_layout",
        "label": "Minimal Layout List",
        "template": PROMPT_4_MINIMAL_LAYOUT,
        "description": "Only 6 core text layouts with English role descriptions",
        "rationale": "12 layouts including irrelevant photo/blank layouts overwhelm the model. Smaller list + descriptions reduces ambiguity.",
    },
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_llm(model_cfg: dict) -> LiteLLM:
    llm_kwargs = dict(model=model_cfg["name"], temperature=0.1, max_tokens=2048)
    additional_kwargs = dict(model_cfg.get("additional_kwargs", {}))
    if additional_kwargs:
        llm_kwargs["additional_kwargs"] = additional_kwargs
    return LiteLLM(**llm_kwargs)


def _check_model_available(model_cfg: dict) -> bool:
    """Quick availability check using a minimal prompt."""
    import litellm
    try:
        resp = litellm.completion(
            model=model_cfg["name"],
            messages=[{"role": "user", "content": "Reply with exactly: OK"}],
            max_tokens=50,
            timeout=30,
        )
        content = resp.choices[0].message.content or ""
        return len(content) > 0
    except Exception as e:
        msg = str(e).lower()
        if any(kw in msg for kw in ["model not found", "404", "not found", "pull", "no such model", "api key", "unauthorized", "invalid key"]):
            return False
        # Other errors (network timeout, etc.) — treat as not available for safety
        print(f"    [availability check] error for {model_cfg['name']}: {str(e)[:120]}")
        return False


# ── Single run: one (model, prompt, slide_type) combination ───────────────────

def run_single(model_cfg: dict, prompt_cfg: dict, slide_outline: dict, expected_layouts: set) -> dict:
    llm = _make_llm(model_cfg)
    t_start = time.perf_counter()
    try:
        program = LLMTextCompletionProgram.from_defaults(
            llm=llm,
            output_cls=SlideOutlineWithLayout,
            prompt_template_str=prompt_cfg["template"],
            verbose=False,
        )
        response = program(
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


# ── Per-model runner (all prompts × all slide types × N_RUNS) ─────────────────

def run_model(model_cfg: dict) -> dict | None:
    """
    Returns nested dict: {prompt_id: {slide_label: [run_dicts]}}
    Returns None if model is not available.
    """
    model_name = model_cfg["name"]
    model_label = model_cfg["label"]

    print(f"\n{'='*80}")
    print(f"  Checking availability: {model_name}")
    available = _check_model_available(model_cfg)
    if not available:
        print(f"  SKIP — model not available or API key missing: {model_name}")
        print(f"{'='*80}")
        return None
    print(f"  OK — model available")
    print(f"{'='*80}")

    all_results = {}  # prompt_id -> {label -> [run_dicts]}

    total_calls = len(PROMPTS) * len(SLIDE_TEST_CASES) * N_RUNS
    call_n = 0

    for prompt_cfg in PROMPTS:
        prompt_id = prompt_cfg["id"]
        prompt_label = prompt_cfg["label"]
        all_results[prompt_id] = {}

        print(f"\n  [{model_label}] Prompt: {prompt_id} — {prompt_label}")
        print(f"  Rationale: {prompt_cfg['rationale']}")

        for test_case in SLIDE_TEST_CASES:
            label = test_case["label"]
            slide = test_case["slide"]
            expected = test_case["expected"]
            description = test_case["description"]

            print(f"\n    [{model_label}][{prompt_id}] [{label}]  {description}")
            print(f"    Expected: {expected}")
            all_results[prompt_id][label] = []

            for run_idx in range(N_RUNS):
                call_n += 1
                print(
                    f"      run {run_idx+1}/{N_RUNS}  (call {call_n}/{total_calls})",
                    end=" ", flush=True,
                )
                result = run_single(model_cfg, prompt_cfg, slide, expected)
                result["run_idx"] = run_idx
                result["label"] = label
                result["prompt_id"] = prompt_id
                all_results[prompt_id][label].append(result)

                if result["success"]:
                    mark = "OK" if result["layout_appropriate"] else "WRONG"
                    chosen = result["layout_chosen"]
                    print(f"-> {mark}  chosen={chosen!r}  ({result['elapsed_s']}s)")
                else:
                    err_preview = result["error"][:80] if result["error"] else "unknown"
                    print(f"-> FAIL  err={err_preview}  ({result['elapsed_s']}s)")

    return all_results


# ── Summary tables ─────────────────────────────────────────────────────────────

def _print_model_summary(model_label: str, all_results: dict) -> list:
    """
    Print per-model table: rows = prompts, columns = slide types.
    Shows appropriate_rate as N/3 format.
    Returns list of summary dicts.
    """
    print(f"\n\n{'='*100}")
    print(f"  MODEL SUMMARY: {model_label}")
    print(f"{'='*100}")

    # Header
    slide_labels = [tc["label"] for tc in SLIDE_TEST_CASES]
    col_w = 20
    header = f"  {'Prompt':<32}"
    for sl in slide_labels:
        short = sl[:col_w]
        header += f"  {short:>{col_w}}"
    header += f"  {'Overall':>10}  {'AvgElap':>8}"
    print(header)
    print(f"  {'-'*120}")

    summary_rows = []
    for prompt_cfg in PROMPTS:
        prompt_id = prompt_cfg["id"]
        prompt_label = prompt_cfg["label"]
        prompt_results = all_results.get(prompt_id, {})

        row = f"  {prompt_label:<32}"
        total_appr = 0
        total_runs = 0
        all_elapsed = []

        per_slide = {}
        for test_case in SLIDE_TEST_CASES:
            label = test_case["label"]
            runs = prompt_results.get(label, [])
            n_appr = sum(1 for r in runs if r.get("layout_appropriate", False))
            n = len(runs)
            cell = f"{n_appr}/{n}"
            row += f"  {cell:>{col_w}}"
            total_appr += n_appr
            total_runs += n
            elapsed_ok = [r["elapsed_s"] for r in runs if r.get("success", False)]
            all_elapsed.extend(elapsed_ok)
            per_slide[label] = {
                "appropriate_rate": f"{n_appr}/{n}",
                "chosen_layouts": [r.get("layout_chosen") for r in runs],
            }

        overall = f"{total_appr}/{total_runs}"
        avg_e = round(sum(all_elapsed) / len(all_elapsed), 1) if all_elapsed else 0.0
        row += f"  {overall:>10}  {avg_e:>7}s"
        print(row)

        summary_rows.append({
            "prompt_id": prompt_id,
            "prompt_label": prompt_label,
            "per_slide": per_slide,
            "overall_appropriate_rate": overall,
            "total_appropriate": total_appr,
            "total_runs": total_runs,
            "avg_elapsed_s": avg_e,
        })

    print(f"{'='*100}")
    return summary_rows


def _print_cross_model_summary(model_summaries: list):
    """
    Print cross-model table: rows = model × prompt, columns = overall metrics.
    model_summaries: list of {model_label, summary_rows, available}
    """
    print(f"\n\n{'='*100}")
    print(f"  CROSS-MODEL SUMMARY")
    print(f"{'='*100}")
    header = f"  {'Model':<30}  {'Prompt':<32}  {'Overall Appr':>14}  {'Overall Succ':>14}  {'Avg Elapsed':>12}"
    print(header)
    print(f"  {'-'*100}")

    for item in model_summaries:
        model_label = item["model_label"]
        if not item["available"]:
            print(f"  {model_label:<30}  {'SKIPPED — not available':<32}")
            continue
        all_results_raw = item["all_results_raw"]
        for prompt_cfg in PROMPTS:
            prompt_id = prompt_cfg["id"]
            prompt_label = prompt_cfg["label"]
            prompt_results = all_results_raw.get(prompt_id, {})

            total_appr = 0
            total_succ = 0
            total_runs = 0
            all_elapsed = []
            for test_case in SLIDE_TEST_CASES:
                label = test_case["label"]
                runs = prompt_results.get(label, [])
                total_appr += sum(1 for r in runs if r.get("layout_appropriate", False))
                total_succ += sum(1 for r in runs if r.get("success", False))
                total_runs += len(runs)
                all_elapsed.extend(r["elapsed_s"] for r in runs if r.get("success", False))

            avg_e = round(sum(all_elapsed) / len(all_elapsed), 1) if all_elapsed else 0.0
            print(
                f"  {model_label:<30}  {prompt_label:<32}  "
                f"{total_appr}/{total_runs:>{3}}  {'':>10}  "
                f"{total_succ}/{total_runs:>{3}}  {'':>10}  "
                f"{avg_e:>10}s"
            )

    print(f"{'='*100}")

    # Also print a clean compact summary table
    print(f"\n\n  COMPACT CROSS-MODEL SUMMARY (appropriate_rate / success_rate / avg_s)")
    print(f"  {'Model':<30}  {'Prompt':<32}  {'appr_rate':>12}  {'succ_rate':>12}  {'avg_s':>8}")
    print(f"  {'-'*100}")
    for item in model_summaries:
        model_label = item["model_label"]
        if not item["available"]:
            print(f"  {model_label:<30}  {'SKIPPED':<32}")
            continue
        all_results_raw = item["all_results_raw"]
        for prompt_cfg in PROMPTS:
            prompt_id = prompt_cfg["id"]
            prompt_label = prompt_cfg["label"]
            prompt_results = all_results_raw.get(prompt_id, {})

            total_appr = 0
            total_succ = 0
            total_runs = 0
            all_elapsed = []
            for test_case in SLIDE_TEST_CASES:
                label = test_case["label"]
                runs = prompt_results.get(label, [])
                total_appr += sum(1 for r in runs if r.get("layout_appropriate", False))
                total_succ += sum(1 for r in runs if r.get("success", False))
                total_runs += len(runs)
                all_elapsed.extend(r["elapsed_s"] for r in runs if r.get("success", False))

            avg_e = round(sum(all_elapsed) / len(all_elapsed), 1) if all_elapsed else 0.0
            appr_str = f"{total_appr}/{total_runs}"
            succ_str = f"{total_succ}/{total_runs}"
            print(
                f"  {model_label:<30}  {prompt_label:<32}  "
                f"{appr_str:>12}  {succ_str:>12}  {avg_e:>7}s"
            )
    print(f"{'='*100}\n")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    output_dir = Path(__file__).parent

    print(f"\n{'='*80}")
    print(f"  Layout Prompt Engineering Test")
    print(f"  Template: template-en.pptx")
    print(f"  Layouts:  {AVAILABLE_LAYOUT_NAMES}")
    print(f"  N_RUNS:   {N_RUNS} per (model × prompt × slide_type)")
    print(f"  Models:   {[m['label'] for m in MODELS]}")
    print(f"  Prompts:  {[p['id'] for p in PROMPTS]}")
    print(f"  ALL EXECUTION IS SEQUENTIAL")
    print(f"{'='*80}\n")

    model_summaries = []

    for model_cfg in MODELS:
        model_label = model_cfg["label"]
        all_results_raw = run_model(model_cfg)

        available = all_results_raw is not None
        summary_rows = []
        if available:
            summary_rows = _print_model_summary(model_label, all_results_raw)

        model_summaries.append({
            "model_label": model_label,
            "model_name": model_cfg["name"],
            "available": available,
            "all_results_raw": all_results_raw or {},
            "summary_rows": summary_rows,
        })

    # Cross-model summary
    _print_cross_model_summary(model_summaries)

    # ── Save raw results JSON ──────────────────────────────────────────────────
    output_data = {
        "n_runs": N_RUNS,
        "template": TEMPLATE_PATH,
        "available_layout_names": AVAILABLE_LAYOUT_NAMES,
        "prompts": [
            {
                "id": p["id"],
                "label": p["label"],
                "description": p["description"],
                "rationale": p["rationale"],
            }
            for p in PROMPTS
        ],
        "models": [],
    }

    for item in model_summaries:
        model_label = item["model_label"]
        model_cfg = next(m for m in MODELS if m["label"] == model_label)
        all_results_raw = item["all_results_raw"]

        # Compute per-prompt totals
        prompt_totals = {}
        for prompt_cfg in PROMPTS:
            pid = prompt_cfg["id"]
            prompt_results = all_results_raw.get(pid, {})
            total_appr = sum(
                sum(1 for r in prompt_results.get(tc["label"], []) if r.get("layout_appropriate", False))
                for tc in SLIDE_TEST_CASES
            )
            total_succ = sum(
                sum(1 for r in prompt_results.get(tc["label"], []) if r.get("success", False))
                for tc in SLIDE_TEST_CASES
            )
            total_runs = len(SLIDE_TEST_CASES) * N_RUNS
            all_elapsed = [
                r["elapsed_s"]
                for tc in SLIDE_TEST_CASES
                for r in prompt_results.get(tc["label"], [])
                if r.get("success", False)
            ]
            avg_e = round(sum(all_elapsed) / len(all_elapsed), 1) if all_elapsed else 0.0
            prompt_totals[pid] = {
                "overall_appropriate_rate": f"{total_appr}/{total_runs}",
                "overall_success_rate": f"{total_succ}/{total_runs}",
                "avg_elapsed_s": avg_e,
            }

        # Serialize all_results_raw (convert sets to lists if any remain)
        def _serialize(obj):
            if isinstance(obj, set):
                return sorted(list(obj))
            return obj

        serialized_raw = {}
        for pid, per_label in all_results_raw.items():
            serialized_raw[pid] = {}
            for label, runs in per_label.items():
                serialized_raw[pid][label] = [
                    {k: _serialize(v) for k, v in r.items()}
                    for r in runs
                ]

        output_data["models"].append({
            "model_name": model_cfg["name"],
            "model_label": model_label,
            "available": item["available"],
            "prompt_totals": prompt_totals,
            "summary_rows": item["summary_rows"],
            "raw_results": serialized_raw,
        })

    json_path = output_dir / "layout_prompt_eng_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"  Raw results saved to: {json_path}")
    print(f"\n{'='*80}")
    print("  DONE")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
