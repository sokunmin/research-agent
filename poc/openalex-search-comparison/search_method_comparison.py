"""
PoC: OpenAlex search method comparison

Experiments:
  Exp 01 — search_filter(title_and_abstract=) — keyword match on title+abstract
  Exp 02 — search()    — BM25 full-text relevance search
  Exp 03 — similar()   — AI semantic (embedding) search
  Exp 04 — Cross-method overlap: M1 (keyword) / M2 (BM25) / M3 (semantic)
  Exp 05 — Tavily query format: bare query vs arxiv-prefix — academic hit rate
  Exp 06 — Tavily seed vs OpenAlex direct — can Tavily be replaced?
  Exp 07 — Tavily arxiv-prefix titles → OpenAlex title match gap
  Exp 08 — per_page sensitivity: N vs downloadable ArXiv paper count
  Exp 09 — Replacement path (Path B): OpenAlex search() + quality filters → E14
           Deterministic; empirical validation across 5 diverse domains
"""

import re
import time
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import click
from dotenv import dotenv_values

from llama_index.core.base.embeddings.base import similarity as cosine_similarity
from llama_index.core.llms import ChatMessage
from llama_index.embeddings.litellm import LiteLLMEmbedding
from llama_index.llms.litellm import LiteLLM
import pyalex
from pyalex import Works

# ── Config ────────────────────────────────────────────────────────────────────
_env = dotenv_values(Path(__file__).resolve().parents[2] / ".env")
pyalex.config.api_key = _env.get("OPENALEX_API_KEY", "")
_email = _env.get("OPENALEX_EMAIL", "")
if _email:
    pyalex.config.email = _email

# ── Constants ─────────────────────────────────────────────────────────────────
PER_PAGE = 25
RESEARCH_TOPIC = "attention mechanism in transformer models"
ACADEMIC_DOMAINS = {"arxiv.org", "doi.org", "pubmed.ncbi.nlm.nih.gov"}
TOPIC_Q = "federated learning privacy preservation"

# ── Exp 09 / 10: pipeline comparison parameters ───────────────────────────────
TOPIC_R   = "reinforcement learning policy gradient optimization"
TOPIC_S   = "convolutional neural network image recognition"
TOPIC_NEW = "CRISPR gene editing therapeutic applications"   # non-ML domain

# Five domains for empirical validation: NLP / distributed / RL / CV / biomedical
FIVE_TOPICS: list[tuple[str, str]] = [
    (RESEARCH_TOPIC, "RESEARCH_TOPIC"),
    (TOPIC_Q,        "TOPIC_Q"),
    (TOPIC_R,        "TOPIC_R"),
    (TOPIC_S,        "TOPIC_S"),
    (TOPIC_NEW,      "TOPIC_NEW"),
]

CITES_PER_SEED     = 50                            # matches original get_citing_papers(limit=50)
PATH_B_PER_PAGE    = 100                           # aligns candidate pool with Path A (2 seeds × 50 = ≤100)
YEAR_WINDOW        = 3                             # publication_year >= today.year - YEAR_WINDOW (same as extract-id.py)
TARGET_OA_STATUSES = ["diamond", "gold", "green"]  # OA types guaranteed freely downloadable (same as extract-id.py)
OA_STATUS_FILTER   = "|".join(TARGET_OA_STATUSES)  # "diamond|gold|green" — pyalex | OR syntax (smoke-tested)
MIN_RELEVANT       = 10                            # target: relevant papers ≥ 10 per topic (PDF download validated separately in extract-id.py)
TAVILY_REPEAT_RUNS = 3                             # runs to quantify Tavily non-determinism in Exp 09 Part 1
CITED_THRESHOLD_MED = 50  # cited_by_count mid-range threshold

# ── Display truncation ────────────────────────────────────────────────────────
DISPLAY_TRUNCATE_LEN = 60  # max chars for title / error / content-type display

# ── Semantic relevance config (two-stage: embedding + LLM, E14 configuration) ─
_EMBED_MODEL_NAME = "ollama/nomic-embed-text"
_LLM_MODEL_NAME   = "ollama/qwen3.5:2b"
_OLLAMA_BASE      = "http://localhost:11434"
_EMBED_THRESH     = 0.500
# Asymmetric score band for Stage-2 routing: papers in [_BAND_LO, _BAND_HI) → LLM.
# lo = classification threshold; naturally separates FP (score ≥ 0.5) from FN (< 0.5).
# hi = empirical max FP score (0.607) + 0.003 buffer; calibrated on RESEARCH_TOPIC.
# Limitation: hi is topic-specific. A multi-topic benchmark is needed for a generalizable value.
_BAND_LO = 0.500   # == _EMBED_THRESH
_BAND_HI = 0.610

_embed_model_instance: LiteLLMEmbedding | None = None
_llm_instance: LiteLLM | None = None
_ollama_unavailable: bool = False  # warn once flag

_TOPIC_EMB_CACHE: dict[str, list[float]] = {}
_WORK_EMB_CACHE:  dict[str, list[float]] = {}


# ── OpenAlex field helpers ────────────────────────────────────────────────────

def _get_abstract(work: dict) -> str:
    """Reconstruct abstract from inverted index if plain text is unavailable."""
    text = work.get("abstract") or ""
    if not text:
        inv = work.get("abstract_inverted_index")
        if inv:
            word_pos = [(w, p) for w, positions in inv.items() for p in positions]
            word_pos.sort(key=lambda x: x[1])
            text = " ".join(w for w, _ in word_pos)
    return text


