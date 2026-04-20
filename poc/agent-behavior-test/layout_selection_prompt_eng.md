# Layout Selection Prompt Engineering — Experiment Report (Updated Run)

**Date:** 2026-03-31
**Script:** `poc/agent-behavior-test/layout_selection_prompt_eng.py`
**Results file:** `poc/agent-behavior-test/layout_prompt_eng_results.json`
**Console log:** `poc/agent-behavior-test/layout_prompt_eng_output_new.txt`

---

## 1. Experiment Overview

### Problem

The PPTX generation pipeline converts research papers into slide decks. For each slide, an LLM must select one of 12 slide layouts from a PowerPoint template. The selected layout determines which placeholders exist on the slide (title placeholder, content placeholder, photo placeholder, etc.). A wrong layout choice causes structural breakage: wrong placeholder indices, visual errors, or runtime crashes when the slide generator attempts to access a non-existent placeholder.

This experiment tests 6 prompt engineering strategies (P0–P5) to determine which most reliably guides LLMs to correct layout selection across all 12 layout types.

### Pipeline context

```
Paper summary
    → SlideOutline {title, content}               (one object per slide)
    → outlines_with_layout step                   (this experiment's focus)
    → SlideOutlineWithLayout {title, content, layout_name,
                               idx_title_placeholder, idx_content_placeholder}
    → slide_gen ReAct agent
    → .pptx file
```

The `outlines_with_layout` step calls an LLM to fill in the `SlideOutlineWithLayout` schema. The experiment tests whether different prompt engineering strategies improve the accuracy of `layout_name` selection.

### Note on P0 — added after initial run

P0 (`P0_baseline`) was run separately after the initial P1–P5 experiment. Its results have now been merged into this report. P0 tests the verbatim production prompt (`AUGMENT_LAYOUT_PMT` from `backend/prompts/prompts.py`) — the prompt currently deployed in the pipeline — against the same 12 slide types and 3 models used for P1–P5. This establishes a true production baseline against which P1–P5 improvements can be measured. All P0 numbers in this report come from `layout_prompt_eng_results_P0_baseline.json`.

### What this experiment adds (changes from previous run)

This is an updated run incorporating three changes from the previous experiment version:

**Change 1 — Schema fix (`schemas.py`):**
`idx_title_placeholder` and `idx_content_placeholder` changed from required `str` to `Optional[str] = None`. A `field_validator` (`coerce_int_to_str`) was added to coerce integer outputs to string before Pydantic validation. This fixes the validation failure that occurred for layouts with no text placeholders (`THREE_PHOTO`, `FULL_PHOTO`, `BLANK`) in the previous run — where the model returning `null` or an integer caused an immediate Pydantic error, forcing `success=False` regardless of whether the `layout_name` was correct.

**Change 2 — `OUTPUT_FIELDS` prompt block:**
Added a CRITICAL instruction explicitly telling the LLM to output `null` (not a number, not a string) for `idx_title_placeholder` and `idx_content_placeholder` when the chosen layout is `THREE_PHOTO`, `FULL_PHOTO`, or `BLANK`.

**Change 3 — `P4_negative_examples` prompt redesigned:**
Rule count reduced from 19 to 8. All "Use instead:" guidance removed from every rule (the model derives the correct layout from `LAYOUT_DESCRIPTIONS`). Photo-vs-photo cross rules removed. Explicit preconditions and exception clauses added to the `TITLE_SLIDE` rule (short attribution text is not "substantial text") and the `BLANK` rule (any text content — even "Thank You" — means BLANK is wrong). Rationale: fewer, more precise rules with no redirect shortcuts reduce inter-rule interference for small models.

### What the experiment measures

For each (model × prompt × slide_type) combination: `appropriate_rate` (layout_name in expected set), `success_rate` (valid parseable response without Pydantic error), and elapsed time.

---

## 2. Setup

### Template and layout names

**Template file:** `assets/template-en.pptx` — fully English layout names. Previous versions of the template used Chinese mixed with English names (e.g., `項目符號` → `BULLET_LIST`, `照片-一頁三張` → `THREE_PHOTO`, `空白` → `BLANK`). These were renamed to ASCII uppercase before this experiment series began.

Layout names are read dynamically at runtime via `get_all_layouts_info()`. The 12 layouts confirmed from the template:

| # | Layout Name |
|---|-------------|
| 1 | TITLE_SLIDE |
| 2 | TITLE_AND_BODY |
| 3 | QUOTE |
| 4 | PHOTO_LANDSCAPE |
| 5 | SECTION_HEADER_CENTER |
| 6 | PHOTO_PORTRAIT |
| 7 | SECTION_HEADER_TOP |
| 8 | CONTENT_WITH_PHOTO |
| 9 | BULLET_LIST |
| 10 | THREE_PHOTO |
| 11 | FULL_PHOTO |
| 12 | BLANK |

### Method: LLMTextCompletionProgram

`LLMTextCompletionProgram` (LlamaIndex) is used exclusively. `FunctionCallingProgram` is excluded because Ollama models do not support the native `tool_calls` API — confirmed in a prior experiment (augment-results experiment). `LLMTextCompletionProgram` uses prompt-based JSON extraction compatible with all Ollama models.

### Models

| Label | Full name | Status |
|-------|-----------|--------|
| `gemma3:4b` | `ollama/gemma3:4b` | Available — ran (local, M1 MacBook) |
| `ministral-3:14b-cloud` | `ollama/ministral-3:14b-cloud` | Available — ran (cloud via Ollama routing) |

Both models were available and contributed results. No models were skipped. A third model (`ollama/gpt-oss:20b-cloud`) mentioned in the script file header was removed from the `MODELS` list and did not run (unavailable in the previous run). Groq models are excluded — the `.env` uses Ollama-based routing for this task.

### Run configuration

- `N_RUNS = 3` per (model × prompt × slide_type)
- `temperature = 0.1`
- `max_tokens = 2048`
- Execution: sequential only — Ollama does not support parallel requests
- Total planned calls (P1–P5): 2 models × 5 prompts × 12 slide types × 3 runs = **360**
- P0 calls executed separately: 2 models × 1 prompt × 12 slide types × 3 runs = **72**
- Total calls executed: **432** (360 P1–P5 + 72 P0, all completed, no errors)

---

## 3. Schema Changes (vs Previous Run)

### SlideOutlineWithLayout — before and after

**Before (previous run):**
```python
idx_title_placeholder: str = Field(..., description="...")
idx_content_placeholder: str = Field(..., description="...")
```

