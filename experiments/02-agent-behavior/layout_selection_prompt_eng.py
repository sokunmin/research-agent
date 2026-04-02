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
]

N_RUNS = 3  # runs per (model × prompt × slide_type)

# Set to a list of prompt IDs to run only those prompts, e.g. ["P1_baseline"].
# Set to None to run all prompts (default behaviour — does not affect existing results).
RUN_PROMPT_IDS = ["P0_baseline"]  # set to None to run all prompts

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

# ── Shared layout descriptions block (used in all prompts) ───────────────────

LAYOUT_DESCRIPTIONS = """LAYOUT DESCRIPTIONS — what each layout is for:

1. TITLE_SLIDE
   Use for: Opening cover slide of the presentation, OR closing thank-you/Q&A slide.
   Structure: Large title + subtitle area. NO body content area.
   Signals: author attribution ("Presented by:"), institution, "Thank You", "Q&A", "Conclusion".

2. TITLE_AND_BODY
   Use for: Standard academic or technical content slide with substantial text.
   Structure: Title + large body text area for paragraphs or bullets.
   Signals: multiple sentences or bullet points of academic/technical content.

3. QUOTE
   Use for: Displaying a quotation with attribution.
   Structure: Large quote text area + attribution line (— Author Name).
   Signals: text in quotes followed by "— Name" attribution format.

4. PHOTO_LANDSCAPE
   Use for: A slide whose main content is a single wide/horizontal image or diagram.
   Structure: Title + caption text + landscape (wide) photo placeholder.
   Signals: "[Wide image/diagram/chart]", horizontal layout, description of a wide visual.

5. SECTION_HEADER_CENTER
   Use for: Chapter or section divider slide — title only, centered.
   Structure: Title centered on slide. NO body content area.
   Signals: empty or near-empty body, "Chapter X", "Section X", "Part X".

6. PHOTO_PORTRAIT
   Use for: A slide whose main content is a single tall/vertical image or portrait photo.
   Structure: Title + caption text + portrait (tall) photo placeholder.
   Signals: "[Portrait photo]", headshot, tall/vertical image description.

7. SECTION_HEADER_TOP
   Use for: Chapter or section divider — title at top. Same role as SECTION_HEADER_CENTER.
   Structure: Title at top of slide. NO body content area.
   Signals: same as SECTION_HEADER_CENTER.

8. CONTENT_WITH_PHOTO
   Use for: A slide combining bullet-point text AND an image/figure side by side.
   Structure: Title + text content area + photo placeholder (split layout).
   Signals: slide body contains BOTH bullet points AND a "[Figure/Image: ...]" reference together.

9. BULLET_LIST
   Use for: Bullet-point content slide — similar to TITLE_AND_BODY but optimized for lists.
   Structure: Title + body text area.
   Signals: body is primarily a list of bullet points (* or -).

10. THREE_PHOTO
    Use for: Comparing or displaying three images side by side.
    Structure: Three photo placeholders. NO title, NO text content area.
    Signals: "[Image 1: ...] [Image 2: ...] [Image 3: ...]", three separate image references.

11. FULL_PHOTO
    Use for: A full-bleed image covering the entire slide with no text.
    Structure: Single full-page photo placeholder. NO title, NO text area.
    Signals: "[Full-page image/visualization]", entirely visual slide with no text content.

12. BLANK
    Use for: A completely empty slide with no content.
    Structure: No placeholders except footer.
    Signals: both title and content are empty strings.
"""

