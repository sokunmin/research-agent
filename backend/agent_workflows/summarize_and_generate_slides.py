import asyncio
import uuid

import click
from llama_index.core.workflow import (
    Context,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)

from agent_workflows.events import *
from agent_workflows.slide_gen import SlideGenerationWorkflow
from agent_workflows.summary_gen import SummaryGenerationWorkflow
from utils.logger import get_logger

logger = get_logger(__name__)


class SummaryAndSlideGenerationWorkflow(Workflow):

    def __init__(
        self,
        summary_gen_wf: SummaryGenerationWorkflow,
        slide_gen_wf: SlideGenerationWorkflow,
        wid: Optional[uuid.UUID] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.wid = wid or uuid.uuid4()
        self.summary_gen_wf = summary_gen_wf
        self.slide_gen_wf = slide_gen_wf
        self.user_input_future = asyncio.Future()

    async def run(self, *args, **kwargs):
        self.loop = asyncio.get_running_loop()  # Store the event loop
        return await super().run(*args, **kwargs)

    async def reset_user_input_future(self):
        self.user_input_future = self.loop.create_future()

    async def run_subworkflow(self, sub_wf, ctx, **kwargs):
        logger.debug(f"Starting sub-workflow: {sub_wf.__class__.__name__}")
        sub_wf.user_input_future = self.user_input_future
        sub_wf.parent_workflow = self
        # Set loop manually: HumanInTheLoopWorkflow.run() normally sets self.loop,
        # but we bypass it below. SlideGenerationWorkflow's HITL step calls
        # self.loop.create_future(), so this must be set before execution.
        sub_wf.loop = asyncio.get_running_loop()

        # llama-index-core 0.14.x: Workflow.run() returns a Handler synchronously;
        # stream_events() lives on the Handler, not on the Workflow instance.
        # We call the base Workflow.run() directly to obtain the Handler.
        # HumanInTheLoopWorkflow.run() is async def and internally awaits the Handler,
        # which consumes it and makes stream_events() unreachable.
        # Trade-off: sub-workflow MLflow runs are not created as nested runs;
        # LLM calls are still tracked under the parent's active MLflow run via autolog.
        # See BACKUP_PLAN.md for Approach B which preserves nested MLflow runs.
        handler = Workflow.run(sub_wf, **kwargs)
        logger.debug(f"Created sub-workflow handler: {handler}")
        try:
            async for event in handler.stream_events():
                logger.debug(f"Relaying event from sub-workflow: {event}")
                if isinstance(event, StopEvent):
                    continue
                ctx.write_event_to_stream(event)
            result = await handler
            logger.debug(f"Sub-workflow completed with result: {result}")
            return result
        except Exception as e:
            logger.error(f"Error in sub-workflow: {e}")
            raise

    @step
    async def summary_gen(
        self, ctx: Context, ev: StartEvent
    ) -> SummaryWfReadyEvent:
        res = await self.run_subworkflow(self.summary_gen_wf, ctx, user_query=ev.user_query)
        return SummaryWfReadyEvent(summary_dir=res)

    @step
    async def slide_gen(
        self,
        ctx: Context,
        ev: SummaryWfReadyEvent,
    ) -> StopEvent:
        res = await self.run_subworkflow(self.slide_gen_wf, ctx, file_dir=ev.summary_dir)
        return StopEvent(res)


async def run_workflow(user_query: str):
    wf = SummaryAndSlideGenerationWorkflow(
        summary_gen_wf=SummaryGenerationWorkflow(timeout=800, verbose=True),
        slide_gen_wf=SlideGenerationWorkflow(timeout=1200, verbose=True),
        timeout=2000,
        verbose=True,
    )
    result = await wf.run(user_query=user_query)
    print(result)


@click.command()
@click.option(
    "--user-query",
    "-q",
    required=False,
    help="The user query",
    default="powerpoint slides automation",
)
def main(user_query: str):
    asyncio.run(run_workflow(user_query))


if __name__ == "__main__":
    from llama_index.utils.workflow import draw_all_possible_flows
    draw_all_possible_flows(
        SummaryAndSlideGenerationWorkflow, filename="summary_slide_gen_flows.html"
    )
    main()
