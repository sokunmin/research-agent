"""
Unit tests for HumanInTheLoopWorkflow helper methods.
No real MLflow server or LLM API required.
"""
from unittest.mock import MagicMock

from llama_index.core.workflow import StartEvent, StopEvent, step

from agent_workflows.hitl_workflow import HumanInTheLoopWorkflow


class _ConcreteWorkflow(HumanInTheLoopWorkflow):
    """Minimal concrete subclass satisfying LlamaIndex's StartEvent requirement."""

    @step
    async def handle_start(self, ev: StartEvent) -> StopEvent:
        return StopEvent(result="ok")


class TestEmitMessage:
    def test_writes_server_message_event_to_stream(self):
        """_emit_message() calls ctx.write_event_to_stream exactly once."""
        wf = _ConcreteWorkflow()
        ctx = MagicMock()
        wf._emit_message(ctx, "my_step", message="hello world")
        ctx.write_event_to_stream.assert_called_once()

    def test_event_has_correct_sender_and_message(self):
        """Emitted event carries correct event_sender and message content."""
        wf = _ConcreteWorkflow()
        ctx = MagicMock()
        wf._emit_message(ctx, "discover_papers", message="Found 42 papers")
        msg = ctx.write_event_to_stream.call_args[0][0].msg
        assert msg["event_type"] == "server_message"
        assert msg["event_sender"] == "discover_papers"
        assert msg["event_content"]["message"] == "Found 42 papers"
