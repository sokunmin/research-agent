# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
This is a forked project from lz-chen's side project. I modified it for finding a GenAI & RAG jobs.
lz-chen's original project path: /Users/chunming/MyWorkSpace/agent_workspace/lzchen-research-agent

Note that the lz-chen use semantic scholar API while I use openalex instead because I don't have access to semantic scholar API. 
I use OpenAlex to simulate semantic scholar query and replace it after some experiment.

## Commands

```bash
# Install all dependencies
make install

# Run unit tests (no external deps)
make test
# Equivalent: cd backend && poetry run pytest tests/unit -v

# Run integration tests (requires API keys + network)
make test-integration
# Equivalent: cd backend && poetry run pytest tests/integration -v -m integration

# Run a specific test marker
cd backend && poetry run pytest tests/ -m llm       # requires API keys
cd backend && poetry run pytest tests/ -m slow      # >60s tests
cd backend && poetry run pytest tests/ -m docker    # requires Docker

# Start all services (Docker)
make up    # docker compose up --build -d
make down  # docker compose down
make logs  # docker compose logs -f
```

## Architecture

This is a **research-to-presentation pipeline** that:
1. Discovers academic papers via OpenAlex API
2. Summarizes papers using VLMs
3. Auto-generates PowerPoint presentations with Human-in-the-Loop (HITL) feedback
4. Streams progress via SSE to a Streamlit frontend

**Tech stack**: FastAPI + LlamaIndex Workflows + LiteLLM + python-pptx + Streamlit + MLflow + Docker

### Workflow Architecture

The core is two composable LlamaIndex Workflows chained in `SummaryAndSlideGenerationWorkflow`:

```
SummaryGenerationWorkflow:
  discover_candidate_papers → filter_papers → download_papers → paper2summary
  (OpenAlex BM25)            (embed + LLM)   (4-strategy fallback)  (VLM)

SlideGenerationWorkflow:
  summary2outline → outlines_with_layout → outlines_with_layout_hitl
  (LLMTextCompletionProgram)  (Negative Examples prompt)      (HITL via async future)
  → json_to_python_code → validate_slides → fix_slides
    (PptxRenderer)          (VLM → issue_type)   (routes to content/visual fix)
```

All workflow events are defined in `backend/agent_workflows/events.py`.

### Key Design Decisions

- **LiteLLM for all LLM calls** — provider/model is configured via `.env` only, no code changes needed to switch models. `ModelFactory` (singleton) exposes `smart_llm()`, `fast_llm()`, `vision_llm()`, `embed_model()`.
- **Deterministic PPTX renderer** — `PptxRenderer` in `tools/pptx_tools.py` takes validated JSON and renders to PPTX deterministically (no LLM code generation at runtime).
- **`LLMTextCompletionProgram`** — used for structured output (not `FunctionCallingProgram`) because it works reliably across all LiteLLM providers including Ollama.
- **Two-stage relevance filter** — Stage 1: embedding similarity (Ollama `nomic-embed-text`), Stage 2: LLM verification. Gives F1=0.974 at 3.3× the speed of LLM-only.
- **Typed error routing** — VLM validates slides and returns `issue_type` (`content_too_long | content_missing | visual_overlap | ok`) to route to the correct fix handler.

### Project Structure

```
backend/
  agent_workflows/     # LlamaIndex Workflow definitions + events + schemas
  services/            # model_factory.py (LLM abstraction), multimodal.py, sandbox.py
  tools/               # paper_tools.py, pptx_tools.py, sandbox_tools.py
  prompts/prompts.py   # All LLM prompts centralized here
  config.py            # Pydantic Settings (all tunable params)
  models.py            # Pydantic request/response models
  main.py              # FastAPI entry point, SSE streaming
  tests/unit|integration|e2e/

frontend/
  Home.py              # Streamlit entry point
  pages/               # slide_generation_page.py handles SSE consumption + HITL UI
```

