# Prompt: Generate Paper-Level Ablation Study

You are a research writing assistant. Using **only the information provided below**, write a complete, self-contained **ablation study section** suitable for inclusion in an academic paper. You have no prior context about this project — everything you need is in this prompt.

---

## Task

Write a paper-level ablation study in English that:
- Systematically analyses the contribution of each design component
- Uses precise, objective academic language
- Includes all necessary tables, observations, and discussion
- Enables a context-free reviewer to understand the experimental differences and their significance

---

## Background

### Problem Definition

The task is **binary relevance classification of academic papers** for automated literature review. Given a research topic and a paper's metadata, a classifier must decide whether the paper is relevant (yes) or not (no).

**Research topic**: *"attention mechanism in transformer models"*

### Dataset

- **Source**: OpenAlex academic paper database
- **Size**: 120 papers — 60 relevant (positive), 60 irrelevant (negative) — **balanced**
- **Labels**: manually verified ground truth
- **Paper metadata fields available**:
  - `title` — paper title
  - `abstract` — full abstract
  - `keywords` — author-provided keywords
  - `topics` — OpenAlex taxonomy topics
  - `primary_topic` — single most representative OpenAlex topic
  - `concepts` — OpenAlex concept tags (hierarchical)

### Models Used

- **LLM**: `qwen3.5:2b` served via Ollama (temperature=0, think=False)
- **Embedding models**: four Ollama-served models evaluated
  - `nomic-embed-text` (referred to as Nomic)
  - `nomic-embed-text-v2-moe` (referred to as Nomic-v2)
  - `qwen3-embedding:0.6b` (referred to as Qwen-S)
  - `qwen3-embedding:4b` (referred to as Qwen-M)
- **Similarity metric**: cosine similarity, threshold = 0.5 (uniform across all embedding experiments)

---

## System Prompts

Three LLM system prompts are used across experiments:

**Prompt-Basic** (no chain-of-thought):
> "You are a research paper relevance classifier. Given a research topic and paper metadata, decide if the paper is relevant. Do not make any assumptions; analyze objectively. Respond with exactly one word: yes or no."

**Prompt-Loose** (domain-specific, no CoT):
> "You are a research paper relevance classifier. Given a research topic and paper metadata, decide if the paper is relevant. Include the paper if its abstract suggests transformers or attention mechanisms are discussed in a substantive way — not merely used as a black-box tool. Respond with exactly one word: yes or no."

**Prompt-Strict** (structured 5-question criteria, no CoT):
> "You are a research paper relevance classifier conducting a literature survey. Research query: 'attention mechanism in transformer models'. A paper is relevant if its core contribution helps answer any of: (1) How does the attention mechanism work or what are its theoretical foundations? (2) How has attention been designed, improved, or made more efficient? (3) What are its known limitations or critical analyses? (4) What motivated alternatives to attention, and how do they relate back? (5) What important capabilities emerge from attention mechanisms, and why? A paper is NOT relevant if it merely uses transformers as a tool, or the connection is incidental. Heuristic: would this paper be cited in a survey on 'attention mechanism in transformer models'? Respond with exactly one word: yes or no."

---

## Experiment Configurations (E01–E15)

### Architecture Types

**Type A — Keyword baseline**: match keywords in title only.

**Type B — Standalone LLM**: call LLM on all 120 papers independently; parallelised with 3 workers.

**Type C — Standalone Embedding**: embed topic string and paper text, compute cosine similarity, threshold at 0.5; run sequentially.

**Type D — Two-Stage**: Stage 1 runs an embedding model on all 120 papers sequentially; Stage 2 runs LLM only on Stage-1 errors (FP + FN); final predictions combine Stage-1 correct + Stage-2 re-judgments.

### Input Fields per Architecture

| Abbreviation | Fields included in text/message |
|---|---|
| Basic | title, abstract, keywords, topics |
| +PT | Basic + primary_topic |
| +PT+C | Basic + primary_topic + concepts |
| +PT (no concepts) | Basic + primary_topic (no concepts) |

### Full Experiment Table

| ID | Name | Type | Embedding Model | LLM Prompt | LLM Input Fields | CoT |
|----|------|------|----------------|-----------|-----------------|-----|
| E01 | KW-Title | A | — | — | title only (keyword match) | — |
| E02 | LLM-Basic | B | — | Prompt-Basic | Basic | No |
| E03 | LLM-Basic-CoT | B | — | Prompt-Basic | Basic | **Yes** |
| E04 | LLM-Extended | B | — | Prompt-Basic | +PT+C | No |
| E05 | Emb-Nomic | C | Nomic | — | Basic | — |
| E06 | Emb-Nomic-v2 | C | Nomic-v2 | — | Basic | — |
| E07 | Emb-Qwen-S | C | Qwen-S | — | Basic | — |
| E08 | Emb-Qwen-M | C | Qwen-M | — | Basic | — |
| E09 | Emb-Qwen-S-Ext | C | Qwen-S | — | +PT+C | — |
| E10 | TS-Qwen-Basic | D | Qwen-S (+PT+C) | Prompt-Basic | +PT+C | No |
| E11 | TS-Qwen-Loose | D | Qwen-S (+PT+C) | Prompt-Loose | +PT+C | No |
| E12 | TS-Qwen-Strict | D | Qwen-S (+PT+C) | Prompt-Strict | +PT+C | No |
| E13 | TS-Nomic-Loose | D | Nomic | Prompt-Loose | +PT+C | No |
| E14 | TS-Nomic-Strict | D | Nomic | Prompt-Strict | +PT+C | No |
| E15 | TS-Nomic-Strict-NoConcepts | D | Nomic | Prompt-Strict | +PT (no concepts) | No |

---

## Experimental Results

