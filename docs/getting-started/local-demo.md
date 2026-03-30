# Local Demo Guide

本指南帶你從零到完整跑完一次 Research Agent demo：輸入研究主題 → 自動搜尋論文 → 審核大綱 → 生成 PPTX。

預計花費時間：**10–20 分鐘**（視 LLM API rate limit 而定）

---

## 前置需求

| 工具 | 說明 |
|------|------|
| Docker Desktop | 必須在背景執行，整個 demo 期間不可關閉 |
| Git | clone 專案用 |
| API Keys | 見下方 Step 1 |

需要準備的 API key：

| 服務 | 取得方式 | 費用 |
|------|---------|------|
| **Tavily** | https://tavily.com → Sign up | 免費層可用 |
| **Google AI Studio (Gemini)** | https://aistudio.google.com → Get API key | **完全免費**（10 RPM / 250 RPD） |

> OpenAlex（論文資料庫）完全免費，無需 API key。

---

## Step 1 — 取得程式碼

```bash
git clone <repository-url>
cd research-agent/dev
```

---

## Step 2 — 設定環境變數

```bash
cp .env.example .env
```

用編輯器開啟 `.env`，填入以下兩個必填欄位：

```env
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GEMINI_API_KEY=AIzaSyxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# 建議填入（提高 OpenAlex API rate limit）
OPENALEX_EMAIL=your@email.com
```

其餘設定保持預設值即可。

> **確認 Docker Desktop 已啟動** — 可在 terminal 執行 `docker info` 驗證。

---

## Step 3 — 建立資料目錄並啟動服務

```bash
# 在 dev/ 目錄下執行
mkdir -p workflow_artifacts mlruns mlartifacts data

docker-compose up --build
```

第一次 build 需要幾分鐘。完成後終端會持續輸出 log，看到類似以下訊息表示服務已就緒：

```
backend-1   | INFO:     Uvicorn running on http://0.0.0.0:80
frontend-1  | You can now view your Streamlit app in your browser.
mlflow-1    | [INFO] Starting gunicorn 23.0.0
```

啟動的服務：

| 服務 | URL | 說明 |
|------|-----|------|
| **Frontend（主操作介面）** | http://localhost:8501 | Streamlit UI |
| **Backend API** | http://localhost:8000/docs | FastAPI 互動文件 |
| **MLflow** | http://localhost:8080 | 實驗追蹤 |

---

## Step 4 — 開始 Demo

### 4-1 開啟前端

瀏覽器開啟 **http://localhost:8501**，點擊左側導覽列 **🧾 Slide Generation**。

### 4-2 輸入研究主題

在左側 sidebar 的輸入框填入研究主題，例如：

```
attention mechanism in transformer models
```

其他可用的 demo 主題：
- `LoRA fine-tuning for large language models`
- `vision transformer image classification`
- `retrieval augmented generation`

點擊 **Submit** 開始執行。

### 4-3 觀察 Agent 執行過程

右側主區域會開始顯示進度訊息（每 2 秒更新一次）：

```
[tavily_query] Querying Tavily with: 'arxiv papers about the state of the art of attention...'
[get_paper_with_citations] Found related paper: Attention Is All You Need
[get_paper_with_citations] Found related paper: ...
[filter_papers] Filtering papers for relevance...
[download_papers] Downloading filtered relevant papers: Attention Is All You Need | ...
[paper2summary] Summarizing paper: Attention Is All You Need.pdf
...
```

**整個 Summary 階段約需 5–10 分鐘**，取決於論文數量與 API 速度。

### 4-4 審核投影片大綱（Human-in-the-Loop）

Summary 完成後，右側會出現 **大綱審核介面**：

```
┌─────────────────────────────────────────┐
│ 📄 Paper Summary                        │
│ [論文摘要內容...]                        │
│                                         │
│ 📋 Proposed Outline                     │
│ { "title": "...", "content": [...] }    │
│                                         │
│ 👍  👎                                  │
│ Feedback: [text input]                  │
│ [Submit Feedback]                       │
└─────────────────────────────────────────┘
```

有兩種選擇：

- **按 👍 → Submit**：核准大綱，Agent 繼續生成投影片
- **按 👎 → 填寫 feedback → Submit**：Agent 會根據你的意見重新生成大綱

> 每篇論文各會出現一次審核，有幾篇論文就需審核幾次（最多 5 篇）。

### 4-5 等待投影片生成

