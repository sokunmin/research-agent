import base64
import json
import logging
from collections import deque

import streamlit as st
import httpx
import asyncio
import threading
import queue

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# Initialize session state variables
if "workflow_complete" not in st.session_state:
    st.session_state.workflow_complete = False

if "received_lines" not in st.session_state:
    st.session_state.received_lines = []

if "workflow_id" not in st.session_state:
    st.session_state.workflow_id = None

if "workflow_thread" not in st.session_state:
    st.session_state.workflow_thread = None

if "user_input_required" not in st.session_state:
    st.session_state.user_input_required = False

if "user_input_prompt" not in st.session_state:
    st.session_state.user_input_prompt = None

if "message_queue" not in st.session_state:
    st.session_state.message_queue = queue.Queue()

if "user_input_event" not in st.session_state:
    st.session_state.user_input_event = threading.Event()

if "user_response_submitted" not in st.session_state:
    st.session_state.user_response_submitted = False

if "download_url_pptx" not in st.session_state:
    st.session_state.download_url_pptx = None

if "download_url_pdf" not in st.session_state:
    st.session_state.download_url_pdf = None

if "pdf_data" not in st.session_state:
    st.session_state.pdf_data = None

if "expander_label" not in st.session_state:
    st.session_state.expander_label = "🤖⚒️Agent is working..."

# Initialize feedback-related session state variables
if "user_feedback" not in st.session_state:
    st.session_state.user_feedback = ""

if "approval_state" not in st.session_state:
    st.session_state.approval_state = None

# Initialize a queue for pending user input prompts
if "pending_user_inputs" not in st.session_state:
    st.session_state.pending_user_inputs = deque()

# Initialize a prompt counter
if "prompt_counter" not in st.session_state:
    st.session_state.prompt_counter = 0

if "current_reasoning" not in st.session_state:
    st.session_state.current_reasoning = ""


async def fetch_streaming_data(url: str, payload: dict = None):
    async with httpx.AsyncClient(timeout=1200.0) as client:
        async with client.stream("POST", url=url, json=payload) as response:
            async for line in response.aiter_lines():
                if line:
                    yield line


def format_workflow_info(info_json: dict):
    # event_type = info_json.get("event_type")
    event_sender = info_json.get("event_sender")
    event_content = info_json.get("event_content")

    try:
        return f"[{event_sender}]: {event_content.get('message')}"
    except Exception as e:
        logging.warning(f"Error formatting workflow info: {str(e)}")
        return json.dumps(info_json)


async def get_stream_data(url, payload, message_queue, user_input_event):
    # message_queue.put(("message", "Starting to fetch streaming data..."))
    data_json = None
    async for data in fetch_streaming_data(url, payload):
        if data:
            try:
                data = data.strip()
                if not data or not data.startswith("data:"):
                    continue
                data_json = json.loads(data[len("data:"):].strip())
                if "workflow_id" in data_json:
                    # Send workflow_id to main thread
                    message_queue.put(("workflow_id", data_json["workflow_id"]))
                    continue
                elif "final_result" in data_json:
                    # Send final_result to main thread
                    message_queue.put(("final_result", data_json["final_result"]))
                    continue
                event_type = data_json.get("event_type")
                event_sender = data_json.get("event_sender")
                event_content = data_json.get("event_content")
                if event_type in ["request_user_input"]:
                    # Send the message to the main thread
                    message_queue.put(("user_input_required", data_json))
                    # Wait until user input is provided
                    user_input_event.wait()
                    user_input_event.clear()
                    continue
                else:
                    if event_sender == "react_agent":
                        msg = event_content.get("message", "") if event_content else ""
                        message_queue.put(("reasoning", msg))
                    else:
                        message_queue.put(("message", format_workflow_info(data_json)))
            except json.JSONDecodeError:  # todo: is this necessary?
                message_queue.put(("message", data))
        if data_json and "final_result" in data_json or "final_result" in str(data):
            break  # Stop processing after receiving the final result


def start_long_running_task(url, payload, message_queue, user_input_event):
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            get_stream_data(url, payload, message_queue, user_input_event)
        )
        loop.close()
    except Exception as e:
        message_queue.put(("error", f"Exception in background thread: {str(e)}"))


