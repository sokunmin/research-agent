# Layout Prompt Engineering Results

**Date:** 2026-03-29
**Test script:** `layout_prompt_eng_test.py`
**Raw results:** `layout_prompt_eng_results.json`
**Output log:** `layout_prompt_eng_output.txt`

---

## 1. Background

### Problem

The research agent pipeline generates PowerPoint presentations from academic papers. A critical step — called `outlines_with_layout` — requires selecting the correct slide layout for each slide from a 12-layout PPTX template. If the model always defaults to `TITLE_AND_BODY`, the resulting deck looks visually uniform: every slide is a content slide with title + body, missing proper cover slides, section breaks, quote cards, and closing slides.

**The layout selection task:** Given a slide's title and body text, select the correct layout name from the 12 available layouts (e.g. `TITLE_SLIDE`, `SECTION_HEADER_CENTER`, `QUOTE`) and identify the correct placeholder indices.

### What Previous Experiments Found

**From `augment-results.md` (2026-03-28):**
- `FunctionCallingProgram` (METHOD_A) fails for ALL Ollama models — must use `LLMTextCompletionProgram`.
- Prompt quality matters for `gemma3:4b`: the original `AUGMENT_LAYOUT_PMT` prompt (without field descriptions) causes 0% structured output success. Adding explicit field descriptions (Prompt 2) brings it to 100% parse success.
- METHOD_C (Ollama `format` param with JSON schema) achieves 100% parse success for all prompts, but this experiment focuses on layout *selection* accuracy, not just parse success.

**From `layout_name_test.md` / `layout_name_test_v2_output.txt` (2026-03-29):**
These are the critical baseline results that this experiment improves upon:

| Model | Appropriate Rate (baseline prompt) |
|---|---|
| `gemma3:4b` | 6/18 (33.3%) |
| `gpt-oss:20b-cloud` | 10/18 (55.6%) |
| `ministral-3:14b-cloud` | 12/18 (66.7%) |

**Universally failed slide types with the baseline prompt:**
- `cover/title_slide`: 0/9 across all 3 models — all chose `TITLE_AND_BODY` instead of `TITLE_SLIDE`
- `closing_slide`: 0/9 across all 3 models — all chose `TITLE_AND_BODY` instead of `TITLE_SLIDE`/`SECTION_HEADER_CENTER`

The baseline `AUGMENT_LAYOUT_PMT` is a generic instruction with no routing rules, no explicit negative constraints, and no chain-of-thought structure. The diagnosis from `layout_name_test.md` §7.6 is: "the current prompt does not give models enough guidance to distinguish cover/closing slides from content slides."

**This experiment** tests 4 prompt engineering strategies specifically designed to fix these failures. The baseline prompt results are NOT re-run here — see `layout_name_test.md` for baseline comparisons.

### Related Files

- `layout_name_test.md` — baseline single-prompt, 3-model layout selection test
- `layout_name_test_v2_output.txt` — raw baseline output
- `augment-results.md` — structured output method comparison (FunctionCallingProgram vs LLMTextCompletionProgram)
- `test_cloud_models.md` — cloud model capabilities (function calling, think mode, availability)
- `layout_prompt_eng_test.py` — this experiment's test script
- `layout_prompt_eng_results.json` — raw run data (all results)

---

## 2. Experiment Setup

### Template File

`/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/assets/template-en.pptx`

### Available Layouts (12 total, read dynamically from template)

| # | Layout Name | Placeholders (idx, name pattern) | Role |
|---|---|---|---|
| 1 | `TITLE_SLIDE` | (0, title), (1, subtitle), (12, footer) | Opening cover or closing slide |
| 2 | `TITLE_AND_BODY` | (1, body), (0, title), (12, footer) | Standard content slide |
| 3 | `QUOTE` | (1, main), (2, attribution), (12, footer) | Large-format quote display |
| 4 | `PHOTO_LANDSCAPE` | (2, photo), (0, title), (1, caption), (12, footer) | Landscape photo slide |
| 5 | `SECTION_HEADER_CENTER` | (0, title), (12, footer) | Section divider (centered) |
| 6 | `PHOTO_PORTRAIT` | (2, photo), (0, title), (1, caption), (12, footer) | Portrait photo slide |
| 7 | `SECTION_HEADER_TOP` | (0, title), (12, footer) | Section divider (top) |
| 8 | `CONTENT_WITH_PHOTO` | (2, photo), (0, title), (1, content), (12, footer) | Text + photo side-by-side |
| 9 | `項目符號` | (1, body), (0, title), (12, footer) | Bullet-list content slide |
| 10 | `照片 - 一頁三張` | (2,3,4, photos), (12, footer) | Three-photo layout |
| 11 | `FULL_PHOTO` | (2, photo), (12, footer) | Full-bleed photo |
| 12 | `空白` | (12, footer) | Blank slide |

