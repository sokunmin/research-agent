import sys

from fastapi import FastAPI, HTTPException, Body
import asyncio
from fastapi.responses import StreamingResponse
import uuid
import json
from models import SlideGenFileDirectory, ResearchTopic
from agent_workflows.schemas import WorkflowStreamingEvent
from agent_workflows.slide_gen import SlideGenerationWorkflow
from agent_workflows.summarize_and_generate_slides import SummaryAndSlideGenerationWorkflow
from agent_workflows.summary_gen import (
    SummaryGenerationWorkflow,
    SummaryGenerationDummyWorkflow,
)
from fastapi.middleware.cors import CORSMiddleware
from llama_index.core.workflow import Workflow, StopEvent

import mlflow
from config import settings
import os
from fastapi.responses import FileResponse
from pathlib import Path
from utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI()
workflows = {}  # Store the workflow instances in a dictionary


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://frontend:8501"],  # Replace with your Streamlit frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/run-slide-gen")
async def run_workflow_endpoint(topic: ResearchTopic):
    workflow_id = str(uuid.uuid4())

    wf = SummaryAndSlideGenerationWorkflow(
        summary_gen_wf=SummaryGenerationWorkflow(
            wid=workflow_id, timeout=800, verbose=True
        ),
        # toggle for skipping SummaryGenerationWorkflow and debugging SlideGenerationWorkflow:
        # summary_gen_wf=SummaryGenerationDummyWorkflow(
        #     wid=workflow_id, timeout=800, verbose=True
        # ),
        slide_gen_wf=SlideGenerationWorkflow(
            wid=workflow_id, timeout=1200, verbose=True
        ),
        wid=workflow_id,
        timeout=2000,
        verbose=True,
    )

    # wf = SlideGenerationWorkflow(timeout=1200, verbose=True)

    workflows[workflow_id] = wf  # Store the workflow instance

    async def event_generator():
        loop = asyncio.get_running_loop()
        logger.debug(f"event_generator: loop id {id(loop)}")
        yield f"data: {json.dumps({'workflow_id': workflow_id})}\n\n"

        # llama-index-core 0.14.x: stream_events() lives on the Handler returned
        # by Workflow.run(), not on the Workflow instance. Call base Workflow.run()
        # directly to obtain the Handler (same approach as run_subworkflow).
        wf.loop = asyncio.get_running_loop()
        handler = Workflow.run(wf, user_query=topic.query)
        logger.debug(f"event_generator: Created handler {handler}")
        try:
            async for ev in handler.stream_events():
                if isinstance(ev, StopEvent):
                    continue
                logger.info(f"Sending message to frontend: {ev.msg}")
                msg_str = json.dumps(ev.msg) if isinstance(ev.msg, dict) else ev.msg
                yield f"data: {msg_str}\n\n"
                await asyncio.sleep(0.1)  # Small sleep to ensure proper chunking
            final_result = await handler

            # Construct the download URL
            download_pptx_url = f"http://backend:80/download_pptx/{workflow_id}"
            download_pdf_url = f"http://backend:80/download_pdf/{workflow_id}"

            final_result_with_url = {
                "result": final_result,
                "download_pptx_url": download_pptx_url,
                "download_pdf_url": download_pdf_url,
            }

            yield f"data: {json.dumps({'final_result': final_result_with_url})}\n\n"
        except Exception as e:
            error_message = f"Error in workflow: {str(e)}"
            logger.error(error_message)
            error_event = WorkflowStreamingEvent(
                event_type="server_message",
                event_sender="system",
                event_content={"message": error_message},
            )
            yield f"data: {json.dumps(error_event.model_dump())}\n\n"
        finally:
            # Clean up
            workflows.pop(workflow_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/submit_user_input")
async def submit_user_input(data: dict = Body(...)):
    workflow_id = data.get("workflow_id")
    user_input = data.get("user_input")
    wf = workflows.get(workflow_id)
    if wf and wf.user_input_future:
        loop = wf.user_input_future.get_loop()  # Get the loop from the future
        logger.info(f"submit_user_input: wf.user_input_future loop id {id(loop)}")
        if not wf.user_input_future.done():
            loop.call_soon_threadsafe(wf.user_input_future.set_result, user_input)
            logger.info("submit_user_input: set_result called")
        else:
            logger.info("submit_user_input: future already done")
        return {"status": "input received"}
    else:
        raise HTTPException(
            status_code=404, detail="Workflow not found or future not initialized"
        )


@app.get("/download_pptx/{workflow_id}")
async def download_pptx(workflow_id: str):
    file_path = (
        Path(settings.WORKFLOW_ARTIFACTS_ROOT)
        / "SlideGenerationWorkflow"
        / workflow_id
        / "final.pptx"
    )
    if file_path.exists():
        return FileResponse(
            path=file_path,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            filename=f"final.pptx",
        )
    else:
        raise HTTPException(status_code=404, detail="File not found")


@app.get("/download_pdf/{workflow_id}")
async def download_pdf(workflow_id: str):
    file_path = (
        Path(settings.WORKFLOW_ARTIFACTS_ROOT)
        / "SlideGenerationWorkflow"
        / workflow_id
        / "final.pdf"
    )
    if file_path.exists():
        return FileResponse(
            path=file_path, media_type="application/pdf", filename=f"{workflow_id}.pdf"
        )
    else:
        raise HTTPException(status_code=404, detail="PDF file not found")


@app.get("/")
async def read_root():
    return {"Hello": "World"}