OUTPUT_FIELDS = """Output the following fields:
- title: the slide title text (copy verbatim from input)
- content: the slide body text (copy verbatim from input)
- layout_name: the exact name string of the chosen layout (must match one of the available layout names exactly)
- idx_title_placeholder: the numeric index (as a string) of the title placeholder in the chosen layout. 
- idx_content_placeholder: the numeric index (as a string) of the content placeholder in the chosen layout. 
CRITICAL: For layouts THREE_PHOTO, FULL_PHOTO, and BLANK:
  - idx_title_placeholder MUST be null (not a number, not a string)
  - idx_content_placeholder MUST be null (not a number, not a string)
  These layouts have NO title or content placeholders. Outputting any number here is incorrect and will cause a runtime error.
"""

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
        "expected": {"TITLE_AND_BODY", "BULLET_LIST"},
        "description": "Regular academic content slide — should pick TITLE_AND_BODY or BULLET_LIST",
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
        "expected": {"BULLET_LIST", "TITLE_AND_BODY"},
        "description": "Bullet list only — should pick BULLET_LIST or TITLE_AND_BODY",
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
    # ── Visual / photo layouts ─────────────────────────────────────────────────
    # NOTE: PHOTO_LANDSCAPE and PHOTO_PORTRAIT have idx=0 (title) + idx=1 (caption) + idx=2 (photo).
    #       CONTENT_WITH_PHOTO has idx=0 (title) + idx=1 (content) + idx=2 (photo).
    #       THREE_PHOTO, FULL_PHOTO, BLANK have NO title/content placeholders —
    #       LLM-returned idx values will be invalid; only layout_name correctness is scored.
    {
        "label": "photo_landscape",
        "slide": {
            "title": "System Architecture",
            "content": "[Wide horizontal diagram showing the end-to-end processing pipeline from input to output]",
        },
        "expected": {"PHOTO_LANDSCAPE"},
        "description": "Wide/landscape image slide — should pick PHOTO_LANDSCAPE",
    },
    {
        "label": "photo_portrait",
        "slide": {
            "title": "About the Authors",
            "content": "[Portrait photo: lead researcher headshot]",
        },
        "expected": {"PHOTO_PORTRAIT"},
        "description": "Portrait-oriented photo slide — should pick PHOTO_PORTRAIT",
    },
    {
        "label": "content_with_photo",
        "slide": {
            "title": "Attention Visualization",
            "content": (
                "* Self-attention assigns weights across all input tokens\n"
                "* Captures long-range dependencies without recurrence\n"
                "[Figure: attention heatmap visualization on the right]"
            ),
        },
        "expected": {"CONTENT_WITH_PHOTO"},
        "description": "Bullet points with accompanying figure — should pick CONTENT_WITH_PHOTO",
    },
    {
        "label": "three_photo",
        "slide": {
            "title": "Qualitative Comparison",
            "content": "[Image 1: baseline output] [Image 2: proposed method] [Image 3: ground truth]",
        },
        "expected": {"THREE_PHOTO"},
        "description": "Three-image comparison slide — should pick THREE_PHOTO",
    },
    {
        "label": "full_photo",
        "slide": {
            "title": "",
            "content": "[Full-page image: t-SNE visualization of learned embedding space]",
        },
        "expected": {"FULL_PHOTO"},
        "description": "Full-bleed image slide — should pick FULL_PHOTO",
    },
    {
        "label": "blank",
        "slide": {
            "title": "",
            "content": "",
        },
        "expected": {"BLANK"},
        "description": "Blank slide with no title or content — should pick BLANK",
    },
]

# ── Prompt Variants ────────────────────────────────────────────────────────────
#
# 6 prompts: P0–P1 are baselines, P2–P5 each add a different guidance strategy.
#
# Strategy summary:
#   PROMPT_0: Original production baseline — AUGMENT_LAYOUT_PMT verbatim (not yet run)
#   PROMPT_1: Descriptions-only baseline — all 12 layout descriptions, no routing guidance
#   PROMPT_2: Decision-tree / explicit routing — step-by-step "if/then" dispatch rules
#   PROMPT_3: Positive examples — semantic USE rules for every layout
#   PROMPT_4: Negative examples — explicit WRONG constraints with structural signals
#   PROMPT_5: Chain-of-thought — ask model to reason about slide role before selecting layout

# ── PROMPT_2: Decision-tree routing ───────────────────────────────────────────
# Rationale: The baseline prompt gives a generic instruction. Models fail cover/title
# and closing slides because they lack explicit routing rules. A decision tree forces
# the model to match slide characteristics to layout before picking.
# Hypothesis: Explicit if/then rules will fix cover_slide and closing_slide failures.

