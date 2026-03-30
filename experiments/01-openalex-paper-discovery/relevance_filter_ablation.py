"""
Relevance classification experiment — 14 methods vs ground truth
Topic: "attention mechanism in transformer models"
LLM:   ollama/qwen3.5:2b  (think=False)
Data:  groundtruth-balanced.json  (120 papers, 60 TP / 60 TN)
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

import click

from llama_index.core.base.embeddings.base import similarity as cosine_similarity
from llama_index.core.llms import ChatMessage
from llama_index.embeddings.litellm import LiteLLMEmbedding
from llama_index.llms.litellm import LiteLLM

# ── Config ─────────────────────────────────────────────────────────────────────

TOPIC              = "attention mechanism in transformer models"
RELEVANCE_KEYWORDS = {"attention", "transformer", "self-attention"}
_LLM_MODEL         = "ollama/qwen3.5:2b"
_API_BASE          = "http://localhost:11434"
_EMBED_THRESH      = 0.5
_LLM_WORKERS       = 3

_GT_PATH = __file__.replace("relevant-test.py", "groundtruth-balanced.json")
with open(_GT_PATH, encoding="utf-8") as _f:
    GROUND_TRUTH: list[dict] = json.load(_f)

_llm = LiteLLM(model=_LLM_MODEL, api_base=_API_BASE, temperature=0.0)
_embed_model_cache: dict[str, LiteLLMEmbedding] = {}
_embed_vec_cache:   dict[tuple[str, str], list[float]] = {}

# ── System prompts ─────────────────────────────────────────────────────────────

_SYS_NO_COT = (
    "You are a research paper relevance classifier. "
    "Given a research topic and paper metadata, decide if the paper is relevant. "
    "Do not make any assumptions; analyze objectively. "
    "Respond with exactly one word: yes or no."
)

_SYS_COT = (
    "You are a research paper relevance classifier. "
    "Given a research topic and paper metadata, reason step by step, "
    "then on the final line respond with exactly one word: yes or no. "
    "Do not make any assumptions; analyze objectively."
)

_SYS_LOOSE = (
    "You are a research paper relevance classifier. "
    "Given a research topic and paper metadata, decide if the paper is relevant. "
    "Include the paper if its abstract suggests transformers or attention mechanisms "
    "are discussed in a substantive way — not merely used as a black-box tool. "
    "Respond with exactly one word: yes or no."
)

_SYS_STRICT = (
    "You are a research paper relevance classifier conducting a literature survey. "
    "Research query: 'attention mechanism in transformer models'. "
    "A paper is relevant if its core contribution helps answer any of: "
    "(1) How does the attention mechanism work or what are its theoretical foundations? "
    "(2) How has attention been designed, improved, or made more efficient? "
    "(3) What are its known limitations or critical analyses? "
    "(4) What motivated alternatives to attention, and how do they relate back? "
    "(5) What important capabilities emerge from attention mechanisms, and why? "
    "A paper is NOT relevant if it merely uses transformers as a tool, "
    "or the connection is incidental. "
    "Heuristic: would this paper be cited in a survey on "
    "'attention mechanism in transformer models'? "
    "Respond with exactly one word: yes or no."
)

# ── Core helpers ───────────────────────────────────────────────────────────────

def _build_paper_text(
    paper: dict,
    *,
    primary_topic: bool = False,
    concepts: bool = False,
) -> str:
    """Concatenate paper fields into a single embedding input string."""
    parts = [paper["title"]]
    if abstract := (paper.get("abstract") or ""):
        parts.append(abstract)
    if kw := ", ".join(paper.get("keywords") or []):
        parts.append(kw)
    if topics := ", ".join(paper.get("topics") or []):
        parts.append(topics)
    if primary_topic:
        raw_pt = paper.get("primary_topic", "")
        pt = raw_pt.get("display_name", "") if isinstance(raw_pt, dict) else (raw_pt or "")
        if pt:
            parts.append(pt)
    if concepts:
        raw_c = paper.get("concepts", [])
        c_str = (
            ", ".join(c.get("display_name", "") for c in raw_c if c.get("display_name"))
            if raw_c and isinstance(raw_c[0], dict)
            else ", ".join(str(c) for c in raw_c)
        )
        if c_str:
            parts.append(c_str)
    return " ".join(parts)


def _build_user_message(
    paper: dict,
    *,
    primary_topic: bool = False,
    concepts: bool = False,
) -> str:
    """Build the LLM user message, optionally including extended metadata."""
    parts = [
        f"Topic: {TOPIC}",
        f"Title: {paper['title']}",
        f"Abstract: {paper.get('abstract') or '(none)'}",
        f"Keywords: {', '.join(paper.get('keywords') or []) or '(none)'}",
        f"Topics: {', '.join(paper.get('topics') or []) or '(none)'}",
    ]
    if primary_topic:
        raw_pt = paper.get("primary_topic", "")
        pt = raw_pt.get("display_name", "") if isinstance(raw_pt, dict) else (raw_pt or "")
        parts.append(f"Primary topic: {pt or '(none)'}")
    if concepts:
        raw_c = paper.get("concepts", [])
        c_str = (
            ", ".join(c.get("display_name", "") for c in raw_c if c.get("display_name"))
            if raw_c and isinstance(raw_c[0], dict)
            else ", ".join(str(c) for c in raw_c)
        )
        parts.append(f"Concepts: {c_str or '(none)'}")
    return "\n".join(parts)


def _llm_call(system: str, user: str, *, cot: bool = False) -> bool:
    """Call LLM and return True if the response starts with 'yes'."""
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user",   content=user),
    ]
    resp = _llm.chat(messages, extra_body={"think": False})
    raw = resp.message.content.strip().lower()
    if cot:
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        answer = lines[-1] if lines else ""
    else:
        answer = raw
    return answer.startswith("yes")


def _get_embed_model(model: str) -> LiteLLMEmbedding:
    if model not in _embed_model_cache:
        _embed_model_cache[model] = LiteLLMEmbedding(
            model_name=f"ollama/{model}", api_base=_API_BASE
        )
    return _embed_model_cache[model]


def _get_embedding(text: str, model: str) -> list[float]:
    """Return a cached embedding vector for the given (model, text) pair."""
    key = (model, text)
    if key not in _embed_vec_cache:
        time.sleep(0.1)
        _embed_vec_cache[key] = _get_embed_model(model).get_text_embedding(text)
    return _embed_vec_cache[key]

# ── Experiment factories ───────────────────────────────────────────────────────

def _make_llm_exp(
    system: str,
    *,
    primary_topic: bool = False,
    concepts: bool = False,
    cot: bool = False,
) -> Callable[[dict], bool]:
    """Return a single-paper LLM classifier with the given prompt settings."""
    def exp(paper: dict) -> bool:
        return _llm_call(
            system,
            _build_user_message(paper, primary_topic=primary_topic, concepts=concepts),
            cot=cot,
        )
    return exp


def _make_embedding_exp(
    model: str,
    *,
    primary_topic: bool = False,
    concepts: bool = False,
) -> Callable[[dict], bool]:
    """Return a single-paper embedding classifier for the given model and fields."""
    def exp(paper: dict) -> bool:
        topic_vec = _get_embedding(TOPIC, model)
        paper_vec = _get_embedding(
            _build_paper_text(paper, primary_topic=primary_topic, concepts=concepts),
            model,
        )
        return cosine_similarity(topic_vec, paper_vec) >= _EMBED_THRESH
    return exp


def _make_two_stage_exp(
    stage1_fn: Callable[[dict], bool],
    stage2_fn: Callable[[dict], bool],
    stage1_label: str,
) -> Callable[[list[dict], list[bool]], list[bool]]:
    """
    Return a two-stage classifier:
      Stage 1 — run stage1_fn on all papers; log per-stage metrics.
      Stage 2 — run stage2_fn only on Stage 1 errors (FP + FN); log per-stage metrics.
      Final   — keep Stage 1 correct predictions; replace errors with Stage 2.
    """
    def exp(papers: list[dict], labels: list[bool]) -> list[bool]:
        print(f"  [Stage 1] Running {stage1_label}...")
        stage1 = [stage1_fn(p) for p in papers]
        _print_stage_metrics("Stage 1", compute_metrics(stage1, labels))

        wrong_idx = [i for i, (pred, lbl) in enumerate(zip(stage1, labels)) if pred != lbl]
        print(f"  [Stage 1] Errors (FP+FN) = {len(wrong_idx)} → sending to LLM")

        stage2 = {i: stage2_fn(papers[i]) for i in wrong_idx}
        s2_preds  = [stage2[i] for i in wrong_idx]
        s2_labels = [labels[i] for i in wrong_idx]
        _print_stage_metrics("Stage 2", compute_metrics(s2_preds, s2_labels))

        return [stage2.get(i, stage1[i]) for i in range(len(papers))]
    return exp

# ── Experiment definitions ─────────────────────────────────────────────────────

# Embedding model shorthands
_NOMIC  = "nomic-embed-text"
_NOMIC2 = "nomic-embed-text-v2-moe"
_QWEN_S = "qwen3-embedding:0.6b"
_QWEN_M = "qwen3-embedding:4b"

# E01 — Keyword
def exp_kw_title(paper: dict) -> bool:
    """Keyword match on title: attention / transformer / self-attention."""
    return any(kw in paper["title"].lower() for kw in RELEVANCE_KEYWORDS)

# E02–E04 — LLM standalone
exp_llm_basic     = _make_llm_exp(_SYS_NO_COT)
exp_llm_basic_cot = _make_llm_exp(_SYS_COT, cot=True)
exp_llm_ext  = _make_llm_exp(_SYS_NO_COT, primary_topic=True, concepts=True)

# E05–E09 — Embedding standalone
exp_emb_nomic_basic  = _make_embedding_exp(_NOMIC)
exp_emb_nomic_ext    = _make_embedding_exp(_NOMIC,  primary_topic=True, concepts=True)
exp_emb_nomic_v2     = _make_embedding_exp(_NOMIC2)
exp_emb_qwen_s_basic = _make_embedding_exp(_QWEN_S)
exp_emb_qwen_m       = _make_embedding_exp(_QWEN_M)
exp_emb_qwen_s_ext   = _make_embedding_exp(_QWEN_S, primary_topic=True, concepts=True)

# LLM callables used only as Stage 2 in two-stage experiments
_llm_loose  = _make_llm_exp(_SYS_LOOSE,  primary_topic=True, concepts=True)
_llm_strict = _make_llm_exp(_SYS_STRICT, primary_topic=True, concepts=True)

# E10–E15 — Two-stage
exp_ts_qwen_s_ext_basic   = _make_two_stage_exp(exp_emb_qwen_s_ext,   exp_llm_ext, "Emb-QwenS-Ext")
exp_ts_qwen_s_ext_loose   = _make_two_stage_exp(exp_emb_qwen_s_ext,   _llm_loose,       "Emb-QwenS-Ext")
exp_ts_qwen_s_ext_strict  = _make_two_stage_exp(exp_emb_qwen_s_ext,   _llm_strict,      "Emb-QwenS-Ext")
exp_ts_nomic_basic_loose  = _make_two_stage_exp(exp_emb_nomic_basic,  _llm_loose,       "Emb-Nomic-Basic")
exp_ts_nomic_basic_strict = _make_two_stage_exp(exp_emb_nomic_basic,  _llm_strict,      "Emb-Nomic-Basic")
exp_ts_nomic_ext_strict   = _make_two_stage_exp(exp_emb_nomic_ext,    _llm_strict,      "Emb-Nomic-Ext")

# ── Experiment registry ────────────────────────────────────────────────────────

@dataclass
class Experiment:
    name:       str
    fn:         Callable
    sequential: bool = False   # True → paper-by-paper (embedding); False → ThreadPoolExecutor (LLM)
    two_stage:  bool = False   # True → fn(papers, labels); False → fn(paper)


EXPERIMENTS: list[Experiment] = [
    # ── Keyword ────────────────────────────────────────────────────────────────
    Experiment("E01 KW-Title",             exp_kw_title),
    # ── LLM standalone ─────────────────────────────────────────────────────────
    Experiment("E02 LLM-Basic",            exp_llm_basic),
    Experiment("E03 LLM-Basic-CoT",        exp_llm_basic_cot),
    Experiment("E04 LLM-Ext",              exp_llm_ext),
    # ── Embedding standalone ───────────────────────────────────────────────────
    Experiment("E05 Emb-Nomic-Basic",      exp_emb_nomic_basic,  sequential=True),
    Experiment("E06 Emb-Nomic-v2",         exp_emb_nomic_v2,     sequential=True),
    Experiment("E07 Emb-QwenS-Basic",      exp_emb_qwen_s_basic, sequential=True),
    Experiment("E08 Emb-QwenM",            exp_emb_qwen_m,       sequential=True),
    Experiment("E09 Emb-QwenS-Ext",        exp_emb_qwen_s_ext,   sequential=True),
    # ── Two-stage ──────────────────────────────────────────────────────────────
    Experiment("E10 TS-QwenS-Ext-Basic",   exp_ts_qwen_s_ext_basic,   two_stage=True),
    Experiment("E11 TS-QwenS-Ext-Loose",   exp_ts_qwen_s_ext_loose,   two_stage=True),
    Experiment("E12 TS-QwenS-Ext-Strict",  exp_ts_qwen_s_ext_strict,  two_stage=True),
    Experiment("E13 TS-Nomic-Basic-Loose",  exp_ts_nomic_basic_loose,  two_stage=True),
    Experiment("E14 TS-Nomic-Basic-Strict", exp_ts_nomic_basic_strict, two_stage=True),
    Experiment("E15 TS-Nomic-Ext-Strict",   exp_ts_nomic_ext_strict,   two_stage=True),
]

# ── Evaluation ─────────────────────────────────────────────────────────────────

def compute_metrics(preds: list[bool], labels: list[bool]) -> dict:
    tp = sum(p and l     for p, l in zip(preds, labels))
    fp = sum(p and not l for p, l in zip(preds, labels))
    fn = sum(not p and l for p, l in zip(preds, labels))
    tn = sum(not p and not l for p, l in zip(preds, labels))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy  = (tp + tn) / len(preds) if preds else 0.0
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "Precision": precision, "Recall": recall, "F1": f1, "Accuracy": accuracy}


def _run_parallel(fn: Callable, papers: list[dict]) -> tuple[list[bool], float]:
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=_LLM_WORKERS) as pool:
        futures = {pool.submit(fn, p): i for i, p in enumerate(papers)}
        results = [None] * len(papers)
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
    return results, time.time() - t0


def _run_sequential(fn: Callable, papers: list[dict]) -> tuple[list[bool], float]:
    t0 = time.time()
    return [fn(p) for p in papers], time.time() - t0


def _fmt_metrics(metrics: dict) -> str:
    return (
        f"TP={metrics['TP']} FP={metrics['FP']} FN={metrics['FN']} TN={metrics['TN']}  "
        f"Prec={metrics['Precision']:.3f}  Rec={metrics['Recall']:.3f}  "
        f"F1={metrics['F1']:.3f}  Acc={metrics['Accuracy']:.3f}"
    )


def _print_metrics(metrics: dict, elapsed: float) -> None:
    print(f"  Time : {elapsed:.1f}s")
    print(f"  {_fmt_metrics(metrics)}")


def _print_stage_metrics(label: str, metrics: dict) -> None:
    print(f"  [{label}] {_fmt_metrics(metrics)}")


_EXPERIMENT_FILTER: dict[str, Callable[[list["Experiment"]], list["Experiment"]]] = {
    "all":       lambda exps: exps,
    "one-stage": lambda exps: [e for e in exps if not e.two_stage],
    "two-stage": lambda exps: [e for e in exps if e.two_stage],
}


@click.command()
@click.option(
    "--run-test",
    "run_test",
    type=click.Choice(list(_EXPERIMENT_FILTER)),
    default="all",
    show_default=True,
    help="Select which experiment subset to run.",
)
def main(run_test: str) -> None:
    labels = [p["relevant"] for p in GROUND_TRUTH]
    experiments = _EXPERIMENT_FILTER[run_test](EXPERIMENTS)
    print(f"\nGround truth: {len(GROUND_TRUTH)} papers  "
          f"(relevant={sum(labels)}, irrelevant={len(labels) - sum(labels)})")
    print(f"Running subset: {run_test!r}  ({len(experiments)} experiments)")
    print("=" * 80)

    all_results: list[tuple[str, dict, float]] = []

    for exp in experiments:
        print(f"\nRunning {exp.name} ...")
        if exp.two_stage:
            t0 = time.time()
            preds = exp.fn(GROUND_TRUTH, labels)
            elapsed = time.time() - t0
        elif exp.sequential:
            preds, elapsed = _run_sequential(exp.fn, GROUND_TRUTH)
        else:
            preds, elapsed = _run_parallel(exp.fn, GROUND_TRUTH)
        metrics = compute_metrics(preds, labels)
        all_results.append((exp.name, metrics, elapsed))
        _print_metrics(metrics, elapsed)

    # ── Summary table ──────────────────────────────────────────────────────────
    print("\n\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    header = (f"{'Method':<26} {'Time':>6}  "
              f"{'TP':>4} {'FP':>4} {'FN':>4} {'TN':>4}  "
              f"{'Prec':>6} {'Rec':>6} {'F1':>6} {'Acc':>6}")
    print(header)
    print("-" * len(header))
    for name, m, elapsed in all_results:
        print(f"{name:<26} {elapsed:>5.1f}s"
              f"  {m['TP']:>4} {m['FP']:>4} {m['FN']:>4} {m['TN']:>4}"
              f"  {m['Precision']:>6.3f} {m['Recall']:>6.3f}"
              f"  {m['F1']:>6.3f} {m['Accuracy']:>6.3f}")


if __name__ == "__main__":
    main()
