#!/usr/bin/env python3
"""
PoC: Search Parameter Extraction Prompt Comparison for OpenAlex BM25 Search
Compares 2 LLM prompt designs for extracting structured search parameters
from a natural-language research query:
  single_call_staged  — one LLM call, seven fields answered in a staged order
  split_topic_filter  — two independent LLM calls: one for topic fields,
                         one for year/citation filter fields

This experiment does NOT call OpenAlex and does NOT compute retrieval
quality metrics (mean_sim@20, precision@5). It only checks whether each
strategy's extracted fields match the hand-authored ground truth in
query_transformation_v2_gt.json — has_identifiable_topic, year_window,
min_citations, and (via a separate Claude review step, not in this script)
clean_topic quality. Excluding OpenAlex keeps the comparison isolated to the
one variable under test: which prompt design extracts parameters more
accurately, without OpenAlex's own retrieval behavior as a confound.

Usage:
    micromamba run -n py3.12 python query-transformation.py
    micromamba run -n py3.12 python query-transformation.py --limit 5
    micromamba run -n py3.12 python query-transformation.py --analyze-only

Output:
    query_transformation_v2_results/plan_comparison.json — per-query
    per-strategy extracted fields and deterministic check results.
"""

import json
import time
import sys
import click
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from dotenv import dotenv_values
from llama_index.core.llms import ChatMessage
from llama_index.llms.litellm import LiteLLM

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # poc/
from poc_base import ConfigResultTracker, ExperimentLogger

# ── Config ─────────────────────────────────────────────────────────────────────

_HERE = Path(__file__).parent
_ENV_PATH = _HERE.parents[1] / ".env"
_env = dotenv_values(_ENV_PATH)

RESULTS_DIR = _HERE / "query_transformation_v2_results"
GT_PATH = _HERE / "query_transformation_v2_gt.json"

_OLLAMA_BASE = "http://localhost:11434"
_TRANSFORM_MODEL = _env.get("LLM_SMART_MODEL", "ollama/ministral-3:14b-cloud")
_DISABLE_THINK = _env.get("DISABLE_OLLAMA_THINK", "false").lower() == "true"

# ── Prompts ────────────────────────────────────────────────────────────────────
# Both strategies ask the exact same seven questions with identical wording —
# the only difference is whether they are asked in one call or split across
# two. This keeps the comparison isolated to call structure, not wording.

SEARCH_PARAMS_STAGED_PMT = (
    "You are an academic search specialist. Today's year is {current_year}.\n"
    "Answer the following about this research query, and return JSON with "
    "exactly seven keys in this order:\n\n"
    "1. Does the query actually request academic literature on some "
    "subject, however broad — not merely mention a subject-related term "
    "while asking for something unrelated to literature search? -> "
    "has_identifiable_topic (true/false)\n"
    "2. If not, why not, in one short sentence? -> topic_missing_reason "
    "(string, null if question 1 is true)\n"
    "3. Does the query express a preference for how recent the papers "
    "should be? -> has_year_constraint (true/false)\n"
    "4. If yes, how many years back does that imply — use the exact "
    "number if given, otherwise your best judgment? -> year_window "
    "(integer 1-20; 3 if question 3 is false)\n"
    "5. Does the query express a preference for how impactful or "
    "well-cited the papers should be? -> has_citation_constraint "
    "(true/false)\n"
    "6. If yes, what citation count does that imply — use the exact "
    "number if given, otherwise your best judgment? -> min_citations "
    "(integer >=0; 50 if question 5 is false)\n"
    "7. What is the research subject, as 2-6 plain keywords? No boolean "
    "operators, quotes, or special characters. Ignore how recent or "
    "well-cited the user wants the papers to be, and ignore how the user "
    "phrased the request. Keep specialized terms, named entities, and "
    "abbreviations exactly as written. -> clean_topic (string, empty if "
    "question 1 is false)\n\n"
    "Return JSON only, no explanation, no markdown fences.\n\n"
    "User research query: {user_query}"
)

TOPIC_EXTRACTION_PMT = (
    "You are an academic search specialist. Answer about this research "
    "query, and return JSON with exactly three keys:\n\n"
    "1. Does the query actually request academic literature on some "
    "subject, however broad — not merely mention a subject-related term "
    "while asking for something unrelated to literature search? -> "
    "has_identifiable_topic (true/false)\n"
    "2. If not, why not, in one short sentence? -> topic_missing_reason "
    "(string, null if question 1 is true)\n"
    "3. What is the research subject, as 2-6 plain keywords for search? "
    "No boolean operators, quotes, or special characters. Ignore how "
    "recent or well-cited the user wants the papers to be, and ignore how "
    "the user phrased the request. Keep specialized terms, named "
    "entities, and abbreviations exactly as written. -> clean_topic "
    "(string, empty if question 1 is false)\n\n"
    "Return JSON only, no explanation, no markdown fences.\n\n"
    "User research query: {user_query}"
)