### Models Tested

| Label | LiteLLM Model Name | Provider | additional_kwargs | Notes |
|---|---|---|---|---|
| `gemma3:4b` | `ollama/gemma3:4b` | Ollama (local M1) | `{}` | Local 4B, worst in baseline |
| `ministral-3:14b-cloud` | `ollama/ministral-3:14b-cloud` | Ollama → Mistral cloud | `{}` | Best in baseline (12/18), no think mode |
| `gpt-oss:20b-cloud` | `ollama/gpt-oss:20b-cloud` | Ollama → OpenAI cloud | `{}` | 2nd in baseline (10/18), think mode always on |

**Why no Groq models?** The `.env` configures `LLM_FAST_MODEL` and `LLM_SMART_MODEL` using Ollama cloud routing. The cloud models tested here (`ministral-3:14b-cloud`, `gpt-oss:20b-cloud`) are the same logical models accessed via Ollama's transparent cloud proxy. Groq models would require `groq/` prefix and separate API routing; since the baseline experiment only tested Ollama-routed models, we continue with the same model set for direct comparability.

### Method

**`LLMTextCompletionProgram`** (LlamaIndex) for all models and all prompts.

`FunctionCallingProgram` is explicitly excluded — it fails for all Ollama models due to missing `tool_calls` support (confirmed in `augment-results.md`).

```python
program = LLMTextCompletionProgram.from_defaults(
    llm=LiteLLM(model=model_name, temperature=0.1, max_tokens=2048),
    output_cls=SlideOutlineWithLayout,
    prompt_template_str=prompt_template,
    verbose=False,
)
response = program(
    slide_content=json.dumps(slide_outline),
    available_layout_names=json.dumps(AVAILABLE_LAYOUT_NAMES),
    available_layouts=json.dumps(AVAILABLE_LAYOUTS, indent=2),
)
```

### Run Configuration

| Parameter | Value |
|---|---|
| N_RUNS | 3 per (model × prompt × slide_type) |
| Temperature | 0.1 |
| max_tokens | 2048 |
| Execution | Sequential only (no asyncio.gather) |
| Total LLM calls | 3 models × 4 prompts × 6 slide_types × 3 runs = 216 |

### Slide Test Cases (identical to `layout_name_test_v2.py`)

| Label | Title | Content (summary) | Expected Layout(s) |
|---|---|---|---|
| `cover/title_slide` | "Attention Is All You Need" | "A Research Presentation / Presented by: John Smith" | `TITLE_SLIDE` |
| `academic_content` | "Transformer Architecture" | 4 bullet points on self-attention, etc. | `TITLE_AND_BODY` or `項目符號` |
| `section_header` | "Chapter 2: Methodology" | "" (empty body) | `SECTION_HEADER_CENTER` or `SECTION_HEADER_TOP` |
| `bullet_list` | "Key Findings" | 4 bullet points on BLEU score improvements | `項目符號` or `TITLE_AND_BODY` |
| `closing_slide` | "Thank You" | "Questions and Discussion / Contact: research@example.com" | `TITLE_SLIDE` or `SECTION_HEADER_CENTER` |
| `quote_slide` | "Inspiration" | `"The measure of intelligence..." — Albert Einstein` | `QUOTE` |

**Scoring:**
- `layout_appropriate = True` if the chosen layout name is in the expected set for that slide type
- `layout_valid = True` if the chosen layout name exists in the template (valid name)

---

## 3. Prompt Variants

All 4 prompts are NEW strategies not tested in previous experiments. The baseline `AUGMENT_LAYOUT_PMT` is not included here.

### PROMPT_1: Decision-Tree Routing (`P1_decision_tree`)

**Rationale:** The baseline prompt gives generic instructions with no routing logic. All models fail cover/closing slides because there are no explicit rules telling them which layouts to use for those roles. A decision tree provides an if/then dispatch the model can follow literally.

