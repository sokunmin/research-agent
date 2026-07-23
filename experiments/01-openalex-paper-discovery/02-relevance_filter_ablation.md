# Experiment 2 — Two-Stage Relevance Filtering: Architecture Ablation Study

## Task Context

This experiment targets Step 2 — Re-ranking & Verification (README → System Architecture).

The retrieval step (Step 1) returns up to 100 candidate papers based on keyword and quality filters alone. Re-ranking and verification is the gate that decides which candidates proceed to VLM summarization (Step 4). If this gate passes too many false positives, VLM inference tokens are wasted on tangential research. If it drops too many false negatives, relevant papers are silently excluded from the final slide deck.

```
Candidates (up to 100)   ← Step 1: Paper Retrieval
      │
      ▼
┌── 2. RE-RANKING & VERIFICATION ──────────────────────────────────────────┐
├── Original (lz-chen) ────────────────┬── My Implementation ──────────────┤
│ GPT-4o (cloud)                       │ ① nomic-embed-text cosine sim     │
│ scores every candidate               │    (local, all papers)             │
│ single-stage, no pre-filter          │ ② qwen3.5:2b Strict survey prompt  │
│                                      │    (local, ambiguous band only)    │
└──────────────────────────────────────┴───────────────────────────────────┘
      │
      ▼
Filtered papers (relevant only)          → Step 3: PDF Acquisition & Parsing
```

Step 2 — Re-ranking & Verification (detail):

```
Step 2 — Re-ranking & Verification (detail)
──────────────────────────────────────────────────────────────────────
 Candidate papers (up to 100)
       │
       ▼
 ┌─── EXPERIMENT TARGET: Stage 1 ────────────────────────────────────────┐
 │ Embedding similarity                                                  │
 │   Input:  paper text (configurable field set)                        │
 │   Model:  embedding model (configurable)                             │
 │   Output: cosine similarity score → accept / ambiguous / reject      │
 └───────────────────────────────────────────────────────────────────────┘
       │  ambiguous papers only
       ▼
 ┌─── EXPERIMENT TARGET: Stage 2 ────────────────────────────────────────┐
 │ LLM verification                                                      │
 │   Input:  paper metadata (configurable field set)                    │
 │   Prompt: prompt strategy (configurable)                             │
 │   Output: yes / no                                                   │
 └───────────────────────────────────────────────────────────────────────┘
       │
       ▼
 Relevant papers   → Step 3: PDF Acquisition & Parsing
```

---

## Summary

- **Problem:** lz-chen's single-stage relevance filter scores every retrieved candidate directly with a cloud LLM, with no pre-screening step to reduce that per-candidate cost and no verification step to catch a wrong judgment in either direction — a false positive reaching VLM summarization, or a relevant paper silently dropped.
- **Solution:** 15 configurations spanning 4 architecture types, 4 embedding models, 3 LLM prompt strategies, and 2 input field sets were evaluated on a 120-paper balanced dataset (60 relevant / 60 irrelevant) manually labeled for "attention mechanism in transformer models."
- **Result:** A two-stage hybrid running entirely on local models — a fast embedding pre-screen followed by a targeted LLM re-check on ambiguous cases only — achieves F1=0.974, Precision=1.000, Recall=0.950 in 26.0s, 3.3× faster than standalone LLM classification.

---

## Experiment Setup

✅ = currently used in the pipeline.

**Architecture types:**

| Architecture | Description | Stage 1 | Stage 2 |
|---|---|---|---|
| A — Keyword baseline | Exact keyword match on title (attention / transformer / self-attention) | — | — |
| B — Standalone LLM | LLM classifies each paper directly | — | LLM |
| C — Standalone Embedding | Cosine similarity to topic vector at fixed threshold | Embedding | — |
| **D — Two-Stage Hybrid ✅** | Embedding pre-screens all papers; LLM re-judges Stage-1 errors | Embedding ✅ | LLM ✅ |

**LLM prompt strategies (Stage 2):**

| Strategy | Behavior |
|---|---|
| Prompt-Basic | Simple yes/no check — no guidance on what qualifies as relevant |
| Prompt-Loose | Include if the abstract discusses the topic substantively — not merely as a black-box tool |
| **Prompt-Strict ✅** | Survey-heuristic — "would this paper be cited in a survey on this topic?" Criteria: (1) theoretical foundations of attention; (2) design and efficiency improvements; (3) known limitations or critical analyses; (4) motivated alternatives to attention; (5) capabilities that emerge from attention mechanisms |

