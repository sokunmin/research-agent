# High-Precision Relevance Filtering: Multi-stage Reranking Ablation Study

## Summary
*   **Problem:** Academic paper discovery often yields high noise. Standard classifiers face a trade-off: fast embedding models have low precision (excessive False Positives), while standalone LLMs are either too slow or prone to "hallucinated relevance" when processing the full corpus.
*   **Solution:** Implementation of a **Two-stage Reranking Strategy**. A fast **Embedding Model** performs an initial broad screen, followed by a **Small LLM (2B)** that re-judges borderline cases using a **Strict Survey-Heuristic** (determining if a paper would be cited in a dedicated survey on the topic).
*   **Result:** This hybrid architecture achieved **Perfect Precision (1.000)** and a near-perfect **F1 Score of 0.974**. It effectively eliminated all irrelevant application-domain papers while remaining ~70% faster than full LLM inference.

---

## Transparency & Traceability
*   **Test Script:** `experiments/01-openalex-paper-discovery/relevance_filter_ablation.py`
*   **Raw Data:** `experiments/01-openalex-paper-discovery/groundtruth-balanced.json` (120 manually verified papers; 60 Relevant / 60 Irrelevant).
*   **Hardware:** Apple MacBook M1 (Unified Memory). All models served locally via Ollama with Apple Metal acceleration.

---

## Task Context
This component acts as the "Gatekeeper" in the Research Agent. It ensures that only papers where the topic is the **core subject of study** proceed to the VLM summarization stage. This prevents the agent from wasting tokens and generating slides on tangential research.

---

## Experiment Setup: Strategy & Metadata Definitions

To ensure the results are self-contained, the following strategies and configurations are used throughout the study:

### 1. LLM Prompting Strategies
*   **Basic**: A simple "Yes/No" relevance check without specific guidance.
*   **Loose**: Includes papers if the topic is discussed substantively (High Recall bias).
*   **Strict (Survey-Heuristic)**: Employs a 5-question framework asking if the paper provides theoretical foundations or architectural improvements. It asks: *"Would this paper be cited in a professional survey on this specific topic?"* (High Precision bias).

### 2. Metadata Field Configurations
*   **Basic Fields**: `title` + `abstract` + `keywords` + `topics`.
*   **Extended (+PT+C)**: Adds OpenAlex taxonomy fields (`primary_topic` and `concepts`) to provide the LLM with expert-labeled context.

---

## Overall Results (Full Benchmark)

All 15 configurations were evaluated on the 120-paper balanced dataset.

| ID | Architecture Type | Stage-1 (Embedding) | Stage-2 (LLM Prompt) | Input Fields | Time (s) | Precision | Recall | F1 | Accuracy |
|----|---|---|---|---|---|---|---|---|---|
| E01 | Keyword Baseline | (Title match only) | — | Title | 0.0 | 0.862 | 0.833 | 0.847 | 0.850 |
| E02 | Standalone LLM | — | Basic | Basic | 85.2 | 0.804 | 0.683 | 0.739 | 0.758 |
| E03 | Standalone LLM | — | Basic | Basic (w/ CoT) | 69.5 | 0.806 | 0.483 | 0.604 | 0.683 |
| E04 | Standalone LLM | — | Basic | Extended | 75.8 | 0.861 | 0.517 | 0.646 | 0.717 |
| E05 | Standalone Embed | Nomic | — | Basic | 22.2 | 0.740 | 0.950 | 0.832 | 0.808 |
| E06 | Standalone Embed | Nomic-v2 | — | Basic | 32.9 | 1.000 | 0.067 | 0.125 | 0.533 |
| E07 | Standalone Embed | Qwen-0.6b | — | Basic | 38.4 | 0.794 | 0.833 | 0.813 | 0.808 |
| E08 | Standalone Embed | Qwen-4b | — | Basic | 127.8 | 0.766 | 0.983 | 0.861 | 0.842 |
| E09 | Standalone Embed | Qwen-0.6b | — | Extended | 38.3 | 0.800 | 0.867 | 0.832 | 0.825 |
| E10 | Two-Stage Hybrid | Qwen-0.6b (Ext) | Basic | Extended | 21.9 | 0.964 | 0.883 | 0.922 | 0.925 |
| E11 | Two-Stage Hybrid | Qwen-0.6b (Ext) | Loose | Extended | 19.4 | 0.965 | 0.917 | 0.940 | 0.942 |
| E12 | Two-Stage Hybrid | Qwen-0.6b (Ext) | Strict | Extended | 22.3 | 1.000 | 0.917 | 0.957 | 0.958 |
| E13 | Two-Stage Hybrid | Nomic (Basic) | Loose | Extended | 21.8 | 0.983 | 0.950 | 0.966 | 0.967 |
| **E14** | **Two-Stage Hybrid** | **Nomic (Basic)** | **Strict** | **Extended** | **26.0** | **1.000** | **0.950** | **0.974** | **0.975** |
| E15 | Two-Stage Hybrid | Nomic (Ext) | Strict | Extended | 53.6 | 1.000 | 0.933 | 0.966 | 0.967 |

