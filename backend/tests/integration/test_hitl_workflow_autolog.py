"""
Integration test for HumanInTheLoopWorkflow — mlflow.litellm.autolog() call.
Uses mocked MLflow to verify autolog is wired into the workflow run path.
No real MLflow server or LLM API required.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from llama_index.core.workflow import StartEvent, StopEvent, step

from agent_workflows.hitl_workflow import HumanInTheLoopWorkflow


class _ConcreteWorkflow(HumanInTheLoopWorkflow):
    """Minimal concrete subclass satisfying LlamaIndex's StartEvent requirement."""

    @step
    async def handle_start(self, ev: StartEvent) -> StopEvent:
        return StopEvent(result="ok")


class TestHitlWorkflowAutolog:
    def test_HumanInTheLoopWorkflow_run_會呼叫_mlflow_litellm_autolog(self):
        mock_mlflow = MagicMock()
        mock_mlflow.start_run.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_mlflow.start_run.return_value.__exit__ = MagicMock(return_value=False)

        with patch("agent_workflows.hitl_workflow.mlflow", mock_mlflow):
            async def _run():
                wf = _ConcreteWorkflow(timeout=10)
                await wf.run()

            asyncio.run(_run())

        mock_mlflow.litellm.autolog.assert_called_once()