PROMPT_2_DECISION_TREE = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and body text.

STEP 1 — Identify the slide role using this decision tree (evaluate in order, stop at first match):
  A. If both title AND body are empty strings
     → role = BLANK
  B. Else if the body describes a single full-page image that covers the entire slide,
     with no title and no readable text content alongside it
     → role = FULL_PHOTO
  C. Else if the body presents three separate images for comparison or display,
     with no substantial text content
     → role = THREE_PHOTO
  D. Else if the body is a direct quote with an attribution line (e.g. "— Author Name")
     → role = QUOTE_SLIDE
  E. Else if the body contains BOTH bullet-point text (* or -) AND a supporting
     image or figure described alongside the text
     → role = CONTENT_WITH_PHOTO
  F. Else if the body's primary content is a single tall or vertical visual —
     such as a portrait photograph, headshot, or portrait-oriented figure
     → role = PHOTO_PORTRAIT
  G. Else if the body's primary content is a single wide or horizontal visual —
     such as a diagram, chart, pipeline figure, or landscape-oriented image
     → role = PHOTO_LANDSCAPE
  H. Else if the body is empty or very short (< 10 characters and no image references)
     → role = SECTION_BREAK
  I. Else if the title begins with "Chapter", "Section", "Part", "Unit", "Module", or a numbered section marker (e.g. "1.", "2.")
     → role = SECTION_BREAK
  J. Else if the title is "Thank You", "Acknowledgements", "References", "Q&A", "Questions and Answers", or the body is a short closing message (contact info, acknowledgements, bibliography)
     → role = CLOSING_SLIDE
  K. Else if the body contains "Presented by:", "Authors:", "Author:", "Affiliation:", "Institution:", or "Department:" without bullet points
     → role = TITLE_COVER
  L. Else if the body contains bullet points (* or -)
     → role = CONTENT_SLIDE
  M. Else
     → role = CONTENT_SLIDE

STEP 2 — Select layout based on role:
  - role = BLANK               → use layout: BLANK
  - role = FULL_PHOTO          → use layout: FULL_PHOTO
  - role = THREE_PHOTO         → use layout: THREE_PHOTO
  - role = QUOTE_SLIDE         → use layout: QUOTE
  - role = CONTENT_WITH_PHOTO  → use layout: CONTENT_WITH_PHOTO
  - role = PHOTO_PORTRAIT      → use layout: PHOTO_PORTRAIT
  - role = PHOTO_LANDSCAPE     → use layout: PHOTO_LANDSCAPE
  - role = SECTION_BREAK       → use layout: SECTION_HEADER_CENTER or SECTION_HEADER_TOP
  - role = CLOSING_SLIDE       → use layout: TITLE_SLIDE or SECTION_HEADER_CENTER
  - role = TITLE_COVER         → use layout: TITLE_SLIDE
  - role = CONTENT_SLIDE       → use layout: TITLE_AND_BODY or BULLET_LIST
""" + LAYOUT_DESCRIPTIONS + """
The following layouts are available: {available_layout_names}
Layout details:
{available_layouts}

Slide content to classify:
{slide_content}

