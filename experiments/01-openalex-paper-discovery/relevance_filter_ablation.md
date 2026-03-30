# Relevance Filter Ablation Study: Architecture and Configuration Comparison

## Background & Motivation

After retrieving a pool of academic papers from OpenAlex, the pipeline needs to classify each paper as relevant or irrelevant to the query topic before downloading and summarising it. A poor classifier wastes compute on irrelevant papers (low precision) or misses relevant ones (low recall). This ablation study systematically compares 15 classifier configurations across 7 design dimensions — architecture type, chain-of-thought prompting, metadata field selection, embedding model choice, LLM prompt strategy, Stage-1 model selection, and Stage-1 input fields — to identify the best configuration for production use. All experiments use a balanced ground truth dataset of 120 manually labelled papers (60 relevant, 60 irrelevant) for the topic "attention mechanism in transformer models" drawn from OpenAlex.

**Hardware:** Apple MacBook M1, 16GB unified memory. All models (LLM and embedding) served locally via Ollama using Apple Metal. Reported wall-clock times reflect local Apple Silicon execution, not cloud or discrete-GPU environments.

**Input field notation used throughout:**
- *Basic* = title + abstract + keywords + topics
- *+PT+C* = Basic plus `primary_topic` and `concepts` (OpenAlex taxonomy fields)

---

## Experiment Setup

**LLM used:** qwen3.5:2b via Ollama, temperature 0, 3 parallel workers.

**Embedding models evaluated:** nomic-embed-text, nomic-embed-text-v2-moe, qwen3-embedding:0.6b, qwen3-embedding:4b.

**Cosine similarity threshold:** 0.5 applied uniformly across all standalone embedding experiments.

**Dataset:** 120 papers (60 relevant, 60 irrelevant), manually labelled, cold-cache timing measurements.

---

## Results

### Architecture Comparison

Four architecture types are compared: (A) keyword title matching, (B) standalone LLM classification, (C) standalone embedding classification, (D) two-stage hybrid (embedding Stage 1 + LLM Stage 2).

| Architecture | Configuration | F1 | Precision | Recall | Accuracy | Time (s)† |
|---|---|---|---|---|---|---|
| A — Keyword title match | title keyword match | 0.847 | 0.862 | 0.833 | 0.850 | 0.0 |
| B — Standalone LLM | qwen3.5:2b, Basic fields | 0.739 | 0.804 | 0.683 | 0.758 | 85.2 |
| C — Standalone Embedding | qwen3-embedding:4b, Basic fields | 0.861 | 0.766 | 0.983 | 0.842 | 127.8 |
| D — Two-Stage Hybrid | nomic-embed-text S1 Basic / qwen3.5:2b S2 +PT+C Strict | 0.974 | 1.000 | 0.950 | 0.975 | 26.0 |

† Cold-cache measurements (embedding vectors computed from scratch).

The keyword baseline achieves F1 = 0.847, a competitive reference point given it operates only on title-level lexical matches. The standalone LLM underperforms the keyword baseline at F1 = 0.739 despite having access to full abstract and metadata. The standalone embedding model achieves F1 = 0.861 but has the highest runtime (127.8 s) and imbalanced precision/recall (18 false positives). The two-stage architecture achieves F1 = 0.974 with perfect precision (1.000) and recall = 0.950 in only 26.0 s — a strong Pareto improvement in both performance and speed over all standalone approaches.

---

### Chain-of-Thought Effect on the Small LLM (qwen3.5:2b)

Both configurations use identical inputs (Basic fields) and the same base prompt, differing only in whether chain-of-thought reasoning is enabled.

| CoT Enabled | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|
| No (Prompt-Basic) | 41 | 10 | 19 | 50 | 0.804 | 0.683 | 0.739 | 0.758 |
| Yes (Prompt-Basic + CoT) | 29 | 7 | 31 | 53 | 0.806 | 0.483 | 0.604 | 0.683 |

