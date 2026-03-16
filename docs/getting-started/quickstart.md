# Quick Start

Research Agent 是一個自動化研究與簡報生成系統。你輸入一個研究主題，它會：

1. 透過 **Tavily** 搜尋相關 arXiv 論文關鍵字
2. 從 **OpenAlex** 取得論文與引用（免費，無需 API key）
3. 用 **LiteLLM**（預設 Gemini AI Studio 免費層）過濾相關論文、下載 PDF、生成摘要
4. 讓你審核每張投影片大綱（Human-in-the-Loop）
5. 用 **ReAct Agent + Docker sandbox** 生成 PPTX，並自動驗證與修正
6. 輸出可下載的 `.pptx` / `.pdf`

```
User query → Paper search (OpenAlex) → Filter & Download → Summarize (VLM)
         → Outline (HITL review) → Slide generation (Docker sandbox) → Validate → PPTX/PDF
```

## Prerequisites

| 工具 | 版本需求 |
|------|---------|
| Python | >= 3.12 |
| Poetry | any |
| Docker Desktop | any（slide generation 需要） |
| Docker Compose | V2+（full stack 部署） |

需要的外部服務帳號：

| 服務 | 用途 | 費用 |
|------|------|------|
| Tavily API | 論文關鍵字搜尋 | 免費層可用 |
| Google AI Studio | Gemini LLM + Embedding（預設） | **免費層**（10 RPM, 250 RPD） |
| OpenAlex | 論文搜尋與引用 | 完全免費 |

> 可透過 `LLM_*_MODEL` env var 切換任意 [LiteLLM 支援的 provider](https://docs.litellm.ai/docs/providers)（OpenAI、Anthropic、OpenRouter 等）。

## Step 1 — Clone & 安裝依賴

```bash
git clone <repository-url>
cd research-agent/dev

# 安裝 Python 依賴（可選，Docker 環境不需要）
cd backend
poetry install
```

## Step 2 — 設定環境變數

複製範本並填入你的 API keys：

```bash
cp .env.example .env
```

編輯 `.env`，填入以下欄位（詳細說明見 [`docs/infrastructure/configuration.md`](../infrastructure/configuration.md)）：

```env
# 必填
TAVILY_API_KEY=your_tavily_key

# Gemini（預設 LLM provider，免費）
GEMINI_API_KEY=your_gemini_key   # aistudio.google.com 取得

# 建議填寫（進入 OpenAlex polite pool，提高 rate limit）
OPENALEX_EMAIL=your@email.com
```

其餘設定均有預設值，使用 Gemini 免費層無需額外設定。

## Step 3 — 啟動服務

```bash
cd research-agent/dev
docker-compose up --build
```

啟動後共有 3 個服務：

| 服務 | URL |
|------|-----|
| Frontend (Streamlit) | http://localhost:8501 |
| Backend (FastAPI) | http://localhost:8000/docs |
| MLflow | http://localhost:8080 |

> **Note:** Slide generation 需要 Docker Desktop 在背景執行（用於 Python sandbox）。

## Step 4 — 開始使用

1. 開啟 http://localhost:8501
2. 點擊左側導覽列 **🧾 Slide Generation**
3. 在 sidebar 輸入研究主題，例如：`powerpoint slides automation with machine learning`
4. 點擊 **Submit**
5. 等待 Agent 搜尋與摘要論文（需要數分鐘）
6. 出現 outline 審核視窗時，查看摘要與大綱，按 👍 核准或填入修改意見後 Submit
7. Agent 完成後，右側產生投影片預覽，可下載 PPTX

## 切換 LLM Provider

修改 `.env` 中的模型 ID 即可切換 provider，無需改程式碼：

```env
# 切換到 OpenRouter 免費模型
LLM_SMART_MODEL=openrouter/meta-llama/llama-3.3-70b-instruct:free
LLM_FAST_MODEL=openrouter/meta-llama/llama-3.3-70b-instruct:free
OPENROUTER_API_KEY=your_key

# 切換到 OpenAI
LLM_SMART_MODEL=openai/gpt-4o
LLM_FAST_MODEL=openai/gpt-4o-mini
OPENAI_API_KEY=your_key
```

## 接下來

- 了解系統架構 → [`docs/agent_workflows/overview.md`](../agent_workflows/overview.md)
- 了解 API → [`docs/backend/api-reference.md`](../backend/api-reference.md)
- 調整設定 → [`docs/infrastructure/configuration.md`](../infrastructure/configuration.md)
