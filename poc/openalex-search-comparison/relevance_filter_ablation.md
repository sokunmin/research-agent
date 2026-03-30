## 5. Ablation Study

This section presents a systematic ablation study examining the contributions of seven design dimensions to the binary relevance classification task: (1) the choice of overall architecture, (2) the use of chain-of-thought (CoT) prompting in a small language model, (3) the effect of extended metadata fields on standalone LLM performance, (4) the choice and scaling of embedding model, (5) the LLM prompt strategy in the second stage of the two-stage architecture, (6) the choice of Stage-1 embedding model in the two-stage architecture, and (7) the effect of extended input fields on Stage-1 embedding performance in the two-stage architecture. All experiments are evaluated on a balanced dataset of 120 papers (60 relevant, 60 irrelevant) drawn from the OpenAlex database and manually labelled for the research topic *"attention mechanism in transformer models"*. The LLM used throughout is `qwen3.5:2b` served via Ollama at temperature 0; four embedding models are evaluated under a uniform cosine similarity threshold of 0.5.

**Input field notation used throughout:** *Basic* = title + abstract + keywords + topics; *+PT+C* = Basic plus `primary_topic` and `concepts` (OpenAlex taxonomy fields). For two-stage experiments, Stage-1 (embedding) and Stage-2 (LLM) may use different field sets and are noted separately.

All experiments are executed locally on an Apple MacBook with an M1 chip. All models — both LLM and embedding — are served via Ollama, which leverages the M1's integrated GPU through Apple Metal. The M1 uses a unified memory architecture (UMA) in which CPU and GPU share the same memory pool; there is no discrete VRAM. Model size and parallelism choices (LLM: 2B parameters; embedding: up to 4B parameters; 3 parallel LLM workers) reflect the unified memory capacity and throughput constraints of this hardware. Reported wall-clock times should therefore be interpreted as local Apple Silicon execution times rather than as estimates for discrete-GPU or cloud deployments.

---

### 5.1 Axis 1 — Architecture Type

Four architecture types are compared using representative configurations: (A) keyword-based title matching (E01), (B) standalone LLM classification (E02, selected as the best-F1 standalone LLM among E02–E04), (C) standalone embedding-based classification (E08, highest-F1 standalone embedding among E05–E09), and (D) two-stage hybrid classification (E14, best overall).

| ID | Name | Architecture | Input Fields | F1 | Precision | Recall | Accuracy | Time (s)† |
|---|---|---|---|---|---|---|---|---|
| E01 | KW-Title | A — Keyword | title (keyword match) | 0.847 | 0.862 | 0.833 | 0.850 | 0.0 |
| E02 | LLM-Basic | B — Standalone LLM | Basic | 0.739 | 0.804 | 0.683 | 0.758 | 85.2 |
| E08 | Emb-QwenM | C — Standalone Embedding | Basic | 0.861 | 0.766 | 0.983 | 0.842 | 127.8 |
| E14 | TS-Nomic-Basic-Strict | D — Two-Stage | S1: Basic / S2: +PT+C | 0.974 | 1.000 | 0.950 | 0.975 | 26.0 |

† All times are cold-cache measurements (embedding vectors computed from scratch).

The keyword baseline (E01) achieves an F1 of 0.847, establishing a surprisingly competitive reference point given that it operates exclusively on title-level lexical matches. The standalone LLM (E02) underperforms this baseline with an F1 of 0.739 — the highest F1 among standalone LLM configurations (E02–E04) — indicating that zero-shot LLM classification with a 2B-parameter model does not reliably generalise beyond surface keyword proximity. The standalone embedding model (E08) surpasses both at F1 = 0.861, though it incurs the highest runtime (127.8 s) and exhibits a markedly imbalanced precision-recall profile (Precision = 0.766, Recall = 0.983), producing 18 false positives.

The two-stage architecture (E14) achieves the highest F1 of 0.974, with perfect precision (1.000) and recall of 0.950, in 26.0 seconds under cold-cache conditions. The efficiency gain arises from the two-stage design: the embedding model processes all 120 papers in Stage 1 using Basic fields, and the LLM is invoked only on the 23 Stage-1 errors using the richer +PT+C field set, avoiding full-corpus LLM inference. These results demonstrate that the two-stage architecture provides a strong Pareto improvement in both classification performance and runtime relative to every standalone baseline.

---

### 5.2 Axis 2 — Effect of Chain-of-Thought on a Small LLM

E02 and E03 use identical inputs (Basic fields: title, abstract, keywords, topics) and the same base system prompt (Prompt-Basic), differing only in whether chain-of-thought reasoning is enabled.

