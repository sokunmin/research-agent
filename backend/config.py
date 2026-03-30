from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Secrets ───────────────────────────────────────────────────────────────
    TAVILY_API_KEY: str
    GEMINI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""

    # ── Infrastructure — no defaults, injected by docker-compose environment ─
    MLFLOW_TRACKING_URI: str       # e.g. http://mlflow:8080
    WORKFLOW_ARTIFACTS_ROOT: str   # container path matching the volume mount
    SLIDE_TEMPLATE_PATH: str       # container path to the PPTX template asset

    # ── LiteLLM model IDs ─────────────────────────────────────────────────────
    LLM_SMART_MODEL: str = "gemini/gemini-2.5-flash"
    LLM_FAST_MODEL: str = "gemini/gemini-2.5-flash"
    LLM_VISION_MODEL: str = "gemini/gemini-2.5-flash"
    LLM_VISION_FALLBACK_MODEL: str = "openrouter/google/gemma-3-27b-it:free"
    LLM_EMBED_MODEL: str = "gemini/gemini-embedding-001"

    MAX_TOKENS: int = 4096

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
