# Workflow 串接全覽

以下單一大圖完整呈現本專案所有 Agentic Workflow 的串接關係、每個 Step 的執行順序、HITL
機制，以及關鍵程式碼對應。

---

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│  FastAPI  POST /run-slide-gen  ·  main.py                                                    │
│                                                                                              │
│  workflow_id = str(uuid.uuid4())                                                             │
│  wf = SummaryAndSlideGenerationWorkflow(wid=workflow_id, timeout=2000)                       │
│  wf.add_workflows(summary_gen_wf = SummaryGenerationWorkflow(wid=workflow_id, timeout=800))  │
│  wf.add_workflows(slide_gen_wf   = SlideGenerationWorkflow(wid=workflow_id, timeout=1200))   │
│  task = asyncio.create_task(wf.run(user_query=topic.query))                                  │
│  async for ev in wf.stream_events(): yield ev.msg          # SSE to frontend                │
└──────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                           │ wf.run(user_query)
                                           ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│  SummaryAndSlideGenerationWorkflow  ·  summarize_and_generate_slides.py                      │
│  extends Workflow                                                                            │
│  ──────────────────────────────────────────────────────────────────────────────────────────  │
│  self.user_input_future = asyncio.Future()   # 共享給兩個子 workflow                         │
│                                                                                              │
│  async def run_subworkflow(sub_wf, ctx, **kwargs):                                           │
│      sub_wf.user_input_future = self.user_input_future   # 注入共享 Future                  │
│      sub_wf.parent_workflow = self                                                           │
│      async for event in sub_wf.stream_events():                                              │
│          ctx.write_event_to_stream(event)                # 轉發所有事件至 FastAPI SSE        │
│  ──────────────────────────────────────────────────────────────────────────────────────────  │
│                                                                                              │
│  @step  summary_gen(StartEvent) ──────────────────────────────────────────────────────────  │
│  │                                                                                           │
│  │  run_subworkflow(summary_gen_wf, ctx, user_query=ev.user_query)                          │
│  │                                                                                           │
│  │  ┌───────────────────────────────────────────────────────────────────────────────────┐   │
│  │  │  SummaryGenerationWorkflow  ·  summary_gen.py                                     │   │
│  │  │  extends HumanInTheLoopWorkflow                                                   │   │
│  │  │  ─────────────────────────────────────────────────────────────────────────────    │   │
│  │  │  StartEvent(user_query)                                                           │   │
│  │  │       │                                                                           │   │
│  │  │       ▼                                                                           │   │
│  │  │  [tavily_query]                                                                   │   │
│  │  │  query = f"arxiv papers about the state of the art of {ev.user_query}"           │   │
│  │  │  TavilyClient(settings.TAVILY_API_KEY).search(query, max_results=2)             │   │
│  │  │       │                                                                           │   │
│  │  │       ▼                                                                           │   │
│  │  │  TavilyResultsEvent(results: List[TavilySearchResult])                           │   │
│  │  │       │                                                                           │   │
│  │  │       ▼                                                                           │   │
│  │  │  [get_paper_with_citations]                                                       │   │
│  │  │  get_paper_with_citations(r.title)  →  pyalex OpenAlex search + citing papers    │   │
│  │  │       │  fan-out: self.send_event(PaperEvent(paper=paper)) per paper             │   │
│  │  │       ├──► PaperEvent                                                             │   │
│  │  │       ├──► PaperEvent                                                             │   │
│  │  │       └──► PaperEvent  × N                                                       │   │
│  │  │                │                                                                  │   │
│  │  │                ▼  num_workers=4                                                   │   │
│  │  │  [filter_papers]                                                                  │   │
│  │  │  process_citation(research_topic, paper, new_fast_llm(temperature=0.0))          │   │
│  │  │  FunctionCallingProgram → IsCitationRelevant(score: int, reason: str)            │   │
│  │  │                │                                                                  │   │
│  │  │                ▼                                                                  │   │
│  │  │  FilteredPaperEvent × N                                                          │   │
│  │  │                │  collect all N  (ctx.collect_events)                            │   │
│  │  │                │  sort by (score DESC, ArXiv available DESC), keep top 5         │   │
│  │  │                ▼                                                                  │   │
│  │  │  [download_papers]                                                               │   │
│  │  │  download_relevant_citations(papers_dict, self.papers_download_path)             │   │
│  │  │  → arxiv 套件下載 PDF 至 workflow_artifacts/SummaryGenerationWorkflow/{wid}/     │   │
│  │  │                │                                                                  │   │
│  │  │                ▼                                                                  │   │
│  │  │  Paper2SummaryDispatcherEvent(papers_path: str)                                  │   │
│  │  │                │                                                                  │   │
│  │  │                ▼                                                                  │   │
│  │  │  [paper2summary_dispatcher]                                                      │   │
│  │  │  for pdf in Path(papers_path).glob("*.pdf"):                                     │   │
│  │  │      self.send_event(Paper2SummaryEvent(pdf_path, image_output_dir, summary_path))│  │
│  │  │                │  fan-out: 每個 PDF 各一個 Paper2SummaryEvent                    │   │
│  │  │                ├──► Paper2SummaryEvent                                            │   │
│  │  │                ├──► Paper2SummaryEvent                                            │   │
│  │  │                └──► Paper2SummaryEvent  × M                                      │   │
│  │  │                         │                                                         │   │
│  │  │                         ▼  num_workers=4                                          │   │
│  │  │  [paper2summary]                                                                  │   │
│  │  │  pdf2images(pdf_path, image_output_dir)          # PDF → PNG per page            │   │
│  │  │  summary = await summarize_paper_images(image_output_dir)  # new_vlm()           │   │
│  │  │  save_summary_as_markdown(summary, summary_path) # → .md                        │   │
│  │  │                         │                                                         │   │
│  │  │                         ▼                                                         │   │
│  │  │  SummaryStoredEvent × M (fpath: Path)                                            │   │
│  │  │                         │  collect all M  (ctx.collect_events)                   │   │
│  │  │                         ▼                                                         │   │
│  │  │  [finish]                                                                         │   │
│  │  │  assert all .md exist  →  return StopEvent(result=fpath.parent.as_posix())       │   │
│  │  │                         │                                                         │   │
│  │  │                         ▼                                                         │   │
│  │  │  StopEvent(result = summary_dir: str)                                            │   │
│  │  │                                                                                   │   │
│  │  │  ▸ HumanInTheLoopWorkflow.run() wraps this entire workflow:                      │   │
│  │  │    mlflow.set_experiment("SummaryGenerationWorkflow")                             │   │
│  │  │    mlflow.llama_index.autolog() + mlflow.litellm.autolog()                       │   │
│  │  │    with mlflow.start_run(): await super().run(...)                                │   │
│  │  └───────────────────────────────────────────────────────────────────────────────────┘   │
│  │                                                                                           │
│  │  return SummaryWfReadyEvent(summary_dir = result)                                        │
│  │                                                                                           │
│  @step  slide_gen(SummaryWfReadyEvent) ───────────────────────────────────────────────────  │
│  │                                                                                           │
│  │  run_subworkflow(slide_gen_wf, ctx, file_dir=ev.summary_dir)                             │
│  │                                                                                           │
│  │  ┌───────────────────────────────────────────────────────────────────────────────────┐   │
│  │  │  SlideGenerationWorkflow  ·  slide_gen.py                                         │   │
│  │  │  extends HumanInTheLoopWorkflow                                                   │   │
│  │  │  self.user_input_future  ◄── injected by SummaryAndSlideGenerationWorkflow        │   │
│  │  │  ─────────────────────────────────────────────────────────────────────────────    │   │
│  │  │  StartEvent(file_dir)                                                             │   │
│  │  │       │                                                                           │   │
│  │  │       ▼                                                                           │   │
│  │  │  [get_summaries]                                                                  │   │
│  │  │  for md in Path(file_dir).glob("*.md"):                                           │   │
│  │  │      self.send_event(SummaryEvent(summary=md.read_text()))                        │   │
│  │  │       │  fan-out: 每篇摘要各一個 SummaryEvent                                    │   │
│  │  │       ├──► SummaryEvent                                                           │   │
│  │  │       ├──► SummaryEvent                                                           │   │
│  │  │       └──► SummaryEvent  × N                                                     │   │
│  │  │                │                                                                  │   │
│  │  │                ▼                                                                  │   │
│  │  │  [summary2outline]        ◄─── 也接收 OutlineFeedbackEvent（HITL 重試路徑）      │   │
│  │  │  new_fast_llm(0.1) + FunctionCallingProgram → SlideOutline(title, content)       │   │
│  │  │  若為 feedback 路徑，使用 MODIFY_SUMMARY2OUTLINE_PMT 帶入原大綱與 feedback       │   │
│  │  │                │                                                                  │   │
│  │  │                ▼                                                                  │   │
│  │  │  OutlineEvent(summary, outline)                                                   │   │
│  │  │                │                                                                  │   │
│  │  │                ▼                                                                  │   │
│  │  │  [gather_feedback_outline]  ◄────────────────────── HITL ──────────────────────  │   │
│  │  │                │                                                                  │   │
│  │  │  ctx.write_event_to_stream(Event(request_user_input))  ──────────────────────────────► Frontend (SSE)
│  │  │  user_response = await self.user_input_future           ◄────────────────────────────  POST /submit_user_input
│  │  │  # main.py: loop.call_soon_threadsafe(future.set_result, user_input)              │   │
│  │  │  # 每次完成後: await parent_workflow.reset_user_input_future()                   │   │
│  │  │                │                                                                  │   │
│  │  │                ├── approval == ":material/thumb_down:" ──► OutlineFeedbackEvent   │   │
│  │  │                │                                               │                  │   │
│  │  │                │                                               └──► [summary2outline] (loop)
│  │  │                │                                                                  │   │
│  │  │                └── approval == ":material/thumb_up:"  ──► OutlineOkEvent         │   │
│  │  │                                                                │  collect all N   │   │
│  │  │                                                                ▼                  │   │
│  │  │  [outlines_with_layout]                                                           │   │
│  │  │  get_all_layouts_info(self.slide_template_path)  # 從 PPTX 模板抽取 layout 資訊  │   │
│  │  │  new_llm(0.1) → 為每個 SlideOutline 選擇最適 layout                              │   │
│  │  │  → 輸出 slide_outlines.json 至 workflow_artifacts/SlideGenerationWorkflow/{wid}/ │   │
│  │  │                                                                │                  │   │
│  │  │                                                                ▼                  │   │
│  │  │  OutlinesWithLayoutEvent(outlines_fpath, outline_example)                         │   │
│  │  │                                                                │                  │   │
│  │  │                                                                ▼                  │   │
│  │  │  [slide_gen]  ReActAgent(llm=new_llm(0.1), tools=self.sandbox.to_tool_list())    │   │
│  │  │  ┌─────────────────────────────────────────────────────────────────────────────┐ │   │
│  │  │  │  LlmSandboxToolSpec  ·  services/sandbox.py                                 │ │   │
│  │  │  │  create_pool_manager(backend="docker", lang="python",                        │ │   │
│  │  │  │                      libraries=["python-pptx"],                              │ │   │
│  │  │  │                      config=PoolConfig(min=1, max=2))                        │ │   │
│  │  │  │  requires: /var/run/docker.sock  (docker-compose.yml backend volumes)        │ │   │
│  │  │  │  tools:  run_code(code: str) → stdout                                        │ │   │
│  │  │  │          list_files(remote_dir) → file paths                                 │ │   │
│  │  │  │          upload_file(local_path) → /sandbox/<filename>                       │ │   │
│  │  │  └─────────────────────────────────────────────────────────────────────────────┘ │   │
│  │  │  Agent flow:                                                                      │   │
│  │  │    upload_file(self.slide_template_path)      # PPTX 模板 → /sandbox/           │   │
│  │  │    run_code(python-pptx script)               # 生成 paper_summaries.pptx        │   │
│  │  │    download_file_to_local(remote, local_path) # 取回結果至 workflow_artifacts/   │   │
│  │  │                                                                │                  │   │
│  │  │                                                                ▼                  │   │
│  │  │  SlideGeneratedEvent(pptx_fpath: str)                                             │   │
│  │  │                                                                │                  │   │
│  │  │                                                                ▼                  │   │
│  │  │  [validate_slides]                                                                │   │
│  │  │  pptx2images(pptx_fpath)  →  PNG per slide                                       │   │
│  │  │  new_vlm() + MultiModalLLMCompletionProgram                                       │   │
│  │  │  → SlideValidationResult(is_valid: bool, suggestion_to_fix: str) per slide       │   │
│  │  │                                                                │                  │   │
│  │  │                             ┌──────────────────────────────────┤                  │   │
│  │  │                             │                                  │                  │   │
│  │  │                  ▼ all valid                       ▼ has issues (retry < 2)      │   │
│  │  │         [copy_final_slide]                   SlideValidationEvent                │   │
│  │  │         copy → final.pptx                    (results: List[SlideNeedModifyResult])│  │
│  │  │         convert → final.pdf                                    │                  │   │
│  │  │                  │                                             ▼                  │   │
│  │  │                  ▼                            [modify_slides]  ReActAgent         │   │
│  │  │         StopEvent(pptx_path)                 (same LlmSandboxToolSpec tools)     │   │
│  │  │                                              modify existing pptx, save _v{n}.pptx│  │
│  │  │                                                                │                  │   │
│  │  │                                                                ▼                  │   │
│  │  │                                               SlideGeneratedEvent ──► [validate_slides]
│  │  │                                               (loop, until all valid or retry==2) │   │
│  │  │                                                                                   │   │
│  │  │  ▸ HumanInTheLoopWorkflow.run() wraps this entire workflow:                      │   │
│  │  │    mlflow.set_experiment("SlideGenerationWorkflow")                               │   │
│  │  │    mlflow.llama_index.autolog() + mlflow.litellm.autolog()                       │   │
│  │  │    with mlflow.start_run(): await super().run(...)                                │   │
│  │  └───────────────────────────────────────────────────────────────────────────────────┘   │
│  │                                                                                           │
│  │  return StopEvent(pptx_path)                                                             │
│  │                                                                                           │
└──┴───────────────────────────────────────────────────────────────────────────────────────────┘
                                           │
                                           ▼
              FastAPI SSE: {"final_result": {
                  "result": pptx_path,
                  "download_pptx_url": "http://backend:80/download_pptx/{workflow_id}",
                  "download_pdf_url":  "http://backend:80/download_pdf/{workflow_id}"
              }}
