import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from poc_base import DoclingPoc

from docling.datamodel.document import DoclingDocument
from docling_core.transforms.chunker.hierarchical_chunker import DocChunk


_ALWAYS_FILTER: frozenset[str] = frozenset({
    "bibliography",
    "checklist",
    "neurips paper checklist",
    "reproducibility statement",
    "author contributions",
    "funding",
    "conflict of interest",
    "data availability",
})


class HeadingAnalyzer:
    def __init__(self, chunk_size: int = 512):
        self._converter = DoclingPoc.build_analysis_converter()
        self._chunker   = DoclingPoc.build_chunker(chunk_size)
        self._records:  list[dict] = []
        self._n_papers: int = 0

    def analyze_paper(self, pdf_path: Path) -> int:
        result = self._converter.convert(str(pdf_path), max_num_pages=50)
        records = self._extract_headings(result.document, self._n_papers)
        self._records.extend(records)
        self._n_papers += 1
        return len(records)

    def analyze_directory(self, pdf_dir: Path, limit: int = 30) -> None:
        paths = sorted(Path(pdf_dir).glob("*.pdf"))[:limit]
        for path in paths:
            try:
                n = self.analyze_paper(path)
                print(f"[{self._n_papers}] {path.name}: {n} records")
            except Exception as e:
                print(f"SKIP {path.name}: {e}")

    def _extract_headings(self, doc: DoclingDocument, paper_idx: int) -> list[dict]:
        chunks = DoclingPoc.get_chunks(doc, self._chunker)
        total = len(chunks)
        if total == 0:
            return []
        return [
            {
                "heading_lower": (chunk.meta.headings or [""])[0].lower().strip(),
                "position": round(i / total, 3),
                "paper_idx": paper_idx,
            }
            for i, chunk in enumerate(chunks)
            if chunk.meta.headings
        ]

    def compute_stats(self) -> dict:
        from collections import defaultdict
        paper_positions: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
        for rec in self._records:
            h = rec["heading_lower"]
            if h:
                paper_positions[h][rec["paper_idx"]].append(rec["position"])

        result = {}
        for h, papers in paper_positions.items():
            n_papers_with = len(papers)
            paper_min_positions = [min(pos) for pos in papers.values()]
            result[h] = {
                "paper_frequency": round(n_papers_with / self._n_papers, 3),
                "mean_position":   round(statistics.mean(paper_min_positions), 3),
                "min_position":    round(min(paper_min_positions), 3),
            }
        return result

    def print_stats(self, min_freq: float = 0.20) -> None:
        stats = self.compute_stats()
        print(f"\n{'heading':<40} {'freq':>6} {'mean_pos':>10} {'min_pos':>8}")
        print("-" * 68)
        for h, s in sorted(stats.items(), key=lambda x: -x[1]["paper_frequency"]):
            if s["paper_frequency"] >= min_freq:
                print(f"{h:<40} {s['paper_frequency']:>6.2f} {s['mean_position']:>10.3f} {s['min_position']:>8.3f}")

    def derive_config(self) -> dict:
        stats = self.compute_stats()
        filter_headings = sorted(
            h for h, s in stats.items()
            if s["paper_frequency"] >= 0.40 and s["mean_position"] > 0.75
        )
        return {
            "filter_headings": filter_headings,
            "always_filter": sorted(_ALWAYS_FILTER),
            "thresholds": {
                "paper_frequency": 0.40,
                "mean_position": 0.75,
            },
            "n_papers": self._n_papers,
        }

    def save_config(self, path: str = "poc/rag-filtering/filter_config.json") -> dict:
        config = self.derive_config()
        Path(path).write_text(json.dumps(config, indent=2))
        print(f"\nSaved filter config → {path}")
        return config

    def save_stats(self, path: str = "poc/rag-filtering/analysis_stats.json") -> None:
        stats = self.compute_stats()
        Path(path).write_text(json.dumps(stats, indent=2))
        print(f"Saved full stats → {path}")


if __name__ == "__main__":
    analyzer = HeadingAnalyzer()
    analyzer.analyze_directory(Path("poc/pdfs"), limit=28)
    analyzer.print_stats()
    analyzer.save_stats()
    config = analyzer.save_config()
    print(json.dumps(config, indent=2))