def _get_primary_topic_name(work: dict) -> str:
    raw = work.get("primary_topic", "")
    return raw.get("display_name", "") if isinstance(raw, dict) else (raw or "")


def _get_concepts_text(work: dict) -> str:
    raw = work.get("concepts", [])
    if raw and isinstance(raw[0], dict):
        return ", ".join(c.get("display_name", "") for c in raw if c.get("display_name"))
    return ", ".join(str(c) for c in raw) if raw else ""


def _work_id(work: dict) -> str:
    return work.get("id", "").replace("https://openalex.org/", "")


def _title(work: dict) -> str:
    """Return display_name or title, falling back to '(no title)'."""
    return work.get("display_name") or work.get("title") or "(no title)"


def _oa_status(work: dict, default: str = "?") -> str:
    """Return open_access.oa_status with a configurable default."""
    return (work.get("open_access") or {}).get("oa_status", default)


def _has_arxiv(work: dict) -> bool:
    for loc in work.get("locations", []):
        url = loc.get("landing_page_url") or ""
        if "arxiv.org" in url:
            return True
    return False


def _is_academic(title: str, url: str) -> bool:
    return any(d in url for d in ACADEMIC_DOMAINS)


def _fmt(work: dict) -> str:
    return f'"{_title(work)}"  cited: {work.get("cited_by_count", 0)}'


# ── Embedding / LLM helpers ───────────────────────────────────────────────────

def _get_embed_model() -> LiteLLMEmbedding | None:
    """Return a cached LiteLLMEmbedding instance; return None if unavailable."""
    global _embed_model_instance, _ollama_unavailable
    if _embed_model_instance is None and not _ollama_unavailable:
        try:
            _embed_model_instance = LiteLLMEmbedding(
                model_name=_EMBED_MODEL_NAME,
                api_base=_OLLAMA_BASE,
            )
        except Exception as e:
            warnings.warn(f"[relevance] embedding model unavailable: {e}", stacklevel=3)
            _ollama_unavailable = True
    return _embed_model_instance


def _get_llm() -> LiteLLM | None:
    """Return a cached LiteLLM instance; return None if unavailable."""
    global _llm_instance, _ollama_unavailable
    if _llm_instance is None and not _ollama_unavailable:
        try:
            _llm_instance = LiteLLM(
                model=_LLM_MODEL_NAME,
                api_base=_OLLAMA_BASE,
                temperature=0.0,
            )
        except Exception as e:
            warnings.warn(f"[relevance] LLM unavailable: {e}", stacklevel=3)
            _ollama_unavailable = True
    return _llm_instance


def _get_topic_embedding(topic: str) -> list[float] | None:
    """Return the cached embedding vector for the topic string."""
    if topic in _TOPIC_EMB_CACHE:
        return _TOPIC_EMB_CACHE[topic]
    model = _get_embed_model()
    if model is None:
        return None
    try:
        vec: list[float] = model.get_text_embedding(topic)
        _TOPIC_EMB_CACHE[topic] = vec
        return vec
    except Exception as e:
        warnings.warn(f"[relevance] failed to embed topic: {e}", stacklevel=3)
        return None


def _build_work_text(work: dict) -> str:
    """Build the Stage-1 embedding input using Basic fields (title + abstract only).

    Matches the E14 ablation study configuration. Extended metadata fields
    (keywords, topics, primary_topic, concepts) are reserved for Stage-2 LLM input.
    """
    parts = [p for p in [work.get("display_name") or work.get("title") or "",
                         _get_abstract(work)] if p]
    return " ".join(parts)


def _get_work_embedding(work: dict) -> list[float] | None:
    """Return the cached embedding vector for a work, building its text if needed."""
    work_id = _work_id(work)
    if work_id in _WORK_EMB_CACHE:
        return _WORK_EMB_CACHE[work_id]
    model = _get_embed_model()
    if model is None:
        return None
    try:
        vec: list[float] = model.get_text_embedding(_build_work_text(work))
        _WORK_EMB_CACHE[work_id] = vec
        return vec
    except Exception as e:
        warnings.warn(f"[relevance] failed to embed work: {e}", stacklevel=3)
        return None


def _make_strict_prompt(topic: str) -> str:
    """Build a Prompt-Strict system message for the given topic.

    Mirrors the _SYS_STRICT configuration validated as best-performing in the
    ablation study (E14). Core strictness criteria:
      - Paper must directly address the topic as its primary subject (not a tool user).
      - Survey-heuristic as the final decision gate.
    Topic is injected dynamically to support multi-topic experiments.
    """
    return (
        "You are a research paper relevance classifier conducting a literature survey. "
        f"Research query: '{topic}'. "
        "A paper is relevant only if its core contribution directly addresses the research query — "
        "meaning the query topic is the primary subject of study, not merely an application context or tool. "
        "A paper is NOT relevant if it merely uses the subject as a black-box tool without contributing "
        "to the understanding of the topic itself, or if the connection is incidental. "
        f"Heuristic: would this paper be cited in a survey specifically on '{topic}'? "
        "Respond with exactly one word: yes or no."
    )


