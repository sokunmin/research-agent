# Stage-1 Cosine Similarity Threshold Analysis: Score Distribution and Production Routing Design

## Background & Motivation

The best-performing relevance classifier (from the ablation study) uses a two-stage design: an embedding model at Stage 1 filters the bulk of papers by cosine similarity score, and an LLM at Stage 2 re-judges only the uncertain cases. In the experimental setup, Stage-2 routing was determined by oracle — papers that Stage 1 misclassified were forwarded to Stage 2, which requires knowing the ground-truth label. In production, labels are unavailable, so oracle routing cannot be used. This analysis characterises the embedding model's score distribution to design a deployable score-based routing band that replaces oracle routing without requiring labels, and quantifies the trade-off between Stage-2 LLM load and error coverage.

All analyses use the nomic-embed-text embedding model with Basic input fields (title + abstract + keywords + topics), consistent with the best experimental configuration. The dataset is the same balanced 120-paper ground truth set (60 relevant, 60 irrelevant) used throughout the ablation study.

---

## Experiment Setup

**Embedding model:** nomic-embed-text, Basic input fields (title + abstract + keywords + topics)

**Classification threshold:** cosine similarity = 0.500

**Dataset:** 120 papers (60 relevant, 60 irrelevant), manually labelled, topic: "attention mechanism in transformer models"

**Analysis:** ROC curve sweep (threshold 0 to 1 in steps of 0.005), score distribution histograms, and Pareto frontier for score-band routing (band boundaries in [0.30, 0.75] at 0.005 resolution).

---

## Results

### ROC Curve and Standalone Threshold Analysis

![Figure 1: ROC Curve — nomic-embed-text Stage-1](imgs/roc_curve.png)

**Figure 1.** ROC curve for nomic-embed-text on the 120-paper balanced dataset (AUC = 0.921). The red circle marks the Youden's J optimal threshold (t = 0.535); the grey diamond marks the threshold used in the best experimental configuration (t = 0.500). The current operating point lies on the plateau of the curve, achieving higher recall (TPR = 0.950) at the cost of substantially higher FPR (0.333) relative to the Youden-optimal point.

| Operating point | Threshold | TPR (Recall) | FPR | F1 |
|---|---|---|---|---|
| Youden's J optimal | 0.535 | 0.867 | 0.150 | 0.860 |
| Production threshold | 0.500 | 0.950 | 0.333 | 0.832 |

AUC = 0.921 confirms strong discriminative power for this topic. The Youden-optimal threshold t = 0.535 reduces FPR from 0.333 to 0.150 (from one in three irrelevant papers misclassified, to one in seven) while TPR decreases from 0.950 to 0.867. For a standalone classifier, t = 0.535 is objectively superior. However, for the two-stage architecture, the optimal Stage-1 threshold is not the standalone-optimal threshold: Stage 2 (Strict prompt) eliminates false positives at near-100% effectiveness but recovers false negatives at 0% effectiveness on the nomic-embed-text error set. The two-stage system benefits from a Stage-1 threshold biased toward high recall — accepting more FP because Stage 2 will correct them — rather than balanced TPR/FPR. The threshold of t = 0.500 is therefore retained.

---

### Score Distribution by Class

![Figure 2: Score Distribution by Label — nomic-embed-text](imgs/score_distribution.png)

**Figure 2.** Cosine similarity score distributions for relevant (blue, n = 60) and irrelevant (salmon, n = 60) papers. The grey dotted line marks the production classification threshold (t = 0.500); the red dashed line marks the Youden-optimal threshold (t = 0.535). The substantial overlap between the two distributions in the interval [0.457, 0.607] motivates the use of a two-stage LLM correction pass.

| Group | Min | Max | Mean | Median |
|---|---|---|---|---|
| Relevant | 0.457 | 0.749 | 0.610 | 0.605 |
| Irrelevant | 0.392 | 0.607 | 0.487 | 0.479 |
| Overlap zone | 0.457 | 0.607 | — | — |

The relevant papers are concentrated in the range 0.55–0.65 with a long tail down to 0.457. The irrelevant papers peak between 0.40 and 0.50, with a tail up to 0.607. The two distributions overlap substantially in [0.457, 0.607] — a width of 0.15. No single threshold can cleanly separate the two populations within this range, which is the fundamental justification for the two-stage architecture. The embedding model's uncertainty in the overlap zone is precisely what Stage-2 LLM judgment is designed to resolve.

---

### Coverage vs. Load: Score-Band Routing Pareto Analysis

![Figure 3: Coverage vs. Load — Band Routing (nomic-embed-text)](imgs/coverage_vs_load.png)

