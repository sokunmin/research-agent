"""
Threshold analysis for Stage-1 embedding model (nomic-embed-text).

Standard approach:
  1. ROC curve        — find optimal single threshold via Youden's J statistic
  2. Precision-Recall curve — visualise precision/recall trade-off
  3. Score distribution     — per-label histogram to confirm overlap zone
  4. Coverage vs Load curve — band equivalent of ROC for Stage-2 routing decision

Scores are cached to disk so subsequent runs skip re-embedding.
"""
import json
import time
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from llama_index.core.base.embeddings.base import similarity as cosine_similarity
from llama_index.embeddings.litellm import LiteLLMEmbedding

# ── Config ────────────────────────────────────────────────────────────────────

TOPIC    = "attention mechanism in transformer models"
MODEL    = "nomic-embed-text"
API_BASE = "http://localhost:11434"
GT_PATH  = Path(__file__).with_name("groundtruth-balanced.json")
OUT_DIR  = Path(__file__).parent
CACHE_PATH = OUT_DIR / "scores_cache.json"

THRESHOLDS = np.round(np.arange(0.0, 1.001, 0.005), 3)

# ── Data ──────────────────────────────────────────────────────────────────────

with GT_PATH.open(encoding="utf-8") as f:
    PAPERS: list[dict] = json.load(f)
LABELS: list[bool] = [p["relevant"] for p in PAPERS]

# ── Embedding (with disk cache) ───────────────────────────────────────────────

def _build_paper_text(paper: dict) -> str:
    parts = [paper["title"]]
    if abstract := (paper.get("abstract") or ""):
        parts.append(abstract)
    if kw := ", ".join(paper.get("keywords") or []):
        parts.append(kw)
    if topics := ", ".join(paper.get("topics") or []):
        parts.append(topics)
    return " ".join(parts)


def load_or_compute_scores() -> list[float]:
    if CACHE_PATH.exists():
        cached = json.loads(CACHE_PATH.read_text())
        if cached.get("model") == MODEL and cached.get("topic") == TOPIC:
            print(f"[Cache] Loaded scores from {CACHE_PATH.name}")
            return cached["scores"]

    print(f"Embedding {len(PAPERS)} papers with '{MODEL}' ...")
    embed = LiteLLMEmbedding(model_name=f"ollama/{MODEL}", api_base=API_BASE)
    t0 = time.time()
    topic_vec = embed.get_text_embedding(TOPIC)
    scores = []
    for i, paper in enumerate(PAPERS):
        time.sleep(0.05)
        vec = embed.get_text_embedding(_build_paper_text(paper))
        scores.append(cosine_similarity(topic_vec, vec))
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(PAPERS)} ({time.time()-t0:.0f}s)")
    print(f"Embedding complete in {time.time()-t0:.1f}s")

    CACHE_PATH.write_text(json.dumps({"model": MODEL, "topic": TOPIC, "scores": scores}))
    print(f"[Cache] Scores saved to {CACHE_PATH.name}")
    return scores

# ── Metrics at a given threshold ──────────────────────────────────────────────

def _metrics_at(scores: list[float], labels: list[bool], t: float) -> dict:
    tp = fp = fn = tn = 0
    for s, l in zip(scores, labels):
        pred = s >= t
        if pred and l:      tp += 1
        elif pred and not l: fp += 1
        elif not pred and l: fn += 1
        else:               tn += 1
    prec = tp / (tp + fp) if (tp + fp) else 1.0   # no positives → define prec=1
    rec  = tp / (tp + fn) if (tp + fn) else 0.0
    fpr  = fp / (fp + tn) if (fp + tn) else 0.0
    f1   = 2*prec*rec / (prec+rec) if (prec+rec) else 0.0
    return dict(tp=tp, fp=fp, fn=fn, tn=tn,
                precision=prec, recall=rec, fpr=fpr, f1=f1, errors=fp+fn)

# ── Plot 1: ROC curve ─────────────────────────────────────────────────────────