def _llm_relevance(work: dict, topic: str) -> bool:
    """Stage-2: LLM re-judges borderline papers using Prompt-Strict criteria.

    Input fields: title + abstract + keywords + topics + primary_topic + concepts
    (+PT+C, matching E14 Stage-2 configuration from the ablation study).
    """
    llm = _get_llm()
    if llm is None:
        return False

    user_msg = "\n".join([
        f"Topic: {topic}",
        f"Title: {_title(work)}",
        f"Abstract: {_get_abstract(work) or '(none)'}",
        f"Keywords: {', '.join(k.get('display_name','') for k in work.get('keywords',[]) if k.get('display_name')) or '(none)'}",
        f"Topics: {', '.join(t.get('display_name','') for t in work.get('topics',[]) if t.get('display_name')) or '(none)'}",
        f"Primary topic: {_get_primary_topic_name(work) or '(none)'}",
        f"Concepts: {_get_concepts_text(work) or '(none)'}",
    ])

    try:
        messages = [
            ChatMessage(role="system", content=_make_strict_prompt(topic)),
            ChatMessage(role="user", content=user_msg),
        ]
        resp = llm.chat(messages, extra_body={"think": False})
        raw = resp.message.content.strip().lower()
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
        return (lines[-1] if lines else "").startswith("yes")
    except Exception as e:
        warnings.warn(f"[relevance] LLM call failed: {e}", stacklevel=3)
        return False


def _embed_relevance(work: dict, topic: str) -> tuple[bool, float]:
    """Stage 1: embedding cosine similarity. Returns (is_relevant, similarity_score)."""
    topic_vec = _get_topic_embedding(topic)
    if topic_vec is None:
        return False, 0.0
    work_vec = _get_work_embedding(work)
    if work_vec is None:
        return False, 0.0
    sim = cosine_similarity(topic_vec, work_vec)
    return sim >= _EMBED_THRESH, sim


def _is_relevant(work: dict, topic: str) -> bool:
    """Two-stage relevance judgment with asymmetric score-band routing (E14 configuration).

    Stage 1 — nomic-embed-text cosine similarity on Basic fields (title + abstract).
               Threshold: _EMBED_THRESH = 0.500.
    Stage 2 — Prompt-Strict LLM re-judges papers in band [_BAND_LO, _BAND_HI).
               Input: +PT+C fields (title + abstract + keywords + topics + primary_topic + concepts).

    Band is asymmetric by design: captures all FP (score ≥ 0.500) up to the empirical
    FP ceiling, while excluding FN (score < 0.500) that Stage-2 cannot recover
    (0/3 recovery rate; see ablation study §5.6).
    """
    verdict, sim = _embed_relevance(work, topic)
    if _BAND_LO <= sim < _BAND_HI:
        return _llm_relevance(work, topic)
    return verdict


# ── Display helpers ───────────────────────────────────────────────────────────

def _exp_header(num: int, title: str, *info_lines: str) -> None:
    """Print the standard experiment header block."""
    sep = "=" * 60
    print(f"\n\n{sep}")
    print(f"EXPERIMENT {num:02d}: {title}")
    for line in info_lines:
        print(f"  {line}")
    print(sep)


def _print_named_works(label: str, works) -> None:
    """Print a labeled bullet list of work titles (accepts list[dict] or WorksResult)."""
    items = list(works)
    print(f"  {label}: {len(items)} 篇")
    for w in items:
        print(f"    • {_title(w)}")


# ── Tavily helper ─────────────────────────────────────────────────────────────

def _tavily_search(query: str, max_results: int = 5) -> list[dict]:
    """Call Tavily and return raw result list; prints warning and returns [] on failure."""
    tavily_key = _env.get("TAVILY_API_KEY", "")
    if not tavily_key:
        print("  TAVILY_API_KEY not set — skipping")
        return []
    try:
        from tavily import TavilyClient
        resp = TavilyClient(api_key=tavily_key).search(query, max_results=max_results)
        time.sleep(1)
        return resp.get("results", [])
    except ImportError:
        print("  tavily-python not installed — skipping")
        return []
    except Exception as e:
        print(f"  Tavily ERROR: {e}")
        return []


def _tavily_arxiv_query(topic: str) -> str:
    """Return the arxiv-prefix query format used in production (summary_gen.py).

    Matches the original author's Tavily query:
        "arxiv papers about the state of the art of {user_query}"
    Single source of truth — all production-equivalent Tavily calls use this.
    """
    return f"arxiv papers about the state of the art of {topic}"


# ── WorksResult ───────────────────────────────────────────────────────────────

