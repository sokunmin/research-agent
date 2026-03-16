# Deployment

本專案透過 **Docker Compose** 管理所有服務，無需手動設定 Python 環境。

## 服務架構

```
  ┌──────────────────┐
  │   User Browser   │
  └────────┬─────────┘
           │ :8501
           ▼
┌──────────────────────────────────────────────────────────────┐
│                  Docker Network (app-network)                │
│                                                              │
│  ┌──────────────────┐       HTTP / SSE       ┌────────────┐ │
│  │    Frontend      │◄──────── :80 ─────────►│  Backend   │ │
│  │   (Streamlit)    │                        │  (FastAPI) │ │
│  └──────────────────┘                        └─────┬──────┘ │
│                                                    │        │
│                                       MLflow :8080 │        │
│                                    ┌───────────────┘        │
│                                    ▼                        │
│                             ┌──────────────┐               │
│                             │    MLflow    │               │
│                             │    Server    │               │
│                             └──────────────┘               │
└──────────────────────────────────────────────────────────────┘
           │ Backend (continued)
    ┌──────┴──────────────┐
    │ Docker socket       │ 外部 API
    ▼                     ▼
┌──────────────────┐  ┌─────────────────────────────┐
│   llm-sandbox    │  │     LiteLLM Provider        │
│ (container pool) │  │  (Gemini / OpenRouter / 等) │
└──────────────────┘  │  Tavily / OpenAlex          │
                      └─────────────────────────────┘
```

## docker-compose 服務清單

### `backend`

| 項目 | 值 |
|------|-----|
| Build context | `./backend` |
| Host port | `8000` → container `80` |
| Network | `app-network` |
| Restart | `on-failure`（僅補捉啟動失敗，不在 mid-run crash 後重啟） |
| Depends on | `mlflow`（`service_healthy`） |
| Healthcheck | `GET /`，interval 5s，timeout 3s，retries 5，start_period 15s |

**環境變數注入：**

| 方式 | 說明 |
|------|------|
| `env_file: .env` | 從根目錄 `.env` 讀取 secrets（API keys 等） |
| `environment:` | docker-compose 直接注入 infra 設定（`WORKFLOW_ARTIFACTS_ROOT`、`SLIDE_TEMPLATE_PATH`、`MLFLOW_TRACKING_URI`） |

**Volumes：**

| Host 路徑 | Container 路徑 | 用途 |
|-----------|---------------|------|
| `/var/run/docker.sock` | `/var/run/docker.sock` | llm-sandbox Docker socket（slide generation 必要） |
| `./assets` | `/app/assets`（唯讀） | PPTX 模板等靜態資源 |
| `./workflow_artifacts` | `/app/workflow_artifacts` | 生成的 PPTX/PDF |
| `./mlruns` | `/app/mlruns` | MLflow run 紀錄 |
| `./mlartifacts` | `/app/mlartifacts` | MLflow artifacts |

> **Note:** `/var/run/docker.sock` 掛載讓 backend container 可以控制 Docker daemon，供 `LlmSandboxToolSpec`（`services/sandbox.py`）建立和管理 Python sandbox container。Slide generation 依賴此掛載，缺少則會在 runtime 拋出 Docker 連線錯誤。

### `frontend`

| 項目 | 值 |
|------|-----|
| Build context | `./frontend` |
| Host port | `8501` → container `8501` |
| Network | `app-network` |
| Restart | `on-failure` |
| Depends on | `backend`（`service_healthy`） |

### `mlflow`

| 項目 | 值 |
|------|-----|
| Image | `ghcr.io/mlflow/mlflow:v3.10.0` |
| Host port | `8080` |
| Backend store | SQLite (`./mlruns/mlruns.db`) |
| Start command | `mlflow server --host 0.0.0.0 --port 8080` |
| Restart | `unless-stopped`（資料持久化在 volume，重啟安全） |
| Healthcheck | `GET /health`，interval 10s，timeout 5s，retries 5，start_period 20s |

## 服務啟動順序

```
mlflow ──(healthcheck OK)──► backend ──(healthcheck OK)──► frontend
```

`depends_on` + `condition: service_healthy` 確保：
- backend 等 mlflow `/health` 通過後才啟動（避免 `mlflow.start_run()` 連線失敗）
- frontend 等 backend `GET /` 通過後才啟動（避免用戶觸發請求時 FastAPI 尚未 ready）

## 常用指令

```bash
# 初次啟動（build image + 啟動）
docker-compose up --build

# 背景執行
docker-compose up -d --build

# 查看 logs
docker-compose logs -f backend
docker-compose logs -f frontend

# 停止所有服務
docker-compose down

# 重新 build 特定服務
docker-compose build backend
docker-compose up -d --no-deps backend
```

## 資料目錄說明

系統運行後，以下目錄會自動產生：

```
.
└── workflow_artifacts/
    ├── SummaryGenerationWorkflow/
    │   └── <workflow_id>/
    │       └── data/
    │           ├── papers/              # 下載的論文 PDF
    │           ├── papers_images/       # PDF 轉圖片（給 VLM 視覺分析用）
    │           └── paper_summaries/     # Markdown 格式摘要
    └── SlideGenerationWorkflow/
        └── <workflow_id>/
            ├── slide_outlines.json   # 投影片大綱 JSON
            ├── paper_summaries.pptx  # 生成的投影片
            ├── final.pptx            # 最終版本
            └── final.pdf             # PDF 版本
```

## Port 衝突處理

若預設 port 已被佔用，修改 `docker-compose.yml` 中的 `ports` 設定：

```yaml
# 改為其他 port，格式：HOST:CONTAINER
ports:
  - "8001:80"   # backend
  - "8502:8501" # frontend
  - "8081:8080" # mlflow
```

## 本機開發（不使用 Docker Compose）

```bash
cd backend
poetry install
poetry run uvicorn main:app --reload --port 8000
```

> 本機執行時，Docker Desktop 仍需在背景執行，供 `LlmSandboxToolSpec` 使用。