### API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /run-slide-gen` | Start workflow, returns SSE stream |
| `POST /submit_user_input` | Send HITL feedback (outline approval/rejection) |
| `GET /download_pptx/{workflow_id}` | Download final PPTX |
| `GET /download_pdf/{workflow_id}` | Download final PDF |

SSE events use `WorkflowStreamingEvent` with `event_type` of `server_message` or `request_user_input`.

### Configuration

All tunable parameters live in `backend/config.py` and are set via `.env`. Key settings:

- `LLM_SMART_MODEL`, `LLM_FAST_MODEL`, `LLM_VISION_MODEL`, `LLM_EMBED_MODEL`, `LLM_RELEVANCE_EMBED_MODEL`
- `NUM_WORKERS_SMART/FAST/VISION`, `DELAY_SECONDS_SMART/FAST/VISION` — concurrency + rate limiting
- `NUM_MAX_FINAL_PAPERS`, `PAPER_CANDIDATE_LIMIT`, `PAPER_CANDIDATE_MIN_CITATIONS`, `PAPER_CANDIDATE_YEAR_WINDOW`
- `SLIDE_GEN_MAX_RETRY_ATTEMPTS`

### MLflow Tracking

All LLM calls are auto-logged (tokens, cost, latency) to MLflow at `http://mlflow:8080`. Artifacts saved under `WORKFLOW_ARTIFACTS_ROOT`:
- `SummaryGenerationWorkflow/{workflow_id}/*.md` — per-paper summaries
- `SlideGenerationWorkflow/{workflow_id}/final.pptx` — final output

### Test Markers

- `@pytest.mark.integration` — requires live APIs/network
- `@pytest.mark.llm` — requires API key
- `@pytest.mark.slow` — >60 seconds
- `@pytest.mark.docker` — requires Docker

### SSE Format

SSE events must follow W3C spec (`data: <payload>\n\n`). Do not add extra prefixes per token delta in streaming responses. See `feedback_sse_format_streamlit_display.md` in memory for history.

### Sandbox

`ArtifactSandboxSession` must be initialized with `enable_plotting=False` to avoid stdout pollution and stray UUID files.

### Git 
* Create git message that matches FAANG git message standard
* Do NOT add co-author on git message
* Do NOT create isolation worktree without user's confirmation

#### Commit Separation Rule (dev → main cherry-pick strategy)
`poc/`, `REPORTING_GUIDE.md`, and `dev-tracker/` are dev-only files that must never reach main.
To support clean cherry-picking, **never mix dev-only changes with public changes in the same commit**.

| Commit type | Allowed paths | Goes to main? |
|---|---|---|
| `feat/fix/refactor/perf` | `backend/`, `frontend/`, `.github/` | ✅ |
| `docs(experiments)` | `experiments/` | ✅ |
| `chore(poc)` | `poc/`, `REPORTING_GUIDE.md`, `dev-tracker/` | ❌ |

**Before every commit: check that staged files do not mix `chore(poc)` paths with public paths.**

Examples:
```
✅ OK — separate commits
  feat(backend): add new paper filter logic
  chore(poc): test new filter in poc/openalex-search-comparison/

❌ VIOLATION — mixed in one commit
  feat(backend) + chore(poc): add filter logic and test it
```

#### Triggering clean-merge-to-main workflow

Always trigger with `--ref dev` to ensure the latest workflow file is used:

```bash
gh workflow run clean-merge-to-main.yml --ref dev \
  --field pr_title="..." \
  --field pr_body="..."
```

**Why `--ref dev`:** GitHub reads the workflow file from the specified ref. Without it, GitHub uses the default branch (main), which may have an older version of the workflow.

#### Known edge cases (low frequency)

- **cherry-pick conflict:** If cherry-pick fails mid-run, the release branch is left in a conflicted state. Run `git cherry-pick --abort` manually on the runner is not possible — close the PR, delete the release branch, fix the conflicting commit on dev, then retrigger.
- **Reuse branch with existing PR:** If the workflow is retriggered and the release branch already exists with an open PR, `gh pr create` will fail. Close the existing PR first, delete the release branch, then retrigger.