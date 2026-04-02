# Slide Layout Selection — Comparing Original vs Redesigned Prompts

**Date:** 2026-03-31

---

## Background & Motivation

This experiment is conducted on the purpose of converting research papers into slide decks. For each slide, an LLM selects one of 12 layouts from a PowerPoint template (`assets/template-en.pptx`). The selected layout determines which placeholders exist on the slide — title, content, photo, or none. A wrong layout choice causes structural failures: incorrect placeholder indices, visual errors, or runtime crashes when the slide generator accesses a non-existent placeholder.

The original codebase uses a prompt called `AUGMENT_LAYOUT_PMT` (tested here as P0) for layout selection. It achieved only 44/72 (61.1%) accuracy across both tested models and all 12 slide types. It provides no layout descriptions, no routing rules, and no constraints — biasing models toward `TITLE_AND_BODY` for almost everything. This experiment tests 5 redesigned prompt strategies (P1–P5) against P0 to identify which design best closes the accuracy gap.

The key question: how much of the failure is prompt design, and which prompt strategy works reliably across model sizes?

---

## Experiment Setup

**Method:** LlamaIndex `LLMTextCompletionProgram` for all models and all prompts. `FunctionCallingProgram` (native tool/function calling) explicitly excluded — it fails for all Ollama models, confirmed in a prior experiment.

**Models tested:** `gemma3:4b` (local, 4B parameters, M1 MacBook), `ministral-3:14b-cloud` (cloud, 14B parameters, Ollama routing). A third model (`gpt-oss:20b-cloud`) was unavailable and excluded from this run.

**Run configuration:** 3 runs per (model × prompt × slide type) at temperature 0.1, max_tokens 2048. Sequential execution only — Ollama does not support parallel requests. Total: 2 models × 6 prompts × 12 slide types × 3 runs = **432 inferences** (360 for P1–P5, 72 for P0 run separately).

**Slide types tested:** 12 total — 6 text-content slides (cover/title, academic content, section header, bullet list, closing, quote) and 6 visual/photo slides (photo landscape, photo portrait, content with photo, three photo, full photo, blank).

**Schema fix (prerequisite):** `idx_title_placeholder` and `idx_content_placeholder` in `SlideOutlineWithLayout` changed from required `str` to `Optional[str] = None`, with a `coerce_int_to_str` field validator added. This fix was necessary for layouts with no text placeholders (`THREE_PHOTO`, `FULL_PHOTO`, `BLANK`): the previous required-`str` typing caused immediate Pydantic validation errors when the model returned `null` or an integer for these fields, producing `success=False` regardless of whether `layout_name` was correct. The fix eliminates this confound.

---

## Prompt Strategies Tested (6 total)

**P0 — Original Codebase Baseline (AUGMENT_LAYOUT_PMT)**
Verbatim copy of the prompt from the original forked codebase. Provides a short task description, a list of available layout names, raw template layout details, and a 5-field output instruction. No layout descriptions, no routing rules, no negative constraints. Contains legacy Norwegian text (`"Plassholder for innhold"`) from the original template. Tested here to measure the original prompt's accuracy against the full 12-layout set as a comparison baseline.

**P1 — Descriptions Only**
Adds a `LAYOUT_DESCRIPTIONS` block covering all 12 layouts, each with three sub-fields: **Use for** (presentation purpose), **Structure** (placeholder arrangement), **Signals** (observable text patterns). No additional routing guidance beyond descriptions. Establishes how much layout descriptions alone improve over P0.

**P2 — Decision-Tree Routing**
A 13-step if/then decision tree (STEP 1) classifies the slide into a semantic role (`BLANK`, `FULL_PHOTO`, `THREE_PHOTO`, `TITLE_COVER`, `CONTENT_SLIDE`, etc.) in priority order. A lookup table (STEP 2) maps each role to one or more valid layout names. Tree is evaluated top-down; restrictive conditions appear first, generic fallbacks last. Followed by `LAYOUT_DESCRIPTIONS` for full context.

**P3 — Positive Examples**
One semantic `USE <LAYOUT> when:` rule per layout, describing purpose and content type in natural language. No negative constraints, no decision tree, no reasoning steps. Rules describe intent rather than surface text patterns. Followed by `LAYOUT_DESCRIPTIONS`.

**P4 — Negative Examples**
8 explicit `WRONG: Choosing X when Y — Why wrong: [structural reason]` rules, with no "Use instead:" redirects. The model must derive the correct layout from `LAYOUT_DESCRIPTIONS` after eliminating wrong choices. Rules are grounded in structural signals (empty body, bullet points, image references, attribution lines). Exception clauses distinguish short attribution text from "substantial text" for `TITLE_SLIDE`, and enforce that any text at all disqualifies `BLANK`. Followed by `LAYOUT_DESCRIPTIONS`.