**After (this run):**
```python
idx_title_placeholder: Optional[str] = Field(
    default=None,
    description="Index of the title placeholder in the page layout. None if the layout has no title placeholder (e.g. THREE_PHOTO, FULL_PHOTO, BLANK)."
)
idx_content_placeholder: Optional[str] = Field(
    default=None,
    description="Index of the content placeholder in the page layout. None if the layout has no content placeholder (e.g. THREE_PHOTO, FULL_PHOTO, BLANK, SECTION_HEADER_CENTER, SECTION_HEADER_TOP)."
)

@field_validator('idx_title_placeholder', 'idx_content_placeholder', mode='before')
@classmethod
def coerce_int_to_str(cls, v):
    if isinstance(v, int):
        return str(v)
    return v
```

### Why these changes matter

In the previous run, layouts `THREE_PHOTO`, `FULL_PHOTO`, and `BLANK` have no title or content text placeholders. The model had no valid integer-as-string to return for these non-existent placeholders. When the model returned `null` (the semantically correct response), Pydantic rejected it because the field was typed as `str` (not `Optional[str]`), producing a validation error and `success=False`. When the model returned an integer (e.g., `0`, `12`), Pydantic again rejected it because integers do not coerce to `str` automatically in Pydantic v2. The result was that these three layouts almost always produced `success=False` in the previous run, regardless of whether the `layout_name` field was correct.

The `Optional[str] = None` change allows the model to output `null` (JSON `null`) for these fields without a validation error. The `coerce_int_to_str` validator additionally catches cases where the model outputs an integer (e.g., `0`) and coerces it to `"0"` before Pydantic validation — preventing validation errors when the model does not follow the null instruction. Note that even when coercion succeeds, the resulting index string may still be wrong at runtime if the layout has no such placeholder; however, this is a separate runtime concern from validation correctness.

The `idx_content_placeholder` field description also lists `SECTION_HEADER_CENTER` and `SECTION_HEADER_TOP` as layouts with no content placeholder — these layouts have only a title placeholder and no body text area.

---

## 4. Shared Prompt Components

All P1–P5 prompt variants include the same two shared blocks, appended into the prompt template. **P0 does not use these blocks — it is self-contained with its own output instructions.**

### LAYOUT_DESCRIPTIONS

Included verbatim in every prompt. Describes all 12 layouts with three sub-fields per layout:

- **Use for:** the presentation purpose of the layout (e.g., "Opening cover slide of the presentation, OR closing thank-you/Q&A slide")
- **Structure:** the placeholder arrangement (e.g., "Large title + subtitle area. NO body content area.", "Three photo placeholders. NO title, NO text content area.")
- **Signals:** observable text patterns that indicate this layout (e.g., `— Author Name` attribution format, `"[Image 1: ...] [Image 2: ...] [Image 3: ...]"` for THREE_PHOTO, empty title and content for BLANK)

### OUTPUT_FIELDS

Appended to every prompt template. Specifies 5 output fields:

1. `title` — copy verbatim from input
2. `content` — copy verbatim from input
3. `layout_name` — must exactly match one of the 12 available layout names
4. `idx_title_placeholder` — numeric index as string; `null` if the layout has no title placeholder
5. `idx_content_placeholder` — numeric index as string; `null` if the layout has no content placeholder

**CRITICAL instruction added in this run:** For layouts `THREE_PHOTO`, `FULL_PHOTO`, and `BLANK`, both `idx_title_placeholder` and `idx_content_placeholder` MUST be `null` (not a number, not a string). The prompt states: "These layouts have NO title or content placeholders. Outputting any number here is incorrect and will cause a runtime error."

---

## 5. Prompt Variants

### P0 — Original Production Baseline (AUGMENT_LAYOUT_PMT)

**ID:** `P0_baseline`
**Strategy:** Verbatim copy of `AUGMENT_LAYOUT_PMT` from `backend/prompts/prompts.py` — the actual prompt currently deployed in production for the `outlines_with_layout` step. No additional blocks are appended. The prompt provides a short task description, a reference to "content placeholder (also referred to as 'Plassholder for innhold')", the list of available layout names, the raw template layout details, and a minimal 5-field output instruction.
**Rationale:** True production baseline: no layout descriptions, no routing rules, no negative constraints. Measures the current deployed prompt's layout selection accuracy against the full 12-layout test set. Establishes the floor that P1–P5 must beat.
**Key feature:** This prompt does NOT use the shared `LAYOUT_DESCRIPTIONS` or `OUTPUT_FIELDS` blocks used by P1–P5. It is self-contained with its own output instructions. The `idx_title_placeholder` and `idx_content_placeholder` fields are described as required strings with no null instruction — the model has no guidance for layouts with no text placeholders (e.g., `THREE_PHOTO`, `FULL_PHOTO`, `BLANK`). Contains Norwegian legacy text `"Plassholder for innhold"` from the original Norwegian template, kept verbatim to reflect the real production state.
**Important:** Because P0 does not include the `OUTPUT_FIELDS` null instruction, the model receives no guidance to output `null` for `idx_title_placeholder`/`idx_content_placeholder` on visual-only layouts. However, the schema fix (`Optional[str] = None` + `coerce_int_to_str`) means validation still succeeds even when the model outputs an incorrect integer or string.

---

### P1 — Baseline (Descriptions Only)

**ID:** `P1_baseline`
**Strategy:** Provide all 12 `LAYOUT_DESCRIPTIONS` with no additional routing guidance.
**Rationale:** Establishes the floor. Measures how well models select layouts from descriptions alone, without any explicit classification rules.
**Structure:** Task instruction + `LAYOUT_DESCRIPTIONS` + available layout names + layout details from template + slide content + `OUTPUT_FIELDS`. No additional guidance.

---

### P2 — Decision-Tree Routing

**ID:** `P2_decision_tree`
**Strategy:** A 13-step if/then decision tree (STEP 1) classifies the slide into a semantic role (e.g., `BLANK`, `THREE_PHOTO`, `TITLE_COVER`, `CONTENT_SLIDE`). A lookup table (STEP 2) maps each role to one or more valid layout names.
**Rationale:** The baseline prompt has no routing rules. Models fail on cover and closing slides because the only guidance is the descriptions. Explicit dispatch through a priority-ordered decision tree forces the model to apply conditions in the correct order.
**Key feature:** Tree is evaluated top-down, stopping at first match. Restrictive conditions (`BLANK`, `FULL_PHOTO`, `THREE_PHOTO`) appear first; generic fallbacks (`CONTENT_SLIDE`) appear last. Followed by `LAYOUT_DESCRIPTIONS` for full context.

---

### P3 — Positive Examples

**ID:** `P3_positive_examples`
**Strategy:** One semantic `USE <LAYOUT> when:` rule per layout, describing purpose and content type in natural language. No negative constraints, no decision tree, no reasoning steps.
**Rationale:** Semantic rules describe intent rather than surface text patterns, which generalises better across paper types and domains. Keeping the prompt purely positive avoids conflicting constraints.
**Key feature:** Each rule is 2–4 lines describing purpose and content type. For example: "USE TITLE_SLIDE when: The slide is the opening cover page of the presentation / The slide introduces the paper with its title, author, or institutional information / The slide is the closing thank-you, Q&A, or conclusion page / The content is presentational rather than informational." Followed by `LAYOUT_DESCRIPTIONS`.

