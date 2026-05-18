import sys

from fastapi import FastAPI, HTTPException, Body, Request
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
    allow_origins=["http://localhost:3001"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["x-vercel-ai-ui-message-stream"],
)


def _sse(event: dict) -> str:
    """Format one AI SDK UIMessageStream v5 SSE event line."""
    return f"data: {json.dumps(event)}\n\n"


@app.post("/run-slide-gen")
async def run_workflow_endpoint(topic: ResearchTopic, request: Request):
    workflow_id = str(uuid.uuid4())

    wf = SummaryAndSlideGenerationWorkflow(
        summary_gen_wf=SummaryGenerationWorkflow(
            wid=workflow_id, timeout=3600, verbose=True
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
        msg_id = f"msg-{uuid.uuid4().hex[:8]}"
        loop = asyncio.get_running_loop()

        yield _sse({"type": "start", "messageId": msg_id})
        yield _sse({"type": "data-workflow-id", "data": {"workflow_id": workflow_id}})

        wf.loop = loop
        handler = Workflow.run(wf, user_query=topic.query)
        try:
            async for ev in handler.stream_events():
                if await request.is_disconnected():
                    logger.info(f"Client disconnected, cancelling workflow {workflow_id}")
                    break
                if isinstance(ev, StopEvent):
                    continue

                raw = ev.msg if isinstance(ev.msg, dict) else json.loads(ev.msg)
                streaming_event = WorkflowStreamingEvent(**raw)
                event_type = streaming_event.event_type
                sender = streaming_event.event_sender
                content = streaming_event.event_content

                if event_type == "server_message":
                    part_type = "data-reasoning" if sender == "react_agent" else "data-step-progress"
                    yield _sse({"type": part_type,
                                "data": {"sender": sender, "message": content.get("message", "")},
                                "transient": True})

                elif event_type == "paper_total":
                    yield _sse({"type": "data-paper-total",
                                "data": {"total": content.get("total")},
                                "transient": True})

                elif event_type == "request_user_input":
                    yield _sse({"type": "data-request-user-input",
                                "id": content.get("eid", uuid.uuid4().hex),
                                "data": {
                                    "eid":           content.get("eid"),
                                    "summary":       content.get("summary"),
                                    "paper_outline": content.get("paper_outline"),
                                    "message":       content.get("message"),
                                }})

                elif event_type == "paper_candidates":
                    yield _sse({
                        "type": "data-paper-candidates",
                        "data": {
                            "candidates":    content.get("candidates", []),
                            "search_params": content.get("search_params", {}),
                        },
                    })

                elif event_type == "no_results":
                    yield _sse({
                        "type": "data-no-results",
                        "data": {
                            "message":     content.get("message", "No relevant papers found."),
                            "suggestions": content.get("suggestions", []),
                        },
                    })

                elif event_type == "supervisor_response":
                    yield _sse({
                        "type": "data-supervisor-response",
                        "data": {"message": content.get("message", "")},
                    })

                await asyncio.sleep(0.1)  # keep existing chunking sleep

            final_result = await handler
            if final_result is not None:
                yield _sse({"type": "data-final-result",
                            "data": {
                                "download_pptx_url": f"http://localhost:8000/download_pptx/{workflow_id}",
                                "download_pdf_url":  f"http://localhost:8000/download_pdf/{workflow_id}",
                            }})

        except asyncio.TimeoutError:
            yield _sse({
                "type": "data-no-results",
                "data": {
                    "message": "Session timed out. Please start a new search.",
                    "suggestions": ["Enter a new research topic below"],
                },
            })
        except Exception as e:
            error_message = f"Error in workflow: {str(e)}"
            logger.error(error_message)
            yield _sse({"type": "data-step-progress",
                        "data": {"sender": "system", "message": error_message},
                        "transient": True})
        finally:
            wf.cancel()
            workflows.pop(workflow_id, None)

        yield _sse({"type": "finish"})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


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


@app.post("/submit_paper_selection")
async def submit_paper_selection(data: dict = Body(...)):
    """Unblock present_paper_candidates HITL with user's paper selection or abort signal."""
    workflow_id = data.get("workflow_id")
    user_input = data.get("user_input")
    wf = workflows.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if wf.user_input_future and not wf.user_input_future.done():
        loop = wf.user_input_future.get_loop()
        loop.call_soon_threadsafe(wf.user_input_future.set_result, user_input)
        return {"status": "selection received"}
    raise HTTPException(status_code=409, detail="No pending paper selection")


@app.post("/submit_paper_question")
async def submit_paper_question(data: dict = Body(...)):
    """Answer a question about listed papers without unblocking the paper selection future."""
    workflow_id = data.get("workflow_id")
    message = data.get("message", "")
    wf = workflows.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    answer = await wf.summary_gen_wf.handle_paper_question(message)
    return {"status": "ok", "answer": answer}


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
