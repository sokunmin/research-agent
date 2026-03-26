"""
test_imports.py
Static import checks and code residue scans.
No network, Docker, or API key required.
"""
from pathlib import Path


def test_agent_workflows_module_imports():
    """All agent_workflows modules can be imported without error."""
    import agent_workflows.slide_gen           # noqa: F401
    import agent_workflows.summary_gen_w_qe   # noqa: F401
    import agent_workflows.events             # noqa: F401
    import agent_workflows.paper_scraping     # noqa: F401


def test_no_from_workflows_residue_in_agent_workflows():
    """No file under agent_workflows/ still uses 'from workflows.' import."""
    aw_dir = Path("agent_workflows")
    for py in aw_dir.glob("**/*.py"):
        content = py.read_text()
        assert "from workflows." not in content, f"Found old import in {py}"


def test_no_tavily_in_summary_gen():
    """summary_gen.py must not import Tavily after pipeline replacement."""
    src = (Path("agent_workflows") / "summary_gen.py").read_text()
    assert "tavily" not in src.lower()


def test_old_filter_api_removed_from_paper_scraping():
    """Deleted symbols must not appear in paper_scraping.py."""
    src = (Path("agent_workflows") / "paper_scraping.py").read_text()
    for symbol in ("IsCitationRelevant", "process_citation",
                   "filter_relevant_citations", "download_paper_arxiv",
                   "download_relevant_citations"):
        assert symbol not in src, f"Deleted symbol still present: {symbol}"


def test_tavily_event_removed_from_events():
    """TavilyResultsEvent and FilteredPapersEvent must not exist in events.py."""
    src = (Path("agent_workflows") / "events.py").read_text()
    assert "TavilyResultsEvent" not in src
    assert "FilteredPapersEvent" not in src