class WorksResult:
    """Thin wrapper around list[dict] of OpenAlex works.

    All methods are pure — no API calls, no side effects beyond printing.
    Designed to replace scattered rel_n/ax_n calculations and row-print loops
    in experiments.

    Usage:
        wr = WorksResult(works, topic=RESEARCH_TOPIC)
        wr.print_table(year=True, oa_status=True)
        rel_n, ax_n = wr.print_stats()
        overlap = wr.overlap(other_wr)
    """

    def __init__(self, works: list[dict], topic: str | None = None):
        self.works = works
        self.topic = topic

    def __len__(self) -> int:
        return len(self.works)

    def __bool__(self) -> bool:
        return bool(self.works)

    def __iter__(self):
        return iter(self.works)

    # ── Identity ──────────────────────────────────────────────────────────────

    def ids(self) -> set[str]:
        return {_work_id(w) for w in self.works}

    # ── Relevance ─────────────────────────────────────────────────────────────

    def _is_rel(self, w: dict) -> bool:
        return _is_relevant(w, self.topic if self.topic else RESEARCH_TOPIC)

    def rel_count(self) -> int:
        return sum(1 for w in self.works if self._is_rel(w))

    def arxiv_count(self) -> int:
        return sum(1 for w in self.works if _has_arxiv(w))

    # ── Set operations ────────────────────────────────────────────────────────

    def overlap(self, other: "WorksResult") -> "WorksResult":
        """Return a new WorksResult containing works present in both self and other."""
        shared = self.ids() & other.ids()
        return WorksResult([w for w in self.works if _work_id(w) in shared], self.topic)

    def unique_from(self, *others: "WorksResult") -> "WorksResult":
        """Return a new WorksResult containing works NOT present in any of others."""
        other_ids = set().union(*(o.ids() for o in others))
        return WorksResult([w for w in self.works if _work_id(w) not in other_ids], self.topic)

    # ── Distribution ──────────────────────────────────────────────────────────

    def year_range(self) -> tuple[int | None, int | None]:
        years = [w.get("publication_year") for w in self.works if w.get("publication_year")]
        return (min(years), max(years)) if years else (None, None)

    def cited_range(self) -> tuple[int, int, float]:
        """Return (min, max, avg) of cited_by_count."""
        vals = [w.get("cited_by_count", 0) for w in self.works]
        return (min(vals), max(vals), sum(vals) / len(vals)) if vals else (0, 0, 0.0)

    def best(self) -> dict | None:
        """Return the work with the highest cited_by_count."""
        return max(self.works, key=lambda w: w.get("cited_by_count", 0)) if self.works else None

    # ── Display ───────────────────────────────────────────────────────────────

    def print_table(self, *, show_rel: bool = True, year: bool = False,
                    oa_status: bool = False, type_: bool = False) -> None:
        """Print one row per work with configurable columns.

        Column order: [rel] [arxiv] [year] [oa] [type] cited title
        set show_rel=False for candidate-listing contexts (e.g. before seed selection).
        """
        if not self.works:
            print("  (no results)")
            return
        if show_rel:
            print(f"  [E14] filtering {len(self.works)} papers...", flush=True)
        for i, w in enumerate(self.works, 1):
            parts = [f"  #{i:<2}"]
            if show_rel:
                parts.append(f" rel:{'✓' if self._is_rel(w) else '✗'}")
            parts.append(f" [{'arxiv ✓' if _has_arxiv(w) else 'arxiv ✗'}]")
            if year:
                parts.append(f" year:{w.get('publication_year', '?')}")
            if oa_status:
                parts.append(f" oa:{_oa_status(w):<8}")
            if type_:
                parts.append(f" type:{w.get('type', '?'):<15}")
            parts.append(f" cited:{w.get('cited_by_count', 0):>6}  {_title(w)}")
            print("".join(parts))

    def print_stats(self, topic: str | None = None) -> tuple[int, int]:
        """Print 相關率/ArXiv line (no leading \\n). Return (rel_n, ax_n)."""
        n = len(self.works)
        if not n:
            print("  (no results)")
            return 0, 0
        rel_fn = (lambda w: _is_relevant(w, topic)) if topic else self._is_rel
        print(f"  [E14] filtering {n} papers...", end=" ", flush=True)
        rel_n = sum(1 for w in self.works if rel_fn(w))
        ax_n  = sum(1 for w in self.works if _has_arxiv(w))
        print("done")
        print(f"  相關率: {rel_n}/{n}={rel_n/n*100:.0f}%  ArXiv: {ax_n}/{n}={ax_n/n*100:.0f}%")
        return rel_n, ax_n


# ── Pipeline comparison (Exp 09 / 10) ────────────────────────────────────────

@dataclass
class PipelineResult:
    """Metrics for one topic run through a retrieval + E14 filter pipeline.

    Used by Exp 09 (Path A) and Exp 10 (Path B) for uniform reporting.
    PDF download reliability is validated separately in extract-id.py and is
    therefore not tracked here.
    """
    label:       str
    candidates:  int   # papers before E14 filter
    relevant:    int   # papers passing E14  ← primary metric
    api_calls:   int
    seeds_found: int = 0   # Path A only: seeds retrieved from OpenAlex

    @classmethod
    def failure(cls, label: str, api_calls: int = 0, seeds_found: int = 0) -> "PipelineResult":
        """Return a zero-candidate result for pipeline steps that fail before producing candidates."""
        return cls(label=label, candidates=0, relevant=0, api_calls=api_calls, seeds_found=seeds_found)

    @property
    def meets_target(self) -> bool:
        return self.relevant >= MIN_RELEVANT

    def row(self, show_seeds: bool = False) -> str:
        cols = [
            f"  {self.label:<18}",
            f"  {self.candidates:>4}",
            f"  {self.relevant:>3}",
            f"  {'✓' if self.meets_target else '✗'}",
        ]
        if show_seeds:
            cols.append(f"  seeds:{self.seeds_found}")
        return "".join(cols)


