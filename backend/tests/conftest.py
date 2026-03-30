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

# config.py requires TAVILY_API_KEY (only field with no default after Azure removal)
os.environ.setdefault("TAVILY_API_KEY", "dummy-tavily-key")

# Fix macOS Python SSL certificate verification (common issue with python.org installer)
try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
    os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
except ImportError:
    pass


@pytest.fixture(autouse=True)
def skip_llm_without_key(request):
    if request.node.get_closest_marker("llm"):
        if not os.environ.get("GEMINI_API_KEY"):
            pytest.skip("GEMINI_API_KEY not set — skipping llm test")


@pytest.fixture(autouse=True)
def skip_docker_unavailable(request):
    if request.node.get_closest_marker("docker"):
        result = subprocess.run(["docker", "info"], capture_output=True)
        if result.returncode != 0:
            pytest.skip("Docker not available — skipping docker test")