---

## Detailed Ablation Axis Analysis

### 1. Architecture Type Comparison
Four architecture types were compared using representative configurations to find the optimal trade-off between semantic depth and execution speed.

| Architecture | F1 | Precision | Recall | Accuracy | Time (s) |
|---|---|---|---|---|---|
| A — Keyword Baseline (E01) | 0.847 | 0.862 | 0.833 | 0.850 | 0.0 |
| B — Standalone LLM (E02) | 0.739 | 0.804 | 0.683 | 0.758 | 85.2 |
| C — Standalone Embedding (E08) | 0.861 | 0.766 | 0.983 | 0.842 | 127.8 |
| **D — Two-Stage Hybrid (E14)** | **0.974** | **1.000** | **0.950** | **0.975** | **26.0** |

The keyword baseline is surprisingly competitive. Standalone LLMs at the 2B scale suffer from "hallucinated relevance," while large embedding models achieve high recall but poor precision (18 False Positives). The **Two-Stage Hybrid** provides a massive Pareto improvement in both F1 and Latency.

### 2. Effect of Chain-of-Thought (CoT) on Small LLMs
Comparison between E02 and E03 (identical inputs and prompt).

| CoT Enabled | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| No (Prompt-Basic) | 41 | 10 | 19 | 50 | 0.804 | 0.683 | 0.739 |
| Yes (Prompt-Basic + CoT) | 29 | 7 | 31 | 53 | 0.806 | 0.483 | 0.604 |

Enabling CoT on `qwen3.5:2b` dropped the F1 score from 0.739 to 0.604. The reasoning chains introduced semantic noise, causing the model to become overly conservative (Recall dropped by 20 points). **Insight: Avoid CoT for classification in models < 5B parameters.**

### 3. Effect of Extended Metadata Fields on Standalone LLM
Comparison between Basic fields (E02) and Extended +PT+C fields (E04).

| Input Fields | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|---|
| Basic | 41 | 10 | 19 | 50 | 0.804 | 0.683 | 0.739 |
| Extended (+PT+C) | 31 | 5 | 29 | 55 | 0.861 | 0.517 | 0.646 |

Adding taxonomy fields improved Precision but crushed Recall. The 2B model's context window was more effectively utilized by Author Abstracts than by structured taxonomy tags, which likely acted as distractors.

### 4. Embedding Model Selection & Scaling
Comparison of standalone embedding performance across 5 configurations.

| Model | Input Fields | TP | FP | FN | Precision | Recall | F1 | Time (s) |
|---|---|---|---|---|---|---|---|---|
| Nomic | Basic | 57 | 20 | 3 | 0.740 | 0.950 | 0.832 | 22.2 |
| Nomic-v2 | Basic | 4 | 0 | 56 | 1.000 | 0.067 | 0.125 | 32.9 |
| Qwen-0.6b | Basic | 50 | 13 | 10 | 0.794 | 0.833 | 0.813 | 38.4 |
| Qwen-4b | Basic | 59 | 18 | 1 | 0.766 | 0.983 | 0.861 | 116.8 |
| Qwen-0.6b | Extended | 52 | 13 | 8 | 0.800 | 0.867 | 0.832 | 38.3 |