**P5 — Chain-of-Thought**
Asks the model to generate a free-form 4-step reasoning chain before selecting a layout: (1) observe slide content, (2) infer the slide's role, (3) match to a layout from descriptions, (4) verify the chosen name is valid. Not constrained to a pre-defined taxonomy — the model writes its own reasoning grounded in `LAYOUT_DESCRIPTIONS`.

All P1–P5 prompts include the same shared `LAYOUT_DESCRIPTIONS` and `OUTPUT_FIELDS` blocks. P0 is self-contained with its own output instructions and does not use these shared blocks.

---

## Results

### gemma3:4b (local, 4B parameters)

| Prompt | cover/ title | academic | section | bullet | closing | quote | photo_ land | photo_ port | content_ photo | three_ photo | full_ photo | blank | Overall | Avg Elap |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| P0 Original Baseline | 0/3 | 3/3 | 0/3 | 3/3 | 0/3 | 0/3 | 0/3 | 3/3 | 3/3 | 0/3 | 3/3 | 0/3 | **15/36** | 9.5s |
| P1 Descriptions Only | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **33/36** | 11.1s |
| P2 Decision-Tree | 0/3 | 0/3 | 3/3 | 0/3 | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 | **21/36** | 12.4s |
| P3 Positive Examples | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **33/36** | 13.0s |
| P4 Negative Examples | 0/3 | 0/3 | 3/3 | 3/3 | 0/3 | 3/3 | 0/3 | 3/3 | 3/3 | 0/3 | 3/3 | 3/3 | **21/36** | 13.2s |
| P5 Chain-of-Thought | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **30/36** | 12.0s |

**Wrong choices by slide type (gemma3:4b):**

| Slide | P0 | P1 | P2 | P3 | P4 | P5 |
|-------|----|----|----|----|----|----|
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

*`TITLE_COVER`, `CONTENT_SLIDE`, `CLOSING_SLIDE` are not valid template layout names — they are intermediate role labels from the P2 decision tree that gemma3:4b output as the final `layout_name` value.*

`cover/title_slide` fails on every prompt (0/3 × 6 prompts = 0/18). P1, P3, P4, P5 all produce `TITLE_AND_BODY`; P2 produces the invalid name `TITLE_COVER`. This is the only slide type where every prompt fails on gemma3:4b.

### ministral-3:14b-cloud (cloud, 14B parameters)

| Prompt | cover/ title | academic | section | bullet | closing | quote | photo_ land | photo_ port | content_ photo | three_ photo | full_ photo | blank | Overall | Avg Elap |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| P0 Original Baseline | 0/3 | 3/3 | 3/3 | 3/3 | 0/3 | 3/3 | 2/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **29/36** | 2.0s |
| P1 Descriptions Only | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **36/36** | 1.7s |
| P2 Decision-Tree | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **36/36** | 1.6s |
| P3 Positive Examples | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **36/36** | 2.3s |
| P4 Negative Examples | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **36/36** | 2.3s |
| P5 Chain-of-Thought | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | 3/3 | **36/36** | 2.0s |

**P0 wrong choices (ministral-3:14b-cloud):** `cover/title_slide` → `TITLE_AND_BODY`×3; `closing_slide` → `TITLE_AND_BODY`×3; `photo_landscape` → `CONTENT_WITH_PHOTO`×1 (2/3 correct). Zero failures across all 180 P1–P5 calls.

### Cross-Model Summary

| Model | Prompt | Appropriate Rate | Success Rate | Avg Elapsed |
|-------|--------|:----------------:|:------------:|:-----------:|
| gemma3:4b | P0 Original Baseline | **15/36** | 36/36 | 9.5s |
| gemma3:4b | P1 Descriptions Only | **33/36** | 36/36 | 11.1s |
| gemma3:4b | P2 Decision-Tree | **21/36** | 36/36 | 12.4s |
| gemma3:4b | P3 Positive Examples | **33/36** | 36/36 | 13.0s |
| gemma3:4b | P4 Negative Examples | **21/36** | 36/36 | 13.2s |
| gemma3:4b | P5 Chain-of-Thought | **30/36** | 36/36 | 12.0s |
| ministral-3:14b-cloud | P0 Original Baseline | **29/36** | 36/36 | 2.0s |
| ministral-3:14b-cloud | P1 Descriptions Only | **36/36** | 36/36 | 1.7s |
| ministral-3:14b-cloud | P2 Decision-Tree | **36/36** | 36/36 | 1.6s |
| ministral-3:14b-cloud | P3 Positive Examples | **36/36** | 36/36 | 2.3s |
| ministral-3:14b-cloud | P4 Negative Examples | **36/36** | 36/36 | 2.3s |
| ministral-3:14b-cloud | P5 Chain-of-Thought | **36/36** | 36/36 | 2.0s |

**Combined score per prompt (both models):**