**Hypothesis:** Explicit routing rules will fix cover_slide (→ TITLE_SLIDE) and closing_slide (→ TITLE_SLIDE/SECTION_HEADER_CENTER) which failed universally in the baseline.

**Design:**
```
STEP 1 — Identify the slide role using this decision tree:
  A. If body is a direct quote with attribution → role = QUOTE_SLIDE
  B. Else if title starts with "Chapter"/"Section" or body is empty → role = SECTION_BREAK
  C. Else if title is "Thank You"/"Conclusion"/"Q&A" or content is closing message → role = CLOSING_SLIDE
  D. Else if body has "Presented by:" or "Author:" with no bullets → role = TITLE_COVER
  E. Else if body has bullet points → role = CONTENT_SLIDE
  F. Else → role = CONTENT_SLIDE

STEP 2 — Select layout based on role:
  QUOTE_SLIDE → QUOTE
  SECTION_BREAK → SECTION_HEADER_CENTER or SECTION_HEADER_TOP
  CLOSING_SLIDE → TITLE_SLIDE or SECTION_HEADER_CENTER
  TITLE_COVER → TITLE_SLIDE
  CONTENT_SLIDE → TITLE_AND_BODY or 項目符號
```

**Known limitation:** gemma3:4b may return the role label (`TITLE_COVER`) as the layout name instead of the actual layout name (`TITLE_SLIDE`). This is a hallucination risk for small models with multi-step instructions.

---

### PROMPT_2: Negative Examples (`P2_negative_examples`)

**Rationale:** All three models exhibit TITLE_AND_BODY bias. The failure mode is always the same: default to TITLE_AND_BODY. Explicit "DO NOT use X for Y" constraints directly counter the bias without requiring complex reasoning steps.

**Hypothesis:** Negative constraints are the most direct way to break TITLE_AND_BODY bias without risking hallucination of intermediate labels.

**Design:**
```
LAYOUT SELECTION RULES:

USE TITLE_SLIDE when:
  - Opening/cover slide (author attribution present)
  - Closing/thank-you slide ("Thank You", "Q&A", "Questions")

USE SECTION_HEADER_CENTER or SECTION_HEADER_TOP when:
  - Body is empty or very short (no bullet points)
  - Title begins with "Chapter", "Section", "Part"

USE QUOTE when:
  - Body contains a quotation with attribution (— Author)

USE TITLE_AND_BODY or 項目符號 when:
  - Slide has multiple bullet points
  - Body is substantive academic/technical content

DO NOT use TITLE_AND_BODY for:
  - Opening cover slides with author attribution
  - Chapter/section transition slides with empty body
  - Closing/thank-you slides
  - Slides whose body is a quoted sentence with attribution
```

---

### PROMPT_3: Chain-of-Thought (`P3_chain_of_thought`)

**Rationale:** Previous prompts ask for the final answer directly. Chain-of-thought explicitly asks the model to classify the slide type first, then select the layout, then verify. Making reasoning explicit may improve accuracy on ambiguous slides by forcing the model to commit to a slide type classification before picking a layout.

**Hypothesis:** CoT reasoning steps give models a chance to self-correct before outputting the final layout.

**Design:**
```
Before selecting a layout, REASON STEP BY STEP:

1. What type of slide is this? Choose one:
   - "cover": opening title page (author attribution, "Presented by")
   - "section_break": chapter/section divider (empty or near-empty body)
   - "closing": thank-you, Q&A, or conclusion slide
   - "quote": body is a quoted sentence with attribution
   - "content": substantive bullet-point content

2. Based on the slide type, which layout is most appropriate?
   cover → TITLE_SLIDE
   section_break → SECTION_HEADER_CENTER or SECTION_HEADER_TOP
   closing → TITLE_SLIDE or SECTION_HEADER_CENTER
   quote → QUOTE
   content → TITLE_AND_BODY or 項目符號

3. Confirm: does the chosen layout exist in the available layout list?
```

---

### PROMPT_4: Minimal Layout List (`P4_minimal_layout`)

**Rationale:** The full layout list of 12 includes 6 photo/visual layouts (`PHOTO_LANDSCAPE`, `PHOTO_PORTRAIT`, `CONTENT_WITH_PHOTO`, `照片 - 一頁三張`, `FULL_PHOTO`, `空白`) that are irrelevant for text-based academic slides. The 3 Chinese-named layouts may be invisible to English-trained models (see `layout_name_test.md` §8.3). Providing only the 6 core text layouts with explicit English role descriptions reduces the choice space and adds semantic grounding for non-ASCII names.

