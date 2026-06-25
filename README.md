# Research Agent

An end-to-end system that takes a research topic, discovers relevant academic
papers via OpenAlex, summarizes them, and auto-generates a PowerPoint
presentation. Built on LlamaIndex event-driven workflows with Human-in-the-Loop
support and real-time streaming via Server-Sent Events.

This repository is a fork of
[lz-chen/research-agent](https://github.com/lz-chen/research-agent) (last updated May 2025). Original author's articles: [Part 1](https://medium.com/data-science/how-i-streamline-my-research-and-presentation-with-llamaindex-workflows-3d75a9a10564) · [Part 2](https://medium.com/data-science/building-an-interactive-ui-for-llamaindex-workflows-842dd7abedde).

## 📺 YouTube Demo Video
[![Research Agent Demo](https://img.youtube.com/vi/FSkvngrjDIQ/maxresdefault.jpg)](https://youtu.be/FSkvngrjDIQ)
> *Click the image to [watch on YouTube](https://youtu.be/FSkvngrjDIQ) — end-to-end: topic input to final slide generation.*

## 🔍 Table of Contents
- [System Architecture](#system-architecture)
- [Experiments](#experiments)
  - [Paper Discovery Pipeline](#experiments--paper-discovery-pipeline)
  - [Slide Generation Pipeline](#experiments--slide-generation-pipeline)
  - [RAG Summarization Pipeline](#experiments--rag-summarization-pipeline)
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

┌─────────────────────────── PAPER DISCOVERY ─────────────────────────────────┐
│                                                                             │
│  ┌── 0. QUERY UNDERSTANDING ────────────────────────────────────────────┐   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ (Not implemented in original)    │ Supervisor                        │   │
│  │                                  │ intent check → route / reject     │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌── 1. PAPER RETRIEVAL ────────────────────────────────────────────────┐   │
│  │                                              Validated by: Exp 1, 5  │   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ Tavily Search                    │ ① Query Transformation           │   │
│  │ → Semantic Scholar Discovery     │   clean_topic + year/citation     │   │
│  │   (Two-stage Discovery)          │   constraints extracted           │   │
│  │   Non-deterministic              ├───────────────────────────────────┤   │
│  │                                  │ ② OpenAlex Retrieval (BM25)      │   │
│  │                                  │   + Metadata Quality Filters      │   │
│  │                                  │   Deterministic                   │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌── 2. RE-RANKING & VERIFICATION ──────────────────────────────────────┐   │
│  │                                              Validated by: Exp 2, 3  │   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ GPT-4o scores every candidate    │ ① Local Embedding Re-scoring     │   │
│  │ (single LLM, no pre-filter)      │ ② LLM Verification (Strict)      │   │
│  │                                  │                                   │   │
│  │                                  │ F1=0.974 · Precision=1.000        │   │
│  │                                  │ 3.3× faster than LLM-only         │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌── 3. PDF ACQUISITION & PARSING ──────────────────────────────────────┐   │
│  │                                                 Validated by: Exp 4  │   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ arxiv library (ArXiv ID          │ Download: 4-strategy fallback     │   │
│  │ required; no fallback)           │ (ArXiv → URL → pyalex → OA)       │   │
│  │ Parsing: marker-pdf              │ Parsing: Docling                  │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
│                                     │                                       │
│                                     ▼                                       │
│  ┌── 4. SUMMARIZATION ──────────────────────────────────────────────────┐   │
│  │                                       Validated by: Exp 11, 12, 13   │   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ GPT-4o (Azure OpenAI)            │ Docling → HybridChunker           │   │
│  │                                  │ + ChunkFilter → Qdrant BM25       │   │
│  │                                  │ 9 fixed queries → LLM summary     │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────── SLIDE GENERATION ─────────────────────────────-──┐
│                                                                             │
│  ┌── 5. SLIDE OUTLINE + HUMAN-IN-THE-LOOP ──────────────────────────────┐   │
│  │                                              Validated by: Exp 6, 7  │   │
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
│  │                                          Validated by: Exp 8, 9, 10  │   │
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
│                                     │                                       │
│                                     ▼                                       │
│  ┌── 8. FINAL OUTPUT ───────────────────────────────────────────────────┐   │
│  ├──────────────────────────────────┬───────────────────────────────────┤   │
│  │ 1 slide per paper                │ N slides per paper (configurable  │   │
│  │ final.pptx + final.pdf           │ via SLIDES_PER_PAPER, default 4)  │   │
│  │                                  │ final.pptx + final.pdf            │   │
│  └──────────────────────────────────┴───────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Stack:** Python · FastAPI · LlamaIndex 0.14 · LiteLLM · Ollama · MLflow · Next.js · Vercel AI SDK

**Frontend:** Replaced Streamlit with Next.js + Vercel AI SDK — SSE streaming with typed custom data parts delivers real-time workflow progress without polling, and a canvas layout (chat thread + artifact preview) supports inline HITL review.

**Backend:** Reformatted `/run-slide-gen` SSE endpoint to AI SDK UIMessageStream v5 wire format — typed `data-*` events with `transient` flag enable direct browser consumption without a proxy layer.

---



## Experiments

- [Paper Discovery Pipeline](#experiments--paper-discovery-pipeline)
  - [Exp 1 — Retrieval Method Comparison & Tavily Replacement](#experiment-1--retrieval-method-comparison--tavily-replacement---2026-03-16)
  - [Exp 2 — Re-ranking & Verification Pipeline](#experiment-2--re-ranking--verification-pipeline---2026-03-17)
  - [Exp 3 — Threshold Analysis for System Routing](#experiment-3--threshold-analysis-for-system-routing---2026-03-17)
  - [Exp 4 — PDF Download Reliability](#experiment-4--pdf-download-reliability---2026-03-18)
  - [Exp 5 — Query Transformation for BM25 Retrieval](#experiment-5--query-transformation-for-bm25-retrieval---2026-05-14)
- [Slide Generation Pipeline](#experiments--slide-generation-pipeline)
  - [Exp 6 — Structured Output Method Comparison](#experiment-6--structured-output-method-comparison---2026-03-28)
  - [Exp 7 — Slide Layout Selection](#experiment-7--slide-layout-selection---2026-04-02)
  - [Exp 8 — ReAct Agent: Model & Prompt Evaluation](#experiment-8--react-agent-model--prompt-evaluation---2026-03-27)
  - [Exp 9 — ReAct Agent: Task Prompt Engineering for PPTX Code Generation](#experiment-9--react-agent-task-prompt-engineering-for-pptx-code-generation---2026-04-05)
  - [Exp 10 — ReAct Agent: How a Prompt Example Key Breaks Tool Dispatch in 4B Models](#experiment-10--react-agent-how-a-prompt-example-key-breaks-tool-dispatch-in-4b-models---2026-04-07)
- [RAG Summarization Pipeline](#experiments--rag-summarization-pipeline)
  - [Exp 11 — PDF Chunking and Boilerplate Filtering](#experiment-11--pdf-chunking-and-boilerplate-filtering---2026-06-11)
  - [Exp 12 — Retrieval Strategy Comparison](#experiment-12--retrieval-strategy-comparison---2026-06-17)
  - [Exp 13 — VLM vs RAG Summarization](#experiment-13--vlm-vs-rag-summarization---2026-06-22)

---

### Experiments — Paper Discovery Pipeline

The four experiments below designed and validated each stage of the replacement
paper discovery pipeline:

```
Research Topic
      │
      ▼
 [Exp 5] How to clean the query for BM25?
 LLM extracts topic + year/citation constraints
      │  clean_topic, year_window, min_citations
      ▼
 [Exp 1] Which OpenAlex search method?
 Can it fully replace Tavily?
      │  ~100 candidate papers
      ▼
 [Exp 2] How to filter relevant papers?
 Which architecture achieves best F1/speed?
      │  ~10–20 relevant papers
      ▼
 [Exp 3] Determining the optimal score threshold for Stage-2 LLM escalation.
      │
      ▼
 [Exp 4] Can open-access papers be 
 reliably downloaded?
      │
      ▼
  Markdown text → Summary & Slide Generation
```

---

#### Experiment 1 — Retrieval Method Comparison & Tavily Replacement   (2026-03-16)

**System Architecture:** Step 1 — Paper Retrieval

| | Path A: Tavily + citation expansion | Path B: OpenAlex direct |
|---|---|---|
| Domains reaching ≥ 10 relevant papers | 2 / 5 | 2 / 5 |
| Total relevant papers found | 53 | **64 (+20.8%)** |
| Domains returning zero candidates | **1 / 5** (flagship NLP topic fails) | **0 / 5** |
| Deterministic results | No | Yes |
| External paid API required | Yes (Tavily) | No |

- *Problem:* The original Tavily → Semantic Scholar path loses 80% of candidates to title-match failures — one of five tested domains returns zero papers entirely.
- *Change:* Replaced with direct OpenAlex BM25 search and quality filters applied at retrieval time.
- *Result:* Zero-candidate failure eliminated across all five domains; +20.8% total relevant papers; no paid external API required.

> ✅ **In current pipeline**
> → Full report: [experiments/01-openalex-paper-discovery/01-search_method_comparison.md](experiments/01-openalex-paper-discovery/01-search_method_comparison.md)

---

#### Experiment 2 — Re-ranking & Verification Pipeline   (2026-03-17)

**System Architecture:** Step 2 — Re-ranking & Verification

| Approach | Description | F1 | Precision | Recall | Time (s) |
|---|---|---|---|---|---|
| Keyword match | Title-level lexical match only | 0.847 | 0.862 | 0.833 | 0.0 |
| Standalone LLM | 2B model classifies each paper | 0.739 | 0.804 | 0.683 | 85.2 |
| Standalone embedding | Cosine similarity, paper vs topic | 0.861 | 0.766 | 0.983 | 127.8 |
| **Two-stage (selected)** | **Embedding pre-screen + LLM** | **0.974** | **1.000** | **0.950** | **26.0** |

- *Problem:* lz-chen's LLM-only filter scores every candidate and achieves F1=0.739 — below the simple keyword baseline (F1=0.847).
- *Change:* Two-stage filter: embedding pre-screen skips the LLM for clear cases; LLM verification handles the ambiguous band only.
- *Result:* F1=0.974, Precision=1.000, 3.3× faster; ~58% of papers skip the LLM entirely.

> ✅ **In current pipeline**
> → Full report: [experiments/01-openalex-paper-discovery/02-relevance_filter_ablation.md](experiments/01-openalex-paper-discovery/02-relevance_filter_ablation.md)

---

#### Experiment 3 — Threshold Analysis for System Routing   (2026-03-17)

**System Architecture:** Step 2 — Re-ranking & Verification (routing threshold)

| Band sent to Stage-2 LLM | Papers routed | % of corpus | Errors captured |
|---|---|---|---|
| Narrow [0.500, 0.610) | 50 | 41.7% | 87% |
| Wide [0.480, 0.610) | 60 | 50.0% | 91% |
| Full [0.455, 0.610) | 77 | 64.2% | 100% |

- *Problem:* The two-stage ablation uses oracle routing requiring ground-truth labels — not deployable at inference time where labels are unavailable.
- *Change:* Derived score-band [0.500, 0.610) from ROC analysis on the 120-paper benchmark using only cosine similarity scores.
- *Result:* Identical final output to oracle routing (F1=0.974, Precision=1.000) with no labels required.

> ✅ **In current pipeline**
> → Full report: [experiments/01-openalex-paper-discovery/03-reranking_threshold_analysis.md](experiments/01-openalex-paper-discovery/03-reranking_threshold_analysis.md)

---

#### Experiment 4 — PDF Download Reliability   (2026-03-18)

**System Architecture:** Step 3 — PDF Acquisition & Parsing

- *Problem:* lz-chen's single-strategy download silently drops non-ArXiv papers. OpenAlex buries ArXiv IDs in a nested locations array — not in the top-level IDs field where Semantic Scholar placed them.
- *Change:* Four-strategy fallback chain with OA status pre-filter at retrieval time; ArXiv IDs parsed from location URLs with version suffix stripped.
- *Result:* 5/5 papers downloaded; structural guarantee that every OA-filtered paper has at least one viable download path.

> ✅ **In current pipeline**
> → Full report: [experiments/01-openalex-paper-discovery/04-pdf_download_fallback.md](experiments/01-openalex-paper-discovery/04-pdf_download_fallback.md)

---

#### Experiment 5 — Query Transformation for BM25 Retrieval   (2026-05-14)

**System Architecture:** Step 1 — Paper Retrieval (query transformation sub-step)

| | Strategy A: Raw query | Strategy C: Clean topic + dynamic filters ✅ |
|---|---|---|
| BM25 input | Original user query | LLM-extracted clean_topic |
| Filters | Fixed defaults | LLM-extracted year_window + min_citations |
| mean_sim@20 (median, N=25) | 0.5321 | 0.5557 |
| precision@5 (mean, N=20) | 0.120 | 0.185 |
| A vs C significance | — | p=0.0043 ✓ |

- *Problem:* Raw queries with time or citation constraint phrases cause BM25 to match constraint words as topic terms — median mean_sim@20 = 0.5321 on the 25-query test set.
- *Change:* A single LLM call extracts clean_topic, year_window, and min_citations from the user query; clean_topic replaces the raw query for BM25 search; extracted filter values are applied to OpenAlex quality filters.
- *Result:* median mean_sim@20 +4.4% (p=0.0043); topic cleaning delivers the full retrieval gain; dynamic filters added at zero extra LLM cost to preserve user-expressed constraints.

> ✅ INTEGRATED
> → Full report: [experiments/01-openalex-paper-discovery/05-query_transformation_strategies.md](experiments/01-openalex-paper-discovery/05-query_transformation_strategies.md)

---

### Experiments — Slide Generation Pipeline

The experiments below are the systematic evaluation that led to replacing LLM code generation with deterministic rendering.

---

#### Experiment 6 — Structured Output Method Comparison   (2026-03-28)

**System Architecture:** Step 5 — Slide Outline + HITL (layout selection sub-step)

| Method | Where structure is enforced | gemma3:4b | qwen3.5:4b |
|---|---|---|---|
| FunctionCallingProgram | LLM provider's function-calling API | **0%** | **0%** |
| **LLMTextCompletionProgram** | **Client-side Pydantic parser** | **0–100%** | **100%** |
| Ollama format parameter | Ollama server (grammar-constrained decoding) | 100% | 100% |
| Structured LLM Wrapper | Client-side Pydantic parser | 0–100% | 100% |
| Structured Predict | Client-side Pydantic parser | 0–100% | 100% |

- *Problem:* FunctionCallingProgram (lz-chen's method) fails unconditionally on all tested local Ollama models — 0% success, crashes before inference.
- *Change:* LLMTextCompletionProgram with client-side Pydantic parsing works across all LiteLLM providers including local Ollama.
- *Result:* 0% → 100% structured output reliability.

> ✅ **In current pipeline**
> → Full report: [experiments/02-agent-behavior/06-structured_output_method_comparison.md](experiments/02-agent-behavior/06-structured_output_method_comparison.md)

---

#### Experiment 7 — Slide Layout Selection   (2026-04-02)

**System Architecture:** Step 5 — Slide Outline + HITL (layout selection sub-step)

| Prompt | Design | Combined | gemma3:4b |
|---|---|---|---|
| P0 Original | No descriptions (baseline) | 44/72 (61%) | 15/36 (42%) |
| **P1 Descriptions Only ✅** | **Layout descriptions (Use for / Structure / Signals)** | **69/72 (96%)** | **33/36** |
| P3 Positive Examples | "USE \<LAYOUT\> when:" rules | 69/72 (96%) | 33/36 |
| P5 Chain-of-Thought | 4-step reasoning before selection | 66/72 (92%) | 30/36 |
| P2/P4 Routing/Elimination | Decision-tree or negative rules | 57/72 (79%) | 21/36 |

- *Problem:* The original layout prompt (P0, no descriptions) achieves only 61% accuracy — gemma3:4b picks wrong layouts for one-third of slides.
- *Change:* Added layout descriptions (Use for / Structure / Signals) to the prompt.
- *Result:* 61% → 96% combined accuracy; P3 ties P1 but costs +1.9s per call on small models.

> ✅ **In current pipeline**
> → Full report: [experiments/02-agent-behavior/07-slide_layout_prompt_comparison.md](experiments/02-agent-behavior/07-slide_layout_prompt_comparison.md)

---

⚠️ **Experiments 8–10 form a sequential diagnostic chain** — each experiment fixed one failure layer of the ReActAgent approach, and together they produced the evidence for replacing it with deterministic rendering.

```
Slide outline (from Step 5 HITL)
      │
      ▼
 [Exp 8] Which local model works for the ReActAgent?
 gemma3:4b completes task but generates invalid python-pptx code 8.3% of the time
      │  1 tool call vs 16 for qwen3.5:4b
      ▼
 [Exp 9] Does fixing the task prompt fix code quality?
 P2 (layout lookup + null guard patterns) achieves 100% code correctness
      │  tool dispatch still broken
      ▼
 [Exp 10] Does fixing the tool dispatch suffix fix agent reliability?
 P4 achieves 100% task completion — but python-pptx lacks markdown support
      │  0% → 100% task completion, avg turns 9.0 → 3.0
      ▼
Architectural finding (2026-04-15): python-pptx has no markdown parser —
LLM-generated content collapsed all bullets into one paragraph, `*` appeared
literally on slides. Docker sandbox added latency and infrastructure dependency
on top of non-deterministic code generation.
      │
      ▼
Decision: LLM → List[ParagraphItem] JSON → PptxRenderer (deterministic)
          Eliminates ReActAgent + Docker sandbox entirely
```

---

#### Experiment 8 — ReAct Agent: Model & Prompt Evaluation   (2026-03-27)

**System Architecture:** Step 6 — PPTX Rendering (original ReAct approach, superseded)

| Model | Size | Slide generation | Tool calls | Slide modification |
|---|---|---|---|---|
| gemma3:4b | 4B | ✅ Success | **1 call** | ✅ Success |
| qwen3.5:4b | 4B | ✅ Success | 16 calls | ✅ Success |
| gemma3n:e2b | 2B | ❌ Timeout (600s) | 0 | — |
| gemma3n:e4b | 4B | ❌ Incompatible | 0 | — |

- *Problem:* Switching from GPT-4o to local 4B models breaks the ReAct agent — vague task phrasing causes models to output text instead of calling tools.
- *Change:* Evaluated 4 local models with explicit task directives; gemma3:4b identified as viable with 1 tool call vs 16 for qwen3.5:4b.
- *Result:* Task completes but generated code fails 8.3% of the time — motivating Exp 8.

> 🚫 **Superseded** — replaced with deterministic rendering.
> → Full report: [experiments/02-agent-behavior/08-react_agent_model_prompt_eval.md](experiments/02-agent-behavior/08-react_agent_model_prompt_eval.md)

---

#### Experiment 9 — ReAct Agent: Task Prompt Engineering for PPTX Code Generation   (2026-04-05)

**System Architecture:** Step 6 — PPTX Rendering (original ReAct approach, superseded)

| Prompt | layout% | null% | overall% | Verdict |
|---|---|---|---|---|
| P0 — vague text only (lz-chen baseline) | 8.3% | 91.7% | 8.3% | Baseline |
| P1 — + layout lookup pattern | 100% | 75.0% | 75.0% | Partial |
| **P2 — + null guard pattern** | **100%** | **100%** | **100%** | **Selected** |
| P3 — + import statement | 100% | 100% | 100% | Same as P2, unnecessary |

- *Problem:* lz-chen's original prompt (P0) generates valid code only 8.3% of the time — gemma3:4b copies the style of the provided code example, including what it omits.
- *Change:* Added explicit layout lookup and null guard code patterns to the prompt (P2).
- *Result:* 100% code correctness — but tool dispatch still broken, leading to Exp 9.

> 🚫 **Superseded** — replaced with deterministic rendering.
> → Full report: [experiments/02-agent-behavior/09-react_agent_task_prompt_eval.md](experiments/02-agent-behavior/09-react_agent_task_prompt_eval.md)

---

#### Experiment 10 — ReAct Agent: How a Prompt Example Key Breaks Tool Dispatch in 4B Models   (2026-04-07)

**System Architecture:** Step 6 — PPTX Rendering (original ReAct approach, superseded)

| Model | Before | After | Delta |
|---|---|---|---|
| gemma3:4b — task completed | 0% | **100%** | +100pp |
| gemma3:4b — avg turns | 9.0 | **3.0** | −67% |
| ministral-3:14b — task completed | 100% | 100% | unchanged |

- *Problem:* gemma3:4b dispatches 0% of tool calls with the correct argument key — it copies the example key `"input"` instead of reading the tool's own parameter spec `"code"`.
- *Change:* Changed the format example key from `"input"` to `"code"` in the ReAct template.
- *Result:* 0% → 100% task completion, avg turns 9.0 → 3.0; python-pptx's lack of markdown parsing then drove the decision to replace ReActAgent with deterministic rendering.

> 🚫 **Superseded** — replaced with deterministic rendering.
> → Full report: [experiments/02-agent-behavior/10-react_agent_tool_dispatch_eval.md](experiments/02-agent-behavior/10-react_agent_tool_dispatch_eval.md)

---

### Experiments — RAG Summarization Pipeline

Experiments 11–13 evaluated and replaced the VLM-based summarization path
(PDF pages → images → vision model) with a text-based RAG pipeline:

```
PDF file
      │
      ▼
 [Exp 11] Which chunking strategy and boilerplate filter?
 HybridChunker 512-token wins; ChunkFilter removes 20.9% of chunks with 0 false positives
      │  Recall@5 = 0.61
      ▼
 [Exp 12] Which retrieval strategy?
 BM25 hybrid + query expansion wins over dense-only
      │  Recall@5 = 0.608
      ▼
 [Exp 13] RAG vs VLM summarization quality?
 RAG factuality 0.945 vs VLM 0.787; 16.5× faster
      │
      ▼
  Paper summary → Slide Outline + HITL
```

---

#### Experiment 11 — PDF Chunking and Boilerplate Filtering   (2026-06-11)

**System Architecture:** Step 4 — Summarization (corpus preparation)

| Strategy | Recall@5 | nDCG@5 | Avg chunks/paper |
|---|---|---|---|
| `sentence_splitter` | 0.60 | **0.49** | 36.6 |
| `semantic_splitter` | 0.59 | 0.40 | 43.7 |
| `hierarchical_chunker` | 0.51 | 0.40 | 175.9 |
| `hybrid_chunker_512` ✅ | **0.61** | 0.48 | 79.5 |

ChunkFilter removed 349 of 1,670 chunks (20.9%) — References (92.0%),
Acknowledgements, Ethics sections — with zero false positives across 28 papers.

- *Problem:* No chunking strategy had been validated for academic paper retrieval;
  boilerplate sections inflate the unverifiable claim rate in summaries by +0.036.
- *Change:* Compared four chunking strategies on 100 ground-truth samples; derived
  filter rules from frequency analysis over 1,670 chunks across 28 papers.
- *Result:* `hybrid_chunker_512` achieves Recall@5 = 0.61 — strongest on
  Keyword-heavy (0.73) and Multi-hop (0.81) queries; ChunkFilter drops 20.9%
  of chunks with zero content sections lost.

> ✅ **In current pipeline**
> → Full report: [experiments/03-rag-summarization-pipeline/11-pdf-chunking-and-filtering-pipeline.md](experiments/03-rag-summarization-pipeline/11-pdf-chunking-and-filtering-pipeline.md)

---

#### Experiment 12 — Retrieval Strategy Comparison   (2026-06-17)

**System Architecture:** Step 4 — Summarization (retrieval sub-step)

| Strategy | Recall@5 | nDCG@5 | Latency (s) |
|---|---|---|---|
| Dense only | 0.553 | 0.426 | 131 |
| BM25 hybrid | 0.566 | 0.456 | 246 |
| **BM25 + query expansion** ✅ | **0.608** | **0.487** | 5,212 |
| BM25 + query expansion + reranker | 0.608 | 0.487 | 6,269 |

- *Problem:* Dense-only retrieval (Recall@5 = 0.553) was unvalidated; no sparse
  model had been selected for hybrid search.
- *Change:* Part A selected `Qdrant/bm25` as the sparse model (fastest, no GPU);
  Part B compared 6 retrieval configs on 28 papers across 4 query types.
- *Result:* BM25 hybrid with query expansion achieves Recall@5 = 0.608 — tied
  with the full reranker stack but 1,057s faster per run.

> ✅ **In current pipeline**
> → Full report: [experiments/03-rag-summarization-pipeline/12-retrieval-strategy-comparison.md](experiments/03-rag-summarization-pipeline/12-retrieval-strategy-comparison.md)

---

#### Experiment 13 — VLM vs RAG Summarization   (2026-06-22)

**System Architecture:** Step 4 — Summarization (strategy selection)

| Metric | `vlm` | `rag_fixed_queries` ✅ | `rag_with_expansion` | `rag_winner_no_filter` |
|---|---|---|---|---|
| avg_factuality | 0.787 | **0.945** | 0.889 | 0.925 |
| avg_hallucination_rate | 0.136 | 0.036 | 0.049 | **0.020** |
| avg_latency_s | 242.3 | 14.7 | 36.9 | **13.9** |

- *Problem:* VLM summarization (PDF pages → images → vision model) had never been
  evaluated for factual accuracy; latency of 200–300s per paper on M1 made
  iteration impractical.
- *Change:* Compared 4 strategies on 8 ML papers using `claude-sonnet-4-6` NLI
  classification to score factual accuracy against the full paper text.
- *Result:* `rag_fixed_queries` achieves avg_factuality = 0.945 (+0.158 over
  VLM's 0.787) at 16.5× lower latency (14.7s vs 242.3s); ChunkFilter reduces
  unverifiable claim rate to 1.9%.

> ✅ **In current pipeline**
> → Full report: [experiments/03-rag-summarization-pipeline/13-summarization-comparison.md](experiments/03-rag-summarization-pipeline/13-summarization-comparison.md)

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

**Multi-agent orchestration**  
A single ReAct agent has limited reasoning depth for multi-paper synthesis.
Planned: compare ReAct, Reflection, and Reflexion patterns on synthesis
tasks using LLM-as-judge evaluation.
