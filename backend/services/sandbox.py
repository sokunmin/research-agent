"""
services/sandbox.py — Docker-based code execution sandbox.

Provides LlmSandboxToolSpec, a container-pooled sandbox for running Python code and
transferring files. Uses llm-sandbox (Docker backend) for efficient resource management.

Usage:
    sandbox = LlmSandboxToolSpec(local_save_path="/path/to/artifacts")
    sandbox.upload_file("/local/template.pptx")
    files = sandbox.list_files()
    agent_tools = sandbox.to_tool_list()   # pass to ReActAgent
    sandbox.download_file_to_local("/sandbox/output.pptx", "/local/output.pptx")
    sandbox.close()

Requires Docker Desktop to be running. Container pool pre-installs python-pptx.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from llm_sandbox import ArtifactSandboxSession
from llm_sandbox.pool import create_pool_manager, PoolConfig, ExhaustionStrategy
from llama_index.core.tools import FunctionTool

# Working directory inside every sandbox container
SANDBOX_DIR = "/sandbox"


@dataclass
class RemoteFile:
    """Metadata for a file inside the sandbox container."""

    filename: str
    file_full_path: str


class LlmSandboxToolSpec:
    """
    Docker-backed code execution sandbox with a container pool.

    Provides upload_file, list_files, download_file_to_local, and to_tool_list()
    so that workflow code integrates cleanly with ReActAgent.

    The pool pre-installs python-pptx, so agent code can use it without
    additional installation. Pool containers are reused across tool calls;
    their filesystems persist for the lifetime of the pool.

    Call close() when the owning workflow finishes to release Docker resources.
    """

    def __init__(
        self,
        local_save_path: str,
        libraries: Optional[list[str]] = None,
    ) -> None:
        self._local_save_path = local_save_path
        self._pool = create_pool_manager(
            backend="docker",
            lang="python",
            libraries=libraries or ["python-pptx"],
            config=PoolConfig(
                min_pool_size=1,
                max_pool_size=2,
                idle_timeout=300.0,
                acquisition_timeout=30.0,
                exhaustion_strategy=ExhaustionStrategy.WAIT,
                enable_prewarming=True,
            ),
        )

    # ── Agent-facing tools (exposed via to_tool_list) ─────────────────────────

    def run_code(self, code: str) -> str:
        """Execute Python code in the sandbox container and return stdout.
        python-pptx is pre-installed. Files persist at /sandbox/ between calls."""
        with ArtifactSandboxSession(pool=self._pool) as session:
            result = session.run(code)
        if result.exit_code != 0:
            return f"ERROR (exit_code={result.exit_code}):\n{result.stderr}"
        return result.stdout or "(no output)"

    def list_files_str(self, remote_dir: str = SANDBOX_DIR) -> str:
        """List files in the sandbox directory. Returns newline-separated file paths."""
        files = self.list_files(remote_dir)
        if not files:
            return f"(no files in {remote_dir})"
        return "\n".join(f.file_full_path for f in files)

    def upload_file(self, local_file_path: str) -> str:
        """Upload a local file into the sandbox container at /sandbox/<filename>."""
        filename = Path(local_file_path).name
        remote_path = f"{SANDBOX_DIR}/{filename}"
        with ArtifactSandboxSession(pool=self._pool) as session:
            session.copy_to_runtime(local_file_path, remote_path)
        return f"Uploaded {local_file_path} → {remote_path}"

    # ── Workflow-facing methods (called directly by workflow steps) ───────────

    def list_files(self, remote_dir: str = SANDBOX_DIR) -> list[RemoteFile]:
        """List files in the sandbox directory. Returns RemoteFile objects."""
        with ArtifactSandboxSession(pool=self._pool) as session:
            result = session.run(
                f"import os\n"
                f"entries = [f for f in os.listdir('{remote_dir}') "
                f"if os.path.isfile(os.path.join('{remote_dir}', f))]\n"
                f"print('\\n'.join(entries))"
            )
        return [
            RemoteFile(filename=name, file_full_path=f"{remote_dir}/{name}")
            for name in result.stdout.strip().splitlines()
            if name
        ]

    def download_file_to_local(
        self, remote_file_path: str, local_file_path: str
    ) -> None:
        """Download a file from the sandbox container to a local path."""
        with ArtifactSandboxSession(pool=self._pool) as session:
            session.copy_from_runtime(remote_file_path, local_file_path)

    # ── LlamaIndex integration ────────────────────────────────────────────────

    def to_tool_list(self) -> list[FunctionTool]:
        """Return LlamaIndex FunctionTools for ReActAgent use.
        Exposes: run_code, list_files_str (as 'list_files'), upload_file."""
        list_tool = FunctionTool.from_defaults(
            fn=self.list_files_str,
            name="list_files",
            description="List files in the sandbox container directory (/sandbox by default). "
            "Returns newline-separated file paths.",
        )
        return [
            FunctionTool.from_defaults(fn=self.run_code),
            list_tool,
            FunctionTool.from_defaults(fn=self.upload_file),
        ]

    # ── Resource management ───────────────────────────────────────────────────

    def close(self) -> None:
        """Shut down the container pool and release all Docker resources."""
        self._pool.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