def plot_roc_curve(scores: list[float], labels: list[bool], out_path: Path) -> float:
    """
    ROC curve (TPR vs FPR). Optimal threshold via Youden's J = TPR − FPR.
    Returns the optimal threshold.
    """
    sweep = {t: _metrics_at(scores, labels, t) for t in THRESHOLDS}

    fprs = [sweep[t]["fpr"]    for t in THRESHOLDS]
    tprs = [sweep[t]["recall"] for t in THRESHOLDS]
    auc  = float(-np.trapezoid(tprs, fprs))        # integrates L→R; negate for R→L

    # Youden's J: max(TPR − FPR)
    j_scores = {t: sweep[t]["recall"] - sweep[t]["fpr"] for t in THRESHOLDS}
    best_t   = max(j_scores, key=j_scores.get)
    m        = sweep[best_t]

    print(f"\n[ROC] AUC = {auc:.4f}")
    print(f"[ROC] Optimal threshold (Youden's J): {best_t:.3f}  "
          f"TPR={m['recall']:.3f}  FPR={m['fpr']:.3f}  F1={m['f1']:.3f}")
    print(f"[ROC] At current threshold (0.500):   "
          f"TPR={sweep[0.5]['recall']:.3f}  FPR={sweep[0.5]['fpr']:.3f}  "
          f"F1={sweep[0.5]['f1']:.3f}")

    fig, ax = plt.subplots(figsize=(7, 6))
    ax.plot(fprs, tprs, color="steelblue", linewidth=2, label=f"ROC curve (AUC = {auc:.3f})")
    ax.plot([0, 1], [0, 1], color="gray", linestyle="--", linewidth=1, label="Random")

    # mark optimal (Youden's J)
    ax.scatter(m["fpr"], m["recall"], color="red", s=100, zorder=5,
               label=f"Youden's J optimal (t={best_t:.3f})")
    ax.annotate(f"t={best_t:.3f}\nTPR={m['recall']:.2f}\nFPR={m['fpr']:.2f}",
                xy=(m["fpr"], m["recall"]), xytext=(m["fpr"]+0.06, m["recall"]-0.12),
                arrowprops=dict(arrowstyle="->", color="red"), fontsize=8, color="red")

    # mark current threshold
    c = sweep[0.5]
    ax.scatter(c["fpr"], c["recall"], color="gray", s=80, zorder=5, marker="D",
               label=f"Current t=0.500")

    ax.set_xlabel("False Positive Rate (FPR = FP / (FP+TN))")
    ax.set_ylabel("True Positive Rate (TPR = Recall)")
    ax.set_title("ROC Curve — nomic-embed-text Stage-1")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[Plot] Saved → {out_path}")
    return best_t

# ── Plot 2: Precision-Recall curve ────────────────────────────────────────────

def plot_pr_curve(scores: list[float], labels: list[bool], out_path: Path) -> None:
    sweep = {t: _metrics_at(scores, labels, t) for t in THRESHOLDS}

    # sort by recall ascending for a clean PR curve
    points = sorted([(sweep[t]["recall"], sweep[t]["precision"], t) for t in THRESHOLDS])
    rcs = [p[0] for p in points]
    prs = [p[1] for p in points]

    best_f1_t = max(sweep, key=lambda t: sweep[t]["f1"])
    m = sweep[best_f1_t]

    # iso-F1 curves
    fig, ax = plt.subplots(figsize=(7, 6))
    for f1_val in [0.6, 0.7, 0.8, 0.9]:
        r_vals = np.linspace(0.01, 1, 200)
        p_vals = f1_val * r_vals / (2 * r_vals - f1_val)
        mask   = (p_vals >= 0) & (p_vals <= 1)
        ax.plot(r_vals[mask], p_vals[mask], color="lightgray",
                linestyle=":", linewidth=1)
        ax.text(r_vals[mask][-1]-0.02, p_vals[mask][-1]+0.01,
                f"F1={f1_val}", fontsize=7, color="gray")

    ax.plot(rcs, prs, color="steelblue", linewidth=2, label="PR curve")

    # best F1 point
    ax.scatter(m["recall"], m["precision"], color="red", s=100, zorder=5,
               label=f"Best F1={m['f1']:.3f} (t={best_f1_t:.3f})")
    ax.annotate(f"t={best_f1_t:.3f}\nP={m['precision']:.2f}\nR={m['recall']:.2f}",
                xy=(m["recall"], m["precision"]),
                xytext=(m["recall"]-0.18, m["precision"]-0.1),
                arrowprops=dict(arrowstyle="->", color="red"), fontsize=8, color="red")

    # current threshold
    c = sweep[0.5]
    ax.scatter(c["recall"], c["precision"], color="gray", s=80, zorder=5, marker="D",
               label=f"Current t=0.500  F1={c['f1']:.3f}")

    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_xlim(0, 1.05)
    ax.set_ylim(0, 1.05)
    ax.set_title("Precision-Recall Curve — nomic-embed-text Stage-1")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[Plot] Saved → {out_path}")

