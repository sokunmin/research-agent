from typing import Literal

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
    LLM_SMART_MODEL: str = "groq/openai/gpt-oss-120b"
    LLM_FAST_MODEL: str = "groq/openai/gpt-oss-20b"
    LLM_VISION_MODEL: str = "gemini/gemini-2.5-flash"
    DISABLE_OLLAMA_THINK: bool = False  # set true for Ollama models with think mode (e.g. qwen3)
    LLM_VISION_FALLBACK_MODEL: str = "openrouter/google/gemma-3-27b-it:free"

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

    # ── Relevance filter ──────────────────────────────────────────────────────
    EMBED_MODEL: str = "ollama/nomic-embed-text"
    # Shared embedding model for relevance filtering, RAG summarization, and Qdrant indexing.
    # Must use the same model family as threshold calibration to keep cosine similarity scores valid.

    # ── Docling PDF parsing ───────────────────────────────────────────────────
    DOCLING_MIN_SUCCESS_RATE: float = 0.70
    # Papers where Docling parses fewer than 70% of pages are dropped.

    # ── Qdrant local vector store ─────────────────────────────────────────────
    QDRANT_PATH: str = "./qdrant_storage"
    # Local Qdrant Gridstore directory. No separate Qdrant server needed.
    QDRANT_COLLECTION_NAME: str = "papers"

    # ── In-memory RAG (summarization) ────────────────────────────────────────
    RAG_CHUNK_SIZE: int = 512
    # Token budget per chunk. Matches nomic-embed-text context window.
    RAG_SIMILARITY_TOP_K: int = 5
    # Chunks retrieved per query. 8 queries × 5 = up to 40 unique chunks.

    # ── Shared cache ──────────────────────────────────────────────────────────
    SHARED_CACHE_ROOT: str = "./shared_cache"
    # Persists parsed docs and summaries across workflow runs, keyed by document_id.

    # ── Chunk filter ─────────────────────────────────────────────────────────
    CHUNK_FILTER_CONFIG_PATH: str = "backend/data/filter_config.json"

    # ── Summarization strategy ────────────────────────────────────────────────
    SUMMARY_STRATEGY: Literal["rag", "vlm"] = "rag"
    # "rag" uses Docling HybridChunker pipeline (default).
    # "vlm" retains the legacy VLM image-based path for baseline comparison.

    # ── Optional provider config ───────────────────────────────────────────────
    OPENALEX_API_KEY: str = ""
    OPENALEX_EMAIL: str = ""


    class Config:
        env_file = ".env"


settings = Settings()