def _print_pipeline_table(results: list[PipelineResult], show_seeds: bool = False) -> None:
    """Print a fixed-width summary table for a list of PipelineResult."""
    header = f"  {'Topic':<18}  {'cand':>4}  {'rel':>3}  ≥{MIN_RELEVANT}?"
    if show_seeds:
        header += "  seeds"
    print(header)
    print("  " + "─" * (len(header) - 2))
    for r in results:
        print(r.row(show_seeds=show_seeds))
    passed = sum(1 for r in results if r.meets_target)
    print(f"\n  Passed ≥{MIN_RELEVANT}: {passed}/{len(results)} topics")


def _path_b_query(topic: str):
    """Build the Path B OpenAlex query with all quality filters applied.

    Single source of truth for the Path B filter configuration:
      search() + is_oa + oa_status∈{diamond,gold,green} + cited>CITED_THRESHOLD_MED
               + year>today-YEAR_WINDOW + !retraction + sort cited desc

    Returns a pyalex query object (no .get() call) so callers can append
    .get(per_page=N) with any pool size — used by both exp_08 (sweep) and
    _run_path_b (fixed PATH_B_PER_PAGE).
    """
    year_floor = date.today().year - YEAR_WINDOW
    return (
        Works()
        .search(topic)
        .filter(
            is_oa=True,
            oa_status=OA_STATUS_FILTER,
            cited_by_count=f">{CITED_THRESHOLD_MED}",
            publication_year=f">{year_floor}",
            type="!retraction",
        )
        .sort(cited_by_count="desc")
    )


def _run_path_a(topic: str, label: str) -> PipelineResult:
    """Path A: Tavily → OpenAlex seed → filter(cites=CITES_PER_SEED) → E14.

    Mirrors the dev-branch production pipeline in paper_scraping.py:
      search_papers(limit=1) per Tavily result → get_citing_papers(limit=50).
    Uses E14 as the common filter to isolate search-path quality.
    """
    api_calls = 1  # Tavily counts as 1 external call

    tavily_results = _tavily_search(_tavily_arxiv_query(topic), max_results=2)
    if not tavily_results:
        print(f"    Tavily: no results — path A yields 0 candidates")
        return PipelineResult.failure(label, api_calls=api_calls)

    seeds: list[dict] = []
    for r in tavily_results:
        title = r.get("title", "")
        if not title:
            continue
        try:
            res = Works().search_filter(title_and_abstract=title).get(per_page=1)
            api_calls += 1
            time.sleep(1)
            if res:
                seeds.append(res[0])
                print(f"    seed: {_title(res[0])[:DISPLAY_TRUNCATE_LEN]}")
        except Exception as e:
            print(f"    seed error for '{title[:40]}': {e}")

    if not seeds:
        print(f"    No seeds matched in OpenAlex")
        return PipelineResult.failure(label, api_calls=api_calls)

    candidates: dict[str, dict] = {}
    for seed in seeds:
        seed_id = _work_id(seed)
        try:
            for w in Works().filter(cites=seed_id).get(per_page=CITES_PER_SEED):
                candidates[_work_id(w)] = w
            api_calls += 1
            time.sleep(1)
        except Exception as e:
            print(f"    cites error for {seed_id}: {e}")

    works = list(candidates.values())
    print(f"    filtering {len(works)} candidates with E14...", end=" ", flush=True)
    relevant = [w for w in works if _is_relevant(w, topic)]
    print(f"→ {len(relevant)} relevant")

    return PipelineResult(
        label       = label,
        candidates  = len(works),
        relevant    = len(relevant),
        api_calls   = api_calls,
        seeds_found = len(seeds),
    )


def _run_path_b(topic: str, label: str) -> PipelineResult:
    """Path B: OpenAlex search() + quality filters → E14.

    Filter configuration delegated to _path_b_query() (single source of truth).
    per_page=PATH_B_PER_PAGE aligns the candidate pool with Path A (≤100).
    """
    try:
        works = _path_b_query(topic).get(per_page=PATH_B_PER_PAGE)
        time.sleep(1)
    except Exception as e:
        print(f"  ERROR fetching works: {e}")
        return PipelineResult.failure(label, api_calls=1)

    print(f"    filtering {len(works)} candidates with E14...", end=" ", flush=True)
    relevant = [w for w in works if _is_relevant(w, topic)]
    print(f"→ {len(relevant)} relevant")

    return PipelineResult(
        label      = label,
        candidates = len(works),
        relevant   = len(relevant),
        api_calls  = 1,
    )


# ── Experiments ───────────────────────────────────────────────────────────────

def exp_01_keyword_search() -> None:
    """Keyword match search — search_filter(title_and_abstract=).

    Searches only title and abstract fields using AND logic.
    Most precise but lowest coverage; no BM25 ranking.
    """
    _exp_header(1, f'search_filter(title_and_abstract="{RESEARCH_TOPIC}")',
                f"per_page={PER_PAGE}",
                "Search scope: title + abstract only (AND logic)")
    try:
        works = Works().search_filter(title_and_abstract=RESEARCH_TOPIC).get(per_page=PER_PAGE)
    except Exception as e:
        print(f"  ERROR: {e}")
        return
    wr = WorksResult(works)
    wr.print_table()
    print()
    wr.print_stats()