**Hypothesis:** A smaller, well-described layout list reduces decision noise and makes Chinese-named layouts like `項目符號` usable by English models.

**Design:**
```
AVAILABLE TEXT LAYOUTS (choose from these 6 for text slides):

1. TITLE_SLIDE — Opening cover OR closing thank-you slide
2. TITLE_AND_BODY — Standard academic/technical content slide
3. 項目符號 (bullet list layout) — Bullet-point content slide
4. SECTION_HEADER_CENTER — Section divider, centered, no body content
5. SECTION_HEADER_TOP — Section divider, top-aligned, no body content
6. QUOTE — Large-format quote display with attribution
```

---

## 4. Results

### 4.1 `gemma3:4b` (local, 4B parameters)

| Prompt | cover/title | academic | section_header | bullet_list | closing | quote | **Overall** | Avg Elapsed |
|---|---|---|---|---|---|---|---|---|
| P1 Decision-Tree Routing | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **15/18** | 11.7s |
| P2 Negative Examples | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 11.6s |
| P3 Chain-of-Thought | 3/3 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 | **12/18** | 11.7s |
| P4 Minimal Layout List | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 | 3/3 | **12/18** | 11.3s |

**Baseline (from layout_name_test.md):** 6/18 (33.3%)

**P1 failure detail:** gemma3:4b returned `TITLE_COVER` (the role label from Step 1) as the layout_name for cover/title_slide, instead of `TITLE_SLIDE`. The model hallucinated the intermediate role label as the final answer — a known risk of multi-step prompts with small models.

**P3 failure detail:** gemma3:4b chose `CONTENT_WITH_PHOTO` for academic_content and bullet_list slides (all 6 runs). The CoT prompt's mention of "content" as a slide type caused the model to mis-associate with `CONTENT_WITH_PHOTO` layout name.

**P4 failure detail:** gemma3:4b chose `TITLE_SLIDE` for section_header slides (all 3 runs). With a reduced layout list, it could not distinguish "section divider with no body" from "title/cover slide." It also reverted to TITLE_AND_BODY bias for cover/title_slide.

**P2 success:** All 18/18 correct. The negative constraint "DO NOT use TITLE_AND_BODY for opening cover slides" directly forced the correct TITLE_SLIDE choice. The explicit positive rules for each slide type were simple enough for the 4B model to follow without hallucination.

---

### 4.2 `ministral-3:14b-cloud` (cloud, 14B parameters)

| Prompt | cover/title | academic | section_header | bullet_list | closing | quote | **Overall** | Avg Elapsed |
|---|---|---|---|---|---|---|---|---|
| P1 Decision-Tree Routing | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.9s |
| P2 Negative Examples | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.1s |
| P3 Chain-of-Thought | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.0s |
| P4 Minimal Layout List | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 1.9s |

**Baseline (from layout_name_test.md):** 12/18 (66.7%)

All 4 prompts achieved perfect 18/18. The model also showed a preference for `項目符號` over `TITLE_AND_BODY` for bullet-point content slides across P1, P3, P4 — demonstrating it understands Chinese-named layouts when prompted clearly. P4 produced the fastest latency (1.9s avg) due to the shorter prompt with fewer tokens.

---

### 4.3 `gpt-oss:20b-cloud` (cloud, 20B parameters, think mode always on)

| Prompt | cover/title | academic | section_header | bullet_list | closing | quote | **Overall** | Avg Elapsed |
|---|---|---|---|---|---|---|---|---|
| P1 Decision-Tree Routing | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.8s |
| P2 Negative Examples | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.8s |
| P3 Chain-of-Thought | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **18/18** | 2.7s |
| P4 Minimal Layout List | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 1/3 | **16/18** | 2.8s |

**Baseline (from layout_name_test.md):** 10/18 (55.6%)

**P4 failure detail:** For quote_slide, run 2 was a parse failure ("Could not extract json string from output") and run 3 chose `TITLE_AND_BODY`. The reduced layout list in P4 coincided with a parse instability — likely the model's think-mode reasoning conflicted with the structured output format under a shorter/simpler prompt. Run 1 correctly chose `QUOTE`.

P1, P2, and P3 all achieved 18/18. The think mode (always active, cannot be disabled per `test_cloud_models.md`) did not impair performance — the internal reasoning may have helped on the harder slide types.

---

