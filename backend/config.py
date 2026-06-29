from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Secrets ───────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""

    # ── Infrastructure — no defaults, injected by docker-compose environment ─
    MLFLOW_TRACKING_URI: str       # e.g. http://mlflow:8080
    WORKFLOW_ARTIFACTS_ROOT: str   # container path matching the volume mount
    SLIDE_TEMPLATE_PATH: str       # container path to the PPTX template asset

    # ── LiteLLM model IDs ─────────────────────────────────────────────────────
    MODEL_PROFILES_PATH: str = "data/model_profiles.json"

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
    # Maximum consecutive run_code failures before the sandbox appends "LIMIT REACHED" to the
    # observation, triggering the Critical Stop Rule in REACT_PROMPT_SUFFIX.
    SLIDE_GEN_MAX_RETRY_ATTEMPTS: int = 3
    PAPER_CANDIDATE_LIMIT: int = 100         # max candidates fetched from OpenAlex
    PAPER_CANDIDATE_MIN_CITATIONS: int = 50  # minimum citation count filter
    PAPER_CANDIDATE_YEAR_WINDOW: int = 3     # publication recency window (years)

    # ── Docling PDF parsing ───────────────────────────────────────────────────
    DOCLING_MIN_SUCCESS_RATE: float = 0.70
    # Papers where Docling parses fewer than 70% of pages are dropped.

    # ── Qdrant ───────────────────────────────────────────────────────────────
    QDRANT_URL: str   # required — set in .env, e.g. http://localhost:6333
    QDRANT_COLLECTION_NAME: str = "papers"

    # ── RAG ──────────────────────────────────────────────────────────────────
    RAG_CHUNK_SIZE: int = 512
    # Token budget per chunk. Matches nomic-embed-text context window.
    RAG_SIMILARITY_TOP_K: int = 10
    # Chunks retrieved per query. 9 queries × 10 = up to 90 unique chunks.

    # ── Chunk filter ─────────────────────────────────────────────────────────
    CHUNK_FILTER_CONFIG_PATH: str = "data/filter_config.json"

    # ── Optional provider config ───────────────────────────────────────────────
    OPENALEX_API_KEY: str = ""
    OPENALEX_EMAIL: str = ""


    class Config:
        env_file = ".env"


settings = Settings()
