# Backend API Reference

Backend 使用 **FastAPI** 建置，提供以下 4 個 endpoints。完整互動式文件請見 http://localhost:8000/docs。

## 資料模型

```python
# ResearchTopic（POST body）
{
  "query": "string"   # 研究主題關鍵字，例如 "powerpoint slides automation"
}
```

---

## `POST /run-slide-gen`

啟動完整的 SummaryAndSlideGenerationWorkflow，以 **Server-Sent Events（SSE）串流** 回傳執行過程。

### Request

```http
POST /run-slide-gen
Content-Type: application/json

{
  "query": "powerpoint slides automation with machine learning"
}
```

### Response

`Content-Type: text/event-stream`，每個 event 是一行 JSON，以 `\n\n` 分隔。

**Event 類型：**

| JSON key | 時機 | 內容 |
|----------|------|------|
| `workflow_id` | 啟動後第一筆 | `"abc-123-..."` UUID，後續 HITL 互動需要 |
| `event_type: "server_message"` | 每個 workflow step | `event_sender`（step 名稱）+ `event_content.message`（進度訊息） |
| `event_type: "request_user_input"` | HITL outline 審核時 | `event_content` 含 `summary`、`outline`、`message`、`eid` |
| `final_result` | 全部完成 | `result`、`download_pptx_url`、`download_pdf_url` |
| `event: "error"` | 發生例外 | `message`（錯誤訊息） |

**SSE 串流示範：**

```
{"workflow_id": "550e8400-e29b-41d4-a716-446655440000"}

{"event_type": "server_message", "event_sender": "tavily_query", "event_content": {"message": "Querying Tavily with: 'arxiv papers about the state of the art of ...'"}}

{"event_type": "request_user_input", "event_sender": "gather_feedback_outline", "event_content": {"eid": "abc123", "summary": "...", "outline": {...}, "message": "Do you approve this outline?"}}

{"final_result": {"result": "...", "download_pptx_url": "http://backend:80/download_pptx/550e...", "download_pdf_url": "http://backend:80/download_pdf/550e..."}}
```

### SSE 串流架構

```
  Frontend                   Backend                    Workflow
     │                          │                          │
     │── POST /run-slide-gen ──►│                          │
     │   {"query": "..."}       │── run(user_query) ──────►│
     │                          │   [背景 task]             │
     │◄── {"workflow_id":"..."} │                          │
     │                          │                          │
     │         (workflow 執行中)│◄── stream_events() ──────│
     │◄── {"event_type":        │                          │
     │     "server_message"} ───│                          │
     │                          │◄── request_user_input ───│
     │◄── {"event_type":        │                          │
     │     "request_user_input"}│                 await future
     │                          │                          │
  顯示 outline，等待 user 操作  │                          │
     │                          │                          │
     │── POST /submit_user_input►│                          │
     │                          │── future.set_result() ──►│
     │                          │                          │
     │         (workflow 繼續)  │◄── stream_events() ──────│
     │◄── {"event_type":        │                          │
     │     "server_message"} ───│                          │
     │◄── {"final_result":{...}}│◄── StopEvent ────────────│
```

---

## `POST /submit_user_input`

在 HITL 等待期間，將 user 的 outline 審核結果送回 workflow。

### Request

```http
POST /submit_user_input
Content-Type: application/json

{
  "workflow_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_input": "{\"approval\": \":material/thumb_up:\", \"feedback\": \"\"}"
}
```

| 欄位 | 說明 |
|------|------|
| `workflow_id` | 從 `/run-slide-gen` 取得的 UUID |
| `user_input` | JSON 字串，含 `approval`（`:material/thumb_up:` 或 `:material/thumb_down:`）及 `feedback` |

### Response

```json
{"status": "input received"}
```

### Errors

| Status | 說明 |
|--------|------|
| `404` | `workflow_id` 不存在或 Future 未初始化 |

---

## `GET /download_pptx/{workflow_id}`

下載生成的 PPTX 檔案。

### Request

```http
GET /download_pptx/550e8400-e29b-41d4-a716-446655440000
```

### Response

`Content-Type: application/vnd.openxmlformats-officedocument.presentationml.presentation`

檔案路徑：`workflow_artifacts/SlideGenerationWorkflow/{workflow_id}/final.pptx`

### Errors

| Status | 說明 |
|--------|------|
| `404` | 檔案尚未產生或 workflow_id 不正確 |

---

## `GET /download_pdf/{workflow_id}`

下載生成的 PDF 檔案。

### Request

```http
GET /download_pdf/550e8400-e29b-41d4-a716-446655440000
```

### Response

`Content-Type: application/pdf`

檔案路徑：`workflow_artifacts/SlideGenerationWorkflow/{workflow_id}/final.pdf`

### Errors

| Status | 說明 |
|--------|------|
| `404` | 檔案尚未產生或 workflow_id 不正確 |

---

## CORS 設定

Backend 只允許來自 `http://frontend:8501` 的請求（Docker 內部網路）。若需本機開發直連，請修改 `main.py` 中的 `allow_origins`。