SEARCH_FILTERS_EXTRACTION_PMT = (
    "You are an academic search specialist. Today's year is {current_year}. "
    "Answer about this research query, and return JSON with exactly four "
    "keys:\n\n"
    "1. Does the query express a preference for how recent the papers "
    "should be? -> has_year_constraint (true/false)\n"
    "2. If yes, how many years back does that imply — use the exact "
    "number if given, otherwise your best judgment? -> year_window "
    "(integer 1-20; 3 if question 1 is false)\n"
    "3. Does the query express a preference for how impactful or "
    "well-cited the papers should be? -> has_citation_constraint "
    "(true/false)\n"
    "4. If yes, what citation count does that imply — use the exact "
    "number if given, otherwise your best judgment? -> min_citations "
    "(integer >=0; 50 if question 3 is false)\n\n"
    "Return JSON only, no explanation, no markdown fences.\n\n"
    "User research query: {user_query}"
)


def _load_gt() -> list[dict]:
    """Load the 40-query ground truth used by run_plan_comparison()."""
    return json.loads(GT_PATH.read_text())


# ── Data model ─────────────────────────────────────────────────────────────────

class ExtractedSearchParams(BaseModel):
    """The structured output of one SearchParamsExtractionStrategy.extract() call."""
    has_identifiable_topic: bool
    topic_missing_reason: Optional[str] = None
    year_window: int
    min_citations: int
    clean_topic: str


# ── Low-level helpers ────────────────────────────────────────────────────────

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


def _parse_json_response(raw: str) -> dict:
    """Strip markdown code fences (if the model added them) and parse JSON."""
    import re
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)

# ── Extraction strategies ────────────────────────────────────────────────────

class SearchParamsExtractionStrategy(ABC):
    """Extracts structured search parameters from a natural-language
    research query using an LLM: whether the query names a research topic,
    whether it expresses a year or citation-count preference, and what the
    core topic keywords are.

    This experiment compares two ways of prompting the LLM to do this
    extraction — one issues a single call for every field, the other splits
    the fields across two independent calls. Both are implemented as
    subclasses of this interface so the rest of the script can run either
    one interchangeably, without knowing which strategy it is running.
    """
    name: str

    @abstractmethod
    def extract(self, query: str, llm: LiteLLM, current_year: int) -> dict:
        """Return a dict with has_identifiable_topic, topic_missing_reason,
        year_window, min_citations, and clean_topic."""
        ...


class SingleCallStagedExtractor(SearchParamsExtractionStrategy):
    """Extracts all seven fields in a single LLM call.

    The prompt orders the seven questions to guide the model through the
    reasoning in stages within that one call: judge whether a topic exists,
    then the year/citation constraints, then extract the topic keywords
    last. No second round trip is needed.
    """
    name = "single_call_staged"

    def extract(self, query: str, llm: LiteLLM, current_year: int) -> dict:
        raw = _chat(llm, [ChatMessage(
            role="user",
            content=SEARCH_PARAMS_STAGED_PMT.format(
                user_query=query, current_year=current_year,
            ),
        )])
        parsed = _parse_json_response(raw)
        return {
            "has_identifiable_topic": bool(parsed["has_identifiable_topic"]),
            "topic_missing_reason": parsed.get("topic_missing_reason"),
            "year_window": int(parsed["year_window"]),
            "min_citations": int(parsed["min_citations"]),
            "clean_topic": str(parsed.get("clean_topic", "")),
        }


class SplitTopicFilterExtractor(SearchParamsExtractionStrategy):
    """Extracts search parameters via two independent LLM calls: one for
    topic-related fields, one for the year/citation filter fields.

    The two calls do not depend on each other's output. This implementation
    issues them sequentially for simplicity; they could be parallelized
    since neither call's input depends on the other's output.

    Splitting them keeps the topic-extraction task (which must *ignore*
    year/citation phrasing when building the topic keywords) separate from
    the filter-extraction task (which must *detect* that same phrasing) —
    avoiding the risk of one instruction interfering with the other when
    both sit in the same prompt.
    """
    name = "split_topic_filter"

    def extract(self, query: str, llm: LiteLLM, current_year: int) -> dict:
        topic_raw = _chat(llm, [ChatMessage(
            role="user", content=TOPIC_EXTRACTION_PMT.format(user_query=query),
        )])
        filters_raw = _chat(llm, [ChatMessage(
            role="user",
            content=SEARCH_FILTERS_EXTRACTION_PMT.format(
                user_query=query, current_year=current_year,
            ),
        )])
        topic = _parse_json_response(topic_raw)
        filters = _parse_json_response(filters_raw)
        return {
            "has_identifiable_topic": bool(topic["has_identifiable_topic"]),
            "topic_missing_reason": topic.get("topic_missing_reason"),
            "year_window": int(filters["year_window"]),
            "min_citations": int(filters["min_citations"]),
            "clean_topic": str(topic.get("clean_topic", "")),
        }


