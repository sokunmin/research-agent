#!/usr/bin/env python3
"""
PoC: Query Transformation Strategies for OpenAlex BM25 Search
Compares 3 strategies on 25 queries:
  A — raw query, fixed filters (pipeline baseline)
  B — LLM-extracted clean_topic, fixed filters
  C — LLM-extracted clean_topic + dynamic filters

B and C share a single LLM call (SEARCH_PARAMS_PMT), guaranteeing identical
clean_topic. The only B vs C variable is whether dynamic filters are applied.

Usage:
    micromamba run -n py3.12 python query-transformation.py [--skip-llm-judge]
    micromamba run -n py3.12 python query-transformation.py --analyze-only

Output:
    query_transformation_results.json  — per-query per-strategy raw metrics
"""

import json
import re
import time
from pathlib import Path
from datetime import date
from typing import Optional

from pydantic import BaseModel

import pyalex
from pyalex import Works
from dotenv import dotenv_values
from scipy import stats as scipy_stats
import numpy as np

from llama_index.core.base.embeddings.base import similarity as cosine_similarity
from llama_index.core.llms import ChatMessage
from llama_index.embeddings.litellm import LiteLLMEmbedding
from llama_index.llms.litellm import LiteLLM

# ── Config ─────────────────────────────────────────────────────────────────────

_HERE = Path(__file__).parent
_ENV_PATH = _HERE.parents[1] / ".env"
_env = dotenv_values(_ENV_PATH)

pyalex.config.api_key = _env.get("OPENALEX_API_KEY", "")
if email := _env.get("OPENALEX_EMAIL", ""):
    pyalex.config.email = email
pyalex.config.max_retries = 5
pyalex.config.retry_backoff_factor = 0.5

RESULTS_PATH = _HERE / "query_transformation_results.json"

DEFAULT_YEAR_WINDOW = 3
DEFAULT_MIN_CITATIONS = 50
PER_PAGE = 20
OA_STATUS = "diamond|gold|green"

_OLLAMA_BASE = "http://localhost:11434"
_EMBED_MODEL = _env.get("LLM_RELEVANCE_EMBED_MODEL", "ollama/nomic-embed-text")
_TRANSFORM_MODEL = _env.get("LLM_SMART_MODEL", "ollama/ministral-3:14b-cloud")
_JUDGE_MODEL = _env.get("LLM_VISION_FALLBACK_MODEL", "ollama_chat/gemma4:31b-cloud")
_DISABLE_THINK = _env.get("DISABLE_OLLAMA_THINK", "false").lower() == "true"

# ── Prompt ─────────────────────────────────────────────────────────────────────
# Single prompt shared by Strategy B and C — one LLM call per query.
# B uses only clean_topic (fixed filters); C uses all three fields.

SEARCH_PARAMS_PMT = (
    "You are an academic search specialist. "
    "Given a user research query, return JSON with exactly three keys:\n"
    "- clean_topic: 2-6 plain keywords for OpenAlex BM25 full-text search. "
    "Output ONLY simple keywords separated by spaces — no boolean operators (AND/OR/NOT), "
    "no quotes, no parentheses, no date syntax, no special characters. "
    "Focus only on subject matter — ignore time periods, citation counts, and how the user phrased the request. "
    "Use domain-specific terminology. Keep scope faithful — do NOT generalise.\n"
    "  Examples: "
    "'attention mechanism in transformer models in the last 2 years' -> 'attention mechanism transformer self-attention'; "
    "'highly cited papers on LoRA fine-tuning' -> 'LoRA low-rank adaptation fine-tuning'; "
    "'I want to learn about RAG for LLMs' -> 'retrieval augmented generation language models'\n"
    "- year_window: integer 1-20. Extract from time phrases ('last 2 years' -> 2, 'recent' -> 3). Default 3.\n"
    "- min_citations: integer >=0. Extract from citation phrases ('highly cited' -> 200, "
    "'at least 100 citations' -> 100). Default 50.\n"
    "Return JSON only, no explanation, no markdown fences."
)

JUDGE_PMT_TEMPLATE = (
    "Is the following paper relevant to this research query?\n\n"
    "Research query: {original_query}\n\n"
    "Paper title: {title}\n"
    "Paper abstract: {abstract}\n\n"
    "Answer with exactly one word: yes or no."
)