---

### P4 — Negative Examples (Redesigned)

**ID:** `P4_negative_examples`
**Strategy:** 8 explicit "WRONG: Choosing X when Y — Why wrong: [structural reason]" rules. No "Use instead:" redirects. The model derives the correct layout from `LAYOUT_DESCRIPTIONS` after eliminating wrong choices.
**Rationale:** Negative constraints directly target the model's default bias toward `TITLE_AND_BODY`. Structural signals (empty body, bullet points, image references, attribution lines) are domain-agnostic and applicable to any paper type. Providing no redirect means the model must reason from descriptions rather than following a shortcut lookup.

**Changes from previous version (19-rule → 8-rule):**
- **Rule count:** 19 WRONG rules → 8 WRONG rules
- **"Use instead:" removed entirely:** All "Use instead:" guidance removed from every rule. The previous version provided a redirect (e.g., "WRONG: ... Use instead: TITLE_SLIDE"). The new version omits this — the model must consult `LAYOUT_DESCRIPTIONS` to find the correct layout.
- **Photo-vs-photo cross rules removed:** Rules like "don't use PHOTO_LANDSCAPE for a portrait image" were removed. These created inter-rule interference for small models without improving accuracy.
- **Exception clauses added:** The `TITLE_SLIDE` rule adds an exception: "Short attribution lines ('Presented by:', author names, institution names) are NOT substantial text and do NOT make this rule apply." The `BLANK` rule adds: "any text content — even 'Thank You', contact info, a single sentence — means BLANK is wrong."
- **Explicit preconditions:** Each rule now states the structural precondition (e.g., "body is empty or very short — fewer than 10 characters") rather than relying on the model's interpretation.

**8 rules cover:**
1. TITLE_AND_BODY or BULLET_LIST when body contains any image/figure/visual reference
2. TITLE_AND_BODY or BULLET_LIST for opening cover slide (author attribution, "Presented by:", etc.)
3. TITLE_AND_BODY or BULLET_LIST for closing slide (short ceremonial content)
4. TITLE_AND_BODY or BULLET_LIST when body is empty or very short
5. TITLE_AND_BODY or BULLET_LIST for a quotation with attribution line
6. TITLE_SLIDE when body contains substantial multi-sentence/bullet content
7. TITLE_SLIDE for a section divider (empty body, no attribution phrasing)
8. BLANK for any slide whose title or body contains any text or visual content

---

### P5 — Chain-of-Thought

**ID:** `P5_chain_of_thought`
**Strategy:** Asks the model to generate a free-form 4-step reasoning chain before selecting a layout: (1) observe slide content, (2) infer the slide's role in a presentation, (3) match to a layout from descriptions, (4) verify the chosen name is valid.
**Rationale:** Free chain-of-thought lets the model weigh multiple signals simultaneously without following a rigid branching path. Not constrained to a pre-defined taxonomy. Reasoning is generated freely and grounded in `LAYOUT_DESCRIPTIONS`.
**Key feature:** The 4 steps are instructional, not prescriptive — the model writes its own reasoning rather than filling in fixed category labels.

---

## 6. Slide Test Cases

12 test cases in total. For each, the model is given `title` and `content` as a JSON object. The `expected` set defines which layout names are considered appropriate.

### Text-content slides (6)

| Label | Title | Content summary | Expected layout(s) |
|-------|-------|-----------------|-------------------|
| `cover/title_slide` | "Attention Is All You Need" | "A Research Presentation\nPresented by: John Smith" | `TITLE_SLIDE` |
| `academic_content` | "Transformer Architecture" | 4 bullet points (* prefix), academic technical content | `TITLE_AND_BODY` or `BULLET_LIST` |
| `section_header` | "Chapter 2: Methodology" | Empty string | `SECTION_HEADER_CENTER` or `SECTION_HEADER_TOP` |
| `bullet_list` | "Key Findings" | 4 bullet points (* prefix), metrics/findings | `BULLET_LIST` or `TITLE_AND_BODY` |
| `closing_slide` | "Thank You" | "Questions and Discussion\nContact: research@example.com" | `TITLE_SLIDE` or `SECTION_HEADER_CENTER` |
| `quote_slide` | "Inspiration" | Quoted sentence + "— Albert Einstein" attribution | `QUOTE` |

### Visual/photo slides (6)

| Label | Title | Content summary | Expected layout(s) |
|-------|-------|-----------------|-------------------|
| `photo_landscape` | "System Architecture" | "[Wide horizontal diagram showing the end-to-end processing pipeline from input to output]" | `PHOTO_LANDSCAPE` |
| `photo_portrait` | "About the Authors" | "[Portrait photo: lead researcher headshot]" | `PHOTO_PORTRAIT` |
| `content_with_photo` | "Attention Visualization" | 2 bullet points + "[Figure: attention heatmap visualization on the right]" | `CONTENT_WITH_PHOTO` |
| `three_photo` | "Qualitative Comparison" | "[Image 1: baseline output] [Image 2: proposed method] [Image 3: ground truth]" | `THREE_PHOTO` |
| `full_photo` | "" (empty) | "[Full-page image: t-SNE visualization of learned embedding space]" | `FULL_PHOTO` |
| `blank` | "" (empty) | "" (empty) | `BLANK` |

### Scoring note for no-placeholder layouts

For `THREE_PHOTO`, `FULL_PHOTO`, and `BLANK`, the scoring only checks whether `layout_name` is in the expected set. `idx_title_placeholder` and `idx_content_placeholder` values are not scored. However, the schema fix means these slides no longer produce `success=False` due to Pydantic validation errors on the idx fields — provided the model outputs either `null` (handled by `Optional[str] = None`) or an integer (handled by `coerce_int_to_str`). If the model outputs a non-null, non-integer value that fails other Pydantic constraints, a validation error is still possible; in practice this did not occur in this run.

---

## 7. Results per Model

### 7.1 gemma3:4b

**Available:** Yes. All 180 P1–P5 calls and 36 P0 calls completed (216 total). `success_rate = 36/36` for every prompt — no Pydantic validation errors in this run.

**Appropriate rate per prompt and slide type:**