def exp_02_bm25_search() -> None:
    """BM25 full-text relevance search — search().

    Searches title, abstract, and full text with BM25 relevance ranking.
    Broader coverage than keyword search; results sorted by relevance score.
    """
    _exp_header(2, f'search("{RESEARCH_TOPIC}")',
                f"per_page={PER_PAGE}",
                "Search scope: title + abstract + full text (BM25 ranking)")
    try:
        works = Works().search(RESEARCH_TOPIC).get(per_page=PER_PAGE)
    except Exception as e:
        print(f"  ERROR: {e}")
        return
    wr = WorksResult(works)
    wr.print_table()
    print()
    wr.print_stats()


def exp_03_semantic_search() -> None:
    """AI semantic (embedding) search — similar().

    Uses OpenAlex's embedding model to find semantically similar papers.
    Captures topic-relevant papers that do not contain the exact query keywords.
    """
    _exp_header(3, f'similar("{RESEARCH_TOPIC}")  [AI semantic search]',
                f"per_page={PER_PAGE}",
                "Search scope: embedding similarity (no keyword requirement)")
    try:
        works = Works().similar(RESEARCH_TOPIC).get(per_page=PER_PAGE)
    except Exception as e:
        print(f"  similar() not supported: {e}")
        return
    wr = WorksResult(works)
    wr.print_table()
    print()
    wr.print_stats()


def exp_04_method_overlap() -> None:
    """Cross-method overlap analysis: M1 (keyword) / M2 (BM25) / M3 (semantic).

    Re-fetches all three methods and computes pairwise intersections and
    method-unique sets to characterise the complementary coverage of each approach.
    """
    _exp_header(4, "Cross-method overlap: M1 (keyword) / M2 (BM25) / M3 (semantic)",
                f"per_page={PER_PAGE}",
                "Re-fetches all three methods; computes pairwise overlap and unique sets.")
    try:
        m1_works = Works().search_filter(title_and_abstract=RESEARCH_TOPIC).get(per_page=PER_PAGE)
        time.sleep(1)
        m2_works = Works().search(RESEARCH_TOPIC).get(per_page=PER_PAGE)
        time.sleep(1)
        m3_works = Works().similar(RESEARCH_TOPIC).get(per_page=PER_PAGE)
        time.sleep(1)
    except Exception as e:
        print(f"  ERROR fetching results: {e}")
        return

    wr1, wr2, wr3 = WorksResult(m1_works), WorksResult(m2_works), WorksResult(m3_works)

    _print_named_works("M1 ∩ M2 (keyword ∩ BM25)", wr1.overlap(wr2))
    _print_named_works("M1 ∩ M3 (keyword ∩ semantic)", wr1.overlap(wr3))
    _print_named_works("M2 ∩ M3 (BM25 ∩ semantic)", wr2.overlap(wr3))
    _print_named_works("M3 unique (semantic only)", wr3.unique_from(wr1, wr2))

    # Deduplicated union of M1+M2, then subtract M3
    seen: set[str] = set()
    m12_deduped: list[dict] = []
    for w in m1_works + m2_works:
        wid = _work_id(w)
        if wid not in seen:
            m12_deduped.append(w)
            seen.add(wid)
    _print_named_works("M1/M2 unique (keyword/BM25 only)", WorksResult(m12_deduped).unique_from(wr3))


def exp_05_tavily_query_format() -> None:
    """Tavily query format sensitivity: bare query vs arxiv-prefix.

    Compares academic hit rate between two Tavily query formats to determine
    which format reliably retrieves academic papers rather than blog posts / tutorials.
    """
    _exp_header(5, "Tavily query format — bare query vs arxiv-prefix",
                f"Topic: {RESEARCH_TOPIC}",
                "Metric: academic hit rate (arxiv.org / doi.org / pubmed)")

    query_a = RESEARCH_TOPIC
    query_b = _tavily_arxiv_query(RESEARCH_TOPIC)

    for label, query in [("A (bare query)", query_a), ("B (arxiv-prefix)", query_b)]:
        print(f"\n[Query {label}]")
        print(f"  → \"{query}\"")
        results = _tavily_search(query)
        if not results:
            continue
        academic_count = 0
        for r in results:
            t_title = r.get("title", "(no title)")
            url     = r.get("url", "")
            score   = r.get("score", 0)
            is_ac   = _is_academic(t_title, url)
            academic_count += is_ac
            tag = "✓ academic" if is_ac else "✗ non-academic"
            print(f"  [{tag}]  score={score:.3f}  {t_title[:DISPLAY_TRUNCATE_LEN]}")
            print(f"    url: {url}")
        print(f"  academic hit rate: {academic_count}/{len(results)}")


