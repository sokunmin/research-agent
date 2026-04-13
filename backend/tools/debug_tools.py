from pathlib import Path

from llama_index.core.tools import FunctionTool


class WorkflowDebugToolSpec:
    """Debug tools for inspecting agent-generated artefacts during development.

    These tools are intentionally excluded from SlideGenerationWorkflow.to_tool_list()
    so they are never exposed to the LLM. They exist to support developer debugging
    workflows without polluting the agent's tool selection.
    """

    def __init__(self, artifacts_path: Path) -> None:
        # Accept Path (as used by SlideGenerationWorkflow.workflow_artifacts_path)
        self._artifacts_path = str(artifacts_path)

    def save_python_code(self, code: str) -> str:
        """Save agent-generated Python code to the workflow artifacts directory.
        Useful for debugging agent output without re-running the full workflow.
        Saved to: <artifacts_path>/code.py"""
        path = f"{self._artifacts_path}/code.py"
        with open(path, "w") as f:
            f.write(code)
        return f"Code saved to {path}"

    def to_tool_list(self) -> list[FunctionTool]:
        """Full list of debug tools available from this spec."""
        return [
            FunctionTool.from_defaults(
                fn=self.save_python_code,
                description=(
                    "Save Python code to the workflow artifacts directory for debugging. "
                    "Use to persist agent-generated code for post-run inspection."
                ),
            )
        ]
