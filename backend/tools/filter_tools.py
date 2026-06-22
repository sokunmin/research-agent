import json
import re
from pathlib import Path

from docling_core.transforms.chunker.hierarchical_chunker import DocChunk


class ChunkFilter:
    """Filter boilerplate headings before embedding.

    Config file (filter_config.json) defines:
      exact_filter   — normalized headings that must match exactly
      keyword_filter — substrings that, if present, mark a heading as boilerplate

    Config path comes from settings.CHUNK_FILTER_CONFIG_PATH — never hardcoded.
    """

    def __init__(self, config_path: Path):
        config = json.loads(Path(config_path).read_text())
        self._exact: frozenset[str] = frozenset(config.get("exact_filter", []))
        self._keywords: list[str] = config.get("keyword_filter", [])

    @staticmethod
    def normalize(h: str) -> str:
        h = h.strip().lower().rstrip(".")
        h = re.sub(r"\s+", " ", h)
        h = re.sub(r"^§\s*", "", h)                               # § symbol prefix
        h = re.sub(r"^[\(\[]\w+[\)\]][\.\:\s\-]*", "", h)        # bracket prefix [A] or (1)
        h = re.sub(r"^\d[\d\.]*\s*[\.\:\-]?\s*", "", h)          # digit prefix 3. or 3.1
        h = re.sub(r"^([a-z]|[ivxlcdm]{2,})[\.\:\-]+\s*", "", h) # letter/roman prefix
        return h.strip()

    def should_skip_heading(self, heading: str) -> bool:
        """Core filter — accepts heading string, works with any chunker."""
        normalized = self.normalize(heading)
        if normalized in self._exact:
            return True
        return any(k in normalized for k in self._keywords)

    def should_skip(self, chunk: DocChunk) -> bool:
        """Convenience wrapper for HybridChunker DocChunk objects."""
        heading = (chunk.meta.headings or [""])[0]
        return self.should_skip_heading(heading)