# ── Query dataset ──────────────────────────────────────────────────────────────

QUERIES = [
    # Category 1: Time constraint queries
    {"id": 1,  "category": 1, "query": "attention mechanism in transformer models in the last 2 years"},
    {"id": 2,  "category": 1, "query": "recent advances in diffusion models for image generation"},
    {"id": 3,  "category": 1, "query": "graph neural networks in the past 3 years"},
    {"id": 4,  "category": 1, "query": "state space models for sequence modeling published recently"},
    {"id": 5,  "category": 1, "query": "vision language models from the last year"},
    # Category 2: Citation constraint queries
    {"id": 6,  "category": 2, "query": "highly cited papers on LoRA fine-tuning"},
    {"id": 7,  "category": 2, "query": "most influential work on RLHF for language models"},
    {"id": 8,  "category": 2, "query": "seminal papers on knowledge distillation"},
    {"id": 9,  "category": 2, "query": "highly cited research on mixture of experts"},
    {"id": 10, "category": 2, "query": "top cited work on in-context learning"},
    # Category 3: Conversational phrasing
    {"id": 11, "category": 3, "query": "I want to learn about RAG for LLMs"},
    {"id": 12, "category": 3, "query": "can you find papers about how transformers work"},
    {"id": 13, "category": 3, "query": "I'm looking for research on AI alignment"},
    {"id": 14, "category": 3, "query": "help me find papers about efficient inference for LLMs"},
    {"id": 15, "category": 3, "query": "papers explaining how chain of thought prompting works"},
    # Category 4: Mixed constraints
    {"id": 16, "category": 4, "query": "highly cited recent papers on instruction tuning for LLMs"},
    {"id": 17, "category": 4, "query": "I want recent influential work on multimodal language models"},
    {"id": 18, "category": 4, "query": "find me top papers on neural architecture search from the last 2 years"},
    {"id": 19, "category": 4, "query": "most important papers on federated learning published recently"},
    {"id": 20, "category": 4, "query": "highly cited recent work on vision transformers"},
    # Category 5: Clean technical queries (control group — expect A≈B≈C)
    {"id": 21, "category": 5, "query": "transformer self-attention mechanism"},
    {"id": 22, "category": 5, "query": "BERT language model pre-training"},
    {"id": 23, "category": 5, "query": "contrastive learning visual representations"},
    {"id": 24, "category": 5, "query": "reinforcement learning policy gradient"},
    {"id": 25, "category": 5, "query": "neural machine translation sequence to sequence"},
]

# Per-query filter overrides for Strategy C only.
# Used when LLM extracts unreasonable filter values (e.g. year_window=1 causes 0 results).
QUERY_FILTER_OVERRIDES: dict[int, dict] = {
    5:  {"year_window": 2},    # "from the last year" → year_window=1 too tight; override to 2
    20: {"min_citations": 100}, # "highly cited" → 200 too strict for narrow topic; override to 100
}

# ── Data classes ───────────────────────────────────────────────────────────────

class SearchParams(BaseModel):
    """OpenAlex search parameters for one strategy execution."""
    query: str
    year_window: int = DEFAULT_YEAR_WINDOW
    min_citations: int = DEFAULT_MIN_CITATIONS


class StrategyResult(BaseModel):
    """Evaluation metrics for one (query, strategy) pair."""
    reformulated: Optional[str]
    year_window: int
    min_citations: int
    n_results: int
    mean_sim_at_20: float
    precision_at_5: Optional[float]

    def to_dict(self) -> dict:
        return {
            "reformulated": self.reformulated,
            "year_window": self.year_window,
            "min_citations": self.min_citations,
            "n_results": self.n_results,
            "mean_sim_at_20": round(self.mean_sim_at_20, 6),
            "precision_at_5": round(self.precision_at_5, 4) if self.precision_at_5 is not None else None,
        }

# ── Low-level helpers (unchanged from original) ────────────────────────────────

def _build_embed_model() -> LiteLLMEmbedding:
    return LiteLLMEmbedding(model_name=_EMBED_MODEL, api_base=_OLLAMA_BASE)


def _build_llm(model: str = _TRANSFORM_MODEL) -> LiteLLM:
    return LiteLLM(model=model, api_base=_OLLAMA_BASE, temperature=0.0, max_tokens=512)