def process_messages():
    while not st.session_state.message_queue.empty():
        try:
            msg_type, content = st.session_state.message_queue.get_nowait()
            if msg_type == "workflow_id":
                st.session_state.workflow_id = content
            elif msg_type == "user_input_required":
                if (
                    st.session_state.user_input_required
                    and not st.session_state.user_response_submitted
                ):
                    # User is currently interacting; enqueue the new prompt
                    st.session_state.pending_user_inputs.append(content)
                    logging.warning("A new user input request has been queued.")
                else:
                    # No active user interaction; process the prompt immediately
                    st.session_state.user_input_required = True
                    st.session_state.user_input_prompt = content
                    st.session_state.user_response_submitted = False

                    # Reset feedback fields
                    st.session_state.user_feedback = ""
                    st.session_state.approval_state = None

                    # Increment the prompt counter
                    st.session_state.prompt_counter += 1

                    # Fragment re-renders only itself; force full app rerun so
                    # gather_outline_feedback() (outside the fragment) can see
                    # the updated user_input_required state and render buttons.
                    st.rerun()
            elif msg_type == "message":
                st.session_state.received_lines.append(content)
                truncated_line = (
                    "🤖⚒️Agent is working...\n" + content[:75] + "..."
                    if len(content) > 75
                    else content
                )
                st.session_state.expander_label = truncated_line
            elif msg_type == "reasoning":
                st.session_state.current_reasoning += content
            elif msg_type == "final_result":
                st.session_state.final_result = content
                st.session_state.download_url_pptx = content.get("download_pptx_url")
                st.session_state.download_url_pdf = content.get("download_pdf_url")
                st.session_state.workflow_complete = (
                    True  # Set the flag to stop auto-refresh
                )
                # Fragment re-renders only itself; force full app rerun so
                # right_column (outside the fragment) can render the download buttons.
                st.rerun()

            elif msg_type == "error":
                st.error(content)
        except queue.Empty:
            pass


_run_every = None if st.session_state.workflow_complete else "5s"


@st.fragment(run_every=_run_every)
def workflow_display():
    process_messages()

    thread = st.session_state.get("workflow_thread")
    is_running = thread is not None and thread.is_alive()
    is_complete = st.session_state.workflow_complete

    # Nothing to show if no workflow has been started yet
    if not is_running and not is_complete and not st.session_state.received_lines:
        return

    state = "complete" if is_complete else "running"
    label = "✅ Agent finished!" if is_complete else "🤖⚒️ Agent is working..."

    with st.status(label, state=state, expanded=not is_complete) as status:
        if not st.session_state.received_lines and not st.session_state.current_reasoning:
            st.write("⏳ Waiting for agent to start...")
        else:
            for line in st.session_state.received_lines:
                st.write(line)
                st.divider()
            if st.session_state.current_reasoning:
                st.caption("💭 Agent thinking:")
                st.code(st.session_state.current_reasoning, language=None)
        if is_complete:
            status.update(label="✅ Agent finished!", state="complete", expanded=False)


