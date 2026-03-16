# Configuration

所有設定透過根目錄的 `.env` 檔案注入，由 `backend/config.py` 的 `Settings` class（基於 `pydantic-settings`）讀取。

## 完整設定項

### API Keys

| 變數名稱 | 必填 | 預設值 | 說明 |
|---------|------|--------|------|
| `TAVILY_API_KEY` | ✅ | — | Tavily 搜尋 API key，用於查找相關 arXiv 論文 |
| `GEMINI_API_KEY` | 建議 | `""` | Google AI Studio API key（免費層可用），供 LiteLLM 呼叫 Gemini 模型 |
| `OPENROUTER_API_KEY` | 條件必填 | `""` | OpenRouter API key；`LLM_VISION_FALLBACK_MODEL` 使用 `openrouter/` 時必填 |
| `MISTRAL_API_KEY` | 可選 | `""` | Mistral API key |
| `OPENALEX_EMAIL` | 建議 | `""` | 填寫後進入 OpenAlex polite pool（rate limit 較高） |
| `OPENALEX_API_KEY` | 可選 | `""` | OpenAlex API key（空值也可使用，但 rate limit 較低） |

### LiteLLM 模型設定

透過環境變數切換任意 LiteLLM 支援的 provider，不需改程式碼。

| 變數名稱 | 預設值 | 說明 |
|---------|--------|------|
| `LLM_SMART_MODEL` | `gemini/gemini-2.5-flash` | 主力 LLM（複雜推理、layout 選擇、slide 生成） |
| `LLM_FAST_MODEL` | `gemini/gemini-2.5-flash` | 快速 LLM（論文過濾、outline 生成等低成本步驟） |
| `LLM_VISION_MODEL` | `gemini/gemini-2.5-flash` | 視覺模型（PDF 圖片摘要、投影片驗證） |
| `LLM_VISION_FALLBACK_MODEL` | `openrouter/google/gemma-3-27b-it:free` | VLM 備援模型，於 429 重試 3 次後自動切換；留空則停用 |
| `LLM_EMBED_MODEL` | `gemini/gemini-embedding-001` | 嵌入模型 |
| `MAX_TOKENS` | `4096` | LLM 最大輸出 token 數 |

**LiteLLM 模型 ID 格式範例：**

```env
# Google AI Studio（免費層：10 RPM / 250 RPD）
LLM_SMART_MODEL=gemini/gemini-2.5-flash
LLM_EMBED_MODEL=gemini/gemini-embedding-001

# OpenRouter 免費模型（50 req/day）
LLM_SMART_MODEL=openrouter/meta-llama/llama-3.3-70b-instruct:free

# OpenAI
LLM_SMART_MODEL=openai/gpt-4o

# Anthropic
LLM_SMART_MODEL=anthropic/claude-3-5-sonnet-20241022
```

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

> 論文 PDF 子路徑（`papers/`、`papers_images/`、`paper_summaries/`）及投影片檔名（`slide_outlines.json`、`paper_summaries.pptx`）均 hardcode 在各自的 workflow class 中，不透過環境變數設定。

## .env 範本

```env
# ── 必填 ──────────────────────────────────────────────────────────────────────
TAVILY_API_KEY=your_tavily_key

# ── LLM Provider（填寫你使用的 provider key）─────────────────────────────────
GEMINI_API_KEY=your_gemini_key        # aistudio.google.com 免費層
OPENROUTER_API_KEY=                   # openrouter.ai（可選）
MISTRAL_API_KEY=                      # console.mistral.ai（可選）

# ── OpenAlex（建議填寫，進入 polite pool）─────────────────────────────────────
OPENALEX_EMAIL=your@email.com
OPENALEX_API_KEY=                     # 可選

# ── LiteLLM 模型 ID（預設已指向 Gemini 免費層，可按需修改）────────────────────
LLM_SMART_MODEL=gemini/gemini-2.5-flash
LLM_FAST_MODEL=gemini/gemini-2.5-flash
LLM_VISION_MODEL=gemini/gemini-2.5-flash
LLM_VISION_FALLBACK_MODEL=openrouter/google/gemma-3-27b-it:free   # VLM 備援，429 重試 3 次後切換；留空停用
LLM_EMBED_MODEL=gemini/gemini-embedding-001
MAX_TOKENS=4096
```

## 載入方式

```python
# backend/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    TAVILY_API_KEY: str   # 唯一必填欄位（無預設值）
    GEMINI_API_KEY: str = ""
    # ...
    class Config:
        env_file = ".env"  # 相對於 backend 執行路徑

settings = Settings()
```

所有模組透過 `from config import settings` 引用統一設定實例。