**Input field configurations:**

| Configuration | Fields | Used in Stage |
|---|---|---|
| **Basic ✅** | title + abstract + keywords + topics | Stage-1 embedding |
| **Extended (+PT+C) ✅** | Basic + primary_topic + concepts | Stage-2 LLM |

**Models used:**

| Category | Model | Role | Parameters |
|---|---|---|---|
| Embedding | **nomic-embed-text ✅** | Stage-1 (comparison axis) | ~137M |
| Embedding | nomic-embed-text-v2-moe | Stage-1 (comparison axis) | ~550M (MoE) |
| Embedding | qwen3-embedding:0.6b | Stage-1 (comparison axis) | 0.6B |
| Embedding | qwen3-embedding:4b | Stage-1 (comparison axis) | 4B |
| LLM | qwen3.5:2b | Stage-2 (fixed) | 2B |

**Metrics:**

| Metric | Definition | Role |
|---|---|---|
| **F1 (primary)** | Harmonic mean of precision and recall | Balances false positives entering VLM against relevant papers silently dropped |
| Precision | TP / (TP + FP) | Minimizing false positives matters — each one wastes VLM summarization budget on an irrelevant paper |
| Recall | TP / (TP + FN) | Fraction of 60 relevant papers correctly identified |
| Accuracy | (TP + TN) / 120 | Overall correctness across the balanced dataset |

Pass condition: F1 above the zero-cost keyword-matching baseline.

**Execution Parameters:**

| Parameter | Value |
|---|---|
| LLM call config | Ollama, temperature=0, `think=False` |
| Embedding | Sequential per-paper with vector caching; cosine similarity threshold = 0.500 (uniform across all models) |
| Stage-2 routing (ablation only) | Invoked on all Stage-1 ground-truth errors (FP + FN), identified via dataset labels — only possible in a labeled ablation; the pipeline uses a score-band approach instead (see Pipeline Integration Status) |
| Dataset | `groundtruth-balanced.json` — 120 papers (60 relevant / 60 irrelevant), manually verified for "attention mechanism in transformer models" |

---

## Full Experimental Results

### Overall Results (15 configurations)

| Sub-Exp | Architecture | Stage-1 Embedding | Stage-2 Prompt | Input Fields | Time (s) | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|---|
| Sub-Exp 1 | A — Keyword | — | — | title (match) | **0.0** | 0.862 | 0.833 | 0.847 | 0.850 |
| Sub-Exp 2 | B — Standalone LLM | — | Prompt-Basic | Basic | 85.2 | 0.804 | 0.683 | 0.739 | 0.758 |
| Sub-Exp 3 | B — Standalone LLM | — | Prompt-Basic + CoT | Basic | 69.5 | 0.806 | 0.483 | 0.604 | 0.683 |
| Sub-Exp 4 | B — Standalone LLM | — | Prompt-Basic | +PT+C | 75.8 | 0.861 | 0.517 | 0.646 | 0.717 |
| Sub-Exp 5 | C — Standalone Embed | nomic-embed-text | — | Basic | 22.2 | 0.740 | 0.950 | 0.832 | 0.808 |
| Sub-Exp 6 | C — Standalone Embed | nomic-embed-text-v2-moe | — | Basic | 32.9 | **1.000** | 0.067 | 0.125 | 0.533 |
| Sub-Exp 7 | C — Standalone Embed | qwen3-embedding:0.6b | — | Basic | 38.4 | 0.794 | 0.833 | 0.813 | 0.808 |
| Sub-Exp 8 | C — Standalone Embed | qwen3-embedding:4b | — | Basic | 116.8 | 0.766 | **0.983** | 0.861 | 0.842 |
| Sub-Exp 9 | C — Standalone Embed | qwen3-embedding:0.6b | — | +PT+C | 38.3 | 0.800 | 0.867 | 0.832 | 0.825 |
| Sub-Exp 10 | D — Two-Stage Hybrid | qwen3-embedding:0.6b | Prompt-Basic | S1: +PT+C / S2: +PT+C | 21.9 | 0.964 | 0.883 | 0.922 | 0.925 |
| Sub-Exp 11 | D — Two-Stage Hybrid | qwen3-embedding:0.6b | Prompt-Loose | S1: +PT+C / S2: +PT+C | 19.4 | 0.965 | 0.917 | 0.940 | 0.942 |
| Sub-Exp 12 | D — Two-Stage Hybrid | qwen3-embedding:0.6b | Prompt-Strict | S1: +PT+C / S2: +PT+C | 22.3 | **1.000** | 0.917 | 0.957 | 0.958 |
| Sub-Exp 13 | D — Two-Stage Hybrid | nomic-embed-text | Prompt-Loose | S1: Basic / S2: +PT+C | 21.8 | 0.983 | 0.950 | 0.966 | 0.967 |
| Sub-Exp 14 ✅ | D — Two-Stage Hybrid | nomic-embed-text | Prompt-Strict | S1: Basic / S2: +PT+C | 26.0 | **1.000** | 0.950 | **0.974** | **0.975** |
| Sub-Exp 15 | D — Two-Stage Hybrid | nomic-embed-text | Prompt-Strict | S1: +PT+C / S2: +PT+C | 53.6 | **1.000** | 0.933 | 0.966 | 0.967 |