### 4.4 Cross-Model Summary

| Model | Prompt | Appropriate Rate | Success Rate | Avg Elapsed |
|---|---|---|---|---|
| `gemma3:4b` | P1 Decision-Tree Routing | 15/18 | 18/18 | 11.7s |
| `gemma3:4b` | P2 Negative Examples | **18/18** | 18/18 | 11.6s |
| `gemma3:4b` | P3 Chain-of-Thought | 12/18 | 18/18 | 11.7s |
| `gemma3:4b` | P4 Minimal Layout List | 12/18 | 18/18 | 11.3s |
| `ministral-3:14b-cloud` | P1 Decision-Tree Routing | **18/18** | 18/18 | 2.9s |
| `ministral-3:14b-cloud` | P2 Negative Examples | **18/18** | 18/18 | 2.1s |
| `ministral-3:14b-cloud` | P3 Chain-of-Thought | **18/18** | 18/18 | 2.0s |
| `ministral-3:14b-cloud` | P4 Minimal Layout List | **18/18** | 18/18 | 1.9s |
| `gpt-oss:20b-cloud` | P1 Decision-Tree Routing | **18/18** | 18/18 | 2.8s |
| `gpt-oss:20b-cloud` | P2 Negative Examples | **18/18** | 18/18 | 2.8s |
| `gpt-oss:20b-cloud` | P3 Chain-of-Thought | **18/18** | 18/18 | 2.7s |
| `gpt-oss:20b-cloud` | P4 Minimal Layout List | 16/18 | 17/18 | 2.8s |

**Slide-type breakdown (appropriate rate across all models and all prompts):**

| Slide Type | gemma3:4b (best) | ministral-3:14b-cloud (best) | gpt-oss:20b-cloud (best) |
|---|---|---|---|
| `cover/title_slide` | 3/3 (P2,P3) | 3/3 (all) | 3/3 (all) |
| `academic_content` | 3/3 (P1,P2,P4) | 3/3 (all) | 3/3 (all) |
| `section_header` | 3/3 (P1,P2,P3) | 3/3 (all) | 3/3 (all) |
| `bullet_list` | 3/3 (P1,P2,P4) | 3/3 (all) | 3/3 (all) |
| `closing_slide` | 3/3 (P1,P2,P3,P4) | 3/3 (all) | 3/3 (all) |
| `quote_slide` | 3/3 (P1,P2,P3,P4) | 3/3 (all) | 3/3 (P1,P2,P3) |

---

## 5. Analysis

### 5.1 What Worked Best Per Model

**`gemma3:4b`:**
- **Best: P2 Negative Examples — 18/18 (100%)** — the only prompt achieving perfect score
- Worst: P3 Chain-of-Thought and P4 Minimal Layout List — both 12/18 (67%)
- The 4B model benefits most from direct, explicit "DO NOT use X" rules. It struggles with multi-step reasoning (P1, P3) where intermediate labels can be hallucinated as final answers.

**`ministral-3:14b-cloud`:**
- **All prompts: 18/18 (100%)** — completely robust across all strategies
- Fastest with P4 Minimal Layout List (1.9s avg) vs 2.9s for P1
- The 14B model has sufficient layout comprehension that any of the 4 prompts achieves perfect accuracy.

**`gpt-oss:20b-cloud`:**
- **Best: P1, P2, P3 — all 18/18 (100%)**
- Worst: P4 Minimal Layout List — 16/18 with 1 parse failure
- The think mode may have interfered with structured output parsing in the shorter P4 prompt

### 5.2 Failure Mode Analysis

**gemma3:4b + P1 Decision-Tree:**
- Returned `TITLE_COVER` (a role label) as the layout name instead of `TITLE_SLIDE`
- Root cause: A 4B model cannot reliably maintain a two-step "classify then map" chain. It follows step 1 (classifying role) but collapses steps 1+2 by outputting the role label as the final layout.
- Lesson: Multi-step prompts with labeled intermediate outputs are risky for small models — the labels leak into the output field.

**gemma3:4b + P3 Chain-of-Thought:**
- Chose `CONTENT_WITH_PHOTO` for academic_content and bullet_list slides (6/6 runs)
- Root cause: The CoT prompt includes "content" as a slide type. `gemma3:4b` associated "content" with `CONTENT_WITH_PHOTO` layout — a name collision between the CoT vocabulary and the layout name.
- Lesson: CoT classification labels must not overlap with layout names for small models. Renaming the content category to "body_text" or "bullet_points" would likely fix this.

