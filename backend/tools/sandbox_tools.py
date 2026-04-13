"""
tools/sandbox_tools.py — Docker-based code execution sandbox.

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

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from llm_sandbox import ArtifactSandboxSession
from llm_sandbox.pool import create_pool_manager, PoolConfig, ExhaustionStrategy
from llama_index.core.tools import FunctionTool

from config import settings

# Working directory inside every sandbox container
SANDBOX_DIR = "/sandbox"

# llm-sandbox writes each run() call as <uuid32>.py inside the container workdir and never
# cleans it up. Filter these execution artifacts out of file listings shown to the LLM.
_SANDBOX_ARTIFACT_RE = re.compile(r'^[0-9a-f]{32}\.[a-z]+$')


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
        # Tracks consecutive run_code failures for the LIMIT REACHED stop signal.
        # Resets to 0 on any successful execution. Instance-scoped so each workflow
        # gets an independent counter.
        self._consecutive_errors: int = 0
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
        """Execute Python code in the sandbox container.

        python-pptx is pre-installed. Files created at /sandbox/ persist between calls.

        Returns:
            - stdout text on success (or "(no output)" if the script produces no output)
            - a string beginning with "ERROR (exit_code=...):" followed by stderr on failure;
              after SLIDE_GEN_MAX_RETRY_ATTEMPTS consecutive failures the string also ends
              with "LIMIT REACHED" — the agent must stop retrying when it sees that token.
        """
        with ArtifactSandboxSession(pool=self._pool, enable_plotting=False) as session:
            result = session.run(code)
        if result.exit_code != 0:
            self._consecutive_errors += 1
            error_msg = f"ERROR (exit_code={result.exit_code}):\n{result.stderr}"
            if self._consecutive_errors >= settings.SLIDE_GEN_MAX_RETRY_ATTEMPTS:
                error_msg += (
                    f"\nAttempt ({self._consecutive_errors}/"
                    f"{settings.SLIDE_GEN_MAX_RETRY_ATTEMPTS}) failed. LIMIT REACHED."
                )
            else:
                error_msg += (
                    f"\nAttempt ({self._consecutive_errors}/"
                    f"{settings.SLIDE_GEN_MAX_RETRY_ATTEMPTS}) failed."
                )
            return error_msg
        # Reset on success — agent has earned a fresh retry budget.
        self._consecutive_errors = 0
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
        with ArtifactSandboxSession(pool=self._pool, enable_plotting=False) as session:
            result = session.run(
                f"import os\n"
                f"entries = [f for f in os.listdir('{remote_dir}') "
                f"if os.path.isfile(os.path.join('{remote_dir}', f))]\n"
                f"print('\\n'.join(entries))"
            )
        return [
            RemoteFile(filename=name, file_full_path=f"{remote_dir}/{name}")
            for name in result.stdout.strip().splitlines()
            if name and not _SANDBOX_ARTIFACT_RE.match(name)
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
        Exposes: run_code, list_files. upload_file is intentionally excluded —
        input files are uploaded by workflow code before the agent starts."""
        list_tool = FunctionTool.from_defaults(
            fn=self.list_files_str,
            name="list_files",
            description="List files in the sandbox container directory (/sandbox by default). "
            "Returns newline-separated file paths.",
        )
        return [
            FunctionTool.from_defaults(
                fn=self.run_code,
                description=(
                    "Execute Python code in the sandbox container. "
                    "python-pptx is pre-installed. Files persist at /sandbox/ between calls. "
                    "Returns stdout on success, or a string starting with 'ERROR' on failure. "
                    "Stop retrying when the observation contains 'LIMIT REACHED'."
                ),
            ),
            list_tool,
            # TODO: upload_file is handled by workflow code before the agent starts.
            # Exposing it to the agent is unnecessary and adds noise to tool selection.
            # Confirm with end-to-end test, then remove this line and the comment.
            # FunctionTool.from_defaults(fn=self.upload_file),
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
