# Research Agent

An end-to-end system that takes a research topic, discovers relevant academic
papers via OpenAlex, summarizes them, and auto-generates a PowerPoint
presentation. Built on LlamaIndex event-driven workflows with Human-in-the-Loop
support and real-time streaming via Server-Sent Events.

This repository is a fork of
[lz-chen/research-agent](https://github.com/lz-chen/research-agent) (last updated May 2025). Original author's articles: [Part 1](https://medium.com/data-science/how-i-streamline-my-research-and-presentation-with-llamaindex-workflows-3d75a9a10564) · [Part 2](https://medium.com/data-science/building-an-interactive-ui-for-llamaindex-workflows-842dd7abedde).

## 📺 Demo Video
[![Research Agent Demo](https://img.youtube.com/vi/9haxpPmvc_o/0.jpg)](https://www.youtube.com/watch?v=9haxpPmvc_o)
> *Watch the Research Agent in action: from topic input to final slide generation.*

## 🔍 Table of Contents
- [System Architecture](#system-architecture)
- [What I Changed and Why](#what-i-changed-and-why)
- [Experiments](#experiments)
  - [Paper Discovery Pipeline](#experiments--paper-discovery-pipeline)
  - [Slide Generation Pipeline](#experiments--slide-generation-pipeline)
- [Setup](#setup)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Roadmap](#roadmap)

---

## System Architecture
> **Development hardware:** MacBook M1 (16 GB unified memory) — all local model
> inference and experiments in this repository run on this machine.

```
  Original (lz-chen)                        My Implementation
  ────────────────────────────────          ──────────────────────────────────

┌─────────────────────────── PAPER DISCOVERY ───────────────────────────-─────┐
│                                                                             │
│  ┌── 1. PAPER RETRIEVAL ────────────────────────────────────────────────┐   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ Tavily Search                    │ OpenAlex Retrieval (BM25)         │   │
│  │ → Semantic Scholar Discovery     │ + Metadata Quality Filters        │   │
│  │   (Two-stage Discovery)           │ (One-stage Discovery)             │   │
│  │                                  │ Deterministic                     │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌── 2. RE-RANKING & VERIFICATION ─────────────────────────────────────┐    │
│  ├──────────────────────────────────┬──────────────────────────────────┤    │
│  │ GPT-4o scores every candidate    │ ① Local Embedding Re-scoring     │   │
│  │ (single LLM, no pre-filter)      │ ② LLM Verification (Strict)      │   │
│  │                                  │                                   │   │
│  │                                  │ F1=0.974 · Precision=1.000        │   │
│  │                                  │ 3.3× faster than LLM-only         │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌── 3. PDF ACQUISITION & PARSING ───────────────────────────────────-──┐   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ LlamaParse (cloud-only,          │ Download: 4-strategy fallback     │   │
│  │ credit-based)                    │ (ArXiv → URL → pyalex → OA)       │   │
│  │                                  │ Parsing: Docling (local, planned) │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌── 4. SUMMARIZATION ───────────────────────────────────────────────-──┐   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ GPT-4o (Azure OpenAI)            │ Any LLM via LiteLLM               │   │
│  │                                  │ Extracts: content · authors · year│   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────── SLIDE GENERATION ─────────────────────────────-──┐
│                                                                             │
│  ┌── 5. SLIDE OUTLINE + HUMAN-IN-THE-LOOP ───────────────────────────-──┐   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ GPT-4o: 1 outline per paper      │ Local LLM: 1 title slide          │   │
│  │ FunctionCallingProgram           │           + 4 content slides      │   │
│  │ HITL: approve / reject           │ LLMTextCompletionProgram          │   │
│  │                                  │ HITL: approve / give feedback     │   │
│  │                                  │ → Layout selection by LLM         │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌── 6. PPTX RENDERING ─────────────────-───────────────────────────────┐   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ ReActAgent (GPT-4o)              │ LLM → schema-validated JSON       │   │
│  │ → writes python-pptx code        │ Deterministic renderer            │   │
│  │ → executes in Azure sandbox      │ → PPTX (no LLM · no sandbox)      │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌── 7. SLIDE VALIDATION & FIX ──────────────────────────-──────────────┐   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ Azure VLM: valid / invalid       │ VLM classifies failure type:      │   │
│  │ → ReActAgent rewrites code       │ content_too_long → LLM trims      │   │
│  │                                  │ content_missing  → re-render      │   │
│  │                                  │ visual_overlap   → Python adjusts │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
                           << final .pptx + .pdf >>
```

**Stack:** Python · FastAPI · LlamaIndex 0.14 · LiteLLM · Ollama · MLflow · Streamlit

---

## What I Changed and Why

**1. Unblocked development — LlamaIndex 0.12 → 0.14 full migration**  
The forked codebase was frozen: LlamaIndex's breaking API changes across
workflow, agent, and tool layers prevented any further work. Migrated the
entire codebase as a prerequisite for all changes below.

**2. Optimized Retrieval & Re-ranking Pipeline**  
- *Problem:* The original **two-stage discovery** (Tavily → Semantic Scholar) suffered from an 80% candidate loss due to web-scraped title mismatches and non-deterministic results.
- *Fix:* Transitioned to **One-stage OpenAlex Standalone Discovery** (BM25 + native Semantic Search) + Local Embedding Re-scoring + Selective LLM Verification.
- *Result:* F1=0.974, Precision=1.000 · 3.3× faster · Fully deterministic retrieval pool.

**3. Replaced LLM code generation with deterministic rendering**  
- *Problem:* ReActAgent (GPT-4o) generated python-pptx code at runtime. After switching to local 4B models, systematic prompt engineering (48 LLM calls, 4 variants) brought static correctness from 8% → 100% — but end-to-end pipeline runs still showed non-deterministic failures when rendering complex nested slide structures, undetectable by visual validation.
- *Fix:* LLM outputs schema-validated JSON only; a deterministic Python renderer constructs the PPTX directly
- *Result:* Eliminates runtime unpredictability regardless of model size

**4. Identified correct structured output method per schema complexity**  
- *Problem:* FunctionCallingProgram returns the schema definition itself on all tested local Ollama models (0% success rate)
- *Fix:* LLMTextCompletionProgram for complex nested schemas; Ollama grammar-constrained decoding for flat schemas
- *Result:* 0% → 100% structured output reliability

**5. Typed error routing for slide validation**  
- *Problem:* VLM could only return valid/invalid — no actionable signal for downstream fix logic
- *Fix:* Three-way failure classification routes each issue to the correct fix path: `content_too_long` → LLM trims JSON · `content_missing` → re-render · `visual_overlap` → Python adjusts placeholder position

**6. Provider-agnostic inference layer**  
Designed `ModelFactory` backed by LiteLLM; any LLM or VLM switched via `.env` only. Custom `LiteLLMMultiModal` class bridges LiteLLM's API with LlamaIndex's multimodal workflow layer, with automatic fallback on rate-limit errors. MLflow auto-logging tracks cost, token usage, and latency on every LLM call.

**7. PDF parser evaluation**  
Evaluated LlamaParse (rejected: cloud-only, credit-based), marker-pdf (rejected: 12–18 min/paper on M1 due to PyTorch MPS lacking FlashAttention), and selected Docling for its native Apple MLX support. Full evaluation notes in the experiments section.

---


## Experiments

All experiments were run locally on an Apple MacBook M1 (16 GB unified memory).
LLM and embedding models were served locally via Ollama using Apple Metal.
Reported times reflect M1 execution and should not be treated as estimates for
GPU server or cloud deployments.

---

### Experiments — Paper Discovery Pipeline

The four experiments below designed and validated each stage of the replacement
paper discovery pipeline:

```
Research Topic
      │
      ▼
 [Exp 1] Which OpenAlex search method?
 Can it fully replace Tavily?
      │  ~100 candidate papers
      ▼
 [Exp 2] How to filter relevant papers?
 Which architecture achieves best F1/speed?
      │  ~10–20 relevant papers
      ▼
 [Exp 3] What cosine score threshold routes
 papers to LLM verification in production?
      │
      ▼
 [Exp 4] Can open-access papers be
 reliably downloaded?
      │
      ▼
  Markdown text → Summary & Slide Generation
```

---

#### Experiment 1 — Retrieval Method Comparison & Tavily Replacement

**Goal:** Determine whether the original Tavily + Semantic Scholar path can be fully replaced by OpenAlex and identify the optimal retrieval method.

> ✅ **In current pipeline** — OpenAlex BM25 search with metadata filtering is the primary retrieval method, replacing the two-stage Tavily path entirely.

**Why the original design was structurally fragile:**

```
Path A — Original (Tavily + SS):           Path B — Replacement (OpenAlex):

Tavily web search                        OpenAlex semantic search
      │                                        │
      │  ← 80% title match failure rate        │
      │   (4/5 titles: wrong or no record)     │  quality filters
      ▼                                        │  (OA status / citations / year)
Semantic Scholar ID Mapping                    ▼
      │                                  Two-stage relevance filter
      │  ← seed quality determines all         │
      ▼                                        ▼
LLM relevance filter                     Relevant papers

Two-stage serial chain —                 One-stage discovery, deterministic,
any failure breaks the pipeline          no external dependency
```

**Three OpenAlex search methods compared** (same topic, 25 results each):

| Search method | Relevant papers | Relevance rate | ArXiv availability |
|---|---|---|---|
| Keyword match (title + abstract) | 15 / 25 | 60% | 12% |
| BM25 full-text | 13 / 25 | 52% | 24% |
| Semantic (embedding-based) | **17 / 25** | **68%** | **36%** |

Semantic search returns a completely disjoint result set from keyword/BM25
(0% overlap) — the three methods are complementary rather than redundant.

**Head-to-head pipeline comparison across 5 research domains**
(NLP, Distributed Systems, RL, Computer Vision, Biomedical):

| | Path A: Tavily + citation expansion | Path B: OpenAlex direct |
|---|---|---|
| Domains reaching ≥ 10 relevant papers | 2 / 5 | 2 / 5 |
| Total relevant papers found | 53 | **64 (+20.8%)** |
| Domains returning zero candidates | **1 / 5** (flagship NLP topic fails) | **0 / 5** |
| Deterministic results | No | Yes |
| External paid API required | Yes (Tavily) | No |

**Decision:** Replace Tavily + Semantic Scholar with OpenAlex standalone. Path B
retrieves 20.8% more relevant papers, fails on zero domains, and removes all
paid API dependencies.

> → Full report: [experiments/01-openalex-paper-discovery/search_method_comparison.md](experiments/01-openalex-paper-discovery/search_method_comparison.md)

---

#### Experiment 2 — Re-ranking & Verification Pipeline

**Goal:** Design a two-stage pipeline to re-rank retrieved candidates and verify their relevance using a cost-effective combination of embedding similarity and LLM judgment.

> ✅ **In current pipeline** — Two-stage re-ranking and verification (`nomic-embed-text` Stage 1 + LLM Stage 2) is the primary relevance filtering step.

**Dataset:** 120 papers manually labelled for *"attention mechanism in
transformer models"* — 60 relevant, 60 irrelevant.

**Four architectures compared:**

| Approach | Description | F1 | Precision | Recall | Time (s) |
|---|---|---|---|---|---|
| Keyword match | Title-level lexical match only | 0.847 | 0.862 | 0.833 | 0.0 |
| Standalone LLM | 2B model classifies each paper | 0.739 | 0.804 | 0.683 | 85.2 |
| Standalone embedding | Cosine similarity, paper vs topic | 0.861 | 0.766 | 0.983 | 127.8 |
| **Two-stage (selected)** | **Embedding pre-screen + LLM** | **0.974** | **1.000** | **0.950** | **26.0** |

The standalone LLM (F1 = 0.739) underperforms even the simple keyword baseline
(F1 = 0.847) — a 2B model does not reliably generalise relevance judgement
from zero-shot prompts alone.

**How the two-stage design achieves better accuracy at lower cost:**

```
All 120 papers
       │
       ▼
Stage 1: nomic-embed-text cosine similarity  (~22s for 120 papers)
       │
       ├── score > 0.610 ──────────────────→  ✅ Relevant
       │                                       (~58% of corpus, no LLM call)
       │
       ├── score 0.500–0.610 ──→  Stage 2: LLM strict prompt  (~4s)
       │   (ambiguous zone)              │
       │                                ├──→  ✅ Relevant
       │                                └──→  ❌ Rejected
       │                                       (~42% of corpus sent to LLM)
       │
       └── score < 0.500 ──────────────────→  ❌ Rejected
                                               (~0% of corpus, no LLM call)

Result: F1 = 0.974 · Precision = 1.000 · Recall = 0.950
        3.3× faster than standalone LLM · ~58% of papers skip the LLM entirely
```

**Three key findings from the ablation study:**

**Finding 1 — Chain-of-Thought prompting degrades small model performance**

| Prompt | F1 | Precision | Recall |
|---|---|---|---|
| Standard | 0.739 | 0.804 | 0.683 |
| Chain-of-Thought | 0.604 | 0.806 | 0.483 |

Adding CoT to a 2B model drops F1 by 13.5 points. Precision is unchanged;
recall collapses. Small models are harmed, not helped, by extended reasoning
chains.

**Finding 2 — Embedding model recall vs compute trade-off**

| Model | Parameters | F1 | Recall | Time (s) |
|---|---|---|---|---|
| nomic-embed-text | ~300M | 0.832 | 0.950 | 22.2 |
| qwen3-embedding:0.6b | 0.6B | 0.813 | 0.833 | 38.4 |
| qwen3-embedding:4b | 4B | 0.861 | 0.983 | 116.8 |

Scaling from 0.6B to 4B improves recall by 15 points but costs 3× more
compute. nomic-embed-text achieves the best recall-to-cost ratio and is
selected for Stage 1.

**Finding 3 — Stage-1 model choice matters more than Stage-2 prompt tuning**

Stage 2 can filter out bad results, but it can't recover papers that Stage 1
already missed. Getting Stage-1 recall right matters more than tuning Stage-2.
nomic-embed-text misses 3 papers vs 8 for qwen3-embedding:0.6b — that gap
directly determines the recall ceiling (0.950 vs 0.917), no matter how well
Stage 2 is tuned.

> → Full report: [experiments/01-openalex-paper-discovery/relevance_filter_ablation.md](experiments/01-openalex-paper-discovery/relevance_filter_ablation.md)

---

#### Experiment 3 — Threshold Analysis for Production Routing

**Goal:** The two-stage filter uses ground-truth labels to decide which papers
go to Stage 2 during experiments. In the actual pipeline, labels are unavailable —
routing must rely solely on the Stage-1 cosine similarity score. This
experiment determines the score band that should trigger Stage-2 LLM review.

> ✅ **In current pipeline** — The `[0.500, 0.610)` band is used by the two-stage filter to route ambiguous papers to LLM review.

ROC analysis on the 120-paper benchmark (AUC = 0.921):

![ROC Curve — nomic-embed-text Stage-1](experiments/01-openalex-paper-discovery/imgs/roc_curve.png)

The score distributions for relevant and irrelevant papers overlap in the range
[0.457, 0.607] — papers in this zone are ambiguous and benefit from LLM review:

![Score Distribution by Label](experiments/01-openalex-paper-discovery/imgs/score_distribution.png)

**Production routing trade-off:**

![Coverage vs Load — Score-Band Routing](experiments/01-openalex-paper-discovery/imgs/coverage_vs_load.png)

| Band sent to Stage-2 LLM | Papers routed | % of corpus | Errors captured |
|---|---|---|---|
| Narrow [0.500, 0.610) | 50 | 41.7% | 87% |
| Wide [0.480, 0.610) | 60 | 50.0% | 91% |
| Full [0.455, 0.610) | 77 | 64.2% | 100% |

**Selected:** [0.500, 0.610) — captures all false positives while keeping
Stage-2 LLM load at 41.7% of corpus. The 3 papers missed in every band cannot
be recovered by Stage 2 regardless of band width, since Stage 1 missed them
entirely.

> → Full report: [experiments/01-openalex-paper-discovery/stage1_threshold_analysis.md](experiments/01-openalex-paper-discovery/stage1_threshold_analysis.md)

---

#### Experiment 4 — PDF Download Reliability

**Goal:** Validate that open-access papers found via OpenAlex can be reliably
downloaded, and identify the correct method for extracting ArXiv IDs.

> ✅ **In current pipeline** — A four-strategy fallback chain with **Browser-mimicking headers** is used to bypass HTTP 403 blocks (e.g., AAAI OJS).

**Quality Gate:** The discovery pipeline only accepts papers with `diamond`, `gold`, or `green` Open Access status to guarantee stable programmatic access.

A four-strategy fallback chain was designed and validated:

```
OpenAlex paper record
        │
        ▼  extract ArXiv ID from locations[].landing_page_url
   ┌────┴────────────────────────────────────────────────┐
   │  Strategy 1: ArXiv API  (arxiv.Client)              │
   │  ── if fail ──────────────────────────────────────  │
   │  Strategy 2: Constructed URL  arxiv.org/pdf/{id}    │
   │  ── if fail ──────────────────────────────────────  │
   │  Strategy 3: pyalex PDF endpoint                    │
   │  ── if fail ──────────────────────────────────────  │
   │  Strategy 4: OpenAlex OA URL                        │
   └─────────────────────────────────────────────────────┘
        │
        ▼
     PDF file
```

Filtering candidates to open-access status (`diamond`/`gold`/`green`) at the
search stage guarantees at least one fallback strategy will succeed for every
paper in the pool.

> → Full report: [experiments/01-openalex-paper-discovery/pdf_download_fallback.md](experiments/01-openalex-paper-discovery/pdf_download_fallback.md)

---

### Experiments — Slide Generation Pipeline

The slide generation pipeline went through a significant architecture change.
The experiments below document the systematic evaluation that informed the
decision to replace LLM code generation with deterministic rendering.

---

#### Experiment 5 — ReAct Agent: Model & Prompt Evaluation

**Goal:** After switching from GPT-4o to local 4B models, identify which model
and prompt strategy produces reliable ReAct agent behavior — and determine
whether the approach is viable for the full pipeline.

> 🚫 **Replaced** — ReActAgent was replaced with deterministic rendering before reaching the full pipeline. These experiments are the evidence trail for that decision.

| Model | Size | Slide generation | Tool calls | Slide modification |
|---|---|---|---|---|
| gemma3:4b | 4B | ✅ Success | **1 call** | ✅ Success |
| qwen3.5:4b | 4B | ✅ Success | 16 calls | ✅ Success |
| gemma3n:e2b | 2B | ❌ Timeout (600s) | 0 | — |
| gemma3n:e4b | 4B | ❌ Incompatible | 0 | — |

**Key findings:**
- Root cause of original failure was prompt ambiguity, not model capability: *"Respond user with the python code"* caused models to output text instead of calling the tool. An explicit directive resolved it.
- Prompt style is task-dependent: the directive that fixes slide generation causes the modification task to fail completely (20-round loop, zero tool calls). Each agent step requires independently designed prompts.
- gemma3n:e4b fails silently: it outputs a Gemini-specific `tool_code` format that LlamaIndex's ReAct parser can't read — the loop just exits at turn 1 with no error, no warning.

> → Full report: [experiments/02-agent-behavior/react_agent_slide_gen.md](experiments/02-agent-behavior/react_agent_slide_gen.md)

---

#### Experiment 6 — Structured Output Method Comparison

**Goal:** Identify a reliable method to extract structured JSON (matching a Pydantic schema) from local Ollama models.

| Method | Where structure is enforced | gemma3:4b | qwen3.5:4b |
|---|---|---|---|
| FunctionCallingProgram | LLM provider's function-calling API | **0%** | **0%** |
| **LLMTextCompletionProgram** | **Client-side Pydantic parser** | **0–100%** | **100%** |
| Ollama format parameter | Ollama server (token-sampling) | 100% | 100% |

**Key Finding:** `FunctionCallingProgram` fails unconditionally on local Ollama models because they return the schema definition itself rather than populated values. While the Ollama `format` parameter is highly robust for flat schemas, it struggles with the complex nested structures required for slide outlines. `LLMTextCompletionProgram` was selected for its superior reliability in multi-level JSON parsing across various model sizes.

> → Full report: [experiments/02-agent-behavior/structured_output_methods.md](experiments/02-agent-behavior/structured_output_methods.md)

---

#### Experiment 7 — Slide Layout Selection

**Goal:** Measure whether LLMs can correctly choose the right PPTX layout
(e.g., `title_slide`, `bullet_list`, `academic_content`) given slide content,
and improve accuracy through prompt design.

> ✅ **In current pipeline** — Negative Examples prompt strategy is used in the `outlines_with_layout` step for layout selection.

**Baseline** — 3 models × 6 slide types × 3 runs = 54 inferences:

| Model | Parameters | Appropriate selections | Avg latency |
|---|---|---|---|
| gemma3:4b (local) | 4B | 6 / 18 **(33%)** | 8.8s |
| gpt-oss:20b (cloud) | 20B | 10 / 18 (56%) | 2.5s |
| ministral-3b (cloud) | 14B | 12 / 18 (67%) | 2.8s |

All three models universally fail on `title_slide` and `closing_slide` — a
systematic bias toward the most common layout regardless of content.

**Prompt engineering** — 4 strategies × 3 models × 6 slide types × 3 runs =
216 inferences:

| Prompt strategy | Description | gemma3:4b | ministral-3b | gpt-oss:20b |
|---|---|---|---|---|
| Decision-tree routing | Explicit if/else layout rules | 83% | 100% | 100% |
| **Negative examples (selected)** | **"Do NOT use X when Y"** | **100%** | **100%** | **100%** |
| Chain-of-Thought | Step-by-step reasoning | 67% | 100% | 100% |
| Minimal layout list | Shortest possible prompt | 67% | 100% | 89% |

The Negative Examples prompt is the only strategy reaching 100% across all
three models including the weakest local 4B model — from 33% to 100% for
gemma3:4b (+67 points). Consistent with the relevance filter finding: CoT
degrades performance on small models.

> → Full report: [experiments/02-agent-behavior/layout_selection_prompt_eng.md](experiments/02-agent-behavior/layout_selection_prompt_eng.md)

---

#### Experiment 8 — ReAct Agent: How a Prompt Example Key Breaks Tool Dispatch in 4B Models

**Goal:** Even with the correct task prompt and best model (gemma3:4b), tool
dispatch still failed. This experiment isolates the ReAct format template as
the failure source and identifies the root cause.

> 🚫 **Replaced** — The fix was valid, but the ReActAgent step was replaced with deterministic rendering before this was deployed. The finding about small-model prompt sensitivity remains transferable.

**Root cause:** The format example in the prompt template contained
`{"input": "hello world"}`. The `run_code` tool expects `code` as its
parameter name. A 4B model uses the example key as a prior — generating
`{"input": ...}` instead of `{"code": ...}` on every call.

**Fix:** Changed the example to `{"code": "print('hello')"} for run_code`.

| Model | Before | After | Delta |
|---|---|---|---|
| gemma3:4b — task completed | 0% | **100%** | +100pp |
| gemma3:4b — avg turns | 9.0 | **3.0** | −67% |
| ministral-3:14b — task completed | 100% | 100% | unchanged |

**Key insight:** For models ≤ 4B, the argument key name in a few-shot format
example has stronger influence on tool call behavior than the tool's own
parameter description. Larger models (14B+) read the tool spec correctly
regardless of example content.

> → Full report: [experiments/02-agent-behavior/slide_gen_react_suffix_eng.md](experiments/02-agent-behavior/slide_gen_react_suffix_eng.md)

---

## Setup

### Prerequisites

- Python >= 3.12
- Poetry
- Docker & Docker Compose
- Ollama (for local model inference)

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd research-agent
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env — set your provider API keys and model names
   ```

3. **Build and start services:**
   ```bash
   docker-compose up --build
   ```

4. **Access the application:**
   - Frontend: `http://localhost:8501`
   - Backend API docs: `http://localhost:8000/docs`

---

## Roadmap

**Docling PDF parsing**  
marker-pdf is not viable on M1: its OCR model requires FlashAttention,
which Apple's Metal GPU backend doesn't support — resulting in 12–18 min/paper
with memory thrashing. Docling uses Apple's MLX
framework natively, bypassing PyTorch MPS entirely. It also provides
full bounding-box coordinates per image block, required for passing
specific figures to a VLM.

**Frontend: Streamlit → Vercel AI SDK**  
Streamlit has no native SSE streaming interface and shows visible
per-token rendering lag. Planned migration to React + Vercel AI SDK
for a proper streaming chat UX.

**RAG pipeline**  
Current summarization uses full-context LLM calls per paper — expensive
in tokens and unable to recall across sessions. Planned: semantic chunking
+ hybrid search (BM25 + vector) + RAGAS evaluation framework, with ablation
across chunking strategies, embedding models, and rerankers.

**Multi-agent orchestration**  
A single ReAct agent has limited reasoning depth for multi-paper synthesis.
Planned: compare ReAct, Reflection, and Reflexion patterns on synthesis
tasks using LLM-as-judge evaluation.
