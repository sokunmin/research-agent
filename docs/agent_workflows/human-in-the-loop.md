# Human-in-the-Loop (HITL)

HITL 機制讓 workflow 在生成每張投影片大綱後**暫停**，等待使用者審核後再繼續，確保最終簡報符合需求。

## 端對端流程

```
  Frontend (Streamlit)         Backend (FastAPI)       SlideGenerationWorkflow
         │                           │                           │
         │                           │              summary2outline 生成大綱
         │                           │◄── stream_events: ────────│
         │                           │    request_user_input     │
         │◄── SSE: request_user_input│    {summary, outline, eid}│
         │                           │                           │
  ┌──────────────────────┐          │              await user_input_future
  │  顯示 outline 審核 UI│          │              ← 暫停
  │  st.text_area(summary)│         │                           │
  │  st.json(outline)    │          │                           │
  │  st.feedback(thumbs) │          │                           │
  └──────────────────────┘          │                           │
         │                           │                           │
  [User 按 👍（核准）]               │                           │
         │                           │                           │
         │── POST /submit_user_input ►│                           │
         │   {approval: thumb_up,    │── future.set_result() ───►│
         │    feedback: ""}          │                           │
         │                           │              喚醒，回傳 user_input
         │                           │              → OutlineOkEvent
         │                           │              (進入 outlines_with_layout)
         │                           │                           │
  [User 按 👎（修改）]               │                           │
         │                           │                           │
         │── POST /submit_user_input ►│                           │
         │   {approval: thumb_down,  │── future.set_result() ───►│
         │    feedback: "加強 XXX"}  │                           │
         │                           │              喚醒，回傳 user_input
         │                           │              → OutlineFeedbackEvent
         │                           │              (重新 summary2outline)
         │                           │                           │
         │                           │    reset_user_input_future()
         │                           │    建立新的 Future，繼續下一篇
```

## 技術實作細節

### 責任分層

HITL 涉及三個 class，各有明確責任：

| Class | 提供的功能 |
|-------|-----------|
| `HumanInTheLoopWorkflow` | `_emit_message()` 輔助方法 + MLflow-wrapped `run()` |
| `SlideGenerationWorkflow` | 定義 `user_input_future`；`gather_feedback_outline` 負責暫停 / 喚醒 |
| `SummaryAndSlideGenerationWorkflow`（Orchestrator） | 擁有共享 Future；提供 `reset_user_input_future()`；透過 `run_subworkflow()` 注入 Future 給子 workflow |

### Future 機制

```python
# SummaryAndSlideGenerationWorkflow.__init__
self.user_input_future = asyncio.Future()      # 建立共享 Future

# run_subworkflow — 注入給子 workflow
sub_wf.user_input_future = self.user_input_future
sub_wf.parent_workflow   = self
sub_wf.loop = asyncio.get_running_loop()       # HITL step 需要此 loop

# gather_feedback_outline step（等待 user）
user_response = await self.user_input_future

# FastAPI /submit_user_input endpoint（由 user 觸發）
loop = wf.user_input_future.get_loop()
loop.call_soon_threadsafe(wf.user_input_future.set_result, user_input)
```

`call_soon_threadsafe` 是關鍵：FastAPI handler 在不同的執行緒中執行，必須透過 thread-safe 方式設定 Future。

### 多篇論文的並行 HITL

每篇論文的 outline 各自觸發一次 HITL。當同時有多個 `request_user_input` event 時，frontend 用 **Queue** 管理：

```python
# 若 user 正在審核中，新的 outline 加入 pending queue
if st.session_state.user_input_required:
    st.session_state.pending_user_inputs.append(content)
else:
    # 直接顯示
    st.session_state.user_input_required = True
    st.session_state.user_input_prompt = content
```

### Future Reset（多輪審核）

每次 user 提交回應後，workflow 必須重置 Future 以準備下一次等待：

```python
# gather_feedback_outline（SlideGenerationWorkflow）
if self.parent_workflow:
    # 透過 Orchestrator 重置，確保 parent 和 child 指向同一個新 Future
    await self.parent_workflow.reset_user_input_future()
    self.user_input_future = self.parent_workflow.user_input_future
else:
    # 獨立執行時（無 Orchestrator），直接建立新 Future
    self.user_input_future = self.loop.create_future()

# SummaryAndSlideGenerationWorkflow.reset_user_input_future()
async def reset_user_input_future(self):
    self.user_input_future = self.loop.create_future()
```

## User Input 格式

Frontend 送出的 JSON：

```json
{
  "workflow_id": "550e8400-...",
  "user_input": "{\"approval\": \":material/thumb_up:\", \"feedback\": \"\"}"
}
```

Workflow 解析邏輯：

```python
response_data = json.loads(user_response)
approval = response_data.get("approval", "").lower().strip()

if approval == ":material/thumb_up:":
    return OutlineOkEvent(...)
else:
    return OutlineFeedbackEvent(..., feedback=response_data["feedback"])
```

## 注意事項

- **Workflow timeout**：`SummaryAndSlideGenerationWorkflow` timeout 為 2000 秒，若 user 長時間未回應會超時
- **Future 生命週期**：每次 `submit_user_input` 後，舊 Future 廢棄，新 Future 建立，不能重複 `set_result`
- **Thread safety**：`user_input_future` 的 loop 必須與 workflow 的 event loop 一致，用 `call_soon_threadsafe` 跨 thread 設值
- **MLflow 追蹤**：子 workflow 透過 `run_subworkflow()` 執行，繞過 `HumanInTheLoopWorkflow.run()`，LLM call 仍透過 autolog 記錄在 parent MLflow run 下（詳見 BACKUP_PLAN.md）