| Prompt | cover/ title | academic | section | bullet | closing | quote | photo_ land | photo_ port | content_ photo | three_ photo | full_ photo | blank | Overall | Avg Elap |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| P0 Prod Baseline | 0/3 | 3/3 | 0/3 | 3/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 0/3 | 3/3 | 0/3 | **15/36** | 9.5s |
| P1 Baseline | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **33/36** | 11.1s |
| P2 Decision-Tree | 0/3 | 0/3 | 3/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 | **21/36** | 12.4s |
| P3 Positive Examples | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **33/36** | 13.0s |
| P4 Negative Examples | 0/3 | 0/3 | 3/3 | 3/3 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 | 0/3 | 3/3 | 3/3 | **21/36** | 13.2s |
| P5 Chain-of-Thought | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **30/36** | 12.0s |

**Wrong choices by slide type for gemma3:4b:**

| Slide | P0 Prod Baseline | P1 Baseline | P2 Decision-Tree | P3 Positive | P4 Negative | P5 CoT |
|-------|-----------------|-------------|------------------|-------------|-------------|--------|
| `cover/title_slide` | `TITLE_AND_BODY`×3 | `TITLE_AND_BODY`×3 | `TITLE_COVER`×3 | `TITLE_AND_BODY`×3 | `TITLE_AND_BODY`×3 | `TITLE_AND_BODY`×3 |
| `academic_content` | 3/3 OK | 3/3 OK | `CONTENT_SLIDE`×3 | 3/3 OK | `CONTENT_WITH_PHOTO`×3 | 3/3 OK |
| `section_header` | `TITLE_AND_BODY`×3 | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK |
| `bullet_list` | 3/3 OK | 3/3 OK | `CONTENT_SLIDE`×3 | 3/3 OK | 3/3 OK | 3/3 OK |
| `closing_slide` | `TITLE_AND_BODY`×3 | 3/3 OK | `CLOSING_SLIDE`×3 | 3/3 OK | `BULLET_LIST`×3 | 3/3 OK |
| `quote_slide` | `TITLE_AND_BODY`×3 | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK |
| `photo_landscape` | `TITLE_AND_BODY`×3 | 3/3 OK | 3/3 OK | 3/3 OK | `CONTENT_WITH_PHOTO`×3 | `CONTENT_WITH_PHOTO`×3 |
| `photo_portrait` | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK |
| `content_with_photo` | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK |
| `three_photo` | `CONTENT_WITH_PHOTO`×3 | 3/3 OK | 3/3 OK | 3/3 OK | `CONTENT_WITH_PHOTO`×3 | 3/3 OK |
| `full_photo` | 3/3 OK | 3/3 OK | `PHOTO_LANDSCAPE`×3 | 3/3 OK | 3/3 OK | 3/3 OK |
| `blank` | `TITLE_SLIDE`×3 | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK | 3/3 OK |

*`TITLE_COVER`, `CONTENT_SLIDE`, `CLOSING_SLIDE` are not valid template layout names — they are intermediate role labels from the P2 decision tree that the model output as the final `layout_name` value.*

---

### 7.2 ministral-3:14b-cloud

**Available:** Yes. All 180 P1–P5 calls and 36 P0 calls completed (216 total). `success_rate = 36/36` for every prompt — no Pydantic validation errors. `appropriate_rate = 36/36` for P1–P5; P0 is 29/36.

**Appropriate rate per prompt and slide type:**

| Prompt | cover/ title | academic | section | bullet | closing | quote | photo_ land | photo_ port | content_ photo | three_ photo | full_ photo | blank | Overall | Avg Elap |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| P0 Prod Baseline | 0/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **29/36** | 2.0s |
| P1 Baseline | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **36/36** | 1.7s |
| P2 Decision-Tree | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **36/36** | 1.6s |
| P3 Positive Examples | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **36/36** | 2.3s |
| P4 Negative Examples | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **36/36** | 2.3s |
| P5 Chain-of-Thought | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **36/36** | 2.0s |

**Wrong choices for ministral-3:14b-cloud — P0 only:**

| Slide | P0 Prod Baseline | P1–P5 |
|-------|-----------------|-------|
| `cover/title_slide` | `TITLE_AND_BODY`×3 | 3/3 OK (all 5 prompts) |
| `closing_slide` | `TITLE_AND_BODY`×3 | 3/3 OK (all 5 prompts) |
| `photo_landscape` | `CONTENT_WITH_PHOTO`×1, `PHOTO_LANDSCAPE`×2 → 2/3 | 3/3 OK (all 5 prompts) |

**P1–P5 wrong/FAIL choices:** None. ministral-3:14b-cloud had zero failures or wrong choices across all 180 P1–P5 calls.

**Selected layout names by ministral-3:14b-cloud (choices that vary across prompts, all within expected set):**

- `academic_content`: `BULLET_LIST` consistently across all 6 prompts (both `BULLET_LIST` and `TITLE_AND_BODY` are in the expected set)
- `section_header`: `SECTION_HEADER_CENTER` for P0/P1/P2/P4/P5; `SECTION_HEADER_TOP` for P3 (both are in the expected set)
- `closing_slide`: `TITLE_SLIDE` consistently across P1–P5; `TITLE_AND_BODY` (wrong) in P0
- All other slide types: consistent correct layout choice across all 6 prompts

---

## 8. Cross-Model Summary

### 8.1 Model × Prompt table

| Model | Prompt | Appropriate Rate | Success Rate | Avg Elapsed |
|-------|--------|:----------------:|:------------:|:-----------:|
| gemma3:4b | P0 Prod Baseline | **15/36** | 36/36 | 9.5s |
| gemma3:4b | P1 Baseline | **33/36** | 36/36 | 11.1s |
| gemma3:4b | P2 Decision-Tree | **21/36** | 36/36 | 12.4s |
| gemma3:4b | P3 Positive Examples | **33/36** | 36/36 | 13.0s |
| gemma3:4b | P4 Negative Examples | **21/36** | 36/36 | 13.2s |
| gemma3:4b | P5 Chain-of-Thought | **30/36** | 36/36 | 12.0s |
| ministral-3:14b-cloud | P0 Prod Baseline | **29/36** | 36/36 | 2.0s |
| ministral-3:14b-cloud | P1 Baseline | **36/36** | 36/36 | 1.7s |
| ministral-3:14b-cloud | P2 Decision-Tree | **36/36** | 36/36 | 1.6s |
| ministral-3:14b-cloud | P3 Positive Examples | **36/36** | 36/36 | 2.3s |
| ministral-3:14b-cloud | P4 Negative Examples | **36/36** | 36/36 | 2.3s |
| ministral-3:14b-cloud | P5 Chain-of-Thought | **36/36** | 36/36 | 2.0s |

### 8.2 Per-slide-type breakdown (combined totals, both models, all 6 prompts)

Maximum possible per slide type (P0–P5): 2 models × 6 prompts × 3 runs = **36**
Maximum possible per slide type (P1–P5 only): 2 models × 5 prompts × 3 runs = **30**