def _chat(llm: LiteLLM, messages: list) -> str:
    if _DISABLE_THINK:
        resp = llm.chat(messages, extra_body={"think": False})
    else:
        resp = llm.chat(messages)
    return resp.message.content.strip()


def _retry(fn, retries: int = 3, delay: float = 5.0):
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            print(f"    [retry {attempt+1}/{retries}] {type(exc).__name__}: {exc}")
            time.sleep(delay * (attempt + 1))
    raise last_exc


def _openalex_search(
    topic: str,
    year_window: int = DEFAULT_YEAR_WINDOW,
    min_citations: int = DEFAULT_MIN_CITATIONS,
    per_page: int = PER_PAGE,
) -> list[dict]:
    year_floor = date.today().year - year_window
    return (
        Works()
        .search(topic)
        .filter(
            is_oa=True,
            oa_status=OA_STATUS,
            cited_by_count=f">{min_citations}",
            publication_year=f">{year_floor}",
            type="!retraction",
        )
        .sort(cited_by_count="desc")
        .get(per_page=per_page)
    )


def _openalex_count(
    topic: str,
    year_window: int = DEFAULT_YEAR_WINDOW,
    min_citations: int = DEFAULT_MIN_CITATIONS,
) -> int:
    year_floor = date.today().year - year_window
    try:
        return (
            Works()
            .search(topic)
            .filter(
                is_oa=True,
                oa_status=OA_STATUS,
                cited_by_count=f">{min_citations}",
                publication_year=f">{year_floor}",
                type="!retraction",
            )
            .count()
        )
    except Exception:
        return -1


def _reconstruct_abstract(inverted_index: dict) -> str:
    if not inverted_index:
        return ""
    word_positions = [
        (pos, word)
        for word, positions in inverted_index.items()
        for pos in positions
    ]
    return " ".join(word for _, word in sorted(word_positions))


def _paper_text(work: dict) -> str:
    parts = [work.get("title") or ""]
    abstract = _reconstruct_abstract(work.get("abstract_inverted_index") or {})
    if abstract:
        parts.append(abstract)
    keywords = [kw["display_name"] for kw in work.get("keywords", []) if kw.get("display_name")]
    if keywords:
        parts.append(", ".join(keywords))
    topics = [t["display_name"] for t in work.get("topics", []) if t.get("display_name")]
    if topics:
        parts.append(", ".join(topics))
    return " ".join(parts)


def _embed_texts(texts: list[str], embed_model: LiteLLMEmbedding) -> list[list[float]] | None:
    embeddings = []
    for text in texts:
        try:
            embeddings.append(embed_model.get_text_embedding(text))
            time.sleep(0.05)
        except Exception as exc:
            print(f"    [embed error] {exc}")
            return None
    return embeddings


def _compute_mean_sim(
    original_query: str,
    works: list[dict],
    embed_model: LiteLLMEmbedding,
) -> float:
    if not works:
        return 0.0
    all_texts = [original_query] + [_paper_text(w) for w in works]
    embeddings = _embed_texts(all_texts, embed_model)
    if embeddings is None:
        return 0.0
    query_emb = embeddings[0]
    sims = [cosine_similarity(query_emb, p) for p in embeddings[1:]]
    return float(np.mean(sims))


def _llm_judge_precision_at_5(
    original_query: str,
    works: list[dict],
    llm: LiteLLM,
    top_k: int = 5,
) -> Optional[float]:
    works_top5 = works[:top_k]
    if not works_top5:
        return None
    yes_count = 0
    for work in works_top5:
        title = work.get("title") or ""
        abstract = _reconstruct_abstract(work.get("abstract_inverted_index") or {})[:500]
        prompt = JUDGE_PMT_TEMPLATE.format(
            original_query=original_query, title=title, abstract=abstract,
        )
        try:
            answer = _retry(
                lambda p=prompt: _chat(llm, [ChatMessage(role="user", content=p)]),
                retries=2, delay=3.0,
            ).lower()
            if answer.startswith("yes"):
                yes_count += 1
        except Exception as exc:
            print(f"    [judge error] {exc}")
        time.sleep(1.0)
    return yes_count / len(works_top5)

# ── Strategy helpers ───────────────────────────────────────────────────────────