大綱全部核准後，Agent 會進入 Slide Generation 階段：

```
[outlines_with_layout] Adding layout info to outlines...
[slide_gen] Agent is generating slide deck...
[react_agent] Reasoning: I'll read the slide_outlines.json file first...
[react_agent] Tool: run_code(...)
[validate_slides] 1th try for validating the generated slide deck...
[validate_slides] The slides are fixed!
```

**此階段約需 3–8 分鐘**。

### 4-6 下載結果

完成後右側會出現：
- **PDF 預覽**（inline iframe）
- **Download Generated PPTX** 按鈕

點擊下載 PPTX，即可用 PowerPoint / Keynote / LibreOffice 開啟。

---

## Step 5 — 查看 MLflow 追蹤記錄（選用）

開啟 **http://localhost:8080**，可以看到每次 workflow run 的：

- 執行時間與狀態
- LLM 呼叫次數與 token 使用量
- 完整 trace（每個 step 的輸入/輸出）

Experiment 名稱對應 workflow class：
- `SummaryGenerationWorkflow`
- `SlideGenerationWorkflow`

---

## 停止服務

```bash
# 在另一個 terminal（或 Ctrl+C 後）
docker-compose down
```

---

## 常見問題

### Docker Desktop 未啟動

```
Error response from daemon: Cannot connect to the Docker daemon
```

**解法**：啟動 Docker Desktop，等待鯨魚圖示變成綠色後重試。

### Gemini API 達到 rate limit

```
429 Too Many Requests
```

**解法**：免費層限制 10 RPM / 250 RPD。若遇到此錯誤：
1. 等待 1 分鐘後前端會自動繼續（workflow 有 retry 機制）
2. 或在 `.env` 改用 OpenRouter 免費模型：
   ```env
   LLM_SMART_MODEL=openrouter/meta-llama/llama-3.3-70b-instruct:free
   LLM_FAST_MODEL=openrouter/meta-llama/llama-3.3-70b-instruct:free
   LLM_VISION_MODEL=openrouter/google/gemini-2.0-flash-exp:free
   OPENROUTER_API_KEY=your_key
   ```

### 找不到 ArXiv PDF

```
No ArXiv ID for '...', skipping.
```

**說明**：部分論文沒有 ArXiv 版本，系統會自動跳過，不影響整體流程。只要有至少 1 篇成功下載即可繼續。

### 前端沒有更新進度

**解法**：
1. 確認 backend container 正常運行：`docker-compose logs -f backend`
2. 重新整理頁面（Streamlit 的 auto-refresh 每 2 秒觸發一次）

### PPTX 下載失敗（404）

**說明**：Workflow 可能仍在執行中，等待「The slides are fixed!」訊息出現後再下載。

---

## 產出物位置

完成後，以下目錄會在 `dev/` 下產生（已透過 volume 掛載到 container）：

```
dev/
├── workflow_artifacts/
│   └── SlideGenerationWorkflow/
│       └── {workflow_id}/
│           ├── slide_outlines.json   # 投影片大綱（含 layout）
│           ├── paper_summaries.pptx  # 初版投影片
│           ├── final.pptx            # 最終版本 ← 下載的就是這個
│           └── final.pdf
└── data/
    └── (空，SummaryGen 的 papers 在 workflow_artifacts 內)
```

---

## 進階：跳過 SummaryGen，直接測試 SlideGen

若已有 `.md` 摘要檔案，可跳過論文搜尋階段，直接測試投影片生成：

```python
# backend/agent_workflows/summarize_and_generate_slides.py
# 取消以下註解，並把上方的 SummaryGenerationWorkflow 加入改為 SummaryGenerationDummyWorkflow

wf.add_workflows(
    summary_gen_wf=SummaryGenerationDummyWorkflow(
        wid=workflow_id, timeout=800, verbose=True
    )
)
```

`SummaryGenerationDummyWorkflow` 會回傳一個固定的 summary 目錄路徑（`workflow_artifacts/SummaryGenerationWorkflow/5sn92wndsx/data/paper_summaries`），讓你直接進入 SlideGen 流程。

---

## 相關文件

- [系統架構](../agent_workflows/overview.md)
- [完整設定說明](../infrastructure/configuration.md)
- [Workflow 事件系統](../agent_workflows/events.md)
- [Human-in-the-Loop 機制](../agent_workflows/human-in-the-loop.md)