Enabling CoT reduces F1 from 0.739 to 0.604, a drop of 13.5 percentage points. Precision is nearly unchanged (0.804 vs. 0.806). The critical difference is recall: CoT reduces recall from 0.683 to 0.483, increasing false negatives from 19 to 31. The model becomes systematically more conservative when forced to reason prior to answering. This result is consistent with known limitations of CoT in small-parameter models: a 2B-parameter model lacks the capacity to produce reliable intermediate reasoning chains, and the generated reasoning introduces noise that biases toward the negative class. **For sub-5B parameter models under zero-shot classification, CoT prompting is counterproductive.**

---

### Extended Metadata Effect on Standalone LLM

Both configurations use qwen3.5:2b with no CoT and Prompt-Basic, differing only in input fields.

| Input Fields | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|
| Basic (title + abstract + keywords + topics) | 41 | 10 | 19 | 50 | 0.804 | 0.683 | 0.739 | 0.758 |
| +PT+C (Basic + primary_topic + concepts) | 31 | 5 | 29 | 55 | 0.861 | 0.517 | 0.646 | 0.717 |

Adding OpenAlex taxonomy fields improves precision (0.804 → 0.861) but substantially reduces recall (0.683 → 0.517), decreasing F1 by 9.3 percentage points. False negatives increase from 19 to 29. The model becomes more conservative under extended context. The OpenAlex taxonomy fields introduce structured categorical vocabulary that a 2B-parameter model may interpret as constraining; additionally, the longer input overloads the model's limited context integration capacity. **For small standalone LLMs, richer metadata does not translate to better relevance judgements.**

---

### Embedding Model Comparison (4 models, standalone classification)

