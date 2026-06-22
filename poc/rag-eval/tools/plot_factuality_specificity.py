import matplotlib.pyplot as plt
import matplotlib.lines as mlines

configs = [
    ("vlm",                   16.427, 0.787),
    ("rag_fixed_queries",     17.453, 0.945),
    ("rag_with_expansion",    20.134, 0.889),
    ("rag_winner_no_filter",  17.759, 0.925),
]

colors  = ["#E67E22", "#2ECC71", "#3498DB", "#9B59B6"]
markers = ["o", "s", "^", "D"]

fig, ax = plt.subplots(figsize=(9, 6))

# scatter points — collect handles for legend
scatter_handles = []
for (label, x, y), color, marker in zip(configs, colors, markers):
    h = ax.scatter(x, y, color=color, marker=marker, s=160, zorder=5, label=label)
    scatter_handles.append(h)

# per-point labels — tight to each marker
# ha='right' for rag_with_expansion: text right-aligns at xytext, extending leftward toward the triangle
label_cfg = {
    "vlm":                  dict(xytext=(16.427 + 0.15, 0.787 - 0.013), ha="left",  va="top"),
    "rag_fixed_queries":    dict(xytext=(17.453 + 0.15, 0.945 + 0.007), ha="left",  va="bottom"),
    "rag_winner_no_filter": dict(xytext=(17.759 + 0.15, 0.925 + 0.005), ha="left",  va="bottom"),
    "rag_with_expansion":   dict(xytext=(20.134, 0.889 + 0.013), ha="center", va="bottom"),
}
for (label, x, y), color in zip(configs, colors):
    kw = label_cfg[label]
    ax.annotate(label, (x, y), fontsize=9, color=color, fontweight="bold",
                annotation_clip=False, **kw)

# Pareto frontier — direct polyline connecting non-dominated points sorted by x
# Non-dominated: rag_fixed_queries, rag_winner_no_filter, rag_with_expansion (vlm is dominated)
frontier = sorted(
    [(17.453, 0.945), (17.759, 0.925), (20.134, 0.889)],
    key=lambda p: p[0]
)
fx = [p[0] for p in frontier]
fy = [p[1] for p in frontier]
ax.plot(fx, fy, color="gray", linestyle="--", linewidth=1.5, alpha=0.7, zorder=3)

# legend: all 4 configs + Pareto frontier line
pareto_handle = mlines.Line2D([], [], color="gray", linestyle="--",
                               linewidth=1.5, alpha=0.7, label="Pareto frontier")
ax.legend(
    handles=scatter_handles + [pareto_handle],
    loc="lower right",
    fontsize=8,
    framealpha=0.92,
    edgecolor="lightgray",
    markerscale=0.55,
)

# axis limits
x_min, x_max = 15.2, 21.2
y_min, y_max = 0.74, 0.97
ax.set_xlim(x_min, x_max)
ax.set_ylim(y_min, y_max)

# only BEST (top-right) and WORST (bottom-left) — avoids bottom-right legend conflict
ax.text(x_max - 0.15, y_max - 0.005, "BEST ✓", ha="right", va="top",
        fontsize=8, color="green", alpha=0.6)
ax.text(x_min + 0.15, y_min + 0.005, "WORST", ha="left", va="bottom",
        fontsize=8, color="darkred", alpha=0.6)

ax.set_xlabel("avg_specificity  (specific claims per 1,000 output tokens)", fontsize=11)
ax.set_ylabel("avg_factuality  (fraction of claims verified against paper)", fontsize=11)
ax.set_title("VLM vs RAG Summarization — Factuality × Specificity\n(top-right = best)", fontsize=12)
ax.grid(True, linestyle="--", alpha=0.3)

plt.tight_layout()
output_path = "/Users/chunming/MyWorkSpace/agent_workspace/research-agent/research-agent-docling-rag-pipeline/poc/rag-eval/imgs/factuality_vs_specificity.png"
plt.savefig(output_path, dpi=150, bbox_inches="tight")
print(f"Saved: {output_path}")