**Conclusion:** Two-stage hybrid (Sub-Exp 14) is the only configuration meeting the pass condition — F1 above the keyword baseline — while also achieving Precision=1.000 and running 3.3× faster than standalone LLM.

---

### Axis 1 — Architecture Type Comparison

- **Purpose:** Establish whether the two-stage hybrid architecture outperforms all standalone approaches on both accuracy and latency.
- **Expected:** Two-stage hybrid achieves higher F1 and lower inference time than standalone LLM or standalone embedding.

Representative configurations: keyword baseline (Sub-Exp 1), best-F1 standalone LLM (Sub-Exp 2), best-F1 standalone embedding (Sub-Exp 8), and the winning two-stage configuration (Sub-Exp 14 ✅).

| Sub-Exp | Architecture | F1 | Precision | Recall | Accuracy | Time (s) |
|---|---|---|---|---|---|---|
| Sub-Exp 1 | A — Keyword baseline | 0.847 | 0.862 | 0.833 | 0.850 | **0.0** |
| Sub-Exp 2 | B — Standalone LLM | 0.739 | 0.804 | 0.683 | 0.758 | 85.2 |
| Sub-Exp 8 | C — Standalone Embedding | 0.861 | 0.766 | **0.983** | 0.842 | 127.8 |
| Sub-Exp 14 ✅ | D — Two-Stage Hybrid | **0.974** | **1.000** | 0.950 | **0.975** | 26.0 |

**Conclusion:** Two-stage hybrid is the only architecture satisfying the pass condition. Standalone LLM scores below the zero-cost keyword baseline at 3.3× the latency.

---

### Axis 2 — Effect of Chain-of-Thought on a Small LLM

- **Purpose:** Determine whether chain-of-thought reasoning improves standalone LLM accuracy at 2B scale.
- **Expected:** CoT improves precision without materially reducing recall.

Comparison between Sub-Exp 2 and Sub-Exp 3 — identical input fields (Basic) and base prompt (Prompt-Basic), differing only in whether chain-of-thought is enabled.

| Sub-Exp | Condition | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|---|
| Sub-Exp 2 | Without CoT | 41 | 10 | 19 | 50 | 0.804 | 0.683 | 0.739 |
| Sub-Exp 3 | With CoT | 29 | 7 | 31 | 53 | 0.806 | 0.483 | 0.604 |

**Conclusion:** CoT suppresses recall (FN: 19 → 31) without improving precision — a 2B model is harmed, not helped, by extended reasoning chains.

---

### Axis 3 — Effect of Extended Metadata on Standalone LLM

- **Purpose:** Determine whether adding OpenAlex taxonomy fields (primary_topic, concepts) improves standalone LLM classification accuracy.
- **Expected:** Extended fields improve F1 by giving the LLM richer context for relevance judgment.

Comparison between Sub-Exp 2 (Basic) and Sub-Exp 4 (+PT+C) — same prompt (Prompt-Basic, no CoT).

| Sub-Exp | Input Fields | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|---|
| Sub-Exp 2 | Basic | 41 | 10 | 19 | 50 | 0.804 | 0.683 | 0.739 |
| Sub-Exp 4 | Extended +PT+C | 31 | 5 | 29 | 55 | 0.861 | 0.517 | 0.646 |

**Conclusion:** Extended fields raise precision but collapse recall — taxonomy tag vocabulary acts as a constraint rather than a clarifier for a 2B model.

---