Nomic-v2 failed entirely under the 0.5 threshold, indicating significant distribution shifts between model generations. Scaling Qwen from 0.6b to 4b significantly improved recall (0.833 -> 0.983) but nearly tripled the runtime. **Nomic (Basic) offered the best balance for a Stage-1 rough filter.**

### 5. Stage-2 Prompt Strategy Comparison
Evaluation of how different LLM instructions correct Stage-1 errors.

| Stage-2 Prompt | S2 TP | S2 FP | S2 FN | S2 TN | FP Eliminated | FN Recovered | Final Precision |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Basic** | 1 | 2 | 7 | 11 | 11/13 (85%) | 1/8 (12%) | 0.964 |
| **Loose** | 3 | 2 | 5 | 11 | 11/13 (85%) | 3/8 (38%) | 0.965 |
| **Strict** | 3 | 0 | 5 | 13 | **13/13 (100%)** | 3/8 (38%) | **1.000** |

The **Strict Prompt** is a highly reliable lever for **False Positive elimination**, reaching 100% precision. However, prompt engineering alone showed limited efficacy in recovering False Negatives already missed by Stage-1.

### 6. Two-Stage: Stage-1 Embedding Model Choice
Comparing Qwen-0.6b vs. Nomic as the initial filter in a hybrid setup.

| Stage-1 Model | S1 FP | S1 FN | S2 Prompt | FP Eliminated | FN Recovered | Final F1 |
|---|---|---|---|---|---|---|
| Qwen-0.6b | 13 | 8 | Strict | 13/13 | 3/8 | 0.957 |
| **Nomic** | 20 | 3 | Strict | 20/20 | 0/3 | **0.974** |

Despite Nomic producing more initial errors, its low False Negative count (3 vs. 8) proved decisive. Since Stage-2 is more effective at pruning than at recovering, a **high-recall Stage-1 (like Nomic)** is the superior choice for the hybrid architecture.

### 7. Effect of Extended Input Fields on Stage-1 (Nomic)
Isolating the impact of metadata on the Stage-1 embedding process.

| Stage-1 Input | S1 FP | S1 FN | S1 F1 | Time (s) | Final F1 |
|---|---|---|---|---|---|
| **Basic** | 20 | 3 | 0.832 | 28.6 | **0.974** |
| Extended (+PT+C) | 21 | 4 | 0.818 | 53.6 | 0.966 |

Adding taxonomy fields to Nomic at Stage-1 increased both errors and runtime. **Basic fields are recommended for the Stage-1 embedding step.**

---

## Observations

1.  **Error Asymmetry:** Stage-2 LLM re-judgment is significantly more effective at correcting False Positives (pruning noise) than recovering False Negatives. This justifies an architecture biased toward **High Recall in Stage 1**.
2.  **Instruction Satiation:** Small models exhibit a "less is more" behavior regarding context window utilization in classification tasks. Clean, author-written abstracts consistently outperformed structured taxonomy tags in standalone tests.
3.  **Efficiency Gain:** By routing only Stage-1 borderline cases to the LLM, the system achieves a 70% reduction in inference time without sacrificing accuracy.

---

## Pipeline Integration Status [INTEGRATED]

The system utilizes the **E14 configuration** as the default relevance filtering logic within the `SummaryGenerationWorkflow` (`backend/agent_workflows/summary_gen.py`):
1.  **Stage 1:** `nomic-embed-text` (Basic fields) for initial 100-paper screening.
2.  **Stage 2:** `qwen3.5:2b` (Strict Prompt + Taxonomy tags) for papers in the uncertainty band [0.500, 0.610).
3.  **Final Metrics:** F1=0.974, Precision=1.000, Recall=0.950.