def _extract_search_params(query: str, llm: LiteLLM) -> dict:
    """One LLM call → {clean_topic, year_window, min_citations}. Shared by Strategy B and C."""
    raw = _chat(llm, [
        ChatMessage(role="system", content=SEARCH_PARAMS_PMT),
        ChatMessage(role="user", content=query),
    ])
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
        return {
            "clean_topic": str(parsed.get("clean_topic", query)),
            "year_window": max(1, min(20, int(parsed.get("year_window", DEFAULT_YEAR_WINDOW)))),
            "min_citations": max(0, int(parsed.get("min_citations", DEFAULT_MIN_CITATIONS))),
        }
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        print(f"    [parse error] {exc} — raw: {raw[:200]}")
        return {"clean_topic": query, "year_window": DEFAULT_YEAR_WINDOW, "min_citations": DEFAULT_MIN_CITATIONS}


def _evaluate_strategy(
    original_query: str,
    params: SearchParams,
    embed_model: LiteLLMEmbedding,
    judge_llm: Optional[LiteLLM],
    reformulated: Optional[str] = None,
) -> StrategyResult:
    """Fetch results for given SearchParams, compute similarity and judge precision."""
    works = _retry(
        lambda: _openalex_search(params.query, params.year_window, params.min_citations),
        retries=3, delay=5.0,
    )
    n_results = _retry(
        lambda: _openalex_count(params.query, params.year_window, params.min_citations),
        retries=2, delay=3.0,
    )
    mean_sim = _compute_mean_sim(original_query, works, embed_model)
    precision = _llm_judge_precision_at_5(original_query, works, judge_llm) if judge_llm else None
    time.sleep(1.0)
    return StrategyResult(
        reformulated=reformulated,
        year_window=params.year_window,
        min_citations=params.min_citations,
        n_results=n_results,
        mean_sim_at_20=mean_sim,
        precision_at_5=precision,
    )


def _run_all_strategies(
    original_query: str,
    query_id: int,
    transform_llm: LiteLLM,
    embed_model: LiteLLMEmbedding,
    judge_llm: Optional[LiteLLM],
) -> tuple[StrategyResult, StrategyResult, StrategyResult]:
    """Run A/B/C for one query. B and C share a single LLM call."""
    # Strategy A: raw query, fixed filters
    print("  [A] raw search...")
    result_a = _evaluate_strategy(
        original_query, SearchParams(query=original_query), embed_model, judge_llm,
    )
    print(f"    n={result_a.n_results}, sim={result_a.mean_sim_at_20:.4f}, p@5={result_a.precision_at_5}")

    # Single LLM call shared by B and C — guarantees identical clean_topic
    print("  [B+C] extracting SearchParams...")
    extracted = _retry(lambda: _extract_search_params(original_query, transform_llm), retries=2, delay=5.0)
    clean_topic = extracted["clean_topic"]
    print(f"    clean_topic: '{clean_topic}', year_window={extracted['year_window']}, min_citations={extracted['min_citations']}")

    # Strategy B: clean_topic + fixed filters
    result_b = _evaluate_strategy(
        original_query, SearchParams(query=clean_topic), embed_model, judge_llm,
        reformulated=clean_topic,
    )
    print(f"  [B] n={result_b.n_results}, sim={result_b.mean_sim_at_20:.4f}, p@5={result_b.precision_at_5}")

    # Apply per-query overrides to Strategy C filter params only
    override = QUERY_FILTER_OVERRIDES.get(query_id, {})
    c_year_window = override.get("year_window", extracted["year_window"])
    c_min_citations = override.get("min_citations", extracted["min_citations"])
    if override:
        print(f"    [override Q{query_id:02d}] year_window={c_year_window}, min_citations={c_min_citations}")

    # Strategy C: clean_topic + dynamic filters
    result_c = _evaluate_strategy(
        original_query,
        SearchParams(query=clean_topic, year_window=c_year_window, min_citations=c_min_citations),
        embed_model, judge_llm,
        reformulated=clean_topic,
    )
    print(f"  [C] n={result_c.n_results}, sim={result_c.mean_sim_at_20:.4f}, p@5={result_c.precision_at_5}")

    return result_a, result_b, result_c

# ── Persistence helpers ────────────────────────────────────────────────────────