""" + OUTPUT_FIELDS

# ── PROMPT_3: Positive examples ───────────────────────────────────────────────
# Rationale: Provide clear, semantic USE rules for every layout — one rule per layout,
# describing the slide's purpose and content type rather than specific text patterns.
# No negative constraints, no decision tree, no reasoning steps.
# Hypothesis: Semantic positive rules generalise better across paper types and domains
# than text-pattern conditions, because they describe intent rather than surface signals.

PROMPT_3_POSITIVE_EXAMPLES = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and main text body.

LAYOUT SELECTION RULES — choose the layout whose description best matches the slide's purpose:

USE TITLE_SLIDE when:
  - The slide is the opening cover page of the presentation
  - The slide introduces the paper with its title, author, or institutional information
  - The slide is the closing thank-you, Q&A, or conclusion page
  - The content is presentational rather than informational — short, ceremonial, or attributional text

USE TITLE_AND_BODY when:
  - The slide has a title and a substantial body of academic or technical text
  - The content consists of explanatory paragraphs or a mix of sentences and short phrases
  - The body is informational but not structured primarily as a list

USE BULLET_LIST when:
  - The body is structured as a list of bullet points (* or -)
  - The slide presents multiple parallel items — findings, contributions, steps, or comparisons
  - The content is best read as a list rather than as flowing prose

USE SECTION_HEADER_CENTER or SECTION_HEADER_TOP when:
  - The slide marks the beginning of a new section, chapter, or topic within the presentation
  - The title alone carries the complete message — no body content is needed
  - The body is empty or contains only a very brief subtitle or tagline

USE QUOTE when:
  - The primary content is a quotation attributed to a named person or source
  - The body presents a quoted sentence followed by an attribution line (e.g. "— Author Name")

USE PHOTO_LANDSCAPE when:
  - The main content is a wide or horizontal visual — a diagram, chart, pipeline figure, or landscape image
  - The slide is built around a single horizontal visual element

USE PHOTO_PORTRAIT when:
  - The main content is a tall or vertical visual — a portrait photograph, headshot, or portrait-oriented figure
  - The slide is built around a single vertical visual element

USE CONTENT_WITH_PHOTO when:
  - The slide combines textual bullet points with an image or figure
  - Both a written explanation and a supporting visual are needed on the same slide

USE THREE_PHOTO when:
  - The slide presents three images for side-by-side comparison or display
  - The content is primarily three separate visual elements with no substantial text

USE FULL_PHOTO when:
  - The entire slide is a single full-page image or visualization with no title or body text
  - The visual content fills the whole slide without any text

USE BLANK when:
  - Both the title and the body are empty
  - No content is placed on this slide
""" + LAYOUT_DESCRIPTIONS + """
The following layouts are available: {available_layout_names}
Layout details:
{available_layouts}

Slide content:
{slide_content}

""" + OUTPUT_FIELDS

# ── PROMPT_4: Negative examples ───────────────────────────────────────────────
# Rationale: Each rule states a WRONG layout choice and explains WHY it is
# structurally wrong. No "Use instead" is provided — the model derives the
# correct layout from LAYOUT_DESCRIPTIONS. This keeps negative rules as pure
# constraints, not lookup shortcuts.
# Rules use only structural signals (empty body, bullet points, visual element
# reference, attribution line, empty title+body) — no domain-specific terms.
# Rules are reduced to the 8 most critical failure modes identified from
# experiment data. Photo-vs-photo cross rules are removed as they create
# interference for small models without improving accuracy.
# Schema note: idx_title_placeholder and idx_content_placeholder may be null
# for layouts with no text placeholders (THREE_PHOTO, FULL_PHOTO, BLANK).
# Hypothesis: Fewer, more precise WRONG rules with explicit preconditions
# outperform the 19-rule version by reducing inter-rule interference.

PROMPT_4_NEGATIVE_EXAMPLES = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and body text.

The following are WRONG layout choices to avoid. Each rule states the wrong choice
and explains why it is structurally incorrect. Use the LAYOUT DESCRIPTIONS below
to determine the correct layout after ruling out the wrong ones.

WRONG: Choosing TITLE_AND_BODY or BULLET_LIST when the body contains any image,
  figure, or visual element reference (whether the body is image-only, or a
  combination of bullet-point text and an image reference together).
  Why wrong: TITLE_AND_BODY and BULLET_LIST have no photo placeholder — visual
  content cannot be displayed in these layouts.

WRONG: Choosing TITLE_AND_BODY or BULLET_LIST for the opening cover slide
  (body contains author name, "Presented by:", institutional affiliation, or
  similar attribution — even if the attribution text is short).
  Why wrong: These layouts are designed for informational content, not for
  the presentation's title page.

WRONG: Choosing TITLE_AND_BODY or BULLET_LIST for the closing slide
  (title is "Thank You", "Q&A", "Questions", "References", or "Acknowledgements",
  and body is short — contact info, bibliography, or acknowledgement text only).
  Why wrong: These layouts are designed for informational content, not for
  closing or ceremonial slides.

