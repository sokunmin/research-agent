# Slide Generation Page

`pages/slide_generation_page.py` 是整個前端的核心頁面，處理 SSE 串流消費、HITL outline 審核、結果下載。

## 頁面佈局

```
┌──────────────────────────────────────────────────────┐
│ Sidebar                                              │
│  ┌────────────────────────────────┐                 │
│  │ Enter the topic of research:   │                 │
│  │ [text input]                   │                 │
│  │ [Submit]                       │                 │
│  └────────────────────────────────┘                 │
├────────────────────────┬─────────────────────────────┤
│ Left Column            │ Right Column                │
│ Workflow Executions    │ Workflow Artifacts          │
│                        │                             │
│ ▼ 🤖⚒️Agent is working │ [outline 審核 UI]           │
│   step message 1       │   或                        │
│   step message 2       │ [PDF 預覽 iframe]            │
│   ...                  │ [Download PPTX button]      │
└────────────────────────┴─────────────────────────────┘
```

## 背景執行架構

Streamlit 是同步框架，無法直接 `await` SSE 串流，因此採用 **背景 Thread + Queue** 解耦：

```
  User 點擊 Submit
       │
       ▼
  start_long_running_task()  ← 啟動背景 Thread
       │
       ▼
  建立 asyncio.new_event_loop()
  loop.run_until_complete(get_stream_data(...))
       │
       ▼
  get_stream_data(): async 消費 SSE
       │
       ├── 進度訊息       ──► message_queue.put("message", ...)
       │
       ├── HITL 請求      ──► message_queue.put("user_input_required", ...)
       │                       user_input_event.wait()  ← 阻塞直到 UI 回應
       │
       └── 完成           ──► message_queue.put("final_result", ...)

  ──────────────────────────────────────────────────────
  @st.fragment(run_every="2s")  workflow_display()
  (workflow_complete 後 run_every=None，停止自動 rerun)
       │
       ▼
  process_messages()  ← 從 message_queue 取出訊息，更新 session_state
       │
       ▼
  st.status("Agent is working...")  ← 重新 render UI
```

### 關鍵函式

| 函式 | 說明 |
|------|------|
| `fetch_streaming_data(url, payload)` | async generator，逐行 yield SSE 內容 |
| `get_stream_data(url, payload, queue, event)` | 消費 SSE，依 event type 放入 queue；遇到 `request_user_input` 時 `event.wait()` 阻塞，等 user 提交後繼續 |
| `start_long_running_task(...)` | Thread target，建立 event loop 執行 `get_stream_data` |
| `process_messages()` | 從 queue 取出所有訊息，更新 `session_state` |

## HITL Outline 審核流程

```
  process_messages() 收到 user_input_required
       │
       ├── 正在審核中？
       │     ├── 是 ──► pending_user_inputs.append(content)
       │     └── 否 ──► session_state.user_input_required = True
       │                 session_state.user_input_prompt = content
       ▼
  gather_outline_feedback()
       │
       ▼
  顯示：
    st.text_area(summary, disabled=True)
    st.json(outline)
    st.feedback("thumbs", key=approval_key)
    st.text_area("feedback", key=feedback_key)
    st.button("Submit Feedback")
       │
       ▼
  User 點擊 Submit Feedback
       │
       ├── approval_state 未選擇？ ──► st.error("請選擇")
       │
       └── 已選擇 ──► httpx.post("/submit_user_input",
                                  {"workflow_id": ...,
                                   "user_input": {"approval": ..., "feedback": ...}})
                          │
                          └── user_input_event.set()  ← 喚醒背景 Thread
                                   │
                                   ├── pending_user_inputs 非空？
                                   │     └── 是 ──► 取出下一個，顯示新的 outline
                                   │
                                   └── 否 ──► 等待下一個 SSE event
```

### Outline 審核 Widget

每次 outline 審核使用 `prompt_counter` 生成唯一 key 避免 Streamlit widget reuse 問題：

```python
approval_key = f"approval_state_{current_prompt}"
feedback_key = f"user_feedback_{current_prompt}"

approval = st.feedback("thumbs", key=approval_key)
feedback = st.text_area("Feedback:", key=feedback_key)
```

User input payload：

```json
{
  "approval": ":material/thumb_up:",   // 或 ":material/thumb_down:"
  "feedback": "請強調 XXX 方法的貢獻"
}
```

## 結果展示

Workflow 完成後，右側 column 展示：

1. **PDF 預覽**：用 `st.pdf()` 原生 API 顯示（Streamlit >= 1.49.0）
2. **PPTX 下載**：`st.download_button`，直接從 backend 抓取二進位內容

```python
# PDF 預覽（pages/slide_generation_page.py）
st.pdf(st.session_state.pdf_data, height=600)

# PPTX 下載
st.download_button(
    label="Download Generated PPTX",
    data=pptx_data,
    file_name="generated_slides.pptx",
    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
)
```

## Auto-refresh 機制

Streamlit 預設只在 user 互動時 rerun。為了顯示 SSE 進度，使用 `@st.fragment(run_every=...)`（Streamlit >= 1.37.0）：

```python
# pages/slide_generation_page.py
_run_every = None if st.session_state.workflow_complete else "2s"

@st.fragment(run_every=_run_every)
def workflow_display():
    process_messages()
    if st.session_state.received_lines:
        state = "complete" if st.session_state.workflow_complete else "running"
        with st.status("🤖⚒️ Agent is working...", state=state):
            for line in st.session_state.received_lines:
                st.write(line)
                st.divider()
```

- `_run_every = "2s"`：workflow 進行中每 **2 秒** 自動重新執行 fragment
- `_run_every = None`：`workflow_complete = True` 後停止自動 rerun（避免不必要刷新）
- 每次執行 fragment 都呼叫 `process_messages()` 取得最新進度

## 並發保護

防止重複啟動 Thread：

```python
if (
    st.session_state.workflow_thread is None
    or not st.session_state.workflow_thread.is_alive()
):
    # 啟動新 thread
```

防止重複提交 user response：

```python
if not st.session_state.user_response_submitted:
    # 執行提交邏輯
    st.session_state.user_response_submitted = True
```