def _load_partial_results() -> tuple[list[dict], set[int]]:
    if not RESULTS_PATH.exists():
        return [], set()
    with open(RESULTS_PATH) as f:
        existing = json.load(f)
    processed = {r["query_id"] for r in existing}
    print(f"Resuming: {len(processed)} queries already done.")
    return existing, processed


def _save_results(results: list[dict]) -> None:
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)

# ── Main experiment loop ───────────────────────────────────────────────────────

def run_experiment(skip_llm_judge: bool = False) -> list[dict]:
    """Run all 25 queries × 3 strategies."""
    embed_model = _build_embed_model()
    transform_llm = _build_llm(_TRANSFORM_MODEL)
    judge_llm = _build_llm(_JUDGE_MODEL) if not skip_llm_judge else None

    existing_results, processed_ids = _load_partial_results()
    results = list(existing_results)

    for q in QUERIES:
        if q["id"] in processed_ids:
            continue

        print(f"\n[Q{q['id']:02d}/25] cat={q['category']} | {q['query'][:80]}")
        # LLM judge only for categories 1-4 (problematic input types)
        effective_judge = judge_llm if q["category"] in {1, 2, 3, 4} else None

        result_a, result_b, result_c = _run_all_strategies(
            q["query"], q["id"], transform_llm, embed_model, effective_judge,
        )
        results.append({
            "query_id": q["id"],
            "category": q["category"],
            "original_query": q["query"],
            "strategy_a": result_a.to_dict(),
            "strategy_b": result_b.to_dict(),
            "strategy_c": result_c.to_dict(),
        })
        _save_results(results)
        print(f"  Saved progress ({len(results)}/25)")

    return results

# ── Statistical analysis (stdout only — no file written) ──────────────────────