WRONG: Choosing TITLE_AND_BODY or BULLET_LIST when the body is empty or very
  short (fewer than 10 characters, no bullet points, no image reference).
  Why wrong: These layouts have a large body content area — an empty body
  creates visual dead space on the slide.

WRONG: Choosing TITLE_AND_BODY or BULLET_LIST when the body is a single
  quotation followed by an attribution line (e.g. "— Author Name").
  Why wrong: These layouts do not provide a large-format quote display with
  a dedicated attribution area.

WRONG: Choosing TITLE_SLIDE when the body contains substantial text such as
  multiple bullet points or multiple full sentences of academic or technical
  content. Short attribution lines ("Presented by:", author names, institution
  names) are NOT substantial text and do NOT make this rule apply.
  Why wrong: TITLE_SLIDE has no body content area — substantial body text
  will not be displayed.

WRONG: Choosing TITLE_SLIDE for a chapter or section divider whose body is
  empty and whose title does not include author attribution or closing phrasing.
  Why wrong: TITLE_SLIDE is for the opening cover or closing slide, not for
  internal section transitions.

WRONG: Choosing BLANK for any slide whose title or body contains any text or
  visual content, even if the text is very short (e.g. "Thank You", contact
  info, a single sentence).
  Why wrong: BLANK is strictly for slides where BOTH the title AND the body
  are completely empty strings.

""" + LAYOUT_DESCRIPTIONS + """
The following layouts are available: {available_layout_names}
Layout details:
{available_layouts}

Slide content:
{slide_content}

""" + OUTPUT_FIELDS

# ── PROMPT_5: Chain-of-thought ────────────────────────────────────────────────
# Rationale: True CoT asks the model to generate its own reasoning chain freely,
# without pre-defined category lists or lookup tables. The model observes slide
# characteristics, reasons about the slide's purpose in a presentation context,
# and derives the layout choice through its own reasoning — not by matching to
# a fixed taxonomy. This makes the prompt flexible and applicable to any paper
# type or domain, since the reasoning is not constrained to pre-defined slots.
# Hypothesis: Free reasoning produces better generalisation to unseen slide types
# than structured classification, because the model can weigh multiple signals
# simultaneously rather than following a rigid branching path.

PROMPT_5_CHAIN_OF_THOUGHT = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and body text.

Before selecting a layout, think step by step and write your reasoning:

Step 1 — Observe: What does this slide contain?
  Describe what you see: the title, the body content type (bullets, quote, image reference,
  empty, short text, etc.), and any notable signals in the text.

Step 2 — Infer purpose: What is the role of this slide in a presentation?
  Think about where this slide would appear and what it is trying to communicate to
  the audience. Consider the full context: is it introducing, summarising, dividing,
  quoting, illustrating, or closing?

Step 3 — Match to layout: Which available layout best serves this purpose?
  Review the layout descriptions below. For each candidate layout, consider whether
  its structure (placeholders, visual format) fits the slide's purpose and content.
  Reason about why the chosen layout fits better than the alternatives.

Step 4 — Verify: Confirm the chosen layout name exactly matches one of the available
  layout names listed below. If not, revise your choice.

""" + LAYOUT_DESCRIPTIONS + """
The following layouts are available: {available_layout_names}
Layout details:
{available_layouts}

Slide content:
{slide_content}

""" + OUTPUT_FIELDS

# ── PROMPT_0_ORIGINAL_BASELINE: Original production prompt from backend/prompts/prompts.py ──
# Sourced verbatim from AUGMENT_LAYOUT_PMT. No LAYOUT_DESCRIPTIONS or OUTPUT_FIELDS
# appended — this prompt is self-contained with its own output instructions.
# Serves as the true production baseline: tests the prompt currently deployed in
# outlines_with_layout (slide_gen.py) before any prompt engineering improvements.
# NOTE: contains "Plassholder for innhold" (Norwegian) — a legacy reference from
# the original Norwegian template. Kept verbatim to reflect the real production state.

PROMPT_0_ORIGINAL_BASELINE = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and main text body.