def exp_06_tavily_vs_openalex() -> None:
    """Tavily seed vs OpenAlex direct search — can Tavily be replaced?

    Method X: Tavily search → extract titles → OpenAlex search_filter per title
    Method Y: OpenAlex search() directly (single API call)
    Compares cited_by_count of retrieved papers and total API call cost.
    """
    _exp_header(6, "Tavily seed vs OpenAlex direct — replacement feasibility",
                f"Topic: {RESEARCH_TOPIC}",
                "Method X: Tavily → title → OpenAlex search_filter",
                "Method Y: Works().search(topic, per_page=5) direct")

    tavily_seeds: list[dict] = []
    tavily_titles: list[str] = []

    print("\n[Method X] Tavily → title → OpenAlex search_filter:")
    results = _tavily_search(_tavily_arxiv_query(RESEARCH_TOPIC))
    if results:
        tavily_titles = [r.get("title", "") for r in results if r.get("title")]
        print("  Tavily titles found:")
        for t in tavily_titles:
            print(f"    • {t}")
        for t in tavily_titles:
            try:
                res = Works().search_filter(title_and_abstract=t).get(per_page=1)
                time.sleep(1)
                if res:
                    tavily_seeds.append(res[0])
                    print(f"  → OpenAlex match: {_fmt(res[0])}")
                else:
                    print(f"  → OpenAlex: no match for '{t}'")
            except Exception as e:
                print(f"  → OpenAlex error for '{t}': {e}")

    print("\n[Method Y] Works().search(topic, per_page=5) direct:")
    openalex_seeds: list[dict] = []
    try:
        openalex_seeds = Works().search(RESEARCH_TOPIC).get(per_page=5)
        time.sleep(1)
        for w in openalex_seeds:
            print(f"  → {_fmt(w)}")
    except Exception as e:
        print(f"  ERROR: {e}")

    cited_x = [w.get("cited_by_count", 0) for w in tavily_seeds]
    cited_y = [w.get("cited_by_count", 0) for w in openalex_seeds]
    overlap  = {_work_id(w) for w in tavily_seeds} & {_work_id(w) for w in openalex_seeds}
    api_x    = f"Tavily 1 + OpenAlex {len(tavily_titles)}" if tavily_titles else "N/A"

    print(f"\n[Conclusion Exp 06]")
    print(f"  Method X (Tavily+OpenAlex) cited_by_count: {cited_x}")
    print(f"  Method Y (OpenAlex only)   cited_by_count: {cited_y}")
    print(f"  Overlap: {len(overlap)} papers")
    print(f"  API calls — X: {api_x}  |  Y: 1")
    if not overlap and cited_y and cited_x:
        if max(cited_y) >= max(cited_x):
            print("  → OpenAlex direct quality ≥ Tavily; Tavily unnecessary")
        else:
            print("  → Tavily yields higher-cited seed; retaining Tavily adds value")
    elif not tavily_seeds:
        print("  → Tavily failed to find OpenAlex-matched papers; limited contribution")
    else:
        print("  → Overlap exists; Method Y (no Tavily) is simpler, consider replacing")


def exp_07_tavily_title_match() -> None:
    """Tavily arxiv-prefix titles → OpenAlex title match gap analysis.

    Uses the arxiv-prefix query (validated in Exp 05) to retrieve paper titles
    from Tavily, then attempts to match each title in OpenAlex via search_filter.
    Quantifies how many Tavily-found papers are discoverable in OpenAlex.
    """
    _exp_header(7, "Tavily arxiv-prefix → OpenAlex title match gap",
                f"Topic: {RESEARCH_TOPIC}",
                "Query format: 'arxiv papers about the state of the art of <topic>'")

    query = _tavily_arxiv_query(RESEARCH_TOPIC)
    print(f"\n  Tavily query: \"{query}\"")

    results = _tavily_search(query)
    if not results:
        return

    tavily_titles = [r.get("title", "") for r in results if r.get("title")]
    print(f"\n  Tavily titles: {tavily_titles}")
    print("\n  → OpenAlex search_filter match:")
    for t in tavily_titles:
        try:
            res = Works().search_filter(title_and_abstract=t).get(per_page=1)
            time.sleep(1)
            if res:
                print(f"    Tavily:   \"{t}\"")
                print(f"    OA match: {_fmt(res[0])}")
                print(f"    ArXiv:    {'✓' if _has_arxiv(res[0]) else '✗'}\n")
            else:
                print(f"    Tavily: \"{t}\" → OA: no match\n")
        except Exception as e:
            print(f"    Tavily: \"{t}\" → OA error: {e}\n")


def exp_08_per_page_sensitivity() -> None:
    """per_page sensitivity: candidate pool size vs relevant paper count.

    Sweeps per_page over [25, 50, 100, 150] using the same Path B filter
    configuration as Exp 10 (_path_b_query): is_oa + oa_status + cited +
    year + !retraction + sort cited desc.
    Answers: what is the minimum per_page to yield sufficient relevant papers
    under production-equivalent filter conditions?

    PDF download reliability is validated separately in extract-id.py and is
    not repeated here.
    """
    year_floor = date.today().year - YEAR_WINDOW
    sweep = [25, 50, 100, 150]
    _exp_header(
        8, "per_page sensitivity — pool size vs relevant paper count",
        f"Topic: {RESEARCH_TOPIC}",
        f"Filters: is_oa + oa_status + cited>{CITED_THRESHOLD_MED} + year>{year_floor} + !retraction",
        f"Sweep: N ∈ {sweep}",
        "PDF download reliability: validated separately in extract-id.py",
    )

    print(f"\n  {'per_page':>8}  {'total':>5}  {'relevant':>8}  {'rel%':>5}")
    print("  " + "─" * 32)

    for n in sweep:
        try:
            works = _path_b_query(RESEARCH_TOPIC).get(per_page=n)
            time.sleep(1)
            wr  = WorksResult(works, topic=RESEARCH_TOPIC)
            rel = wr.rel_count()
            pct = f"{rel / len(works) * 100:.0f}%" if works else "—"
            print(f"  {n:>8}  {len(works):>5}  {rel:>8}  {pct:>5}")
        except Exception as e:
            print(f"  {n:>8}  ERROR: {str(e)[:DISPLAY_TRUNCATE_LEN]}")