**gemma3:4b + P4 Minimal Layout:**
- Chose `TITLE_SLIDE` for section_header (all 3 runs)
- Root cause: With only 6 layouts and no negative examples, the model conflated "no body text" (section header) with "title slide" (also no body). The reduced list eliminated the disambiguation guardrails.

**gpt-oss:20b-cloud + P4 Minimal Layout (quote_slide):**
- 1 parse failure + 1 wrong choice out of 3 runs
- Root cause: The shorter minimal-layout prompt may provide fewer anchoring tokens for the think-mode model's reasoning, leading to occasional output format corruption.

### 5.3 Comparison with Baseline

| Condition | Baseline (layout_name_test.md) | Best this experiment | Improvement |
|---|---|---|---|
| `gemma3:4b` | 6/18 (33.3%) | 18/18 (100%) with P2 | +67pp |
| `ministral-3:14b-cloud` | 12/18 (66.7%) | 18/18 (100%) with any prompt | +33pp |
| `gpt-oss:20b-cloud` | 10/18 (55.6%) | 18/18 (100%) with P1/P2/P3 | +44pp |

All three models improved substantially. The biggest gain was `gemma3:4b`: from 6/18 (extreme TITLE_AND_BODY bias) to 18/18 with the Negative Examples prompt.

### 5.4 Do Cloud Models Outperform Local?

With the right prompt:
- `ministral-3:14b-cloud` and `gpt-oss:20b-cloud` achieve 100% on P1/P2/P3 — they are robust across multiple prompt strategies.
- `gemma3:4b` achieves 100% only on P2 — it is prompt-sensitive and fragile; wrong prompt structure triggers hallucination.

Cloud models are **more reliable** (not just higher accuracy, but also more consistent across prompts). Local `gemma3:4b` can match cloud accuracy with the right prompt, but has no tolerance for suboptimal prompt design.

### 5.5 Which Slide Types Are Hardest

Previous baseline: cover/title_slide and closing_slide were universally hard (0/9 each).

With the new prompts, **all 6 slide types are solved** for ministral-3:14b-cloud and for gpt-oss:20b-cloud (with P1/P2/P3). For gemma3:4b, the residual difficulty is:
- cover/title_slide: fails on P1 (label hallucination) and P4 (reverting to TITLE_AND_BODY bias without negative constraints)
- academic_content + bullet_list: fails on P3 (CONTENT_WITH_PHOTO confusion)
- section_header: fails on P4 (confused with TITLE_SLIDE when list is minimal)

The fundamental finding is that **small models (4B) require negative constraints to stay on-task**, while larger models can correctly interpret multiple reasoning styles.

---

## 6. Recommendations

### 6.1 Production Prompt

**Recommended prompt: P2 Negative Examples**

