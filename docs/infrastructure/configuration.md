# Configuration

所有設定透過根目錄的 `.env` 檔案注入，由 `backend/config.py` 的 `Settings` class（基於 `pydantic-settings`）讀取。

## 完整設定項

### API Keys

| 變數名稱 | 必填 | 預設值 | 說明 |
|---------|------|--------|------|
| `GEMINI_API_KEY` | 建議 | `""` | Google AI Studio API key（免費層可用），供 LiteLLM 呼叫 Gemini 視覺模型 |
| `GROQ_API_KEY` | 建議 | `""` | Groq API key；`LLM_SMART_MODEL` / `LLM_FAST_MODEL` 預設使用 Groq |
| `OPENROUTER_API_KEY` | 條件必填 | `""` | OpenRouter API key；`LLM_VISION_FALLBACK_MODEL` 使用 `openrouter/` 時必填 |
| `OPENALEX_EMAIL` | 建議 | `""` | 填寫後進入 OpenAlex polite pool（rate limit 較高） |
| `OPENALEX_API_KEY` | 可選 | `""` | OpenAlex API key（空值也可使用，但 rate limit 較低） |
| `TAVILY_API_KEY` | 可選 | `""` | Tavily API key（目前主要 workflow 不使用） |
| `MISTRAL_API_KEY` | 可選 | `""` | Mistral API key |

### LiteLLM 模型設定

透過環境變數切換任意 LiteLLM 支援的 provider，不需改程式碼。

| 變數名稱 | 預設值 | 說明 |
|---------|--------|------|
| `LLM_SMART_MODEL` | `groq/openai/gpt-oss-120b` | 主力 LLM（複雜推理、layout 選擇、slide 生成） |
| `LLM_FAST_MODEL` | `groq/openai/gpt-oss-20b` | 快速 LLM（查詢改寫、論文過濾 Stage-2、outline 生成） |
| `LLM_VISION_MODEL` | `gemini/gemini-2.5-flash` | 視覺模型（PDF 圖片摘要、投影片驗證） |
| `LLM_VISION_FALLBACK_MODEL` | `openrouter/google/gemma-3-27b-it:free` | VLM 備援模型，於 429 重試 3 次後自動切換；留空則停用 |
| `LLM_EMBED_MODEL` | `gemini/gemini-embedding-001` | 通用嵌入模型（LlamaIndex Settings.embed_model） |
| `LLM_RELEVANCE_EMBED_MODEL` | `ollama/nomic-embed-text` | 論文相關性 Stage-1 embedding 模型（本地 Ollama）。必須使用與閾值校準時相同的模型族 |
| `MAX_TOKENS` | `4096` | LLM 最大輸出 token 數 |

**LiteLLM 模型 ID 格式範例：**

```env
# Groq（預設，RPM=60）
LLM_SMART_MODEL=groq/openai/gpt-oss-120b
LLM_FAST_MODEL=groq/openai/gpt-oss-20b

# Google AI Studio（免費層：10 RPM / 250 RPD）
LLM_VISION_MODEL=gemini/gemini-2.5-flash
LLM_EMBED_MODEL=gemini/gemini-embedding-001

# OpenRouter 免費模型（50 req/day）
LLM_SMART_MODEL=openrouter/meta-llama/llama-3.3-70b-instruct:free

# OpenAI
LLM_SMART_MODEL=openai/gpt-4o

# Anthropic
LLM_SMART_MODEL=anthropic/claude-3-5-sonnet-20241022
```

### LLM 並行度與 Rate Limit 調整

控制各 LLM 的並行 worker 數量與每次呼叫間隔。數值設計對應 LiteLLM provider 的免費層限制，換 provider 時建議同步調整。

```
安全 delay 公式：delay = 60秒 / RPM × num_workers
```

| 變數名稱 | 預設值 | 說明 |
|---------|--------|------|
| `NUM_WORKERS_SMART` | `1` | smart_llm 並行 workers（outlines_with_layout, slide_gen, modify_slides） |
| `DELAY_SECONDS_SMART` | `0.0` | smart_llm 每次呼叫間隔（秒） |
| `NUM_WORKERS_FAST` | `2` | fast_llm 並行 workers（filter_papers, summary2outline） |
| `DELAY_SECONDS_FAST` | `2.0` | fast_llm 每次呼叫間隔（Groq RPM=60，2 workers → 2s） |
| `NUM_WORKERS_VISION` | `2` | vision_llm 並行 workers（paper2summary, validate_slides） |
| `DELAY_SECONDS_VISION` | `12.0` | vision_llm 每次呼叫間隔（Gemini RPM=10，2 workers → 12s） |

