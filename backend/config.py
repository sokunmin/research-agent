from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    TAVILY_API_KEY: str
    OPENALEX_API_KEY: str = ""   # 免費，空值也能用但 rate limit 較低
    OPENALEX_EMAIL: str = ""     # 建議填寫，進入 polite pool（較高 rate limit）

    # ── LiteLLM model IDs ─────────────────────────────────────────────────────
    LLM_SMART_MODEL: str = "gemini/gemini-2.5-flash"
    LLM_FAST_MODEL: str = "gemini/gemini-2.5-flash"
    LLM_VISION_MODEL: str = "gemini/gemini-2.5-flash"
    LLM_EMBED_MODEL: str = "gemini/gemini-embedding-001"

    # ── Provider API keys ─────────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
    MISTRAL_API_KEY: str = ""

    MAX_TOKENS: int = 4096

    # vector store
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: str = "6333"

    # doc store
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # path and file name configuration
    WORKFLOW_ARTIFACTS_PATH: str = "./workflow_artifacts"

    PAPERS_DOWNLOAD_PATH: str = "data/papers"
    PAPERS_IMAGES_PATH: str = "data/papers_images"
    PAPER_SUMMARY_PATH: str = "data/paper_summaries"

    SLIDE_TEMPLATE_PATH: str = "./data/Inmeta 2023 template.pptx"
    SLIDE_OUTLINE_FNAME: str = "slide_outlines.json"
    GENERATED_SLIDE_FNAME: str = "paper_summaries.pptx"

    MLFLOW_TRACKING_URI: str = "http://mlflow:8080"

    class Config:
        env_file = ".env"  # relative to execution path


settings = Settings()