class GroundTruthChecker:
    """Compares an LLM's extracted search parameters against the
    hand-authored ground truth for a query, field by field.

    Each field has a different comparison rule depending on how the ground
    truth defines "correct" for that field:
      - has_topic: exact match against the expected boolean
      - year_window: exact match if the query gave an explicit number,
        otherwise must fall within an acceptable range
      - min_citations: exact match if explicit, otherwise must meet or
        exceed a minimum floor (a stricter-than-expected value is not
        penalized — it is still consistent with the query's intent)
    """

    @staticmethod
    def check_has_topic(actual: bool, gt: dict) -> bool:
        return actual == gt["expected"]

    @staticmethod
    def check_year_window(actual: int, gt: Optional[dict]) -> bool:
        if gt is None:
            return True
        if gt["type"] in ("explicit", "absent"):
            return actual == gt["expected_value"]
        if gt["type"] == "vague":
            lo, hi = gt["acceptable_range"]
            return lo <= actual <= hi
        raise ValueError(f"unknown year_window GT type: {gt['type']}")

    @staticmethod
    def check_min_citations(actual: int, gt: Optional[dict]) -> bool:
        if gt is None:
            return True
        if gt["type"] in ("explicit", "absent"):
            return actual == gt["expected_value"]
        if gt["type"] == "vague":
            return actual >= gt["floor"]
        raise ValueError(f"unknown min_citations GT type: {gt['type']}")

    def check_all(self, actual: dict, gt: dict) -> dict:
        return {
            "has_topic_correct": self.check_has_topic(
                actual["has_identifiable_topic"], gt["has_topic"]),
            "year_window_correct": self.check_year_window(
                actual["year_window"], gt["year_window"]),
            "min_citations_correct": self.check_min_citations(
                actual["min_citations"], gt["min_citations"]),
        }

# ── Main experiment loop ───────────────────────────────────────────────────────

def run_plan_comparison(limit: Optional[int] = None) -> None:
    """Run every ground-truth query through both extraction strategies and
    record deterministic pass/fail results. No OpenAlex calls."""
    logger = ExperimentLogger("query_transformation_v2_plan_comparison")
    logger.header(transform_model=_TRANSFORM_MODEL)

    gt_entries = _load_gt()
    if limit:
        gt_entries = gt_entries[:limit]

    llm = _build_llm(_TRANSFORM_MODEL)
    checker = GroundTruthChecker()
    strategies = [SingleCallStagedExtractor(), SplitTopicFilterExtractor()]
    tracker = ConfigResultTracker(RESULTS_DIR, "plan_comparison")
    current_year = date.today().year

    for entry in gt_entries:
        query_id = str(entry["id"])
        for strategy in strategies:
            if tracker.is_sample_done(query_id, strategy.name):
                continue
            try:
                extracted = _retry(
                    lambda: strategy.extract(entry["query"], llm, current_year),
                    retries=3, delay=5.0,
                )
                checks = checker.check_all(extracted, entry)
                tracker.write_result(
                    query_id, strategy.name,
                    query=entry["query"], category=entry["category"],
                    extracted=extracted, checks=checks,
                )
                logger.result(query_id=query_id, plan=strategy.name, **checks)
            except Exception as exc:
                tracker.write_error(query_id, strategy.name, str(exc))
                logger.error(query_id=query_id, plan=strategy.name, msg=str(exc))

    tracker.mark_config_complete()
    logger.end()


def print_diagnostic_summary() -> None:
    """Print per-strategy field accuracy — a diagnostic pass/fail count,
    not a statistical significance test (the 40-query test set is designed
    for edge-case coverage, not statistical power)."""
    tracker = ConfigResultTracker(RESULTS_DIR, "plan_comparison")
    samples = [s for s in tracker._data["samples"] if s["status"] == "success"]

    by_plan_field = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for s in samples:
        for field in ("has_topic_correct", "year_window_correct", "min_citations_correct"):
            by_plan_field[s["query_type"]][field][1] += 1
            if s["checks"][field]:
                by_plan_field[s["query_type"]][field][0] += 1

    print("\n=== Deterministic field accuracy (no OpenAlex, no similarity metric) ===")
    for plan in sorted(by_plan_field):
        print(f"\n{plan}:")
        for field, (correct, total) in by_plan_field[plan].items():
            print(f"  {field}: {correct}/{total}")

# ── Entry point ────────────────────────────────────────────────────────────────

@click.command()
@click.option(
    "--limit",
    "limit",
    default=None,
    type=int,
    metavar="N",
    help="Only run the first N ground-truth queries (for quick testing).",
)
@click.option(
    "--analyze-only",
    "analyze_only",
    is_flag=True,
    default=False,
    help="Skip the run, just print the diagnostic summary from saved results.",
)
def main(limit: Optional[int], analyze_only: bool) -> None:
    """Compare two LLM prompt designs for extracting search parameters
    (topic, year, citation constraints) from a research query. No OpenAlex
    calls — this experiment only checks extraction accuracy against
    hand-authored ground truth, not downstream retrieval quality.
    """
    if not analyze_only:
        run_plan_comparison(limit=limit)
    print_diagnostic_summary()


if __name__ == "__main__":
    main()
