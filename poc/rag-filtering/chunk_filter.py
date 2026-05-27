"""ChunkFilter — heading-based chunk filter for RAG pipelines.

Reads filter_config.json and filters chunk lists by heading text.
No Docling imports — accepts any chunk objects with `.meta.headings`.
"""
import json
from pathlib import Path


class ChunkFilter:
    """Two-layer heading filter: exact match then keyword match.

    Layer 1 — exact: normalized heading is in the exact_filter set.
    Layer 2 — keyword: any keyword from keyword_filter appears in the heading.
    Chunks with no heading are always kept.
    """

    def __init__(self, config_path: str | Path = "poc/rag-filtering/filter_config.json"):
        config = json.loads(Path(config_path).read_text())
        self._exact: frozenset[str] = frozenset(config.get("exact_filter", []))
        self._keywords: list[str] = config.get("keyword_filter", [])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_filter(self, heading: str) -> tuple[bool, str]:
        """Return (True, reason) if the heading should be filtered, else (False, "").

        reason is "exact" or "keyword".
        """
        normalized = heading.lower().strip()
        if normalized in self._exact:
            return True, "exact"
        if any(k in normalized for k in self._keywords):
            return True, "keyword"
        return False, ""

    def filter_chunks(self, chunks: list) -> tuple[list, list]:
        """Partition chunks into (kept, dropped).

        Chunks without headings are always kept.
        """
        kept: list = []
        dropped: list = []
        for chunk in chunks:
            headings = chunk.meta.headings
            if not headings:
                kept.append(chunk)
                continue
            heading = headings[0]
            should_drop, _ = self.should_filter(heading)
            if should_drop:
                dropped.append(chunk)
            else:
                kept.append(chunk)
        return kept, dropped