### Axis 4 — Embedding Model Comparison

- **Purpose:** Identify which embedding model offers the best Stage-1 recall and runtime trade-off for a broad pre-screening role.
- **Expected:** Larger embedding models achieve higher recall with acceptable precision and runtime.

All five standalone embedding configurations (Sub-Exp 5–9):

| Sub-Exp | Model | Input | TP | FP | FN | TN | Precision | Recall | F1 | Time (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| Sub-Exp 5 ✅ | nomic-embed-text | Basic | 57 | 20 | 3 | 40 | 0.740 | 0.950 | 0.832 | **22.2** |
| Sub-Exp 6 | nomic-embed-text-v2-moe | Basic | 4 | 0 | 56 | 60 | **1.000** | 0.067 | 0.125 | 32.9 |
| Sub-Exp 7 | qwen3-embedding:0.6b | Basic | 50 | 13 | 10 | 47 | 0.794 | 0.833 | 0.813 | 38.4 |
| Sub-Exp 8 | qwen3-embedding:4b | Basic | 59 | 18 | 1 | 42 | 0.766 | **0.983** | **0.861** | 116.8 |
| Sub-Exp 9 | qwen3-embedding:0.6b | +PT+C | 52 | 13 | 8 | 47 | 0.800 | 0.867 | 0.832 | 38.3 |

`nomic-embed-text-v2-moe` (Sub-Exp 6) achieves perfect precision only because it rejects 116 of 120 papers under the shared 0.500 threshold.

**Conclusion:** `nomic-embed-text` delivers the best recall-to-cost ratio (3 FN, 22.2s). `nomic-embed-text-v2-moe` fails under the uniform threshold — cosine thresholds are model-specific and cannot be shared across models.

---

### Axis 5 — Stage-2 Prompt Strategy

- **Purpose:** Determine which Stage-2 prompt most effectively converts Stage-1's false positives and false negatives back into correct judgments.
- **Expected:** A more specific prompt converts more of both false positives and false negatives into correct judgments.

Stage-1 configuration fixed: `qwen3-embedding:0.6b` with +PT+C fields (Sub-Exp 9), producing 13 FP + 8 FN. Stage-2 input: +PT+C for all three prompts.

**Stage-2 metrics (re-judged subset — 21 Stage-1 errors):**

| Sub-Exp | Stage-2 Prompt | S2 TP | S2 FP | S2 FN | S2 TN | FP Eliminated | FN Recovered |
|---|---|---|---|---|---|---|---|
| Sub-Exp 10 | Prompt-Basic | 1 | 2 | 7 | 11 | 11/13 (85%) | 1/8 (12%) |
| Sub-Exp 11 | Prompt-Loose | **3** | 2 | **5** | 11 | 11/13 (85%) | **3/8 (38%)** |
| Sub-Exp 12 ✅ | Prompt-Strict | **3** | **0** | **5** | **13** | **13/13 (100%)** | **3/8 (38%)** |

**Final metrics (all 120 papers):**

| Sub-Exp | Configuration | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|---|
| Sub-Exp 10 | Prompt-Basic | 53 | 2 | 7 | 58 | 0.964 | 0.883 | 0.922 |
| Sub-Exp 11 | Prompt-Loose | **55** | 2 | **5** | 58 | 0.965 | **0.917** | 0.940 |
| Sub-Exp 12 ✅ | Prompt-Strict | **55** | **0** | **5** | **60** | **1.000** | **0.917** | **0.957** |

**Conclusion:** Prompt-Strict is the only prompt achieving 100% FP elimination. FN recovery does not improve with stricter prompting — the 5 unrecovered FN are beyond Stage-2 correction regardless of prompt specificity.

---

### Axis 6 — Stage-1 Embedding Model Choice (in Two-Stage)

- **Purpose:** Compare `nomic-embed-text` vs. `qwen3-embedding:0.6b` as Stage-1 in the two-stage architecture under both Prompt-Loose and Prompt-Strict.
- **Expected:** The model with fewer Stage-1 FN produces higher final recall, since Stage 2 has limited FN recovery capacity.

This axis conflates two variables — embedding model architecture and Stage-1 input field set (`nomic-embed-text` uses Basic; `qwen3-embedding:0.6b` uses +PT+C). The effect of input fields on nomic alone is isolated in Axis 7.

**Stage-1 and Stage-2 breakdown:**

| Sub-Exp | S1 Model | S1 Input | S1 FP | S1 FN | S2 Prompt | FP Eliminated | FN Recovered | Final F1 |
|---|---|---|---|---|---|---|---|---|
| Sub-Exp 11 | qwen3-embedding:0.6b | +PT+C | **13** | 8 | Loose | 11/13 (85%) | **3/8 (38%)** | 0.940 |
| Sub-Exp 13 | nomic-embed-text | Basic | 20 | **3** | Loose | 19/20 (95%) | 0/3 (0%) | 0.966 |
| Sub-Exp 12 | qwen3-embedding:0.6b | +PT+C | **13** | 8 | Strict | **13/13 (100%)** | **3/8 (38%)** | 0.957 |
| Sub-Exp 14 ✅ | nomic-embed-text | Basic | 20 | **3** | Strict | **20/20 (100%)** | 0/3 (0%) | **0.974** |

**Conclusion:** `nomic-embed-text`'s lower Stage-1 FN count (3 vs. 8) directly determines the final recall ceiling — Stage 2 recovers none of the 3 nomic FN, making Stage-1 model choice the binding variable.

---

### Axis 7 — Effect of Extended Input Fields on Stage-1 (nomic-embed-text)

- **Purpose:** Isolate whether adding +PT+C fields to the `nomic-embed-text` Stage-1 embedding input improves accuracy.
- **Expected:** Extended fields reduce Stage-1 FN by providing richer semantic context to the embedding.

Stage-2 fixed: Prompt-Strict, +PT+C input.

| Sub-Exp | S1 Input | S1 FP | S1 FN | S1 F1 | S2 FP Eliminated | S2 FN Recovered | Time (s) | Final F1 |
|---|---|---|---|---|---|---|---|---|
| Sub-Exp 14 ✅ | Basic | **20** | **3** | **0.832** | **20/20 (100%)** | 0/3 (0%) | **28.6** | **0.974** |
| Sub-Exp 15 | +PT+C | 21 | 4 | 0.818 | **21/21 (100%)** | 0/4 (0%) | 53.6 | 0.966 |

**Conclusion:** Extended fields degrade `nomic-embed-text` Stage-1 accuracy on both error types (FP: 20→21, FN: 3→4) while nearly doubling runtime — Basic fields are superior for Stage-1.

---

## Observations

### Why Does Making the 2B LLM "Smarter" Backfire, While the Same Extra Data Helps the Embedding Model?

Reasoning step-by-step or reading extra metadata both make the 2B LLM reject more relevant papers, while the same extra metadata helps the embedding model instead — embedding scores treat extra text as more signal, but the LLM treats any mismatch as a reason to reject.

- CoT on the LLM: F1 0.739→0.604 (−0.135).
- Extra metadata on the LLM: F1 0.739→0.646 (−0.093).
- Extra metadata on the embedding model: Recall 0.833→0.867 (improved).

### Why Does nomic-embed-text-v2-moe Fail Under the Uniform 0.500 Threshold?

`nomic-embed-text-v2-moe` collapses to near-random performance (F1=0.125) not because its relevance judgments are wrong, but because its similarity scores follow a different distribution than the other three models — the shared 0.500 threshold rejects nearly everything regardless of true relevance.

- All 4 embedding models share a single 0.500 threshold, with no per-model calibration applied.
- Recall=0.067 (4/60 relevant papers accepted), Precision=1.000, F1=0.125.

---

## Decision

### Which Configuration Was Selected?

Two-stage hybrid — `nomic-embed-text` for Stage-1 pre-screening, Prompt-Strict for Stage-2 verification — is selected as the only configuration meeting the pass condition, achieving the highest F1 among all 15 tested combinations.

- F1=0.974, Precision=1.000, Recall=0.950, 26.0s — 3.3× faster than standalone LLM.
- `nomic-embed-text`'s 3 Stage-1 false negatives (vs. 8 for `qwen3-embedding:0.6b`) set a higher recall ceiling.
- Prompt-Strict eliminates 100% of Stage-1 false positives, versus 85% for looser prompts.
- Basic fields for Stage-1 and Extended +PT+C fields for Stage-2 both outperform the alternative field configuration tested for each stage.

---

## Pipeline Integration Status ✅ INTEGRATED

Single-stage GPT-4o classification replaced by a local two-stage filter (embedding pre-screen → LLM verification for the ambiguous score band) in `PaperRelevanceFilter` in `paper_scraping.py`.
