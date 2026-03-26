import os
import subprocess
from pathlib import Path
import pytest

# Load .env from backend/ directory (pydantic-settings reads it for config.py)
# This ensures API keys set in .env are available to conftest fixtures
_env_file = Path(__file__).parent.parent / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_file)

# Fix macOS Python SSL certificate verification (common issue with python.org installer)
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass


_LLM_KEY_VARS = ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")


@pytest.fixture(autouse=True)
def skip_llm_without_key(request):
    if request.node.get_closest_marker("llm"):
        if not any(os.environ.get(k) for k in _LLM_KEY_VARS):
            pytest.skip("No LLM API key set — skipping llm test")


@pytest.fixture(autouse=True)
def skip_docker_unavailable(request):
    if request.node.get_closest_marker("docker"):
        result = subprocess.run(["docker", "info"], capture_output=True)
        if result.returncode != 0:
            pytest.skip("Docker not available — skipping docker test")


@pytest.fixture(autouse=True)
def _skip_marker_by_default(request):
    """test_3_marker.py runs marker models (~3–5 GB download, 10–20 min).
    Skipped by default; run explicitly with: pytest tests/.../test_3_marker.py
    """
    if request.node.path.name == "test_3_marker.py":
        pytest.skip("Skipped by default (slow — marker models); run file explicitly to enable")
