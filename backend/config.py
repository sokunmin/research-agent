from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Secrets ───────────────────────────────────────────────────────────────
    TAVILY_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""

    # ── Infrastructure — no defaults, injected by docker-compose environment ─
    MLFLOW_TRACKING_URI: str       # e.g. http://mlflow:8080
    WORKFLOW_ARTIFACTS_ROOT: str   # container path matching the volume mount
    SLIDE_TEMPLATE_PATH: str       # container path to the PPTX template asset

    # ── LiteLLM model IDs ─────────────────────────────────────────────────────
    LLM_SMART_MODEL: str = "groq/openai/gpt-oss-120b"
    LLM_FAST_MODEL: str = "groq/openai/gpt-oss-20b"
    LLM_VISION_MODEL: str = "gemini/gemini-2.5-flash"
    LLM_DISABLE_THINK: bool = False  # set true for Ollama models with think mode (e.g. qwen3)
    LLM_VISION_FALLBACK_MODEL: str = "openrouter/google/gemma-3-27b-it:free"
    LLM_EMBED_MODEL: str = "gemini/gemini-embedding-001"

    MAX_TOKENS: int = 4096

    # ── LLM concurrency & rate-limit tuning ───────────────────────────────────
    # smart_llm: outlines_with_layout, slide_gen (ReAct), modify_slides
    NUM_WORKERS_SMART: int = 1
    DELAY_SECONDS_SMART: float = 0.0
    # fast_llm: filter_papers, summary2outline
    NUM_WORKERS_FAST: int = 2
    DELAY_SECONDS_FAST: float = 2.0   # Groq RPM=60, 2 workers → 60/60×2=2s
    # vision_llm: paper2summary, validate_slides
    NUM_WORKERS_VISION: int = 2
    DELAY_SECONDS_VISION: float = 12.0  # Gemini RPM=10, 2 workers → 60/10×2=12s

    # ── Paper discovery tuning ────────────────────────────────────────────────
    NUM_MAX_FINAL_PAPERS: int = 5        # top-N papers to download after filtering
    ENABLE_QUERY_REFORMULATION: bool = False  # set true to reformulate user query via LLM before OpenAlex search
    # Maximum consecutive run_code failures before the sandbox appends "LIMIT REACHED" to the
    # observation, triggering the Critical Stop Rule in REACT_PROMPT_SUFFIX.
    SLIDE_GEN_MAX_RETRY_ATTEMPTS: int = 3
    PAPER_CANDIDATE_LIMIT: int = 100         # max candidates fetched from OpenAlex
    PAPER_CANDIDATE_MIN_CITATIONS: int = 50  # minimum citation count filter
    PAPER_CANDIDATE_YEAR_WINDOW: int = 3     # publication recency window (years)

    # ── Relevance filter ──────────────────────────────────────────────────────
    LLM_RELEVANCE_EMBED_MODEL: str = "ollama/nomic-embed-text"
    # Embedding model used for Stage 1 relevance pre-screening.
    # Must be the same model family used during threshold calibration.
    # Run via local Ollama; isolated from the general-purpose embed model.

    # ── Optional provider config ───────────────────────────────────────────────
    OPENALEX_API_KEY: str = ""
    OPENALEX_EMAIL: str = ""

    # ── summary_gen_w_qe.py (vector/doc store, alternate workflow path) ───────
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: str = "6333"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    class Config:
        env_file = ".env"


settings = Settings()