def print_analysis(results: list[dict]) -> None:
    """Print structured analysis to stdout. Output is read by AI agent to write MD report."""

    sims_a = [r["strategy_a"]["mean_sim_at_20"] for r in results]
    sims_b = [r["strategy_b"]["mean_sim_at_20"] for r in results]
    sims_c = [r["strategy_c"]["mean_sim_at_20"] for r in results]

    def wilcoxon_row(x: list, y: list, label: str) -> dict:
        x_arr, y_arr = np.array(x), np.array(y)
        diffs = y_arr - x_arr
        non_tied = diffs != 0
        if non_tied.sum() < 2:
            return {"label": label, "median_x": np.median(x), "median_y": np.median(y),
                    "W": None, "p": None, "r": None, "sig": "—"}
        stat, p = scipy_stats.wilcoxon(x_arr[non_tied], y_arr[non_tied])
        N = non_tied.sum()
        z = scipy_stats.norm.ppf(1 - p / 2) * np.sign(np.median(diffs))
        r = z / np.sqrt(N)
        return {"label": label, "median_x": float(np.median(x)), "median_y": float(np.median(y)),
                "W": float(stat), "p": float(p), "r": float(r),
                "sig": "significant" if p < 0.05 else "not significant"}

    sep = "=" * 72

    print(f"\n{sep}")
    print("QUERY TRANSFORMATION STRATEGIES — ANALYSIS")
    print(f"Queries evaluated: {len(results)}/25")
    print(sep)

    print("\n[Per-Query Results]")
    print(f"{'Q':>3}  {'Cat':>3}  {'sim_A':>7}  {'sim_B':>7}  {'sim_C':>7}  "
          f"{'p5_A':>5}  {'p5_B':>5}  {'p5_C':>5}  clean_topic[:40]")
    print("-" * 110)
    for r in results:
        sa, sb, sc = r["strategy_a"], r["strategy_b"], r["strategy_c"]
        p5a = f"{sa['precision_at_5']:.2f}" if sa["precision_at_5"] is not None else "  —  "
        p5b = f"{sb['precision_at_5']:.2f}" if sb["precision_at_5"] is not None else "  —  "
        p5c = f"{sc['precision_at_5']:.2f}" if sc["precision_at_5"] is not None else "  —  "
        print(f"{r['query_id']:>3}  {r['category']:>3}  "
              f"{sa['mean_sim_at_20']:>7.4f}  {sb['mean_sim_at_20']:>7.4f}  {sc['mean_sim_at_20']:>7.4f}  "
              f"{p5a:>5}  {p5b:>5}  {p5c:>5}  {(sb['reformulated'] or '')[:40]}")

    print(f"\n[Overall Medians]")
    print(f"  A (raw)          mean_sim@20 = {np.median(sims_a):.4f}")
    print(f"  B (clean_topic)  mean_sim@20 = {np.median(sims_b):.4f}")
    print(f"  C (+ dyn filters)mean_sim@20 = {np.median(sims_c):.4f}")

    tests = [
        wilcoxon_row(sims_a, sims_b, "A vs B (raw → clean_topic)"),
        wilcoxon_row(sims_b, sims_c, "B vs C (fixed → dynamic filters)"),
        wilcoxon_row(sims_a, sims_c, "A vs C (raw → full extraction)"),
    ]
    print(f"\n[Wilcoxon Signed-Rank Tests  N=25  threshold p<0.05]")
    print(f"{'Comparison':<35}  {'med_X':>7}  {'med_Y':>7}  {'W':>8}  {'p':>7}  {'r':>6}  Verdict")
    print("-" * 90)
    for t in tests:
        if t["W"] is not None:
            print(f"{t['label']:<35}  {t['median_x']:>7.4f}  {t['median_y']:>7.4f}  "
                  f"{t['W']:>8.1f}  {t['p']:>7.4f}  {t['r']:>6.3f}  {t['sig']}")
        else:
            print(f"{t['label']:<35}  {t['median_x']:>7.4f}  {t['median_y']:>7.4f}  "
                  f"{'—':>8}  {'—':>7}  {'—':>6}  {t['sig']}")

    cat_names = {1: "Time constraints", 2: "Citation constraints",
                 3: "Conversational", 4: "Mixed constraints", 5: "Clean (control)"}
    print(f"\n[Per-Category Breakdown  median mean_sim@20]")
    print(f"{'Cat':>3}  {'N':>2}  {'Description':<22}  {'A':>7}  {'B':>7}  {'C':>7}  B>A?  C>B?")
    print("-" * 70)
    for cat in range(1, 6):
        cr = [r for r in results if r["category"] == cat]
        if not cr:
            continue
        ma = float(np.median([r["strategy_a"]["mean_sim_at_20"] for r in cr]))
        mb = float(np.median([r["strategy_b"]["mean_sim_at_20"] for r in cr]))
        mc = float(np.median([r["strategy_c"]["mean_sim_at_20"] for r in cr]))
        print(f"{cat:>3}  {len(cr):>2}  {cat_names[cat]:<22}  {ma:>7.4f}  {mb:>7.4f}  {mc:>7.4f}"
              f"  {'✓' if mb > ma else '✗':>4}  {'✓' if mc > mb else '✗':>4}")

    # Only include queries where ALL three strategies have a precision value (paired comparison)
    p5_paired = [
        (r["strategy_a"]["precision_at_5"], r["strategy_b"]["precision_at_5"], r["strategy_c"]["precision_at_5"])
        for r in results
        if all(r[s]["precision_at_5"] is not None for s in ("strategy_a", "strategy_b", "strategy_c"))
    ]
    p5_a = [t[0] for t in p5_paired]
    p5_b = [t[1] for t in p5_paired]
    p5_c = [t[2] for t in p5_paired]
    if p5_a:
        print(f"\n[LLM-as-Judge Precision@5  paired queries only (all 3 strategies have results)]")
        print(f"  A mean={np.mean(p5_a):.3f}  B mean={np.mean(p5_b):.3f}  C mean={np.mean(p5_c):.3f}  N={len(p5_a)}")
        p5_tests = [
            wilcoxon_row(p5_a, p5_b, "A vs B (raw → clean_topic)"),
            wilcoxon_row(p5_b, p5_c, "B vs C (fixed → dynamic filters)"),
            wilcoxon_row(p5_a, p5_c, "A vs C (raw → full extraction)"),
        ]
        print(f"\n[Wilcoxon on Precision@5  N≤20  threshold p<0.05]")
        print(f"{'Comparison':<35}  {'med_X':>7}  {'med_Y':>7}  {'W':>8}  {'p':>7}  {'r':>6}  Verdict")
        print("-" * 90)
        for t in p5_tests:
            if t["W"] is not None:
                print(f"{t['label']:<35}  {t['median_x']:>7.4f}  {t['median_y']:>7.4f}  "
                      f"{t['W']:>8.1f}  {t['p']:>7.4f}  {t['r']:>6.3f}  {t['sig']}")
            else:
                print(f"{t['label']:<35}  {t['median_x']:>7.4f}  {t['median_y']:>7.4f}  "
                      f"{'—':>8}  {'—':>7}  {'—':>6}  {t['sig']}")

    print(f"\n[Strategy C — Extracted SearchParams per Query]")
    print(f"{'Q':>3}  {'Cat':>3}  {'year_win':>8}  {'min_cit':>7}  clean_topic[:50]")
    print("-" * 80)
    for r in results:
        sc = r["strategy_c"]
        print(f"{r['query_id']:>3}  {r['category']:>3}  {sc['year_window']:>8}  "
              f"{sc['min_citations']:>7}  {(sc['reformulated'] or '')[:50]}")

    print(f"\n{sep}")
    print("END OF ANALYSIS — results saved to query_transformation_results.json")
    print(sep)