```

---

## HITL 機制補充說明

```
  SlideGenerationWorkflow                  FastAPI (main.py)              Frontend (Streamlit)
           │                                      │                               │
  gather_feedback_outline                         │                               │
  ctx.write_event_to_stream(                      │                               │
    request_user_input{summary, outline}    ──────►  SSE stream  ────────────────►
  )                                               │                               │
  user_response = await self.user_input_future    │                         顯示審核 UI
  ◄─── 暫停，等待前端回應 ─────────────────────────────────────────────────────── │
           │                                      │                               │
           │                                      │◄── POST /submit_user_input ───│
           │                         loop.call_soon_threadsafe(                   │
           │◄── future.set_result(user_input) ────  future.set_result, user_input)│
           │                                      │                               │
  解析 approval 欄位:                             │                               │
    ":material/thumb_up:"   → OutlineOkEvent      │                               │
    ":material/thumb_down:" → OutlineFeedbackEvent│                               │
           │                                      │                               │
  await parent_workflow.reset_user_input_future() │                               │
  self.user_input_future = parent_workflow.user_input_future  # 準備下一輪        │
```

---

## wid 跨 Workflow 共享與輸出路徑

所有 Workflow 以**相同的 `wid`** 初始化，輸出路徑在同一 `workflow_artifacts/` 目錄下：

```
workflow_artifacts/
├── SummaryGenerationWorkflow/{wid}/
│   └── data/
│       ├── papers/                  ← download_papers 下載的 PDF
│       ├── papers_images/           ← paper2summary 轉出的 PNG
│       └── papers_images/*.md       ← paper2summary 輸出的摘要（傳遞給 SlideGen）
└── SlideGenerationWorkflow/{wid}/
    ├── slide_outlines.json          ← outlines_with_layout 輸出
    ├── paper_summaries.pptx         ← slide_gen 初版
    ├── paper_summaries_v1.pptx      ← modify_slides 第 1 次修改（若有）
    ├── final.pptx                   ← GET /download_pptx/{wid}
    └── final.pdf                    ← GET /download_pdf/{wid}
```

---

## Debug Stub：SummaryGenerationDummyWorkflow

當需要跳過論文搜尋、直接測試 `SlideGenerationWorkflow` 時，在 `main.py` 替換：

```python
# main.py — 取消以下注解，替換 SummaryGenerationWorkflow
wf.add_workflows(
    summary_gen_wf=SummaryGenerationDummyWorkflow(wid=workflow_id, timeout=800)
)
```

`SummaryGenerationDummyWorkflow` 直接回傳固定路徑：
`workflow_artifacts/SummaryGenerationWorkflow/5sn92wndsx/data/paper_summaries`

---

## 相關文件

- [SummaryGenerationWorkflow 詳細步驟](./summary-gen-workflow.md)
- [SlideGenerationWorkflow 詳細步驟](./slide-gen-workflow.md)
- [Event 定義與流向](./events.md)
- [Human-in-the-Loop 機制](./human-in-the-loop.md)
- [Backend API Reference](../backend/api-reference.md)