| ID | Name | Input Fields | CoT | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E02 | LLM-Basic | Basic | No | 41 | 10 | 19 | 50 | 0.804 | 0.683 | 0.739 | 0.758 |
| E03 | LLM-Basic-CoT | Basic | Yes | 29 | 7 | 31 | 53 | 0.806 | 0.483 | 0.604 | 0.683 |

Enabling CoT degrades F1 from 0.739 to 0.604, a drop of 13.5 percentage points. The precision values are nearly identical (0.804 vs. 0.806), indicating that the precision-recall trade-off is not the source of divergence. The critical difference lies in recall: CoT reduces recall from 0.683 to 0.483, increasing false negatives from 19 to 31. The model becomes systematically more conservative when forced to reason prior to answering.

This result is consistent with known limitations of CoT prompting in small-parameter models. A 2B-parameter model lacks the representational capacity to produce reliable intermediate reasoning chains; rather than sharpening the final decision, the generated reasoning introduces noise that biases the model toward the negative class. The total number of positive predictions drops from 51 (E02) to 36 (E03), confirming that CoT suppresses recall without materially improving precision. For sub-5B parameter models operating under a zero-shot classification protocol, CoT prompting is counterproductive and should be avoided.

---

### 5.3 Axis 3 — Effect of Extended Metadata on Standalone LLM

E02 and E04 both use Prompt-Basic with no CoT. E02 provides Basic fields (title, abstract, keywords, topics); E04 additionally provides `primary_topic` and `concepts` (the +PT+C configuration, reflected in the name suffix *-Ext*).

| ID | Name | Input Fields | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|---|---|
| E02 | LLM-Basic | Basic | 41 | 10 | 19 | 50 | 0.804 | 0.683 | 0.739 | 0.758 |
| E04 | LLM-Ext | +PT+C | 31 | 5 | 29 | 55 | 0.861 | 0.517 | 0.646 | 0.717 |

Adding `primary_topic` and `concepts` to the LLM input improves precision from 0.804 to 0.861 but reduces recall from 0.683 to 0.517 and decreases F1 by 9.3 percentage points. False negatives increase from 19 to 29, while false positives decrease from 10 to 5. The extended fields make the model more conservative, generating fewer positive predictions overall (36 vs. 51).

The performance degradation under extended context is attributable to two compounding factors. First, the OpenAlex taxonomy fields — particularly the hierarchical `concepts` tags — introduce structured categorical vocabulary that a 2B-parameter model may interpret as constraining rather than clarifying. When the taxonomy labels do not precisely align with the research topic, the model discounts the abstract evidence and defaults to rejection. Second, the total input length for the +PT+C configuration is substantially longer; a small model with limited context integration capacity may lose coherence when processing a longer structured prompt. In contrast, the Basic fields closely mirror the natural language an author uses to describe the paper, which the model processes more reliably. These findings indicate that for small LLMs in a standalone architecture, richer metadata does not translate to better relevance judgements.

---

### 5.4 Axis 4 — Embedding Model Comparison

Five standalone embedding experiments (E05–E09) are compared, covering four model variants and two input configurations.