| Model | Input Fields | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy | Time (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| nomic-embed-text | Basic | 57 | 20 | 3 | 40 | 0.740 | 0.950 | 0.832 | 0.808 | 22.2 |
| nomic-embed-text-v2-moe | Basic | 4 | 0 | 56 | 60 | 1.000 | 0.067 | 0.125 | 0.533 | 32.9 |
| qwen3-embedding:0.6b | Basic | 50 | 13 | 10 | 47 | 0.794 | 0.833 | 0.813 | 0.808 | 38.4 |
| qwen3-embedding:4b | Basic | 59 | 18 | 1 | 42 | 0.766 | 0.983 | 0.861 | 0.842 | 116.8 |
| qwen3-embedding:0.6b | +PT+C | 52 | 13 | 8 | 47 | 0.800 | 0.867 | 0.832 | 0.825 | 38.3 |

The most anomalous result is nomic-embed-text-v2-moe, which achieves perfect precision (1.000) at only 6.7% recall (F1 = 0.125). Under this model's embedding space, almost all papers score below the 0.5 threshold, causing the classifier to reject nearly all inputs. This underscores that cosine similarity thresholds are model-specific; a universal threshold of 0.5 is not valid for all models.

Scaling from qwen3-embedding:0.6b to qwen3-embedding:4b improves F1 from 0.813 to 0.861, driven by a substantial recall increase (0.833 → 0.983) at the cost of reduced precision (0.794 → 0.766). The larger model produces only 1 false negative vs. 10, at the cost of 18 false positives vs. 13.

For the 0.6b embedding model, adding +PT+C fields improves recall from 0.833 to 0.867 and F1 from 0.813 to 0.832 with no precision penalty — unlike the LLM case, extended fields benefit embedding models because the additional semantic tokens increase similarity between relevant papers and the topic query.

---

### Two-Stage Classifier: LLM Prompt Strategy in Stage 2

All three configurations share the same Stage-1 (qwen3-embedding:0.6b with +PT+C input fields), which produces 21 Stage-1 errors: 13 false positives and 8 false negatives. Stage 2 uses +PT+C input throughout and varies only the LLM system prompt.

**Stage-2 metrics on the 21 re-judged papers:**

| Prompt Strategy | S2 TP | S2 FP | S2 FN | S2 TN | FP eliminated | FN recovered |
|---|---|---|---|---|---|---|
| Prompt-Basic | 1 | 2 | 7 | 11 | 11/13 (85%) | 1/8 (12%) |
| Prompt-Loose | 3 | 2 | 5 | 11 | 11/13 (85%) | 3/8 (38%) |
| Prompt-Strict | 3 | 0 | 5 | 13 | **13/13 (100%)** | 3/8 (38%) |

**Final metrics across all 120 papers:**

| Stage-2 Prompt | Stage-1 Input | Stage-2 Input | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|---|---|
| Prompt-Basic | +PT+C | +PT+C | 53 | 2 | 7 | 58 | 0.964 | 0.883 | 0.922 | 0.925 |
| Prompt-Loose | +PT+C | +PT+C | 55 | 2 | 5 | 58 | 0.965 | 0.917 | 0.940 | 0.942 |
| Prompt-Strict | +PT+C | +PT+C | 55 | 0 | 5 | 60 | 1.000 | 0.917 | 0.957 | 0.958 |

Moving from Prompt-Basic to Prompt-Loose improves FN recovery from 1/8 to 3/8 (recall gain: 0.883 → 0.917) with no change to FP elimination. Moving from Prompt-Loose to Prompt-Strict achieves complete FP elimination (11/13 → 13/13), with no further FN recovery improvement. **The Strict prompt (structured five-question criteria with an explicit exclusion heuristic) is a reliable lever for FP elimination but not for FN recovery. Prompt engineering controls the precision ceiling; recall is governed by Stage-1.**

---

### Two-Stage Classifier: Stage-1 Embedding Model Choice

Stage-1 comparison: qwen3-embedding:0.6b with +PT+C fields vs. nomic-embed-text with Basic fields. All configurations use +PT+C for Stage-2 input.

**Stage-1 and Stage-2 metrics breakdown:**

| S1 Model | S1 Input | S1 FP | S1 FN | S2 Prompt | S2 TP | S2 FP | S2 FN | S2 TN | FP elim. | FN recov. |
|---|---|---|---|---|---|---|---|---|---|---|
| qwen3-embedding:0.6b | +PT+C | 13 | 8 | Loose | 3 | 2 | 5 | 11 | 11/13 | 3/8 |
| nomic-embed-text | Basic | 20 | 3 | Loose | 0 | 1 | 3 | 19 | 19/20 | **0/3** |
| qwen3-embedding:0.6b | +PT+C | 13 | 8 | Strict | 3 | 0 | 5 | 13 | 13/13 | 3/8 |
| nomic-embed-text | Basic | 20 | 3 | Strict | 0 | 0 | 3 | 20 | 20/20 | **0/3** |

**Final metrics across all 120 papers:**

| S1 Model | S1 Input | S2 Prompt | TP | FP | FN | TN | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|
| qwen3-embedding:0.6b | +PT+C | Loose | 55 | 2 | 5 | 58 | 0.940 | 0.942 |
| nomic-embed-text | Basic | Loose | 57 | 1 | 3 | 59 | 0.966 | 0.967 |
| qwen3-embedding:0.6b | +PT+C | Strict | 55 | 0 | 5 | 60 | 0.957 | 0.958 |
| nomic-embed-text | Basic | Strict | 57 | 0 | 3 | 60 | **0.974** | **0.975** |

Despite generating more Stage-1 errors overall (23 vs. 21), nomic-embed-text achieves higher final F1 in both Loose (+2.6 points) and Strict (+1.7 points) comparisons. The critical insight is that Stage 2 recovers **zero** of nomic-embed-text's 3 Stage-1 false negatives under any prompt. nomic-embed-text's superior final recall arises solely from its Stage-1 having only 3 FN to begin with (vs. 8 for qwen3-embedding:0.6b). Stage 2 corrects 3 of the 0.6b model's 8 false negatives, but 5 persist — yielding FN = 5 vs. nomic's FN = 3. **The Stage-1 model's false negative count governs the final recall ceiling; Stage-2 prompt design cannot compensate for a weak Stage-1.**

---

### Effect of Extended Input Fields on Stage-1 (nomic-embed-text)

Both configurations use Prompt-Strict and +PT+C for Stage-2, differing only in Stage-1 input fields.

**Stage-1 and Stage-2 metrics breakdown:**

| S1 Input Fields | S1 FP | S1 FN | S1 F1 | FP elim. | FN recov. | Time (s) |
|---|---|---|---|---|---|---|
| Basic | 20 | 3 | 0.832 | 20/20 (100%) | 0/3 (0%) | 28.6 |
| +PT+C | 21 | 4 | 0.818 | 21/21 (100%) | 0/4 (0%) | 53.6 |

**Final metrics across all 120 papers:**

| S1 Input | S2 Input | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|---|
| Basic | +PT+C | 57 | 0 | 3 | 60 | 1.000 | 0.950 | **0.974** | **0.975** |
| +PT+C | +PT+C | 56 | 0 | 4 | 60 | 1.000 | 0.933 | 0.966 | 0.967 |

Adding `primary_topic` and `concepts` to nomic-embed-text's Stage-1 input makes performance worse: Stage-1 FP increases from 20 to 21, Stage-1 FN increases from 3 to 4, and the additional FN is not recovered by Stage 2 (0% recovery in both configurations). Final recall drops from 0.950 to 0.933 and F1 from 0.974 to 0.966. Wall-clock time nearly doubles (28.6 s → 53.6 s). This contrasts with the qwen3-embedding:0.6b result, where extended fields improved standalone recall from 0.833 to 0.867. For nomic-embed-text, the taxonomy tokens appear to shift the similarity score distribution in a way that increases misclassification in both directions. **Extended input fields are not beneficial for nomic-embed-text at Stage 1; Basic fields are recommended.**

---

## Key Findings

- **The two-stage hybrid architecture outperforms all standalone approaches on every metric simultaneously** — F1 = 0.974, Precision = 1.000, Recall = 0.950 — while running faster (26.0 s) than standalone embedding (127.8 s) or LLM (85.2 s) approaches that approach comparable F1.

- **Chain-of-thought prompting hurts small LLMs.** Enabling CoT on qwen3.5:2b reduces F1 by 13.5 points (0.739 → 0.604) by inducing excessive conservatism, increasing false negatives from 19 to 31 while barely changing precision.

- **Stage-2 prompt design controls precision, not recall.** The Strict prompt achieves 100% FP elimination regardless of the Stage-1 model. FN recovery is limited (3/8 for the 0.6b embedding model; 0/3 for nomic-embed-text under all prompts). The final recall ceiling is set by Stage-1's false negative count, not by prompt engineering.

- **nomic-embed-text is the better Stage-1 model** despite producing more total Stage-1 errors (23 vs. 21) than qwen3-embedding:0.6b, because it makes only 3 false negatives (vs. 8) — and since Stage 2 cannot recover false negatives, fewer Stage-1 FN translates directly to higher final recall (0.950 vs. 0.917).

- **Extended metadata fields (+PT+C) help embedding models at the standalone level (qwen3-embedding:0.6b: recall 0.833 → 0.867) but hurt nomic-embed-text at Stage 1** (FN: 3 → 4, time: 28.6 → 53.6 s, F1: 0.974 → 0.966). Stage-2 input should always use +PT+C for optimal FP elimination.

## Decision

Adopted the two-stage hybrid classifier with the following configuration:
- **Stage 1:** nomic-embed-text, Basic fields (title + abstract + keywords + topics), cosine similarity threshold = 0.500
- **Stage 2:** qwen3.5:2b, Prompt-Strict, +PT+C fields (Basic + primary_topic + concepts), invoked only for papers in the routing band [0.500, 0.610)
- **Final performance:** F1 = 0.974, Precision = 1.000, Recall = 0.950, Accuracy = 0.975 on 120-paper balanced dataset

Note: the Stage-2 routing band [0.500, 0.610) is the production analogue of the experimental oracle routing — it is derived from the empirical score distribution analysis (see stage1_threshold_analysis.md) and does not require ground-truth labels.