gemma3:4b per-slide breakdown (P0/P1/P2/P3/P4/P5):
- `cover/title_slide`: 0+0+0+0+0+0 = **0/18**
- `academic_content`: 3+3+0+3+0+3 = **12/18**
- `section_header`: 0+3+3+3+3+3 = **15/18**
- `bullet_list`: 3+3+0+3+3+3 = **15/18**
- `closing_slide`: 0+3+0+3+0+3 = **9/18**
- `quote_slide`: 0+3+3+3+3+3 = **15/18**
- `photo_landscape`: 0+3+3+3+0+0 = **9/18**
- `photo_portrait`: 3+3+3+3+3+3 = **18/18**
- `content_with_photo`: 3+3+3+3+3+3 = **18/18**
- `three_photo`: 0+3+3+3+0+3 = **12/18**
- `full_photo`: 3+3+0+3+3+3 = **15/18**
- `blank`: 0+3+3+3+3+3 = **15/18**

ministral-3:14b-cloud per-slide breakdown (P0/P1/P2/P3/P4/P5):
- `cover/title_slide`: 0+3+3+3+3+3 = **15/18**
- `academic_content`: 3+3+3+3+3+3 = **18/18**
- `section_header`: 3+3+3+3+3+3 = **18/18**
- `bullet_list`: 3+3+3+3+3+3 = **18/18**
- `closing_slide`: 0+3+3+3+3+3 = **15/18**
- `quote_slide`: 3+3+3+3+3+3 = **18/18**
- `photo_landscape`: 2+3+3+3+3+3 = **17/18**
- `photo_portrait`: 3+3+3+3+3+3 = **18/18**
- `content_with_photo`: 3+3+3+3+3+3 = **18/18**
- `three_photo`: 3+3+3+3+3+3 = **18/18**
- `full_photo`: 3+3+3+3+3+3 = **18/18**
- `blank`: 3+3+3+3+3+3 = **18/18**

| Slide Type | gemma3:4b (/ 18) | ministral (/ 18) | Total (/ 36) |
|------------|:----------------:|:----------------:|:------------:|
| `cover/title_slide` | 0 | 15 | **15/36** |
| `academic_content` | 12 | 18 | **30/36** |
| `section_header` | 15 | 18 | **33/36** |
| `bullet_list` | 15 | 18 | **33/36** |
| `closing_slide` | 9 | 15 | **24/36** |
| `quote_slide` | 15 | 18 | **33/36** |
| `photo_landscape` | 9 | 17 | **26/36** |
| `photo_portrait` | 18 | 18 | **36/36** |
| `content_with_photo` | 18 | 18 | **36/36** |
| `three_photo` | 12 | 18 | **30/36** |
| `full_photo` | 15 | 18 | **33/36** |
| `blank` | 15 | 18 | **33/36** |

---

## 9. Analysis

All numbers in this section are drawn directly from `layout_prompt_eng_results.json`, `layout_prompt_eng_results_P0_baseline.json`, and `layout_prompt_eng_output_new.txt`.

### 9.1 Best prompt per model (exact numbers)

**gemma3:4b:** P1 Baseline and P3 Positive Examples tie for best at **33/36 appropriate** (91.7%). P5 Chain-of-Thought is second at **30/36** (83.3%). P2 Decision-Tree and P4 Negative Examples tie for worst at **21/36** (58.3%). P0 Production Baseline is lowest at **15/36** (41.7%).

**ministral-3:14b-cloud:** All P1–P5 prompts tie at **36/36** (100%). P0 Production Baseline is **29/36** (80.6%). No engineered prompt is distinguishable from another for this model on this test set — the between-prompt variance comes entirely from P0 vs the rest.

### 9.2 Hardest slide types (ranked by combined total P0–P5, lowest first)

Maximum possible per slide type across all 6 prompts and 2 models: **36**.

| Rank | Slide Type | Total / 36 | Notes |
|------|------------|:----------:|-------|
| 1 (hardest) | `cover/title_slide` | 15 | gemma3:4b scores 0/18 across all 6 prompts; ministral scores 0/3 on P0, 15/15 on P1–P5 |
| 2 | `closing_slide` | 24 | gemma3:4b scores 0/3 on P0, P2, P4; ministral scores 0/3 on P0 |
| 3 | `photo_landscape` | 26 | gemma3:4b scores 0/3 on P0, P4, P5; ministral scores 2/3 on P0 (1 wrong) |
| 4 | `academic_content` | 30 | gemma3:4b scores 0/3 on P2 and P4 |
| 4 | `three_photo` | 30 | gemma3:4b scores 0/3 on P0 and P4 |
| 6 | `section_header` | 33 | gemma3:4b scores 0/3 on P0 only |
| 6 | `bullet_list` | 33 | gemma3:4b scores 0/3 on P2 only |
| 6 | `quote_slide` | 33 | gemma3:4b scores 0/3 on P0 only |
| 6 | `full_photo` | 33 | gemma3:4b scores 0/3 on P2 only |
| 6 | `blank` | 33 | gemma3:4b scores 0/3 on P0 only |
| 11 (easiest, 2-way tie) | `photo_portrait` | 36 | Perfect across both models and all 6 prompts |
| 11 | `content_with_photo` | 36 | Perfect across both models and all 6 prompts |

`cover/title_slide` is the only slide type where gemma3:4b fails on every prompt (0/3 × 6 prompts = 0/18). P0 and P1/P3/P4/P5 all produce `TITLE_AND_BODY`; P2 produces the invalid name `TITLE_COVER`.

For P1–P5 only (excluding P0), the hardest slides remain: `cover/title_slide` (15/30), `academic_content` (24/30), `closing_slide` (24/30), `photo_landscape` (24/30). The P0 data adds new failures for gemma3:4b on `section_header`, `quote_slide`, `blank` — slide types where P1–P5 were perfect.

### 9.3 Failure mode analysis

**gemma3:4b — three distinct failure modes in this run:**

**Failure Mode A — Invalid layout name (P2 decision tree):** When P2 Decision-Tree routing is used, gemma3:4b outputs the intermediate decision-tree role label as the final `layout_name` instead of the actual template layout name. Specifically:
- `cover/title_slide` → outputs `TITLE_COVER` (not in the valid layout set)
- `academic_content` → outputs `CONTENT_SLIDE` (not in the valid layout set)
- `bullet_list` → outputs `CONTENT_SLIDE` (not in the valid layout set)
- `closing_slide` → outputs `CLOSING_SLIDE` (not in the valid layout set)

The model appears to stop at the role-labelling step (STEP 1) rather than proceeding to the layout-name lookup (STEP 2). All P2 failures output strings that match role names defined in the decision tree, not layout names defined in the template.