| ID | Name | Model | Input Fields | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy | Time (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E05 | Emb-Nomic-Basic | nomic-embed-text | Basic | 57 | 20 | 3 | 40 | 0.740 | 0.950 | 0.832 | 0.808 | 22.2 |
| E06 | Emb-Nomic-v2 | nomic-embed-text-v2-moe | Basic | 4 | 0 | 56 | 60 | 1.000 | 0.067 | 0.125 | 0.533 | 32.9 |
| E07 | Emb-QwenS-Basic | qwen3-embedding:0.6b | Basic | 50 | 13 | 10 | 47 | 0.794 | 0.833 | 0.813 | 0.808 | 38.4 |
| E08 | Emb-QwenM | qwen3-embedding:4b | Basic | 59 | 18 | 1 | 42 | 0.766 | 0.983 | 0.861 | 0.842 | 116.8 |
| E09 | Emb-QwenS-Ext | qwen3-embedding:0.6b | +PT+C | 52 | 13 | 8 | 47 | 0.800 | 0.867 | 0.832 | 0.825 | 38.3 |

The most anomalous result is E06 (Emb-Nomic-v2), which achieves perfect precision (1.000) at a recall of only 0.067 and F1 of 0.125 — barely above random performance on the balanced dataset. This near-complete recall failure arises from threshold miscalibration: the uniform cosine similarity threshold of 0.5, determined to be appropriate for other models, is not calibrated to the embedding distribution of `nomic-embed-text-v2-moe`. Under this model's embedding space, all but four papers receive a similarity score below 0.5, causing the classifier to reject nearly all inputs. This result underscores that cosine similarity thresholds are model-specific and that a universal threshold constitutes a confound when comparing embedding models at a fixed operating point.

The effect of model scale is examined by comparing E07 (Emb-QwenS-Basic, 0.6B parameters) and E08 (Emb-QwenM, 4B parameters), both using Basic fields. Scaling from 0.6B to 4B improves F1 from 0.813 to 0.861, driven primarily by a substantial recall increase (0.833 → 0.983) at the cost of reduced precision (0.794 → 0.766). The larger model produces only 1 false negative across 120 papers, compared to 10 for the smaller variant, at the cost of 18 false positives versus 13. The recall gain from model scaling indicates that the 4B embedding model captures finer semantic relationships to the research topic, though it also becomes more permissive in its similarity scoring.

The effect of extended metadata on embedding performance is examined by comparing E07 (Emb-QwenS-Basic) and E09 (Emb-QwenS-Ext), both using QwenS. Adding `primary_topic` and `concepts` (+PT+C) improves recall from 0.833 to 0.867 and F1 from 0.813 to 0.832, while precision remains unchanged at 0.794–0.800. Unlike the LLM case, extended fields benefit the embedding model because the embedding is computed over a concatenated text string; the additional semantic tokens increase the similarity between relevant papers and the topic query, particularly for papers whose relevance is topically explicit in the taxonomy but not prominent in the abstract. Note that the *-Basic* and *-Ext* suffixes in the experiment names directly reflect this field-set distinction.

---

### 5.5 Axis 5 — Two-Stage: LLM Prompt Strategy in Stage 2

E10, E11, and E12 share the same Stage-1 configuration (Emb-QwenS-Ext: qwen3-embedding:0.6b with +PT+C input fields, i.e., E09), which produces 21 Stage-1 errors: 13 false positives and 8 false negatives. Stage 2 uses the same +PT+C input fields throughout and varies only the LLM system prompt: Prompt-Basic (E10), Prompt-Loose (E11), and Prompt-Strict (E12). The table below reports both Stage-2 performance on the 21-paper re-judged subset and the resulting final metrics across all 120 papers.

**Stage-2 metrics (on the 21 re-judged papers; all use S1: QwenS +PT+C → 13 FP + 8 FN):**

| ID | S2 Prompt | S2 Input | S2 TP | S2 FP | S2 FN | S2 TN | FP eliminated | FN recovered |
|---|---|---|---|---|---|---|---|---|
| E10 | Prompt-Basic | +PT+C | 1 | 2 | 7 | 11 | 11/13 (85%) | 1/8 (12%) |
| E11 | Prompt-Loose | +PT+C | 3 | 2 | 5 | 11 | 11/13 (85%) | 3/8 (38%) |
| E12 | Prompt-Strict | +PT+C | 3 | 0 | 5 | 13 | **13/13 (100%)** | 3/8 (38%) |

**Final metrics (all 120 papers):**

| ID | Name | S1 Input | S2 Prompt | S2 Input | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E10 | TS-QwenS-Ext-Basic | +PT+C | Prompt-Basic | +PT+C | 53 | 2 | 7 | 58 | 0.964 | 0.883 | 0.922 | 0.925 |
| E11 | TS-QwenS-Ext-Loose | +PT+C | Prompt-Loose | +PT+C | 55 | 2 | 5 | 58 | 0.965 | 0.917 | 0.940 | 0.942 |
| E12 | TS-QwenS-Ext-Strict | +PT+C | Prompt-Strict | +PT+C | 55 | 0 | 5 | 60 | 1.000 | 0.917 | 0.957 | 0.958 |

The Stage-2 metrics reveal an important asymmetry in prompt effectiveness. Moving from Prompt-Basic to Prompt-Loose improves FN recovery from 1/8 to 3/8, while FP elimination remains unchanged at 11/13; this explains the recall gain (0.883 → 0.917) without any change in precision. Moving from Prompt-Loose to Prompt-Strict achieves complete FP elimination (11/13 → 13/13), but FN recovery does not improve further (3/8 in both cases); this explains the precision gain (0.965 → 1.000) with recall unchanged at 0.917.

The Strict prompt's structured five-question criteria with an explicit exclusion heuristic is therefore a reliable lever for FP elimination but not for FN recovery. The remaining 5 false negatives in E12 represent papers that all three prompts fail to recover — a recall ceiling determined by the composition of Stage-1 errors rather than by prompt design. These findings indicate that within the two-stage framework, prompt engineering controls the precision ceiling, while recall is primarily governed by Stage-1 characteristics.

---

### 5.6 Axis 6 — Two-Stage: Stage-1 Embedding Model Choice

E11 and E13 use Prompt-Loose in Stage 2 but differ in Stage-1 model and input fields: QwenS with +PT+C (E09 configuration) vs. Nomic with Basic fields (E05 configuration). E12 and E14 apply the same Stage-1 contrast under Prompt-Strict. All four experiments use +PT+C for Stage-2 input.

Note that this comparison conflates two factors — embedding model architecture and input field configuration — because no experiment in this axis tests Nomic with +PT+C fields or QwenS with Basic fields. This constitutes a confound that is addressed separately in Axis 7 (Section 5.7), which isolates the effect of Stage-1 input fields for the Nomic model.

**Stage-1 and Stage-2 metrics breakdown:**

| ID | S1 Model | S1 Input | S1 FP | S1 FN | S2 Prompt | S2 TP | S2 FP | S2 FN | S2 TN | FP elim. | FN recov. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E11 | QwenS | +PT+C | 13 | 8 | Loose | 3 | 2 | 5 | 11 | 11/13 | 3/8 |
| E13 | Nomic | Basic | 20 | 3 | Loose | 0 | 1 | 3 | 19 | 19/20 | **0/3** |
| E12 | QwenS | +PT+C | 13 | 8 | Strict | 3 | 0 | 5 | 13 | 13/13 | 3/8 |
| E14 | Nomic | Basic | 20 | 3 | Strict | 0 | 0 | 3 | 20 | 20/20 | **0/3** |

**Final metrics (all 120 papers):**

| ID | Name | S1 Input | S2 Prompt | TP | FP | FN | TN | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|---|
| E11 | TS-QwenS-Ext-Loose | +PT+C | Loose | 55 | 2 | 5 | 58 | 0.940 | 0.942 |
| E13 | TS-Nomic-Basic-Loose | Basic | Loose | 57 | 1 | 3 | 59 | 0.966 | 0.967 |
| E12 | TS-QwenS-Ext-Strict | +PT+C | Strict | 55 | 0 | 5 | 60 | 0.957 | 0.958 |
| E14 | TS-Nomic-Basic-Strict | Basic | Strict | 57 | 0 | 3 | 60 | **0.974** | **0.975** |

The Stage-2 breakdown reveals the precise mechanism behind Nomic's advantage. Despite generating more Stage-1 errors (23 vs. 21), Nomic-based configurations achieve higher final F1 in both the Loose (+2.6 points) and Strict (+1.7 points) comparisons. The critical observation is that Stage 2 recovers zero of Nomic's three Stage-1 false negatives across all prompt variants (FN recovered = 0/3 for E13, E14). The three papers that Nomic misclassifies as negative at Stage 1 are hard negatives that the LLM also consistently classifies as negative regardless of prompt design. Nomic's superior final recall therefore does not arise from Stage-2 FN recovery; it arises solely from Nomic's Stage-1 having only 3 FN to begin with, compared to 8 for Qwen-S.

Stage 2 corrects 3 of Qwen-S's 8 false negatives under both Loose and Strict prompts, but 5 persist in the final output. Since Nomic starts from 3 FN and Stage 2 recovers none, both pipelines converge to FN = 3 (Nomic) vs. FN = 5 (Qwen-S), yielding a recall of 0.950 vs. 0.917 in the Strict configuration. The choice of Stage-1 embedding model therefore governs the final recall ceiling through its Stage-1 false negative count, not through the LLM's ability to correct Stage-1 errors post hoc.

---

### 5.7 Axis 7 — Effect of Extended Input Fields on Stage-1 Embedding (Nomic)

E14 and E15 share the same Stage-2 configuration (Prompt-Strict, +PT+C input) and differ only in the Stage-1 embedding input fields: E14 uses Basic fields (Emb-Nomic-Basic), while E15 uses the extended field set (Emb-Nomic-Ext, i.e., Basic + `primary_topic` + `concepts`). This isolates the contribution of extended metadata to Stage-1 embedding quality for the Nomic model, complementing the analogous comparison for QwenS in Axis 4 (E07 vs. E09).

**Stage-1 and Stage-2 metrics breakdown:**

| ID | S1 Input | S1 FP | S1 FN | S1 F1 | S2 Prompt | S2 Input | FP elim. | FN recov. | Time (s) |
|---|---|---|---|---|---|---|---|---|---|
| E14 | Basic | 20 | 3 | 0.832 | Strict | +PT+C | 20/20 (100%) | **0/3 (0%)** | 28.6 |
| E15 | +PT+C | 21 | 4 | 0.818 | Strict | +PT+C | 21/21 (100%) | **0/4 (0%)** | 53.6 |

**Final metrics (all 120 papers):**

| ID | Name | S1 Input | S2 Input | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |
|---|---|---|---|---|---|---|---|---|---|---|---|
| E14 | TS-Nomic-Basic-Strict | Basic | +PT+C | 57 | 0 | 3 | 60 | 1.000 | 0.950 | **0.974** | **0.975** |
| E15 | TS-Nomic-Ext-Strict | +PT+C | +PT+C | 56 | 0 | 4 | 60 | 1.000 | 0.933 | 0.966 | 0.967 |

Adding `primary_topic` and `concepts` to the Nomic Stage-1 input does not improve performance. Stage-1 FP increases from 20 to 21, and Stage-1 FN increases from 3 to 4, reducing Stage-1 F1 from 0.832 to 0.818. Stage-2 eliminates all FP in both configurations (100%), but recovers zero FN in both (0/3 for E14, 0/4 for E15). The additional FN introduced by the Ext field set is therefore permanent: it carries through to the final output, reducing recall from 0.950 to 0.933 and F1 from 0.974 to 0.966. Final precision remains 1.000 in both cases.

This result contrasts with the QwenS comparison (E07 vs. E09, Axis 4), where extended fields improved recall from 0.833 to 0.867. For the Nomic model, the additional taxonomy tokens appear to shift the similarity score distribution in a way that increases misclassification in both directions (more FP and more FN), rather than reducing them. Wall-clock time also increases substantially (28.6 s → 53.6 s) due to the longer embedding input.

The extended field set is therefore not beneficial for Nomic Stage-1. The Basic field configuration (E14) remains the recommended Stage-1 setup for the two-stage architecture.

---

### 5.8 Summary

The ablation study reveals several consistent findings across all seven axes. The two-stage architecture uniformly outperforms all standalone approaches, achieving the best F1 (0.974), the best precision (1.000), and competitive recall (0.950) in 26.0 seconds under cold-cache conditions — faster than any standalone model that approaches comparable F1. Chain-of-thought prompting is detrimental for a 2B-parameter model, reducing recall by 20 percentage points by inducing excessive conservatism, while extended metadata fields similarly degrade standalone LLM performance by overloading the model's limited context integration capacity. Among embedding models, the uniform cosine threshold of 0.5 is incompatible with `nomic-embed-text-v2-moe`, resulting in near-complete recall failure; threshold calibration per model is a prerequisite for fair evaluation. Model scale improves embedding recall substantially (0.833 → 0.983 from 0.6B to 4B), and extended metadata fields improve QwenS embedding recall without harming precision (E07 → E09: 0.833 → 0.867).

In the two-stage framework, Stage-2 prompt specificity governs FP elimination but not FN recovery: the Strict prompt achieves 100% FP elimination regardless of the Stage-1 model, while FN recovery rates remain limited (3/8 for QwenS Stage-1; 0/3 for Nomic Stage-1 under all prompts). The final recall is therefore determined by the Stage-1 model's false negative count rather than by Stage-2 prompt design. Nomic achieves higher recall than QwenS in the two-stage setting (0.950 vs. 0.917) because its Stage-1 produces only 3 false negatives — papers that Stage 2 consistently fails to recover — compared to 8 for QwenS, of which Stage 2 corrects 3.

The effect of extended input fields on Stage-1 embedding is model-dependent. For QwenS, adding +PT+C improves standalone recall (Axis 4). For Nomic in the two-stage setting (E14 vs. E15), adding +PT+C to Stage-1 input increases both FP (20 → 21) and FN (3 → 4), reducing final recall from 0.950 to 0.933 with no compensating gain. The Basic field configuration is therefore recommended for Nomic Stage-1. Stage-2 input should use +PT+C in all configurations, as the richer context supports FP elimination at the LLM re-judgment step.

One methodological limitation of all two-stage experiments (E10–E15) warrants explicit acknowledgement: Stage-2 routing is performed using ground-truth labels to identify Stage-1 errors, which is not possible in a production deployment without prior annotation. The reported metrics therefore represent an upper bound on achievable performance. The translation of the best experimental configuration (E14) to a deployable system — including calibration of a score-based routing band that does not require ground-truth labels — is addressed in Section 6.