| Prompt | Combined | % |
|--------|:--------:|:---:|
| P0 Original Baseline | **44/72** | 61.1% |
| P1 Descriptions Only | **69/72** | 95.8% |
| P2 Decision-Tree | **57/72** | 79.2% |
| P3 Positive Examples | **69/72** | 95.8% |
| P4 Negative Examples | **57/72** | 79.2% |
| P5 Chain-of-Thought | **66/72** | 91.7% |

**Improvement over P0:**

| Model | P0 (original) | Best redesigned prompt | Improvement |
|-------|:-------------:|:---------------------:|:-----------:|
| gemma3:4b | 15/36 (41.7%) | 33/36 (91.7%) — P1 or P3 | +50 percentage points |
| ministral-3:14b-cloud | 29/36 (80.6%) | 36/36 (100%) — any P1–P5 | +19 percentage points |

---

## Key Findings

- **Adding layout descriptions (P1) produces the single largest accuracy jump.** Moving from P0 to P1 alone closes most of the gap: gemma3:4b goes from 15/36 to 33/36 (+18 calls, +50pp); ministral from 29/36 to 36/36 (+7 calls, +19pp). The structured `LAYOUT_DESCRIPTIONS` block — not routing rules or negative constraints — is the dominant improvement over the original prompt.

- **P1 and P3 are the best prompts for gemma3:4b (tied at 33/36).** All additional routing guidance (P2–P5) does not uniformly improve over descriptions-only for the 4B model. P2 Decision-Tree and P4 Negative Examples are worse than P1 for gemma3:4b and introduce new failure modes.

- **ministral-3:14b-cloud achieves 100% on all engineered prompts (P1–P5).** Between-prompt variance for the 14B model is entirely driven by P0 vs the rest. All P1–P5 prompts are equivalent for this model on this test set.

- **P2 Decision-Tree uniquely introduces invalid layout names for gemma3:4b.** The 4B model collapses the two-step classify-then-map chain, outputting intermediate role labels (`TITLE_COVER`, `CONTENT_SLIDE`, `CLOSING_SLIDE`) as the final `layout_name` — names not present in the template. This failure mode does not occur in any other prompt.

- **P4 Negative Examples backfires for gemma3:4b.** The rules against `TITLE_AND_BODY` redirect the model to unexpected alternatives: `CONTENT_WITH_PHOTO` for academic content, photo landscape, and three-photo slides; `BULLET_LIST` for closing slides. The 4B model cannot navigate the elimination-based reasoning P4 requires.

- **`cover/title_slide` is the only slide type that gemma3:4b fails on every prompt (0/18).** No prompt strategy tested here resolves this failure for the 4B model. All non-P2 prompts produce `TITLE_AND_BODY`; P2 produces the invalid name `TITLE_COVER`. This represents a fundamental limit of the 4B model for this slide type without further prompt work.

- **`photo_portrait` and `content_with_photo` are the easiest slide types (36/36 across both models and all 6 prompts).** These layouts have unambiguous structural signals — headshot reference or mixed text+figure reference — that models of all sizes handle correctly.

- **The schema fix eliminated all Pydantic validation errors.** `success_rate = 36/36` for every model and every prompt, including P0 which has no null instruction for placeholder index fields. The `Optional[str] = None` change and `coerce_int_to_str` validator absorbed whatever the model returned for index fields on no-placeholder layouts, allowing layout name accuracy to be evaluated without validation noise.

- **Prompt complexity inversely correlates with gemma3:4b accuracy.** Ranked by score for gemma3:4b: P1=P3 (33/36) > P5 (30/36) > P2=P4 (21/36) > P0 (15/36). Simpler strategies (descriptions, positive rules) outperform complex ones (decision trees, negative constraints, chain-of-thought) for the 4B model.

---

## Decision

**P3 (Positive Examples) is the recommended replacement for the original `AUGMENT_LAYOUT_PMT`.**

P1 (Descriptions Only) and P3 (Positive Examples) are tied on accuracy (33/36 for gemma3:4b, 36/36 for ministral-3:14b-cloud, 69/72 combined). P3 is preferred over P1 on the basis of semantic clarity: each explicit `USE <LAYOUT> when:` rule grounds the model in the presentation intent of the layout rather than relying solely on the description block. For ministral-3:14b-cloud, both achieve 36/36; for gemma3:4b, both achieve 33/36 with the same failure on `cover/title_slide`. P3's additional semantic rules may also generalise better across paper types not represented in the test set.

P5 Chain-of-Thought (66/72 combined) is a viable alternative if reasoning transparency is valued at the cost of slightly higher latency (12.0s avg for gemma3:4b vs 13.0s for P3 — comparable). P2 and P4 should not be used with gemma3:4b.

**Recommended model + prompt combinations:**

| Priority | Model | Prompt | Appropriate Rate | Avg Latency |
|----------|-------|--------|:----------------:|:-----------:|
| Primary | `ollama/ministral-3:14b-cloud` | P3 Positive Examples | 36/36 | 2.3s |
| Local-only / offline | `ollama/gemma3:4b` | P3 Positive Examples | 33/36 | 13.0s |
