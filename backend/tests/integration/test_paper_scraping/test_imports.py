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


def test_no_azure_in_services():
    """services/ has zero azure imports."""
    svc_dir = Path("services")
    for py in svc_dir.glob("**/*.py"):
        content = py.read_text().lower()
        assert "azure" not in content, f"Found azure reference in {py}"
