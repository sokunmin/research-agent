from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    TAVILY_API_KEY: str
    OPENALEX_API_KEY: str = ""   # 免費，空值也能用但 rate limit 較低
    OPENALEX_EMAIL: str = ""     # 建議填寫，進入 polite pool（較高 rate limit）

    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_API_VERSION: str
    AZURE_OPENAI_GPT4O_MODEL: str
    AZURE_OPENAI_GPT4O_MINI_MODEL: str
    AZURE_OPENAI_EMBEDDING_MODEL: str
    MAX_TOKENS: int
    AZURE_DYNAMIC_SESSION_MGMT_ENDPOINT: str

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