**Figure 3.** Coverage vs. Load curve for score-based band routing. The solid blue line is the Pareto frontier — the maximum achievable error coverage for each Stage-2 load level. The orange dashed line shows the symmetric band expansion around t = 0.535. The red star marks the oracle operating point (23/120 papers, 100% coverage), which lies above the Pareto frontier and is unreachable without ground-truth labels.

The Pareto frontier rises steeply from zero and reaches 100% error coverage at approximately 64% of the corpus (77 papers). The oracle routing point is at (19.2%, 100%) — forwarding only 23 papers with complete error coverage — but is unreachable without ground-truth labels.

| Routing strategy | Band | Stage-2 papers | % of corpus | Error coverage | Errors missed |
|---|---|---|---|---|---|
| Oracle (experimental) | — | 23 | 19.2% | 100% (23/23) | 0 |
| Band — full coverage | [0.455, 0.610) | 77 | 64.2% | 100% (23/23) | 0 |
| Band — high coverage | [0.480, 0.610) | 60 | 50.0% | 91.3% (21/23) | 2 FN |
| Band — standard coverage | [0.500, 0.610) | 50 | 41.7% | 87.0% (20/23) | 3 FN |

**Critical asymmetry in error score distribution:** All 20 Stage-1 false positive papers have scores in (0.500, 0.607] — above the threshold. All 3 Stage-1 false negative papers have scores in [0.457, 0.500) — below the threshold. This means:

- The **standard coverage band** [0.500, 0.610) excludes all 3 FN papers (score < 0.500) but captures all 20 FP papers. Since Stage-2 with Strict prompt achieves 0% FN recovery on the nomic-embed-text error set regardless of routing, these 3 FN papers would not have been corrected even under oracle routing. The standard band therefore achieves **functionally equivalent final output to oracle routing** — the same 3 FN remain and all 20 FP are submitted for correction — while requiring 50 papers instead of 23 (2.2× overhead).

- The **high coverage band** [0.480, 0.610) additionally captures FN papers with score in [0.480, 0.499], excluding only the 2 lowest-scoring FN papers. Since Stage-2 cannot recover nomic FN papers regardless, the practical improvement over the standard band is negligible.

- The **full coverage band** [0.455, 0.610) includes all 23 Stage-1 errors and sends 77 papers to Stage-2. It does not improve final recall beyond the standard band, as the recovered FN papers remain unresolvable by Stage-2.

---

## Key Findings

- **AUC = 0.921** confirms nomic-embed-text has strong discriminative power for the relevance classification task on this topic, but its score distributions overlap in [0.457, 0.607], making a single-threshold approach inherently limited in this range.

- **The Youden-optimal threshold (t = 0.535) is not optimal for the two-stage architecture.** It reduces FPR from 0.333 to 0.150 but also reduces recall from 0.950 to 0.867 — an undesirable trade-off given Stage 2 can correct FP but not FN. The threshold of t = 0.500 is retained for Stage 1.

- **The standard coverage band [0.500, 0.610) is functionally equivalent to oracle routing.** All 3 Stage-1 false negatives have scores below 0.500 (the lower bound) and would not be recovered by Stage 2 anyway; all 20 Stage-1 false positives have scores above 0.500 and are captured. Final precision and recall are identical to the experimental oracle result.

- **Production overhead is 2.2× oracle, not 3.3×.** The standard band sends 50 papers (vs. 23 under oracle) to Stage 2 — a manageable overhead that applies whether Stage 2 runs via a local LLM (Apple M1 via Ollama) or a cloud API.

- **The upper bound hi = 0.610 is topic-specific.** It is derived from the empirical maximum FP similarity score (0.607) plus a 0.003 buffer. For new topics, hi should be re-estimated by embedding known-irrelevant papers and setting hi = max(irrelevant scores) + 0.005. The lower bound lo = 0.500 is fixed to the Stage-1 classification threshold and remains valid across topics.

## Decision

Production routing band adopted: **[0.500, 0.610)**

- Papers with score < 0.500: classified as irrelevant by Stage 1, no LLM call
- Papers with score ≥ 0.610: classified as relevant by Stage 1, no LLM call
- Papers with score in [0.500, 0.610): forwarded to Stage-2 LLM (qwen3.5:2b, Prompt-Strict) for re-judgment

This band sends 50 of 120 papers (41.7%) to Stage 2 and achieves final F1 = 0.974, Precision = 1.000, Recall = 0.950 — functionally identical to the experimental oracle result. The lower bound is fixed; the upper bound should be re-calibrated per topic in production.