# ── Plot 3: Score distribution ────────────────────────────────────────────────

def plot_score_distribution(scores: list[float], labels: list[bool],
                            best_t: float, out_path: Path) -> None:
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]

    print(f"\n[Scores] Relevant   min={min(pos):.3f}  max={max(pos):.3f}"
          f"  mean={np.mean(pos):.3f}  median={np.median(pos):.3f}")
    print(f"[Scores] Irrelevant min={min(neg):.3f}  max={max(neg):.3f}"
          f"  mean={np.mean(neg):.3f}  median={np.median(neg):.3f}")

    fig, ax = plt.subplots(figsize=(10, 4))
    bins = np.linspace(0.3, 0.8, 51)
    ax.hist(pos, bins=bins, alpha=0.6, color="steelblue", label=f"Relevant (n={len(pos)})")
    ax.hist(neg, bins=bins, alpha=0.6, color="salmon",    label=f"Irrelevant (n={len(neg)})")
    ax.axvline(0.5,    color="gray", linestyle=":",  linewidth=1.5, label="Current t=0.500")
    ax.axvline(best_t, color="red",  linestyle="--", linewidth=1.5, label=f"Optimal t={best_t:.3f}")
    ax.set_xlabel("Cosine similarity to topic")
    ax.set_ylabel("Paper count")
    ax.set_title("Score Distribution by Label — nomic-embed-text")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[Plot] Saved → {out_path}")

# ── Plot 4: Coverage vs Load (band Pareto frontier) ───────────────────────────

