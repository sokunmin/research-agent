# Layout Name Comprehension Test — Report

**Date:** 2026-03-29
**Test script:** `layout_name_test_v2.py`
**Results file:** `layout_name_test_v2_results.json`
**Output log:** `layout_name_test_v2_output.txt`

---

## 1. Experiment Overview

### Purpose

This experiment evaluates whether three LLMs can correctly select the appropriate PPTX slide layout given slide content (title + body text). Layout selection is a critical step in the research agent's PPTX generation pipeline: when converting an academic paper outline into slides, the agent must choose from 12 available layouts (e.g., `TITLE_SLIDE`, `SECTION_HEADER_CENTER`, `QUOTE`, `TITLE_AND_BODY`) based purely on the slide's semantic role.

A model that always defaults to `TITLE_AND_BODY` for every slide type will produce visually uniform, low-quality presentations — all slides look the same, missing title slides, section breaks, and quote highlights. The goal is to find which model best understands these layout semantics.

### Why This Matters

The PPTX generation pipeline uses `LLMTextCompletionProgram` (LlamaIndex's structured output method) to call the LLM and parse its response into a `SlideOutlineWithLayout` Pydantic object. If the model cannot correctly identify the layout type, the resulting PPTX will use structurally wrong layouts, degrading presentation quality regardless of content quality.

---

## 2. Setup

### Template File

**File:** `/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/assets/template-en.pptx`

### Available Layouts

Layouts are read dynamically from the template file via `get_all_layouts_info()` — they are never hardcoded. The template contains **12 layouts**:

| # | Layout Name |
|---|---|
| 1 | `TITLE_SLIDE` |
| 2 | `TITLE_AND_BODY` |
| 3 | `QUOTE` |
| 4 | `PHOTO_LANDSCAPE` |
| 5 | `SECTION_HEADER_CENTER` |
| 6 | `PHOTO_PORTRAIT` |
| 7 | `SECTION_HEADER_TOP` |
| 8 | `CONTENT_WITH_PHOTO` |
| 9 | `項目符號` |
| 10 | `照片 - 一頁三張` |
| 11 | `FULL_PHOTO` |
| 12 | `空白` |

### Method

**Method:** `LLMTextCompletionProgram` (LlamaIndex) — also referred to as METHOD_B.

This method sends the prompt as a text completion request to the LLM. The LLM's output is then parsed into a `SlideOutlineWithLayout` Pydantic object using LlamaIndex's text-based extraction (not function calling). The `LLMTextCompletionProgram` uses the model's text completion capability, so it works even for models that do not support the tool_calls API format.

### `SlideOutlineWithLayout` Schema

```python
class SlideOutlineWithLayout(BaseModel):
    title: str                    # slide title (verbatim copy from input)
    content: str                  # slide body text (verbatim copy from input)
    layout_name: str              # chosen layout name (must be in available list)
    idx_title_placeholder: str    # numeric index of title placeholder (as string)
    idx_content_placeholder: str  # numeric index of content placeholder (as string)
```

### Prompt (AUGMENT_LAYOUT_PMT)

The following prompt is used for all models and all slide types (no model-specific prompt tuning):

```
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
```

### Run Configuration

- **N_RUNS:** 3 per (model × slide_type)
- **Temperature:** 0.1
- **max_tokens:** 2048
- **Execution:** Sequential only (no asyncio.gather — Ollama does not support parallel inference)
- **gemma3:4b:** Results loaded from `layout_name_test_results.json` (prior run with identical test cases) — no re-inference

---

## 3. Models Tested

| Model Label | LiteLLM Model Name | Provider | additional_kwargs | Notes |
|---|---|---|---|---|
| `gemma3:4b` | `ollama/gemma3:4b` | Ollama (local) | `{}` | Local 4B model, baseline |
| `ministral-3:14b-cloud` | `ollama/ministral-3:14b-cloud` | Ollama → Mistral cloud | `{}` | Cloud-routed 14B, no think mode |
| `gpt-oss:20b-cloud` | `ollama/gpt-oss:20b-cloud` | Ollama → OpenAI cloud | `{}` | Cloud-routed 20B, think mode always on (cannot be disabled) |

**Notes on model config:**
- All three models use the `ollama/` prefix as the litellm provider identifier. For cloud models, Ollama acts as a transparent proxy routing requests to the upstream cloud provider.
- `gpt-oss:20b-cloud` always runs in think mode regardless of `think=False` being set (per `test_cloud_models.md` findings). No `extra_body` is passed — the model's internal reasoning is accepted as-is.
- `ministral-3:14b-cloud` has no think mode. No special kwargs needed.
- Config was taken exactly from `test_cloud_models.py` MODELS_TO_TRY entries.

---

## 4. Slide Test Cases

| Label | Title | Content (truncated) | Expected Layout(s) | Rationale |
|---|---|---|---|---|
| `cover/title_slide` | "Attention Is All You Need" | "A Research Presentation\nPresented by: John Smith" | `TITLE_SLIDE` | Opening/cover slide with author attribution |
| `academic_content` | "Transformer Architecture" | "* Key Approach: Self-attention mechanism..." (4 bullets) | `TITLE_AND_BODY` or `項目符號` | Standard academic content with bullet points |
| `section_header` | "Chapter 2: Methodology" | "" (empty body) | `SECTION_HEADER_CENTER` or `SECTION_HEADER_TOP` | Chapter transition with no body text |
| `bullet_list` | "Key Findings" | "* 15% improvement in BLEU score..." (4 bullets) | `項目符號` or `TITLE_AND_BODY` | Pure bullet list content |
| `closing_slide` | "Thank You" | "Questions and Discussion\nContact: research@example.com" | `TITLE_SLIDE` or `SECTION_HEADER_CENTER` | Closing/acknowledgement slide |
| `quote_slide` | "Inspiration" | `"The measure of intelligence is the ability to change." — Albert Einstein` | `QUOTE` | Attributed quote, not body text |

**Notes on expected layouts:**
- `academic_content` and `bullet_list` both accept `TITLE_AND_BODY` or `項目符號` because both layouts are functionally appropriate for bullet point content.
- `cover/title_slide` and `closing_slide` require layouts without a content body placeholder (`TITLE_SLIDE`, `SECTION_HEADER_CENTER`) — choosing `TITLE_AND_BODY` forces a content body where there should be none or minimal text.
- `quote_slide` requires `QUOTE` specifically — this is the only layout designed for large-text quote formatting.
- `section_header` requires one of the two section header layouts — choosing `TITLE_AND_BODY` creates a content area for a slide that has no body content.

---

## 5. Results per Model

### 5.1 `gemma3:4b` (local, 4B parameters)

Results loaded from `layout_name_test_results.json` (prior run, identical test cases confirmed).

| Slide Type | Expected Layout(s) | Run 1 | Run 2 | Run 3 | Appropriate Rate | Avg Elapsed |
|---|---|---|---|---|---|---|
| `cover/title_slide` | `TITLE_SLIDE` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 9.7s |
| `academic_content` | `TITLE_AND_BODY` / `項目符號` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 9.0s |
| `section_header` | `SECTION_HEADER_CENTER` / `SECTION_HEADER_TOP` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 7.9s |
| `bullet_list` | `TITLE_AND_BODY` / `項目符號` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 9.1s |
| `closing_slide` | `TITLE_SLIDE` / `SECTION_HEADER_CENTER` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 8.2s |
| `quote_slide` | `QUOTE` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 8.7s |

**Overall success rate:** 18/18 (all responses were valid, parseable `SlideOutlineWithLayout` objects)
**Overall appropriate rate:** 6/18 (33.3%)
**Avg elapsed per call:** 8.8s

**Verdict per slide type:**
- `cover/title_slide`: INCORRECT — chose `TITLE_AND_BODY` all 3 runs
- `academic_content`: CORRECT all 3 runs
- `section_header`: INCORRECT — chose `TITLE_AND_BODY` all 3 runs
- `bullet_list`: CORRECT all 3 runs
- `closing_slide`: INCORRECT — chose `TITLE_AND_BODY` all 3 runs
- `quote_slide`: INCORRECT — chose `TITLE_AND_BODY` all 3 runs

---

### 5.2 `ministral-3:14b-cloud` (cloud, 14B parameters)

| Slide Type | Expected Layout(s) | Run 1 | Run 2 | Run 3 | Appropriate Rate | Avg Elapsed |
|---|---|---|---|---|---|---|
| `cover/title_slide` | `TITLE_SLIDE` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 3.3s |
| `academic_content` | `TITLE_AND_BODY` / `項目符號` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 3.1s |
| `section_header` | `SECTION_HEADER_CENTER` / `SECTION_HEADER_TOP` | `SECTION_HEADER_TOP` | `SECTION_HEADER_TOP` | `SECTION_HEADER_TOP` | 3/3 | 2.5s |
| `bullet_list` | `TITLE_AND_BODY` / `項目符號` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 2.8s |
| `closing_slide` | `TITLE_SLIDE` / `SECTION_HEADER_CENTER` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 2.7s |
| `quote_slide` | `QUOTE` | `QUOTE` | `QUOTE` | `QUOTE` | 3/3 | 2.7s |

**Overall success rate:** 18/18
**Overall appropriate rate:** 12/18 (66.7%)
**Avg elapsed per call:** 2.8s

**Verdict per slide type:**
- `cover/title_slide`: INCORRECT — chose `TITLE_AND_BODY` all 3 runs
- `academic_content`: CORRECT all 3 runs
- `section_header`: CORRECT all 3 runs (chose `SECTION_HEADER_TOP` consistently)
- `bullet_list`: CORRECT all 3 runs
- `closing_slide`: INCORRECT — chose `TITLE_AND_BODY` all 3 runs
- `quote_slide`: CORRECT all 3 runs (chose `QUOTE` consistently)

---

### 5.3 `gpt-oss:20b-cloud` (cloud, 20B parameters)

| Slide Type | Expected Layout(s) | Run 1 | Run 2 | Run 3 | Appropriate Rate | Avg Elapsed |
|---|---|---|---|---|---|---|
| `cover/title_slide` | `TITLE_SLIDE` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 2.1s |
| `academic_content` | `TITLE_AND_BODY` / `項目符號` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 2.5s |
| `section_header` | `SECTION_HEADER_CENTER` / `SECTION_HEADER_TOP` | `TITLE_AND_BODY` | `SECTION_HEADER_TOP` | `SECTION_HEADER_TOP` | 2/3 | 3.2s |
| `bullet_list` | `TITLE_AND_BODY` / `項目符號` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 3/3 | 2.0s |
| `closing_slide` | `TITLE_SLIDE` / `SECTION_HEADER_CENTER` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | `TITLE_AND_BODY` | 0/3 | 3.1s |
| `quote_slide` | `QUOTE` | `TITLE_AND_BODY` | `QUOTE` | `QUOTE` | 2/3 | 2.3s |

**Overall success rate:** 18/18
**Overall appropriate rate:** 10/18 (55.6%)
**Avg elapsed per call:** 2.5s

**Verdict per slide type:**
- `cover/title_slide`: INCORRECT — chose `TITLE_AND_BODY` all 3 runs
- `academic_content`: CORRECT all 3 runs
- `section_header`: PARTIAL — 2/3 correct (chose `TITLE_AND_BODY` on run 1, `SECTION_HEADER_TOP` on runs 2 and 3)
- `bullet_list`: CORRECT all 3 runs
- `closing_slide`: INCORRECT — chose `TITLE_AND_BODY` all 3 runs
- `quote_slide`: PARTIAL — 2/3 correct (chose `TITLE_AND_BODY` on run 1, `QUOTE` on runs 2 and 3)

---

## 6. Cross-Model Comparison

| Model | Parameters | Provider | Overall Success Rate | Overall Appropriate Rate | Avg Elapsed (s) | Notes |
|---|---|---|---|---|---|---|
| `gemma3:4b` | 4B | Local Ollama | 18/18 (100%) | 6/18 (33.3%) | 8.8s | Extreme TITLE_AND_BODY bias |
| `gpt-oss:20b-cloud` | 20B | Ollama → cloud | 18/18 (100%) | 10/18 (55.6%) | 2.5s | Think mode always on |
| `ministral-3:14b-cloud` | 14B | Ollama → cloud | 18/18 (100%) | 12/18 (66.7%) | 2.8s | Best appropriate rate |

**Slide-type breakdown (appropriate rate per model):**

| Slide Type | `gemma3:4b` | `ministral-3:14b-cloud` | `gpt-oss:20b-cloud` |
|---|---|---|---|
| `cover/title_slide` | 0/3 | 0/3 | 0/3 |
| `academic_content` | 3/3 | 3/3 | 3/3 |
| `section_header` | 0/3 | 3/3 | 2/3 |
| `bullet_list` | 3/3 | 3/3 | 3/3 |
| `closing_slide` | 0/3 | 0/3 | 0/3 |
| `quote_slide` | 0/3 | 3/3 | 2/3 |
| **Total** | **6/18** | **12/18** | **10/18** |

---

## 7. Analysis

### 7.1 Which Slide Types Are Handled Correctly

**Universally correct (all 3 models, all 3 runs):**
- `academic_content` — All models chose `TITLE_AND_BODY`, which is appropriate. This is the simplest case: standard content slides with bullet points are the most common slide type, and all models default to `TITLE_AND_BODY` naturally.
- `bullet_list` — Same as above; `TITLE_AND_BODY` is an accepted answer.

**Correctly handled by only larger models (`ministral-3:14b-cloud`):**
- `section_header` — `ministral-3:14b-cloud` chose `SECTION_HEADER_TOP` consistently (3/3). `gpt-oss:20b-cloud` chose `SECTION_HEADER_TOP` in 2/3 runs (failed on run 1 with `TITLE_AND_BODY`). `gemma3:4b` failed all 3 runs.
- `quote_slide` — `ministral-3:14b-cloud` chose `QUOTE` consistently (3/3). `gpt-oss:20b-cloud` chose `QUOTE` in 2/3 runs (failed on run 1 with `TITLE_AND_BODY`). `gemma3:4b` failed all 3 runs.

**Universally incorrect (all 3 models fail):**
- `cover/title_slide` — All models chose `TITLE_AND_BODY` instead of `TITLE_SLIDE` across all 9 runs. No model recognized the cover/title slide pattern.
- `closing_slide` — All models chose `TITLE_AND_BODY` instead of `TITLE_SLIDE` or `SECTION_HEADER_CENTER` across all 9 runs.

### 7.2 What Each Model Picks When Wrong

All three models use `TITLE_AND_BODY` as their default fallback for every incorrectly classified slide type. There is no variety in errors — the failure mode is always the same: `TITLE_AND_BODY`.

- `gemma3:4b` chose `TITLE_AND_BODY` for all 18 runs without a single exception.
- `ministral-3:14b-cloud` chose `TITLE_AND_BODY` for its 6 incorrect runs (`cover/title_slide` ×3, `closing_slide` ×3).
- `gpt-oss:20b-cloud` chose `TITLE_AND_BODY` for its 8 incorrect/partial runs.

### 7.3 TITLE_AND_BODY Bias

`TITLE_AND_BODY` bias is present in all three models and is the dominant failure mode. However, the severity differs significantly by model:

| Model | `TITLE_AND_BODY` chosen count (out of 18 runs) | Appropriate `TITLE_AND_BODY` uses | Inappropriate uses |
|---|---|---|---|
| `gemma3:4b` | 18/18 (100%) | 6 (academic_content + bullet_list) | 12 |
| `ministral-3:14b-cloud` | 9/18 (50%) | 6 | 3 |
| `gpt-oss:20b-cloud` | 11/18 (61%) | 6 | 5 |

`gemma3:4b` defaults to `TITLE_AND_BODY` for every single slide type with complete consistency, indicating it has essentially no layout discrimination capability beyond identifying content slides. `ministral-3:14b-cloud` reduces inappropriate `TITLE_AND_BODY` use to 3 cases (only `cover/title_slide` and `closing_slide`). `gpt-oss:20b-cloud` falls between the two, with inconsistent layout discrimination for `section_header` and `quote_slide`.

### 7.4 Does Model Size Correlate with Appropriate Layout Selection?

Within this experiment, model size partially correlates with appropriate rate:

- 4B (gemma3:4b): 6/18 = 33.3%
- 14B (ministral-3:14b-cloud): 12/18 = 66.7%
- 20B (gpt-oss:20b-cloud): 10/18 = 55.6%

The 14B model outperforms the 20B model, which means raw parameter count is not the sole determinant. The differences may be due to: (1) model architecture and training data composition, (2) `gpt-oss:20b-cloud` always running in think mode which may alter its text completion behavior through `LLMTextCompletionProgram`, or (3) prompt sensitivity differences between the Mistral and GPT-OSS model families.

### 7.5 Latency

- `gemma3:4b`: avg 8.8s per call. This is local inference on an M1 chip — the model runs entirely on-device.
- `ministral-3:14b-cloud`: avg 2.8s per call. Cloud routing adds network latency but the 14B model is faster than local 4B due to the cloud provider's hardware.
- `gpt-oss:20b-cloud`: avg 2.5s per call. Fastest despite being largest — cloud provider has substantial GPU capacity. Think mode latency is absorbed by the cloud-side hardware.

### 7.6 `cover/title_slide` and `closing_slide` — Universal Failure

The two universally failed cases share a pattern: they are slides where the semantic role ("this is the opening slide" / "this is the closing slide") is conveyed by context rather than explicit layout keywords in the content. The title "Thank You" and the subtitle "Questions and Discussion" do not strongly signal a specific layout to the models. The cover slide ("Attention Is All You Need" + "A Research Presentation") looks like a normal content slide to models that do not attend carefully to the "Presented by:" author attribution pattern.

This suggests that the current prompt does not give models enough guidance to distinguish cover/closing slides from content slides. The instruction "closing/thank-you slide" exists in the prompt's example list but is not sufficiently emphasized for models to override the `TITLE_AND_BODY` default.

---

## 8. Recommendations

### 8.1 Model Recommendation

For layout selection in the PPTX generation pipeline, **`ollama/ministral-3:14b-cloud` is the strongest candidate** based on the data:

- Appropriate rate: 12/18 (66.7%) — highest of the three models tested
- No `TITLE_AND_BODY` bias for `section_header` (3/3 correct) or `quote_slide` (3/3 correct)
- Consistent: never produced partial correct results — slide types were either 0/3 or 3/3, indicating stable behavior
- Latency: 2.8s avg — acceptable for non-real-time generation
- No think mode overhead — straightforward text completion behavior

`gpt-oss:20b-cloud` (10/18, 55.6%) is second. Its inconsistency on `section_header` and `quote_slide` (2/3 each, not 3/3) makes it less reliable for production use where deterministic layout selection is preferred.

`gemma3:4b` (6/18, 33.3%) is not suitable for layout selection in its current form. It cannot distinguish non-content slides (title, section headers, quote, closing) from content slides.

### 8.2 Residual Problem: cover/title_slide and closing_slide

All three models fail `cover/title_slide` and `closing_slide` uniformly (0/9 total across all models). This is a prompt engineering problem rather than a model capability problem. The following additions to the AUGMENT_LAYOUT_PMT prompt are worth testing:

1. **Explicit semantic role hints in the slide schema** — Add a `slide_role` field to the input (values: "cover", "section_break", "content", "closing", "quote") and let the upstream outline generator populate it. The layout selector can then use this field directly.

2. **Explicit layout usage examples** — Add to the prompt: "If the slide title is 'Thank You', 'Conclusion', or similar closing phrasing, and the content is minimal (contact info or acknowledgements only), use TITLE_SLIDE or SECTION_HEADER_CENTER rather than TITLE_AND_BODY."

3. **One-shot examples in the prompt** — Prepend a few (slide_content → correct layout_name) pairs directly in the prompt to demonstrate the cover and closing slide cases.

### 8.3 Layout Name Disambiguation

The layout list contains mixed-language names (`項目符號`, `照片 - 一頁三張`, `空白`). All three models appear to ignore these non-ASCII layouts entirely — no model ever chose any of them. This may be because the English-only models do not associate traditional Chinese layout names with any slide type. If these layouts need to be used, their Chinese names should be either translated in the template file or the prompt should include explicit English descriptions of what each Chinese-named layout is for.

### 8.4 Production Configuration

If deploying `ministral-3:14b-cloud` for layout selection:

```python
MODEL = {
    "name": "ollama/ministral-3:14b-cloud",
    "additional_kwargs": {},
}
llm = LiteLLM(model=MODEL["name"], temperature=0.1, max_tokens=2048)
```

- `temperature=0.1` is appropriate given the deterministic nature of layout classification.
- `max_tokens=2048` is sufficient (responses are compact JSON-like structured outputs).
- No `extra_body` or `additional_kwargs` needed — the model has no think mode.
- Add fallback logic: if the returned `layout_name` is not in `VALID_LAYOUT_NAMES`, default to `TITLE_AND_BODY` and log a warning.

### 8.5 Re-testing Scope

The current test suite has 6 slide types with 3 runs each (18 total per model). Before making a production decision, consider expanding to:
- At least 10 slide types including more edge cases (agenda/TOC slides, image-caption slides, statistical result slides)
- N_RUNS = 5 to better characterize partial-correct models like `gpt-oss:20b-cloud`
- Testing `ollama/ministral-3:14b-cloud` with the modified prompts described in §8.2 to see if cover/closing accuracy improves