Select the layout and placeholder indices based on the content type
(e.g. agenda/overview, regular content, title slide, or closing/thank-you slide).

For content slides:
 - choose a layout that has a content placeholder (also referred to as 'Plassholder for innhold') after the title placeholder
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

# ── PROMPT_0: Baseline — layout descriptions only, no routing guidance ────────
# Rationale: Provides all 12 layout descriptions (Use for / Structure / Signals)
# without any routing rules, negative constraints, or reasoning steps.
# Serves as the baseline to measure how much P1/P2/P3 guidance strategies improve
# layout selection accuracy over a description-only prompt.
# Hypothesis: Without explicit guidance, models default to TITLE_AND_BODY bias
# even when layout descriptions are provided.

PROMPT_1_BASELINE = """
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and body text.

""" + LAYOUT_DESCRIPTIONS + """
The following layouts are available: {available_layout_names}
Layout details:
{available_layouts}

Slide content to classify:
{slide_content}

""" + OUTPUT_FIELDS

# ── Prompt registry ────────────────────────────────────────────────────────────

PROMPTS = [
    {
        "id": "P0_baseline",
        "label": "P0 Original Baseline (AUGMENT_LAYOUT_PMT)",
        "template": PROMPT_0_ORIGINAL_BASELINE,
        "description": "Verbatim AUGMENT_LAYOUT_PMT from backend/prompts/prompts.py — the current production prompt",
        "rationale": "True production baseline: no layout descriptions, no routing rules, no negative constraints. Measures the current deployed prompt's layout selection accuracy against the full 12-layout test set.",
    },
    {
        "id": "P1_baseline",
        "label": "P1 Baseline (Descriptions Only)",
        "template": PROMPT_1_BASELINE,
        "description": "All 12 layout descriptions (Use for / Structure / Signals), no routing guidance",
        "rationale": "Baseline: measures how well models select layouts from descriptions alone, without any explicit routing rules.",
    },
    {
        "id": "P2_decision_tree",
        "label": "P2 Decision-Tree Routing",
        "template": PROMPT_2_DECISION_TREE,
        "description": "Explicit if/then decision tree: classify slide role → pick layout",
        "rationale": "Baseline prompt has no routing rules. Explicit dispatch may fix cover/closing failures.",
    },
    {
        "id": "P3_positive_examples",
        "label": "P3 Positive Examples",
        "template": PROMPT_3_POSITIVE_EXAMPLES,
        "description": "Semantic USE rules for every layout — describes slide purpose, not text patterns",
        "rationale": "Semantic positive rules generalise across paper types; no negative constraints or routing steps.",
    },
    {
        "id": "P4_negative_examples",
        "label": "P4 Negative Examples",
        "template": PROMPT_4_NEGATIVE_EXAMPLES,
        "description": "Explicit DO NOT constraints for every layout — structural signals only, no domain-specific terms",
        "rationale": "Negative constraints block the TITLE_AND_BODY default directly. Structural conditions (empty body, bullets, image refs, attribution) are domain-agnostic and applicable to any paper type.",
    },
    {
        "id": "P5_chain_of_thought",
        "label": "P5 Chain-of-Thought",
        "template": PROMPT_5_CHAIN_OF_THOUGHT,
        "description": "Ask model to classify slide type explicitly before selecting layout",
        "rationale": "Making reasoning explicit via CoT steps may improve accuracy on ambiguous slides.",
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

    prompts_to_run = [p for p in PROMPTS if RUN_PROMPT_IDS is None or p["id"] in RUN_PROMPT_IDS]
    total_calls = len(prompts_to_run) * len(SLIDE_TEST_CASES) * N_RUNS
    call_n = 0

    for prompt_cfg in prompts_to_run:
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

    if RUN_PROMPT_IDS is not None:
        suffix = "_" + "_".join(RUN_PROMPT_IDS)
        json_path = output_dir / f"layout_prompt_eng_results{suffix}.json"
    else:
        json_path = output_dir / "layout_prompt_eng_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"  Raw results saved to: {json_path}")
    print(f"\n{'='*80}")
    print("  DONE")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