def plot_coverage_vs_load(scores: list[float], labels: list[bool],
                          best_t: float, out_path: Path) -> None:
    """
    For each possible band [lo, hi] (symmetric around best_t or asymmetric),
    plot Pareto frontier: error coverage (Y) vs Stage-2 load (X = band_size/total).

    Also plots:
      - Symmetric expansion curve (lo = best_t - w, hi = best_t + w)
      - Current E14 operating point (threshold=0.5, sends only known errors)
    """
    n_total  = len(scores)
    preds_05 = [s >= 0.5 for s in scores]
    error_idx = {i for i, (p, l) in enumerate(zip(preds_05, labels)) if p != l}
    n_errors  = len(error_idx)

    # ── Pareto frontier from full (lo, hi) sweep ──
    band_steps = np.round(np.arange(0.3, 0.75, 0.005), 3)
    pareto_points: dict[int, float] = {}   # load_count → max coverage

    for lo in band_steps:
        for hi in band_steps:
            if hi <= lo:
                continue
            in_band  = {i for i, s in enumerate(scores) if lo <= s < hi}
            covered  = len(in_band & error_idx)
            load     = len(in_band)
            cov_rate = covered / n_errors
            if load not in pareto_points or cov_rate > pareto_points[load]:
                pareto_points[load] = cov_rate

    loads_pareto = sorted(pareto_points)
    # keep only non-dominated points (increasing coverage as load increases)
    frontier_x, frontier_y = [], []
    max_cov = -1.0
    for l in loads_pareto:
        c = pareto_points[l]
        if c > max_cov:
            frontier_x.append(l / n_total)
            frontier_y.append(c)
            max_cov = c

    # ── Symmetric expansion around best_t ──
    half_widths = np.round(np.arange(0.0, 0.25, 0.005), 3)
    sym_loads, sym_covs = [], []
    for w in half_widths:
        lo, hi  = round(best_t - w, 3), round(best_t + w, 3)
        in_band = {i for i, s in enumerate(scores) if lo <= s < hi}
        covered = len(in_band & error_idx)
        sym_loads.append(len(in_band) / n_total)
        sym_covs.append(covered / n_errors)

    # ── Print key points ──
    full_cov_load = next(
        (frontier_x[i] for i, c in enumerate(frontier_y) if c >= 1.0), None
    )
    print(f"\n[Band] Minimum Stage-2 load for 100% error coverage: "
          f"{full_cov_load*100:.1f}% of corpus "
          f"({int(full_cov_load*n_total)} papers)" if full_cov_load else
          f"\n[Band] 100% coverage not achievable in swept range")

    # find 80%, 90% coverage on Pareto frontier
    for target in [0.80, 0.90, 1.00]:
        pts = [(x, y) for x, y in zip(frontier_x, frontier_y) if y >= target]
        if pts:
            x, y = pts[0]
            print(f"[Band] {target*100:.0f}% coverage → load={x*100:.1f}% "
                  f"({int(x*n_total)} papers)")

    # ── Plot ──
    fig, ax = plt.subplots(figsize=(8, 6))

    ax.plot(frontier_x, frontier_y, color="steelblue", linewidth=2,
            label="Pareto frontier (best coverage per load)")
    ax.plot(sym_loads, sym_covs, color="darkorange", linewidth=1.5,
            linestyle="--", label=f"Symmetric band around t={best_t:.3f}")

    # 100% coverage line
    ax.axhline(1.0, color="green", linestyle=":", linewidth=1, alpha=0.7,
               label="100% error coverage")

    # current E14 operating point (oracle routing: 23 errors, load=23/120)
    e14_load = n_errors / n_total
    ax.scatter(e14_load, 1.0, color="red", s=120, zorder=6, marker="*",
               label=f"E14 oracle point ({n_errors}/{n_total} papers)")
    ax.annotate(f"E14 (oracle)\n{n_errors} papers",
                xy=(e14_load, 1.0), xytext=(e14_load+0.04, 0.92),
                arrowprops=dict(arrowstyle="->", color="red"), fontsize=8, color="red")

    ax.set_xlabel("Stage-2 Load (fraction of corpus sent to LLM)")
    ax.set_ylabel("Error Coverage (fraction of Stage-1 errors in band)")
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.08)
    ax.set_title("Coverage vs Load — Band Threshold Selection\n"
                 "(nomic-embed-text, Stage-1 errors at t=0.5)")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # secondary x-axis: absolute paper count
    ax2 = ax.secondary_xaxis("top",
                              functions=(lambda x: x * n_total,
                                         lambda x: x / n_total))
    ax2.set_xlabel("Papers sent to Stage-2 (absolute)")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()
    print(f"[Plot] Saved → {out_path}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    scores = load_or_compute_scores()

    # 1. ROC curve → optimal threshold
    best_t = plot_roc_curve(scores, LABELS, OUT_DIR / "plot_roc_curve.png")

    # 2. PR curve
    plot_pr_curve(scores, LABELS, OUT_DIR / "plot_pr_curve.png")

    # 3. Score distribution
    plot_score_distribution(scores, LABELS, best_t,
                            OUT_DIR / "plot_score_distribution.png")

    # 4. Coverage vs Load (band selection)
    plot_coverage_vs_load(scores, LABELS, best_t,
                          OUT_DIR / "plot_coverage_vs_load.png")


if __name__ == "__main__":
    main()