@st.fragment
def gather_outline_feedback():
        logging.debug(
            f"gather_outline_feedback: "
            f"st.session_state.user_input_required: {st.session_state.user_input_required}"
        )
        logging.debug(
            f"gather_outline_feedback: "
            f"st.session_state.user_response_submitted: {st.session_state.user_response_submitted}"
        )

        if st.session_state.user_input_required:
            data = st.session_state.user_input_prompt
            event_type = data.get("event_type")
            if event_type == "request_user_input":
                logging.info(
                    f"User input required. "
                    f"current submit state: {st.session_state.get('user_response_submitted')}"
                )
                summary = data.get("event_content").get("summary")
                outline = data.get("event_content").get("paper_outline")
                prompt_message = data.get("event_content").get(
                    "message", "Please review the outline."
                )

                # display the content for user input
                st.markdown("## Original Summary:")
                st.text_area("Summary", summary, disabled=True, height=400)
                st.divider()
                st.markdown("## Generated Slide Outline:")
                st.json(outline)
                st.write(prompt_message)

                # Define unique keys for widgets
                current_prompt = st.session_state.prompt_counter
                approval_key = f"approval_state_{current_prompt}"
                feedback_key = f"user_feedback_{current_prompt}"

                # Display the approval feedback widget
                approval = st.feedback("thumbs", key=approval_key)
                st.write(f"Current Approval state is: {approval}")
                logging.info(f"Current Approval state is: {approval}")

                # Display the feedback text area
                feedback = st.text_area(
                    "Please provide feedback if you have any:", key=feedback_key
                )

                # Handle the submission of user response
                if st.button(
                    "Submit Feedback", key=f"submit_response_{current_prompt}"
                ):
                    if not st.session_state.user_response_submitted:
                        # Retrieve approval and feedback using unique keys
                        approval_state = st.session_state.get(approval_key)
                        user_feedback = st.session_state.get(feedback_key, "")

                        # Ensure approval_state is valid
                        if approval_state not in [0, 1]:
                            st.error("Please select an approval option.")
                            return

                        user_response = {
                            "approval": (
                                ":material/thumb_down:"
                                if approval_state == 0
                                else ":material/thumb_up:"
                            ),
                            "feedback": user_feedback,
                        }
                        # Send the user's response to the backend
                        st.write(
                            f"Submitting user response: {user_response}"
                        )  # Logging
                        logging.debug(
                            f"Submitting approval: {approval_state}, feedback: {user_feedback}"
                        )  # Logging
                        try:
                            response = httpx.post(
                                "http://backend:80/submit_user_input",
                                json={
                                    "workflow_id": st.session_state.workflow_id,
                                    "user_input": json.dumps(user_response),
                                },
                            )
                            response.raise_for_status()
                            logging.info(
                                f"Backend response for submitting approval: {response.status_code}"
                            )
                        except httpx.HTTPError as e:
                            st.error(f"Failed to submit user input: {str(e)}")
                            return

                        st.session_state.user_input_required = False
                        st.session_state.user_input_prompt = None
                        st.session_state.user_response_submitted = True
                        # Signal the background thread
                        st.session_state.user_input_event.set()

                        st.success(f"```Response submitted for {summary[:40]}...```")

                        # Process the next prompt in the queue, if any
                        if st.session_state.pending_user_inputs:
                            next_prompt = st.session_state.pending_user_inputs.popleft()
                            st.session_state.user_input_required = True
                            st.session_state.user_input_prompt = next_prompt
                            st.session_state.user_response_submitted = False

                            # Reset feedback fields
                            st.session_state.user_feedback = ""
                            st.session_state.approval_state = None

                            # Increment the prompt counter for the new prompt
                            st.session_state.prompt_counter += 1

                            st.success("A new user input request has been loaded.")
                    else:
                        st.write("Response already submitted.")
            else:
                st.write("No user input required at this time.")


def main():
    st.title("Slide Generation")

    # Sidebar with form
    with st.sidebar:
        with st.form(key="slide_gen_form"):
            query = st.text_input(
                "Enter the topic of your research:",
                value="",
                placeholder="",
            )
            submit_button = st.form_submit_button(label="Submit")

    # Main view divided into two columns
    left_column, right_column = st.columns(2)

    with left_column:
        st.write("Workflow Executions:")

    with right_column:
        st.write("Workflow Artifacts:")

    if submit_button:
        # Reset the workflow_complete flag for a new workflow
        st.session_state.workflow_complete = False
        # Start the long-running task in a separate thread
        if (
            st.session_state.workflow_thread is None
            or not st.session_state.workflow_thread.is_alive()
        ):
            st.write("Starting the background thread...")

            st.session_state.workflow_thread = threading.Thread(
                target=start_long_running_task,
                args=(
                    "http://backend:80/run-slide-gen",
                    {"query": query},
                    st.session_state.message_queue,
                    st.session_state.user_input_event,
                ),
            )
            st.session_state.workflow_thread.start()
            st.session_state.received_lines = []
            st.session_state.current_reasoning = ""
        else:
            st.write("Background thread is already running.")

    with left_column:
        workflow_display()

    with right_column:
        gather_outline_feedback()

    # Render PDF preview and download button full-width below both columns
    if "download_url_pdf" in st.session_state and st.session_state.download_url_pdf:
        st.divider()
        st.markdown("### Generated Slide Deck:")
        try:
            pdf_response = httpx.get(st.session_state.download_url_pdf)
            pdf_response.raise_for_status()
            st.session_state.pdf_data = pdf_response.content
            st.pdf(st.session_state.pdf_data, height=800)
        except Exception as e:
            st.error(f"Failed to load the PDF file: {str(e)}")

    if (
        "download_url_pptx" in st.session_state
        and st.session_state.download_url_pptx
    ):
        try:
            pptx_response = httpx.get(st.session_state.download_url_pptx)
            pptx_response.raise_for_status()
            st.download_button(
                label="Download Generated PPTX",
                data=pptx_response.content,
                file_name="generated_slides.pptx",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        except Exception as e:
            st.error(f"Failed to load the PPTX file: {str(e)}")


main()