def exp_09_production_path() -> None:
    """Production path baseline (Path A): Tavily → seed → filter(cites=50) → E14.

    Part 1 — Tavily non-determinism quantification:
        Run Path A 3 times on RESEARCH_TOPIC with an identical query.
        Any Δ in relevant count across runs is directly attributable to Tavily's
        non-deterministic retrieval — the core motivation for replacement.

    Part 2 — Empirical validation across 5 diverse domains:
        Run Path A once per topic in FIVE_TOPICS.
        Topics spanning ML (NLP/RL/CV) and non-ML (biomedical) test whether
        the production path generalises beyond its development domain.

    Filter: E14 (nomic-embed-text + qwen3.5:2b Strict) used as the common
    relevance filter, replacing the cloud LLM to isolate search-path quality.
    """
    _exp_header(
        9, "Production Path (Path A) — Tavily → seed → filter(cites=50) → E14",
        f"tavily_max=2  cites_per_seed={CITES_PER_SEED}  filter=E14",
        f"target: relevant ≥ {MIN_RELEVANT} per topic",
    )

    # ── Part 1: Tavily non-determinism ────────────────────────────────────────
    print(f"\n[Part 1] Tavily non-determinism — {TAVILY_REPEAT_RUNS} runs on RESEARCH_TOPIC")
    print(f'  query: "{_tavily_arxiv_query(RESEARCH_TOPIC)}"')

    repeat_results: list[PipelineResult] = []
    for run in range(1, TAVILY_REPEAT_RUNS + 1):
        print(f"\n  ── Run {run}/{TAVILY_REPEAT_RUNS} ──")
        repeat_results.append(_run_path_a(RESEARCH_TOPIC, f"Run {run}"))

    print("\n  Non-determinism summary:")
    _print_pipeline_table(repeat_results, show_seeds=True)
    vals = [r.relevant for r in repeat_results]
    delta = max(vals) - min(vals)
    print(f"\n  relevant per run: {vals}  Δ = {delta}")
    if delta > 0:
        print("  → Tavily non-determinism confirmed: identical query yields different outputs")
    else:
        print("  → Results stable across 3 runs (possible Tavily-side caching)")

    # ── Part 2: 5 diverse domains ─────────────────────────────────────────────
    print(f"\n[Part 2] Empirical validation — {len(FIVE_TOPICS)} domains × 1 run")
    domain_results: list[PipelineResult] = []
    for topic, label in FIVE_TOPICS:
        print(f"\n  [{label}] {topic}")
        domain_results.append(_run_path_a(topic, label))

    print("\n[Path A — Domain Summary]")
    _print_pipeline_table(domain_results, show_seeds=True)


def exp_10_replacement_path() -> None:
    """Replacement path (Path B): OpenAlex search() + quality filters → E14.

    Uses the search configuration validated in extract-id.py:
      search() + is_oa + oa_status∈{diamond,gold,green} + cited>10
               + year>today-3 + !retraction + sort cited desc
    per_page=PATH_B_PER_PAGE (100) aligns the candidate pool with Path A (≤100),
    ensuring the comparison isolates search-path quality rather than pool size.

    Path B is deterministic: the same query always returns the same result set
    (no Tavily dependency), making experiments fully reproducible.

    Run independently from Exp 09; compare the two summary tables side-by-side
    to evaluate whether OpenAlex standalone can replace the production path.
    """
    year_floor = date.today().year - YEAR_WINDOW
    _exp_header(
        10, "Replacement Path (Path B) — OpenAlex search() + filters → E14",
        f"search()+is_oa+cited>{CITED_THRESHOLD_MED}+year>{year_floor}+!retraction",
        f"sort=cited_by_count desc  per_page={PATH_B_PER_PAGE}  filter=E14",
        f"target: relevant ≥ {MIN_RELEVANT} per topic",
        "Deterministic: same query → same result set (no Tavily dependency)",
    )

    print(f"\n  year_floor = {year_floor}  (today.year − {YEAR_WINDOW})")
    print(f"  {len(FIVE_TOPICS)} topics × 1 run\n")

    results: list[PipelineResult] = []
    for topic, label in FIVE_TOPICS:
        print(f"  [{label}] {topic}")
        results.append(_run_path_b(topic, label))

    print("\n[Path B — Domain Summary]")
    _print_pipeline_table(results)


# ── Entry point ───────────────────────────────────────────────────────────────

@click.command()
@click.option("--exp", multiple=True, type=int,
              help="Experiment number(s) to run (e.g. --exp 3 --exp 9). Omit to run all.")
def main(exp):
    # Discover all exp_NN_* functions by parsing their numeric prefix
    experiments: dict[int, callable] = {}
    for k, v in sorted(globals().items()):
        m = re.match(r"^exp_(\d+)_", k)
        if m and callable(v):
            experiments[int(m.group(1))] = v

    selected = sorted(exp) if exp else sorted(experiments.keys())
    for n in selected:
        if n not in experiments:
            click.echo(f"[WARN] exp_{n:02d} not found, skipping.")
            continue
        click.echo(f"\n{'=' * 60}\nRunning experiment {n:02d}...\n{'=' * 60}")
        experiments[n]()


if __name__ == "__main__":
    main()