**Failure Mode B — Wrong valid name (covering the remaining failures):** gemma3:4b outputs a valid layout name (present in the template) that is inappropriate for the slide:
- `cover/title_slide` → `TITLE_AND_BODY`×3 in P1, P3, P4, P5 (consistent across all 4 prompts)
- `academic_content` → `CONTENT_WITH_PHOTO`×3 in P4 (the negative rules against TITLE_AND_BODY redirect the model to an unexpected layout)
- `closing_slide` → `BULLET_LIST`×3 in P4 (the negative rule against TITLE_AND_BODY/BULLET_LIST for closing slides appears to mismatch the model's pattern matching)
- `photo_landscape` → `CONTENT_WITH_PHOTO`×3 in P4 and P5 (the model detects a visual element reference in the content and picks the combined-content-plus-photo layout)
- `full_photo` → `PHOTO_LANDSCAPE`×3 in P2 (the model recognises a full-image slide but picks the single-landscape-image layout instead)
- `three_photo` → `CONTENT_WITH_PHOTO`×3 in P4 (similar to `photo_landscape` — visual element detected, wrong layout chosen)

**ministral-3:14b-cloud:** No failures on P1–P5 (zero wrong choices across all 180 calls). P0 has 7 wrong choices: `cover/title_slide` (0/3, `TITLE_AND_BODY`×3), `closing_slide` (0/3, `TITLE_AND_BODY`×3), `photo_landscape` (2/3, `CONTENT_WITH_PHOTO`×1).

### 9.4 Impact of schema fix: THREE_PHOTO, FULL_PHOTO, BLANK

**Context:** In the previous run, `idx_title_placeholder` and `idx_content_placeholder` were typed as required `str`. Models returning `null` or an integer for these fields triggered immediate Pydantic validation errors. For layouts without text placeholders (`THREE_PHOTO`, `FULL_PHOTO`, `BLANK`), the model had no valid value to return, so almost all calls on these slide types produced `success=False` (validation failure), regardless of whether `layout_name` was correct.

**Previous run results for these layouts (from prior run data):** Both gemma3:4b and ministral-3:14b-cloud had validation failures on `THREE_PHOTO`, `FULL_PHOTO`, and `BLANK` in the previous run. ministral in particular had notable validation failures, contributing to its previous overall score being below perfect.

**This run results:**

`success_rate` for every model and every prompt in this run is **36/36**. No Pydantic validation errors occurred on any slide type, including `THREE_PHOTO`, `FULL_PHOTO`, and `BLANK`. The schema fix (`Optional[str] = None` + `coerce_int_to_str`) completely eliminated validation failures.

**Appropriate rates for the three no-placeholder layouts:**

| Slide | gemma3:4b (all 6 prompts P0–P5) | ministral (all 6 prompts P0–P5) |
|-------|:--------------------------------:|:--------------------------------:|
| `three_photo` | P0=0/3, P1=3/3, P2=3/3, P3=3/3, P4=0/3, P5=3/3 → **12/18** | P0=3/3, P1–P5=15/15 → **18/18** |
| `full_photo` | P0=3/3, P1=3/3, P2=0/3, P3=3/3, P4=3/3, P5=3/3 → **15/18** | P0=3/3, P1–P5=15/15 → **18/18** |
| `blank` | P0=0/3, P1=3/3, P2=3/3, P3=3/3, P4=3/3, P5=3/3 → **15/18** | P0=3/3, P1–P5=15/15 → **18/18** |

The schema fix resolved the validation failures. In this run, failures for these slide types are due to wrong `layout_name` choices (Failure Mode A or B), not schema validation errors. For example, gemma3:4b P0 `three_photo` fails with `CONTENT_WITH_PHOTO` (wrong but valid name), and gemma3:4b P4 `three_photo` also fails with `CONTENT_WITH_PHOTO`; in the previous run both would have failed with a Pydantic error before the layout name could even be evaluated.

Notably, for gemma3:4b P0 `blank`: the production prompt has no null instruction for idx fields, yet `success=True` was achieved (36/36 success rate). The model produced a non-null value for the idx fields on `blank`, which the schema's `coerce_int_to_str` validator handled without error. The `blank` wrong choice (`TITLE_SLIDE`×3) is a layout selection error, not a schema error. ministral P0 on `blank` chose `BLANK` correctly (3/3).

The `coerce_int_to_str` validator was not triggered in any observable way in the P1–P5 run — the output log shows no coercion warnings, and all 360 calls completed with `success=True`. For P0, `success_rate = 36/36` for both models, confirming the schema fix handles P0's missing null instruction gracefully. The validator serves as a defensive measure for future edge cases.

### 9.5 Impact of P4 redesign (8 rules vs previous 19 rules)

**Previous run P4 scores:** gemma3:4b = 15/36, ministral-3:14b-cloud = 29/36.

**This run P4 scores:** gemma3:4b = **21/36**, ministral-3:14b-cloud = **36/36**.

**gemma3:4b P4:** Improved from 15/36 to 21/36 (+6 appropriate calls). However, this improvement cannot be attributed solely to the P4 redesign — the schema fix eliminated Pydantic validation errors that contributed to failures in the previous run. In this run, gemma3:4b P4 still fails on 5 slide types: `cover/title_slide` (0/3, `TITLE_AND_BODY`), `academic_content` (0/3, `CONTENT_WITH_PHOTO`), `closing_slide` (0/3, `BULLET_LIST`), `photo_landscape` (0/3, `CONTENT_WITH_PHOTO`), `three_photo` (0/3, `CONTENT_WITH_PHOTO`). The `CONTENT_WITH_PHOTO` wrong choice appearing 3 times in gemma3:4b P4 suggests the 8 rules (which do not cover visual layout disambiguation) are insufficient for preventing visual layout confusion in the 4B model. P4 remains the worst or second-worst prompt for gemma3:4b.

**ministral-3:14b-cloud P4:** Improved from 29/36 to 36/36 (+7). Again, the schema fix is a confounding factor — the previous 7 failures may have been validation errors. In this run, ministral achieves 36/36 on all 5 prompts, making it impossible to attribute the improvement specifically to the P4 redesign vs the schema fix.

**Conclusion on P4 redesign:** The reduction from 19 to 8 rules did not worsen results for either model. Whether it independently improved results cannot be determined without an isolated control run (same schema fix, old 19-rule P4 prompt).

### 9.6 How all 6 prompts compare across both models

| Prompt | gemma3:4b | ministral | Combined |
|--------|:---------:|:---------:|:--------:|
| P0 Prod Baseline | 15/36 | 29/36 | **44/72** |
| P1 Baseline | 33/36 | 36/36 | **69/72** |
| P2 Decision-Tree | 21/36 | 36/36 | **57/72** |
| P3 Positive Examples | 33/36 | 36/36 | **69/72** |
| P4 Negative Examples | 21/36 | 36/36 | **57/72** |
| P5 Chain-of-Thought | 30/36 | 36/36 | **66/72** |

P0 is the lowest combined score at 44/72 (61.1%). P1 and P3 tie for highest (69/72, 95.8%). P2 and P4 tie at 57/72 (79.2%). P5 is 66/72 (91.7%).

P1 (adding LAYOUT_DESCRIPTIONS alone) already lifts gemma3:4b from 15/36 to 33/36 (+18 appropriate calls, +50pp). Adding routing guidance (P2–P5) does not uniformly improve over P1 for gemma3:4b. For ministral-3:14b-cloud, P1–P5 all achieve 36/36; P0 alone falls short at 29/36.

For ministral-3:14b-cloud, P1–P5 are indistinguishable — the model achieves 36/36 regardless of prompt strategy. The between-prompt variance is entirely driven by gemma3:4b.

For gemma3:4b specifically:
- P0 Prod Baseline (15/36) is the floor — the current production prompt
- P1 Baseline (33/36) and P3 Positive Examples (33/36) tie for best among engineered prompts
- P5 Chain-of-Thought (30/36) is second
- P2 Decision-Tree (21/36) and P4 Negative Examples (21/36) tie for worst among engineered prompts (but both still outperform P0)
- P2 is uniquely harmful: it introduces Failure Mode A (invalid layout names as role labels), which does not occur in any other prompt

### 9.7 Latency

| Model | P0 | P1 | P2 | P3 | P4 | P5 |
|-------|:--:|:--:|:--:|:--:|:--:|:--:|
| gemma3:4b | 9.5s | 11.1s | 12.4s | 13.0s | 13.2s | 12.0s |
| ministral-3:14b-cloud | 2.0s | 1.7s | 1.6s | 2.3s | 2.3s | 2.0s |

**gemma3:4b:** P0 Production Baseline is the fastest at **9.5s** — it is a shorter prompt with no LAYOUT_DESCRIPTIONS block. P1 Baseline is next at 11.1s. P4 Negative Examples is slowest (13.2s). The 3.7s spread from P0 to P4 corresponds to increased token count for longer prompt templates. P5 Chain-of-Thought (12.0s) is only 0.9s slower than P1 despite requiring the model to generate multi-step reasoning before the JSON output.

**ministral-3:14b-cloud:** P2 Decision-Tree is fastest (1.6s). P3 and P4 are slowest (2.3s each). P0 is 2.0s — comparable to P5. ministral-3:14b-cloud runs approximately 6–8× faster than gemma3:4b (cloud routing vs local M1 inference). P5 Chain-of-Thought (2.0s) is not the slowest for ministral in this run, unlike the typical CoT overhead pattern.

### 9.8 P0 analysis — production prompt accuracy

**P0 overall accuracy (both models combined):** 44/72 (61.1%). This is the accuracy of the prompt currently deployed in production against the 12-layout test set.

**P0 vs P1 — does adding LAYOUT_DESCRIPTIONS alone improve accuracy?**

| Model | P0 (no descriptions) | P1 (descriptions only) | Delta |
|-------|:--------------------:|:----------------------:|:-----:|
| gemma3:4b | 15/36 (41.7%) | 33/36 (91.7%) | **+18 (+50pp)** |
| ministral-3:14b-cloud | 29/36 (80.6%) | 36/36 (100%) | **+7 (+19pp)** |
| Combined | 44/72 (61.1%) | 69/72 (95.8%) | **+25 (+34pp)** |

Adding `LAYOUT_DESCRIPTIONS` alone (P1 vs P0) produces the single largest accuracy improvement in this experiment. The full routing engineering in P2–P5 adds relatively little beyond P1 for most cases. This directly answers the P0 vs P1 question: yes, LAYOUT_DESCRIPTIONS alone produces a large gain.

**P0 vs P2–P5 — how much does routing guidance help beyond descriptions?**

For gemma3:4b: P1 and P3 are best (33/36). P2, P4 are worse (21/36). P5 is intermediate (30/36). Routing guidance does not consistently improve over descriptions-only for the small 4B model.

For ministral-3:14b-cloud: P1–P5 all achieve 36/36. All engineered prompts are equivalent improvements over P0. The 7-call gap (P0 29/36 → P1 36/36) is fully closed by any prompt with LAYOUT_DESCRIPTIONS.

**Which slide types P0 fails on and why:**

*gemma3:4b P0 (15/36, 7 types failed):*
- `cover/title_slide` (0/3, `TITLE_AND_BODY`×3): Without LAYOUT_DESCRIPTIONS, the model has no guidance distinguishing TITLE_SLIDE from TITLE_AND_BODY. The production prompt's only routing hint is "agenda/overview, regular content, title slide, or closing/thank-you" — too vague.
- `section_header` (0/3, `TITLE_AND_BODY`×3): No description of SECTION_HEADER_CENTER/TOP in P0. The model defaults to TITLE_AND_BODY for any titled slide.
- `closing_slide` (0/3, `TITLE_AND_BODY`×3): Same as above — no description distinguishing closing slides from regular content.
- `quote_slide` (0/3, `TITLE_AND_BODY`×3): QUOTE layout has no guidance in P0. Model defaults to TITLE_AND_BODY.
- `photo_landscape` (0/3, `TITLE_AND_BODY`×3): The production prompt says "choose a layout that has a content placeholder" — biasing toward text-bearing layouts even for visual slides. Result: `TITLE_AND_BODY` instead of `PHOTO_LANDSCAPE`.
- `three_photo` (0/3, `CONTENT_WITH_PHOTO`×3): Model detects multiple image references and picks the combined layout rather than the three-photo-specific layout.
- `blank` (0/3, `TITLE_SLIDE`×3): No guidance for completely empty slides. Model picks `TITLE_SLIDE` (the emptiest-seeming layout it knows).

*ministral-3:14b-cloud P0 (29/36, 2 types fully failed + 1 partial):*
- `cover/title_slide` (0/3, `TITLE_AND_BODY`×3): Same failure as gemma3:4b — no description distinguishing TITLE_SLIDE from TITLE_AND_BODY.
- `closing_slide` (0/3, `TITLE_AND_BODY`×3): Same failure — no guidance for ceremonial closing slides.
- `photo_landscape` (2/3, `CONTENT_WITH_PHOTO`×1, `PHOTO_LANDSCAPE`×2): Mostly correct (2/3), with 1 wrong choice. ministral generally handles visual layouts well even without detailed descriptions.

**P0 on visual layouts (THREE_PHOTO, FULL_PHOTO, BLANK) — null instruction missing:**

P0 does not instruct the model to output `null` for `idx_title_placeholder`/`idx_content_placeholder` on layouts with no text placeholders. Despite this, `success_rate = 36/36` for both models under P0. The schema fix (`Optional[str] = None` + `coerce_int_to_str`) absorbed whatever the model returned for these fields. Layout selection correctness for these slides under P0:
- `full_photo`: gemma3:4b 3/3 correct (FULL_PHOTO); ministral 3/3 correct.
- `blank`: gemma3:4b 0/3 wrong (`TITLE_SLIDE`×3 — layout confusion, not idx issue); ministral 3/3 correct (BLANK).
- `three_photo`: gemma3:4b 0/3 wrong (`CONTENT_WITH_PHOTO`×3); ministral 3/3 correct.

The missing null instruction in P0 does not cause validation failures under the current schema, but the layout selection errors on `blank` and `three_photo` for gemma3:4b indicate that the absence of LAYOUT_DESCRIPTIONS (which provides Signals for these layouts) is the primary cause of failure, not the idx field instruction.

**P0 latency vs other prompts:**

P0 is the fastest prompt for gemma3:4b (9.5s vs 11.1–13.2s for P1–P5) because the production prompt has fewer tokens — no LAYOUT_DESCRIPTIONS block. For ministral, P0 (2.0s) is comparable to P1 (1.7s) and P5 (2.0s). Speed advantage of P0 is not sufficient justification to keep it given the 34pp accuracy gap over P1 combined.

---

## 10. Conclusions and Recommendations

**P0 is the lowest-performing prompt overall.** The production prompt (`AUGMENT_LAYOUT_PMT`, P0) achieves 44/72 combined (61.1%) vs 69/72 (95.8%) for the best engineered prompts (P1 and P3). This is the accuracy of layout selection in the currently deployed pipeline. Every engineered prompt P1–P5 outperforms P0 for both models.

**P1 (LAYOUT_DESCRIPTIONS alone) is the most impactful change.** Moving from P0 to P1 closes most of the accuracy gap: gemma3:4b goes from 15/36 to 33/36 (+18 calls), ministral from 29/36 to 36/36 (+7 calls). The addition of structured layout descriptions (Use for / Structure / Signals per layout) is the dominant improvement over the production prompt — not routing rules or negative constraints.

**Best prompt for deployment:** P1 or P3 (tied at 69/72 combined). For gemma3:4b, both achieve 33/36. For ministral-3:14b-cloud, all P1–P5 achieve 36/36. P3 (Positive Examples) is semantically richer and may generalise better across paper types; P1 is simpler. P5 Chain-of-Thought (66/72) is a viable alternative if reasoning transparency is valued. P2 Decision-Tree and P4 Negative Examples should be avoided for gemma3:4b — they are worse than P1/P3 and introduce new failure modes.

**P0 failure pattern:** The production prompt has no layout descriptions, biasing models to pick `TITLE_AND_BODY` for any slide with text and creating no guidance for specialist layouts (QUOTE, SECTION_HEADER_*, THREE_PHOTO, BLANK). For gemma3:4b, 7 out of 12 slide types fail under P0. For ministral-3:14b-cloud, 2 slide types fail completely (`cover/title_slide`, `closing_slide`) with a third partial failure (`photo_landscape`). The Norwegian legacy text ("Plassholder for innhold") in P0 does not appear to cause visible harm to either model's layout name output, but is a maintenance liability.

**Recommendation:** Replace `AUGMENT_LAYOUT_PMT` in production with a prompt that includes `LAYOUT_DESCRIPTIONS`. P1 (`P1_baseline`) is the minimum viable replacement. P3 (`P3_positive_examples`) is the recommended replacement given its semantic clarity and equal accuracy. The `OUTPUT_FIELDS` null instruction should be included to properly guide models on visual-only layouts, even though the schema fix (`Optional[str] = None`) prevents validation failures without it.

---

## 12. Limitations

1. **Near-determinism:** `temperature=0.1` and `N_RUNS=3` means most cells are deterministically 0/3 or 3/3. Three runs provide minimal statistical value for estimating variance in layout selection. A meaningful variance estimate would require `N_RUNS >= 10` with higher temperature.

2. **Visual test case fidelity:** Visual slide cases use bracketed text as image proxies (e.g., `"[Wide horizontal diagram showing the end-to-end processing pipeline from input to output]"`). In the real pipeline, the content field for a visual slide may be empty or contain only a caption — not an explicit bracketed `[Wide image]` tag. Results on visual layouts may not transfer directly to production inputs where the signal is weaker.

3. **Unused slide types in production:** `section_header` and `quote_slide` do not appear in the current real pipeline. Their results are valid as isolated test cases but do not represent production workload distribution.

4. **Only 2 models tested:** `gpt-oss:20b-cloud` was removed from the `MODELS` list. Conclusions apply only to gemma3:4b and ministral-3:14b-cloud. Results are not generalisable to other models without additional testing.

5. **Schema fix and P4 redesign are confounded:** The schema fix (`Optional[str] = None`) and the P4 redesign were applied simultaneously. The previous run had validation failures that affected the P4 score. It is not possible to determine how much of the P4 score change (gemma: 15→21, ministral: 29→36) is attributable to the schema fix vs the prompt redesign vs the expanded test set (6→12 slide types, with different scoring for the new cases).

6. **Null idx validation dependency:** The `idx_title_placeholder` and `idx_content_placeholder` null instruction in `OUTPUT_FIELDS` depends on the LLM correctly following the CRITICAL note in the prompt. If an LLM outputs an integer (e.g., `"0"`) instead of `null`, the `coerce_int_to_str` validator coerces it to the string `"0"`, preventing a validation error — but the placeholder index may still be structurally wrong at runtime if the layout has no such placeholder. In this run, no such runtime consequence was observed because the experiment only evaluates `layout_name` correctness, not idx correctness.

---

## 13. File Index

| File | Absolute path | Description |
|------|---------------|-------------|
| Experiment script | `poc/agent-behavior-test/layout_selection_prompt_eng.py` | Full Python experiment: models, prompts, test cases, runner, JSON output |
| Console output (this run) | `poc/agent-behavior-test/layout_prompt_eng_output_new.txt` | Full per-run console output from this execution |
| Raw results JSON (P1–P5) | `poc/agent-behavior-test/layout_prompt_eng_results.json` | Structured results: per-model, per-prompt, per-slide, per-run (P1–P5 only) |
| Raw results JSON (P0) | `poc/agent-behavior-test/layout_prompt_eng_results_P0_baseline.json` | Structured results for P0 production baseline run (merged into this report) |
| This report | `poc/agent-behavior-test/layout_selection_prompt_eng.md` | This document |
| SlideOutlineWithLayout schema | `backend/agent_workflows/schemas.py` | Pydantic schema with `Optional[str] = None` idx fields and `coerce_int_to_str` validator |
| Template file | `assets/template-en.pptx` | PPTX master with 12 English-named layouts |
