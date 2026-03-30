"""
Unit tests for MLflow v2 → v3 upgrade.
Validates: package version, autolog API availability,
main.py env var removal, docker-compose config correctness.
No API keys or running services required.
"""
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


# ── Helpers ───────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent.parent.parent  # dev-mlflow-v3-upgrade/
DOCKER_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


def _load_mlflow_service() -> dict:
    with open(DOCKER_COMPOSE_PATH) as f:
        compose = yaml.safe_load(f)
    return compose["services"]["mlflow"]


# ── 單元測試 — Python 套件版本 ──────────────────────────────────────────────────

class TestMlflowPackageVersion:
    def test_mlflow_版本為_3x(self):
        import mlflow
        assert mlflow.__version__.startswith("3."), (
            f"Expected mlflow 3.x, got {mlflow.__version__}"
        )


# ── 單元測試 — autolog API 可用性 ────────────────────────────────────────────────

class TestAutologAvailability:
    def test_mlflow_litellm_autolog_可呼叫且不拋出例外(self):
        import mlflow
        mlflow.litellm.autolog()  # should not raise

    def test_mlflow_llama_index_autolog_仍可正常呼叫_v3向下相容(self):
        import mlflow
        mlflow.llama_index.autolog()  # should not raise


# ── 單元測試 — main.py 環境變數行為 ──────────────────────────────────────────────

class TestMainEnvVar:
    def test_main_匯入後_MLFLOW_DEFAULT_ARTIFACT_ROOT_未被設定(self):
        # Ensure the key is absent before import
        os.environ.pop("MLFLOW_DEFAULT_ARTIFACT_ROOT", None)

        # Mock out heavy workflow imports so we only test env var side-effect
        with patch.dict("sys.modules", {
            "agent_workflows.slide_gen": __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(),
            "agent_workflows.summarize_and_generate_slides": __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(),
            "agent_workflows.summary_gen": __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock(),
        }):
            import importlib
            import main as _main  # noqa: F401 — import for side effects
            importlib.reload(_main)

        assert os.environ.get("MLFLOW_DEFAULT_ARTIFACT_ROOT") is None, (
            "MLFLOW_DEFAULT_ARTIFACT_ROOT should not be set by main.py"
        )


# ── 單元測試 — docker-compose.yml 配置正確性 ────────────────────────────────────

class TestDockerComposeConfig:
    def test_mlflow_service_image_tag_為_v3x(self):
        svc = _load_mlflow_service()
        image = svc["image"]
        assert "v2" not in image, f"Old v2 image still present: {image}"
        assert "v3" in image, f"Expected v3 image tag, got: {image}"

    def test_mlflow_service_不再暴露_port_5000(self):
        svc = _load_mlflow_service()
        ports = svc.get("ports", [])
        for p in ports:
            assert "5000" not in str(p), f"Port 5000 should be removed, found: {p}"

    def test_mlflow_backend_store_uri_使用四斜線絕對路徑(self):
        svc = _load_mlflow_service()
        command = svc.get("command", "")
        assert "sqlite:////" in command, (
            f"Expected 4-slash absolute SQLite URI, got: {command}"
        )

    def test_mlflow_command_含_default_artifact_root_參數(self):
        svc = _load_mlflow_service()
        command = svc.get("command", "")
        assert "--default-artifact-root" in command, (
            f"--default-artifact-root missing from command: {command}"
        )