### 論文搜尋調整

| 變數名稱 | 預設值 | 說明 |
|---------|--------|------|
| `NUM_MAX_FINAL_PAPERS` | `5` | 相關性過濾後，最多下載幾篇論文（取 top-N） |
| `PAPER_CANDIDATE_LIMIT` | `100` | OpenAlex 每次搜尋最多取幾篇候選論文 |
| `PAPER_CANDIDATE_MIN_CITATIONS` | `50` | 候選論文最低引用次數門檻 |
| `PAPER_CANDIDATE_YEAR_WINDOW` | `3` | 候選論文的發表年份窗口（近幾年） |

### 儲存服務（選填，有預設值）

| 變數名稱 | 預設值 | 說明 |
|---------|--------|------|
| `QDRANT_HOST` | `localhost` | Qdrant vector store host |
| `QDRANT_PORT` | `6333` | Qdrant port |
| `REDIS_HOST` | `localhost` | Redis doc store host |
| `REDIS_PORT` | `6379` | Redis port |

> **Note:** 目前主要 workflow（SummaryGen + SlideGen）不依賴 Qdrant / Redis，這些是預留給未來擴充用。

### Infra 設定（由 docker-compose 注入，不需在 .env 設定）

以下三個變數在 `config.py` 中**無預設值**，必須由環境注入。使用 docker-compose 時，`docker-compose.yml` 的 `environment:` 區塊已自動注入；本機開發時需手動設定。

| 變數名稱 | docker-compose 注入值 | 說明 |
|---------|----------------------|------|
| `WORKFLOW_ARTIFACTS_ROOT` | `/app/workflow_artifacts` | 所有 workflow 產出（PPTX、PDF）的根目錄 |
| `SLIDE_TEMPLATE_PATH` | `/app/assets/pptx-template.pptx` | PPTX 模板路徑（對應 `./assets` volume mount） |
| `MLFLOW_TRACKING_URI` | `http://mlflow:8080` | MLflow tracking server URI（Docker 網路內） |

> 論文 PDF 子路徑（`papers/`、`papers_images/`）及投影片檔名（`slide_outlines.json`、`paper_summaries.pptx`）均 hardcode 在各自的 workflow class 中，不透過環境變數設定。

## .env 範本

```env
# ── LLM Provider（填寫你使用的 provider key）─────────────────────────────────
GROQ_API_KEY=your_groq_key           # console.groq.com（free tier RPM=60）
GEMINI_API_KEY=your_gemini_key       # aistudio.google.com（vision model）
OPENROUTER_API_KEY=                  # openrouter.ai（VLM fallback，可選）
MISTRAL_API_KEY=                     # console.mistral.ai（可選）

# ── OpenAlex（建議填寫，進入 polite pool）────────────────────────────────────
OPENALEX_EMAIL=your@email.com
OPENALEX_API_KEY=                    # 可選

# ── LiteLLM 模型 ID（預設：Groq for smart/fast，Gemini for vision/embed）────
LLM_SMART_MODEL=groq/openai/gpt-oss-120b
LLM_FAST_MODEL=groq/openai/gpt-oss-20b
LLM_VISION_MODEL=gemini/gemini-2.5-flash
LLM_VISION_FALLBACK_MODEL=openrouter/google/gemma-3-27b-it:free  # 留空停用
LLM_EMBED_MODEL=gemini/gemini-embedding-001
LLM_RELEVANCE_EMBED_MODEL=ollama/nomic-embed-text  # 需本地 Ollama 服務
MAX_TOKENS=4096

# ── 並行度調整（對應 provider RPM；換 provider 時同步調整）─────────────────
NUM_WORKERS_FAST=2
DELAY_SECONDS_FAST=2.0    # Groq RPM=60, 2 workers → 2s
NUM_WORKERS_VISION=2
DELAY_SECONDS_VISION=12.0 # Gemini RPM=10, 2 workers → 12s
```

## 載入方式

```python
# backend/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    # ...
    class Config:
        env_file = ".env"  # 相對於 backend 執行路徑

settings = Settings()
```

所有模組透過 `from config import settings` 引用統一設定實例。
