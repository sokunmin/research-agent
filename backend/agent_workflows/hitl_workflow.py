import asyncio
import mlflow
from typing import Literal
from config import settings
from llama_index.core.workflow import Context, Event, Workflow
from llama_index.core.workflow.retry_policy import RetryPolicy
from agent_workflows.schemas import WorkflowStreamingEvent
from utils.logger import get_logger

logger = get_logger(__name__)


class LLMRetryPolicy(RetryPolicy):
    """Retry policy with logging for LLM steps.

    Logs each attempt and the final exhaustion so transient errors
    (rate limits, JSON parse failures) are visible in the workflow log.
    """
    def __init__(self, max_attempts: int = 3, wait_seconds: float = 5.0):
        self.max_attempts = max_attempts
        self.wait_seconds = wait_seconds

    def next(self, elapsed_time: float, attempts: int, error: Exception) -> float | None:
        if attempts >= self.max_attempts:
            logger.error(
                f"LLM retry exhausted after {attempts} attempts. "
                f"Last error: {type(error).__name__}: {error}"
            )
            return None
        logger.warning(
            f"LLM retry attempt {attempts + 1}/{self.max_attempts}: "
            f"{type(error).__name__}: {error}"
        )
        return self.wait_seconds


# Cloud LLM: longer wait for rate limits (smart_llm)
CLOUD_LLM_RETRY_POLICY = LLMRetryPolicy(max_attempts=3, wait_seconds=10.0)
# Local Ollama: shorter wait for transient connection errors (fast_llm)
LOCAL_LLM_RETRY_POLICY = LLMRetryPolicy(max_attempts=3, wait_seconds=5.0)


class HumanInTheLoopWorkflow(Workflow):
    def _emit_message(
        self,
        ctx: Context,
        sender: str,
        event_type: Literal["server_message", "request_user_input"] = "server_message",
        **event_content,
    ) -> None:
        """Write a streaming event to the workflow stream."""
        ctx.write_event_to_stream(
            Event(
                msg=WorkflowStreamingEvent(
                    event_type=event_type,
                    event_sender=sender,
                    event_content=event_content,
                ).model_dump()
            )
        )

    async def run(self, *args, **kwargs):
        self.loop = asyncio.get_running_loop()  # Store the event loop
        mlflow.set_tracking_uri(settings.MLFLOW_TRACKING_URI)

        mlflow.set_experiment(self.__class__.__name__)
        # mlflow.config.enable_async_logging()
        # mlflow.tracing.enable()
        mlflow.llama_index.autolog()
        mlflow.litellm.autolog()
        with mlflow.start_run():
            logger.debug(
                f"{self.__class__.__name__}: MLflow tracking URI {mlflow.get_tracking_uri()}"
            )
            logger.debug(
                f"{self.__class__.__name__}: MLflow artifact store {mlflow.get_artifact_uri()}"
            )
            logger.debug(f"{self.__class__.__name__}: MLflow run started")
            try:
                result = await super().run(*args, **kwargs)
                # mlflow.log_param("status", "success")
                logger.debug(f"{self.__class__.__name__}: Workflow succeeded")
                return result
            except Exception as e:
                # Log the exception details to MLflow
                mlflow.log_param("status", "failed")
                mlflow.log_param("error_message", str(e))
                logger.error(f"Workflow failed with exception: {e}")
                raise  # Re-raise the exception after logging
            finally:
                # mlflow.end_run()
                logger.debug(f"{self.__class__.__name__}: MLflow run ended")
