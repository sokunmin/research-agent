# Event System

本專案採用 **LlamaIndex Event-driven Workflow** 架構。每個 workflow step 透過發送/接收特定 Event 類型來串聯，實現非同步、可並行的處理管線。

## 核心概念

- **Event**：LlamaIndex `Event` 的子類，攜帶 step 間傳遞的資料
- **`@step`**：裝飾器，定義接受哪種 Event 作為輸入，回傳哪種 Event
- **`send_event()`**：主動發送 Event（用於 fan-out，即一個 step 產生多個事件）
- **`collect_events()`**：等待所有預期 Event 收齊後才繼續（用於 fan-in 合併）
- **`stream_events()`**：外部消費者（FastAPI 的 SSE）監聽 workflow 的實時進度

## 所有 Event 定義

> 定義於 `backend/agent_workflows/events.py`

### Paper Scraping 相關

| Event 類別 | 欄位 | 說明 |
|-----------|------|------|
| `PaperEvent` | `paper: Paper` | 單篇候選論文（fan-out，每篇發一個） |
| `FilteredPaperEvent` | `paper: Paper`, `relevance: PaperRelevanceResult` | 過濾後的論文，含相關性結果（`is_relevant: bool`, `similarity_score: float`） |
| `Paper2SummaryDispatcherEvent` | `papers_path: str` | 已下載 PDF 的目錄路徑 |
| `Paper2SummaryEvent` | `pdf_path: Path`, `image_output_dir: Path`, `summary_path: Path` | 單篇論文待摘要任務（fan-out） |
| `SummaryStoredEvent` | `fpath: Path` | 摘要已儲存完成，回傳 .md 路徑 |
| `SummaryWfReadyEvent` | `summary_dir: str` | SummaryGenerationWorkflow 完成，傳遞摘要目錄給 SlideGen |

### Slide Generation 相關

| Event 類別 | 欄位 | 說明 |
|-----------|------|------|
| `SummaryEvent` | `summary: str` | 單篇論文摘要內容（fan-out） |
| `OutlineEvent` | `summary: str`, `outline: SlideOutline` | 生成的投影片大綱 |
| `OutlineFeedbackEvent` | `summary: str`, `outline: SlideOutline`, `feedback: str` | User 拒絕後帶回 feedback，觸發重新生成 |
| `OutlineOkEvent` | `summary: str`, `outline: SlideOutline` | User 核准的大綱 |
| `OutlinesWithLayoutEvent` | `outlines_fpath: Path`, `outline_example: SlideOutlineWithLayout` | 所有大綱加上 layout 資訊後的結果 |
| `ConsolidatedOutlineEvent` | `outlines: List[SlideOutline]` | 合併後的大綱清單 |
| `PythonCodeEvent` | `code: str` | Agent 生成的 Python 代碼 |
| `SlideGeneratedEvent` | `pptx_fpath: str` | 生成的 PPTX 路徑（可能是初版或修改版） |
| `SlideValidationEvent` | `results: List[SlideNeedModifyResult]` | 驗證失敗的投影片清單，含修改建議 |

### 其他

| Event 類別 | 欄位 | 說明 |
|-----------|------|------|
| `DummyEvent` | `result: str` | Debug 用，替代 SummaryGenerationWorkflow 的 stub |
| `WorkflowStreamingEvent` | `event_type: str`, `event_sender: str`, `event_content: dict` | 包裝成 SSE 格式的進度訊息（定義於 `agent_workflows/schemas.py`） |

## Event 流向圖

### SummaryGenerationWorkflow

```
  StartEvent (user_query)
       │
       ▼
  [discover_candidate_papers]
  fast_llm 改寫查詢語 → OpenAlex 全文搜尋（is_oa, citations>50, 近 3 年）
       │ fan-out
       ├──► PaperEvent (paper 1)
       ├──► PaperEvent (paper 2)
       └──► PaperEvent (paper N)
            │
            ▼  (num_workers=NUM_WORKERS_FAST)
       [filter_papers]
       Stage 1: embedding similarity (Ollama local)
       Stage 2: fast_llm 驗證（僅 borderline ~41%）
            │
            ▼
       FilteredPaperEvent × N
            │ collect all N，過濾 is_relevant=True，依 similarity_score 排序，取前 N
            ▼
       [download_papers] (4-strategy fallback: ArXiv API → ArXiv direct → PyAlex → OA URL)
            │
            ▼
       Paper2SummaryDispatcherEvent
            │ fan-out
            ├──► Paper2SummaryEvent (pdf 1)
            ├──► Paper2SummaryEvent (pdf 2)
            └──► Paper2SummaryEvent (pdf M)
                 │
                 ▼  (num_workers=NUM_WORKERS_VISION, delay=DELAY_SECONDS_VISION)
            [paper2summary] (PDF → images → VLM)
                 │
                 ▼
            SummaryStoredEvent × M
                 │ collect all M
                 ▼
            [finish]
                 │
                 ▼
            StopEvent (summary_dir)
```

### SlideGenerationWorkflow

```
  StartEvent (file_dir)
       │
       ▼
  [get_summaries] (reads *.md files)
       │ fan-out
       ├──► SummaryEvent (summary 1)
       ├──► SummaryEvent (summary 2)
       └──► SummaryEvent (summary N)
            │
            ▼
       [summary2outline] (new_fast_llm)
            │
            ▼
       OutlineEvent
            │
            ▼
       [gather_feedback_outline]  ← HITL: await user_input_future
            │
            ├── user 拒絕 ──► OutlineFeedbackEvent ──► [summary2outline] (loop back)
            │
            └── user 核准 ──► OutlineOkEvent
                                   │ collect all N
                                   ▼
                              [outlines_with_layout] (new_llm)
                                   │
                                   ▼
                              OutlinesWithLayoutEvent
                                   │
                                   ▼
                              [slide_gen] (ReAct Agent + Docker sandbox)
                                   │
                                   ▼
                              SlideGeneratedEvent
                                   │
                                   ▼
                              [validate_slides] (new_vlm)
                                   │
                    ┌──────────────┴──────────────┐
                    │                             │
                    ▼ pass                        ▼ fail (retry < 2)
               StopEvent                    SlideValidationEvent
             (pptx path)                         │
                                                 ▼
                                           [modify_slides] (ReAct Agent)
                                                 │
                                                 ▼
                                           SlideGeneratedEvent ──► [validate_slides]
```

## Fan-out / Fan-in 並行模式

**Fan-out（`send_event`）：** 一個 step 主動產生多個 Event，同類的下游 step 並行處理

```python
# 範例：paper2summary_dispatcher 發出多個 Paper2SummaryEvent
for pdf_name in Path(ev.papers_path).glob("*.pdf"):
    ctx.data["n_pdfs"] += 1
    self.send_event(Paper2SummaryEvent(...))
```

**Fan-in（`collect_events`）：** 下游等到所有預期 Event 都到齊才執行

```python
# 範例：download_papers 等全部 FilteredPaperEvent
ready = ctx.collect_events(ev, [FilteredPaperEvent] * ctx.data["n_all_papers"])
if ready is None:
    return None  # 未齊，繼續等
```