All metrics evaluated on the full 120-paper balanced dataset.

| ID | Name | Time (s) | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |
|----|------|---------|----|----|----|----|-----------|--------|----|----------|
| E01 | KW-Title | 0.0 | 50 | 8 | 10 | 52 | 0.862 | 0.833 | 0.847 | 0.850 |
| E02 | LLM-Basic | 72.6 | 41 | 10 | 19 | 50 | 0.804 | 0.683 | 0.739 | 0.758 |
| E03 | LLM-Basic-CoT | 69.5 | 29 | 7 | 31 | 53 | 0.806 | 0.483 | 0.604 | 0.683 |
| E04 | LLM-Extended | 75.8 | 31 | 5 | 29 | 55 | 0.861 | 0.517 | 0.646 | 0.717 |
| E05 | Emb-Nomic | 22.2 | 57 | 20 | 3 | 40 | 0.740 | 0.950 | 0.832 | 0.808 |
| E06 | Emb-Nomic-v2 | 32.9 | 4 | 0 | 56 | 60 | 1.000 | 0.067 | 0.125 | 0.533 |
| E07 | Emb-Qwen-S | 38.4 | 50 | 13 | 10 | 47 | 0.794 | 0.833 | 0.813 | 0.808 |
| E08 | Emb-Qwen-M | 116.8 | 59 | 18 | 1 | 42 | 0.766 | 0.983 | 0.861 | 0.842 |
| E09 | Emb-Qwen-S-Ext | 38.3 | 52 | 13 | 8 | 47 | 0.800 | 0.867 | 0.832 | 0.825 |
| E10 | TS-Qwen-Basic | 21.9 | 53 | 2 | 7 | 58 | 0.964 | 0.883 | 0.922 | 0.925 |
| E11 | TS-Qwen-Loose | 19.4 | 55 | 2 | 5 | 58 | 0.965 | 0.917 | 0.940 | 0.942 |
| E12 | TS-Qwen-Strict | 22.3 | 55 | 0 | 5 | 60 | 1.000 | 0.917 | 0.957 | 0.958 |
| E13 | TS-Nomic-Loose | 21.8 | 57 | 1 | 3 | 59 | 0.983 | 0.950 | 0.966 | 0.967 |
| E14 | TS-Nomic-Strict | 24.8 | 57 | 0 | 3 | 60 | 1.000 | 0.950 | 0.974 | 0.975 |
| E15 | TS-Nomic-Strict-NoConcepts | 27.2 | 57 | 1 | 3 | 59 | 0.983 | 0.950 | 0.966 | 0.967 |

---

## Ablation Axes to Cover

Structure the ablation study to address the following axes. Each axis should have its own subsection with a comparison table, key observations, and a brief interpretation.

### Axis 1 — Architecture Type
Compare the four architecture types using representative experiments:
- Keyword baseline: E01
- Standalone LLM (best): E02
- Standalone Embedding (best): E08
- Two-stage (best): E14

Show that two-stage consistently outperforms both standalone approaches, and explain why the architecture is effective.

### Axis 2 — Effect of Chain-of-Thought (CoT) on Small LLMs
Compare E02 vs E03 (same prompt, same fields, CoT on/off).
Discuss the counterintuitive result that CoT degrades recall significantly for a 2B-parameter model.

### Axis 3 — Effect of Extended Metadata Fields on Standalone LLM
Compare E02 (Basic fields) vs E04 (+PT+C fields), both using Prompt-Basic, no CoT.
Discuss why adding more context degrades performance for a small LLM.

### Axis 4 — Embedding Model Comparison
Compare E05, E06, E07, E08, E09 — all standalone embedding experiments.
Highlight:
- E06 failure (threshold miscalibration / distribution shift)
- Model scaling effect: E07 vs E08 (0.6b vs 4b, same fields)
- Feature engineering effect: E07 vs E09 (same model, Basic vs +PT+C)

### Axis 5 — Two-Stage: LLM Prompt Strategy in Stage 2
Compare E10, E11, E12 (same Stage-1: Qwen-S-Ext; varying Stage-2 prompt: Basic / Loose / Strict).
Show how Strict prompt eliminates all FP while maintaining recall.

### Axis 6 — Two-Stage: Stage-1 Embedding Model Choice
Compare E11 vs E13 (Loose prompt, Qwen-S-Ext vs Nomic as Stage 1) and E12 vs E14 (Strict prompt, same comparison).
Discuss that despite Nomic producing more Stage-1 errors (23 vs 21), the Nomic-based two-stage achieves higher final F1. Interpret in terms of error type distribution (FP-dominant vs FN-dominant Stage-1 errors).

### Axis 7 — Ablation of Concepts Field in Stage-2 LLM Input
Compare E14 vs E15 (identical except E15 removes concepts from Stage-2 LLM input).
Discuss the marginal but measurable contribution of the concepts field to precision.

---

## Writing Requirements

1. **Format**: academic paper section (LaTeX-style prose, no bullet points for main body — bullets only acceptable inside tables or enumerated lists)
2. **Language**: precise, third-person, formal academic English
3. **Tone**: objective — do not advocate for any method beyond what the numbers support
4. **Length**: sufficient to be publication-ready; each axis subsection should be 2–4 paragraphs
5. **Tables**: include a formatted markdown table for each axis comparison; use the exact numbers from the results table above
6. **Opening**: begin with a 1-paragraph overview of the ablation structure
7. **Closing**: end with a 1-paragraph summary of the key findings across all axes
8. **Do not** fabricate numbers, cite external papers, or make claims not supported by the provided data
9. **Do not** use hedging language like "it seems" or "it appears" — state findings directly from the data

---

## Output

Write the full ablation study section now, starting with a section heading (e.g., `## 5. Ablation Study`).