Rationale:
1. Only prompt to achieve 18/18 on `gemma3:4b` (the weakest local model)
2. Achieves 18/18 on both cloud models (P2 and others do equally well)
3. No multi-step reasoning = no hallucination of intermediate labels
4. Clear explicit rules are easy to maintain and extend (add new slide types with a new "USE X when" block)
5. Fast latency for ministral (2.1s avg vs P1's 2.9s)

### 6.2 Recommended Model + Prompt Combination

**For production deployment:**

| Priority | Model | Prompt | Appropriate Rate | Avg Latency | Notes |
|---|---|---|---|---|---|
| **Primary** | `ollama/ministral-3:14b-cloud` | P2 Negative Examples | 18/18 | 2.1s | Best latency + perfect accuracy |
| **Fallback** | `ollama/gpt-oss:20b-cloud` | P2 Negative Examples | 18/18 | 2.8s | Think mode always on; reliable |
| **Local only** | `ollama/gemma3:4b` | P2 Negative Examples | 18/18 | 11.6s | Acceptable for offline/air-gapped; slower |

**Production config (primary):**
```python
MODEL = {
    "name": "ollama/ministral-3:14b-cloud",
    "additional_kwargs": {},
}
llm = LiteLLM(model=MODEL["name"], temperature=0.1, max_tokens=2048)
program = LLMTextCompletionProgram.from_defaults(
    llm=llm,
    output_cls=SlideOutlineWithLayout,
    prompt_template_str=PROMPT_2_NEGATIVE_EXAMPLES,
    verbose=False,
)
```

### 6.3 Updating `AUGMENT_LAYOUT_PMT` in Production

The current `AUGMENT_LAYOUT_PMT` in `/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/backend/prompts/prompts.py` still uses the baseline approach. To deploy the improvement:
1. Replace `AUGMENT_LAYOUT_PMT` with the P2 Negative Examples prompt (full text in `layout_prompt_eng_test.py` → `PROMPT_2_NEGATIVE_EXAMPLES`).
2. Keep `{available_layout_names}` and `{available_layouts}` template variables — these are still populated dynamically from the template file.
3. Keep `{slide_content}` variable.
4. No changes needed to `SlideOutlineWithLayout` schema or `LLMTextCompletionProgram` setup.

### 6.4 Caveats and Limitations

1. **N_RUNS = 3 per cell**: Small sample size. The 18/18 perfect scores should be validated with N=10 before deploying to production. Partial results (e.g., gpt-oss P4 quote_slide 1/3) need more runs to determine if they are statistical noise.

2. **6 slide types**: Only covers the most common academic slide patterns. Edge cases like agenda slides, statistical result slides, image-caption slides, and comparison tables are not tested. Add them before production sign-off.

3. **gemma3:4b P2 18/18 result**: This is a significant improvement from baseline 6/18. However, given the model's demonstrated sensitivity (hallucinating role labels in P1, misidentifying layouts in P3 and P4), the 100% result on P2 should be verified with a larger N before trusting it in production.

4. **Chinese layout names**: `項目符號` is now being chosen correctly by all models under prompts that describe it in English ("bullet list layout"). This is an improvement over the baseline where Chinese-named layouts were ignored. However, `照片 - 一頁三張` and `空白` are still never chosen — they may need English alias descriptions if they are ever needed in the pipeline.

### 6.5 Further Improvements

1. **Combine P2 + P3**: Test a hybrid prompt that includes both negative constraints (P2 style) AND chain-of-thought classification (P3 style). The combination may generalize better to unseen slide types.

2. **Fix P3 for gemma3:4b**: Rename CoT classification labels to avoid collision with layout names (e.g. use "cover_page" instead of "content" for the label that maps to CONTENT_WITH_PHOTO). This might bring P3 to 18/18 for small models.

3. **Expand test suite**: Add edge cases — agenda/TOC slides, statistical/chart slides, definition/glossary slides, two-column comparison slides.

4. **Validate on real paper outlines**: The current test cases are artificial. Run the same prompts on actual paper summaries to verify generalization.

---

## 7. File Index

| File | Location | Description |
|---|---|---|
| `layout_prompt_eng_test.py` | `poc/agent-behavior-test/` | This experiment's test script — 4 prompts × 3 models × 6 slide types × 3 runs |
| `layout_prompt_eng_output.txt` | `poc/agent-behavior-test/` | Full console output from the test run |
| `layout_prompt_eng_results.json` | `poc/agent-behavior-test/` | Raw JSON with all 216 run results |
| `layout_name_test.md` | `poc/agent-behavior-test/` | Report on baseline single-prompt test (this experiment's baseline) |
| `layout_name_test_v2.py` | `poc/agent-behavior-test/` | Baseline test script (3 models, baseline prompt, 18 runs each) |
| `layout_name_test_v2_output.txt` | `poc/agent-behavior-test/` | Baseline test output |
| `augment-results.md` | `poc/agent-behavior-test/` | Structured output method comparison (FunctionCallingProgram vs LLMTextCompletionProgram) |
| `test_cloud_models.md` | `poc/agent-behavior-test/` | Cloud model capability audit (think mode, function calling) |
| `prompts.py` | `backend/prompts/` | Current `AUGMENT_LAYOUT_PMT` — replace with P2 Negative Examples for production |
| `schemas.py` | `backend/agent_workflows/` | `SlideOutlineWithLayout` Pydantic schema |
| `tools.py` | `backend/utils/` | `get_all_layouts_info()` — reads layout metadata from PPTX template |
| `template-en.pptx` | `assets/` | PPTX template with 12 layouts used in all experiments |

---

## Appendix: Key Prompt Text

### P2 Negative Examples (Recommended Production Prompt)

```
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

USE TITLE_AND_BODY or 項目符號 when:
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
```

---

*Report generated 2026-03-29. 所有實驗在 MacBook M1 chip 執行，gemma3:4b 為本機模型，ministral 和 gpt-oss 為 Ollama cloud routing。*