# ── Entry point ────────────────────────────────────────────────────────────────

def run_extraction_diff() -> None:
    """Compare old vs new clean_topic for all 25 queries without calling OpenAlex.

    Reads existing results from RESULTS_PATH for old clean_topics, runs the new
    prompt extraction, and prints a diff table. Use this to identify which queries
    need a full re-run after a prompt change before committing to the full experiment.
    """
    if not RESULTS_PATH.exists():
        print(f"ERROR: {RESULTS_PATH} not found. Run the full experiment first.")
        raise SystemExit(1)
    with open(RESULTS_PATH) as f:
        existing = json.load(f)
    old_topics = {r["query_id"]: r["strategy_b"]["reformulated"] for r in existing}

    transform_llm = _build_llm(_TRANSFORM_MODEL)
    changed: list[int] = []

    print(f"\n{'Q':>3}  {'Cat':>3}  {'Changed':>7}  {'Old clean_topic':<45}  New clean_topic")
    print("-" * 120)
    for q in QUERIES:
        old = old_topics.get(q["id"], "")
        extracted = _retry(lambda qr=q["query"]: _extract_search_params(qr, transform_llm), retries=2, delay=3.0)
        new = extracted["clean_topic"]
        diff = old.strip() != new.strip()
        if diff:
            changed.append(q["id"])
        marker = "YES" if diff else ""
        print(f"{q['id']:>3}  {q['category']:>3}  {marker:>7}  {old[:45]:<45}  {new}")
        time.sleep(0.5)

    print(f"\nChanged queries (need full re-run for B+C): {changed if changed else 'none'}")
    print("Strategy A is unaffected — raw query unchanged.")
    print("Re-run command for changed queries only:")
    print(f"  micromamba run -n py3.12 python query-transformation.py --skip-llm-judge")
    print("  (Script resumes from last saved checkpoint — already-done queries are skipped.)")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Query transformation PoC experiment")
    parser.add_argument("--skip-llm-judge", action="store_true",
                        help="Skip LLM-as-judge precision@5 (faster, ~15 min)")
    parser.add_argument("--analyze-only", action="store_true",
                        help="Skip experiment, re-analyze existing query_transformation_results.json")
    parser.add_argument("--extraction-diff", action="store_true",
                        help="Compare old vs new clean_topic for all 25 queries (no OpenAlex calls). "
                             "Use after a prompt change to identify which queries need full re-run.")
    args = parser.parse_args()

    if args.extraction_diff:
        run_extraction_diff()
    elif not args.analyze_only:
        results = run_experiment(skip_llm_judge=args.skip_llm_judge)
        print_analysis(results)
    else:
        if not RESULTS_PATH.exists():
            print(f"ERROR: {RESULTS_PATH} not found. Run without --analyze-only first.")
            raise SystemExit(1)
        with open(RESULTS_PATH) as f:
            results = json.load(f)
        print(f"Loaded {len(results)} results from {RESULTS_PATH}")
        print_analysis(results)
    # Note: MD report is NOT written here.
    # An AI agent reads this stdout log and writes the report to
    # experiments/01-openalex-paper-discovery/ per REPORTING_GUIDE.md
