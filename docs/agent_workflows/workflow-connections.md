# Workflow 串接全覽

> **讀圖說明**
> - `┌─ [@step name] ─┐` 框 = 一個 LlamaIndex `@step` 函式
> - `│` → `▼` 箭頭 = Event 傳遞方向
> - ⚠️ = HITL 暫停點，workflow 阻塞等待 user 輸入
> - 兩個子 workflow 都 extends `HumanInTheLoopWorkflow`，執行時自動包裹 MLflow tracking

---

## 架構總覽

```
  User Browser
       │  POST /run-slide-gen  {"query": "..."}
       ▼
  ┌─ FastAPI (main.py) ──────────────────────────────────────────────────┐
  │  建立 SummaryAndSlideGenerationWorkflow（Orchestrator）              │
  │  並注入兩個子 workflow，透過 SSE stream 持續推送進度給前端           │
  └──────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 ▼
  ┌─ SummaryAndSlideGenerationWorkflow  (Orchestrator) ──────────────────┐
  │  summarize_and_generate_slides.py  ·  extends Workflow               │
  │                                                                      │
  │  建立共享 user_input_future = asyncio.Future()                       │
  │  透過 run_subworkflow() 注入給子 workflow 並轉發 SSE 事件            │
  │                                                                      │
  │   step ①                                  step ②                    │
  │  ┌────────────────────────────┐   ──►   ┌────────────────────────┐  │
  │  │  SummaryGenerationWorkflow │         │ SlideGenerationWorkflow │  │
  │  │  搜尋論文 → 生成摘要       │         │ 生成投影片 + HITL 審核  │  │
  │  │  summary_gen.py            │         │ slide_gen.py            │  │
  │  └────────────────────────────┘         └────────────────────────┘  │
  │                                                                      │
  │  兩個子 workflow 都 extends HumanInTheLoopWorkflow：                 │
  │  └── run() 自動包裹 mlflow.start_run() + llama_index.autolog()      │
  └──────────────────────────────────────────────────────────────────────┘
                                 │ SSE final_result
                                 ▼
                    {"download_pptx_url": "...", "download_pdf_url": "..."}
```

---

## ① FastAPI Entry Point — main.py

```
  POST /run-slide-gen  {"query": "powerpoint slides automation"}
       │
       │  workflow_id = str(uuid.uuid4())
       │
       │  wf = SummaryAndSlideGenerationWorkflow(wid=workflow_id, timeout=2000)
       │  wf.add_workflows(
       │      summary_gen_wf = SummaryGenerationWorkflow(wid=workflow_id, timeout=800)
       │  )
       │  wf.add_workflows(
       │      slide_gen_wf = SlideGenerationWorkflow(wid=workflow_id, timeout=1200)
       │  )
       │
       │  task = asyncio.create_task(wf.run(user_query=topic.query))
       │
       │  async for ev in wf.stream_events():   # SSE 持續推送進度至前端
       │      yield f"{ev.msg}\n\n"
       │
       ▼
  SummaryAndSlideGenerationWorkflow.run()
```

---

## ② Orchestrator — SummaryAndSlideGenerationWorkflow

**summarize_and_generate_slides.py  ·  extends Workflow**

```
  ┌─ 共用機制 ─────────────────────────────────────────────────────────────┐
  │                                                                        │
  │  self.user_input_future = asyncio.Future()  # 共享給兩個子 workflow    │
  │                                                                        │
  │  async def run_subworkflow(sub_wf, ctx, **kwargs):                    │
  │      sub_wf.user_input_future = self.user_input_future  # 注入 Future │
  │      sub_wf.parent_workflow   = self                                   │
  │      async for event in sub_wf.stream_events():                       │
  │          ctx.write_event_to_stream(event)   # 轉發所有 SSE 事件       │
  │      return await sub_task                                             │
  │                                                                        │
  └────────────────────────────────────────────────────────────────────────┘

  StartEvent(user_query)
       │
       ▼
  ┌─ @step  summary_gen ───────────────────────────────────────────────────┐
  │  await run_subworkflow(summary_gen_wf, ctx, user_query=ev.user_query)  │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ SummaryWfReadyEvent(summary_dir)
                                                      ▼
  ┌─ @step  slide_gen ─────────────────────────────────────────────────────┐
  │  await run_subworkflow(slide_gen_wf, ctx, file_dir=ev.summary_dir)     │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ StopEvent(pptx_path)
                                                      ▼
                                            FastAPI 推送 final_result SSE
```

---

## ③ SummaryGenerationWorkflow — summary_gen.py

**extends HumanInTheLoopWorkflow  ·  無 HITL 步驟**

```
  StartEvent(user_query: str)
       │
       ▼
  ┌─ @step  tavily_query ──────────────────────────────────────────────────┐
  │  query = f"arxiv papers about the state of the art of {user_query}"   │
  │  TavilyClient(TAVILY_API_KEY).search(query, max_results=2)            │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ TavilyResultsEvent(results)
                                                      ▼
  ┌─ @step  get_paper_with_citations ──────────────────────────────────────┐
  │  for r in results:                                                     │
  │      paper     = search_papers(r.title, limit=1)[0]   # pyalex        │
  │      citations = get_citing_papers(paper, limit=50)                    │
  │      self.send_event(PaperEvent(paper))                # fan-out       │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ PaperEvent × N（fan-out）
                                                      │ 每篇論文各一個 Event
                                                      ▼
  ┌─ @step  filter_papers ───────────────── num_workers=4 並行 ────────────┐
  │  new_fast_llm(temperature=0.0) + FunctionCallingProgram                │
  │  → IsCitationRelevant(score: int, reason: str)                         │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ FilteredPaperEvent × N
                                                      │ collect all N（fan-in）
                                                      │ sort by (score DESC, ArXiv DESC)
                                                      │ keep top 5
                                                      ▼
  ┌─ @step  download_papers ───────────────────────────────────────────────┐
  │  arxiv.Client().get_paper(arxiv_id).download_pdf()                    │
  │  → workflow_artifacts/SummaryGenerationWorkflow/{wid}/data/papers/    │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ Paper2SummaryDispatcherEvent(papers_path)
                                                      ▼
  ┌─ @step  paper2summary_dispatcher ─────────────────────────────────────┐
  │  for pdf in Path(papers_path).glob("*.pdf"):                          │
  │      self.send_event(Paper2SummaryEvent(pdf_path, ...))  # fan-out   │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ Paper2SummaryEvent × M（fan-out）
                                                      │ 每個 PDF 各一個 Event
                                                      ▼
  ┌─ @step  paper2summary ───────────────── num_workers=4 並行 ────────────┐
  │  pdf2images(pdf_path, image_output_dir)    # PDF → PNG per page       │
  │  summary = await summarize_paper_images()  # new_vlm().acomplete()    │
  │  save_summary_as_markdown(summary, path)   # → .md 檔                 │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ SummaryStoredEvent × M
                                                      │ collect all M（fan-in）
                                                      ▼
  ┌─ @step  finish ────────────────────────────────────────────────────────┐
  │  assert all .md files exist                                            │
  │  return StopEvent(result = summary_dir: str)                           │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │
                                                      ▼
                                      SummaryWfReadyEvent(summary_dir)
                                      → 觸發 SlideGenerationWorkflow
```

---

## ④ SlideGenerationWorkflow — slide_gen.py

**extends HumanInTheLoopWorkflow  ·  含 HITL：每篇論文大綱需 user 審核**
`self.user_input_future` ← 由 Orchestrator 注入（共享 asyncio.Future）

```
  StartEvent(file_dir: str)   ← summary_dir（Markdown 摘要目錄）
       │
       ▼
  ┌─ @step  get_summaries ─────────────────────────────────────────────────┐
  │  for md in Path(file_dir).glob("*.md"):                               │
  │      self.send_event(SummaryEvent(summary=md.read_text()))  # fan-out │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ SummaryEvent × N（fan-out）
                          ┌───────────────────────────┘
                          │  也接收 OutlineFeedbackEvent（HITL 不通過時的重試路徑）
                          ▼
  ┌─ @step  summary2outline ───────────────────────────────────────────────┐
  │  new_fast_llm(0.1) + FunctionCallingProgram                            │
  │  → SlideOutline(title: str, content: List[str])                        │
  │                                                                        │
  │  若收到 OutlineFeedbackEvent（user 按 👎）：                           │
  │      使用 MODIFY_SUMMARY2OUTLINE_PMT                                   │
  │      帶入原大綱 + user feedback 重新生成                                │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ OutlineEvent(summary, outline)
                                                      ▼
  ┌─ @step  gather_feedback_outline ──────── ⚠️ HITL 暫停點 ───────────────┐
  │                                                                        │
  │  ① 推送大綱至前端：                                                    │
  │     ctx.write_event_to_stream(request_user_input{summary, outline})   │──► Frontend SSE
  │                                                                        │
  │  ② 阻塞等待 user 回應：                                                │
  │     user_response = await self.user_input_future     ◄── 暫停          │◄── POST /submit_user_input
  │     # main.py: loop.call_soon_threadsafe(future.set_result, input)     │
  │                                                                        │
  │  ③ 重置 Future 準備下一輪：                                            │
  │     await parent_workflow.reset_user_input_future()                    │
  │                                                                        │
  │  ④ 解析 user 回應：                                                    │
  │     approval = json.loads(user_response)["approval"]                   │
  │                                                                        │
  └───────────────────────┬────────────────────────────┬───────────────────┘
                          │                            │
                   👍 thumb_up                  👎 thumb_down
                          │                            │
                   OutlineOkEvent            OutlineFeedbackEvent(feedback)
                          │                            │
                          │                            └──► [summary2outline]（重試 loop）
                          │ collect all N OutlineOkEvent（fan-in）
                          ▼
  ┌─ @step  outlines_with_layout ──────────────────────────────────────────┐
  │  get_all_layouts_info(slide_template_path)  # 從 PPTX 模板抽取        │
  │  new_llm(0.1) → 為每個 SlideOutline 選擇最適 layout                   │
  │  寫出 slide_outlines.json                                              │
  │  → workflow_artifacts/SlideGenerationWorkflow/{wid}/                   │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ OutlinesWithLayoutEvent
                                                      ▼
  ┌─ @step  slide_gen ────────────────── ReActAgent ───────────────────────┐
  │                                                                        │
  │  ReActAgent(llm=new_llm(0.1), tools=self.sandbox.to_tool_list())      │
  │                                                                        │
  │  ┌─ LlmSandboxToolSpec  (services/sandbox.py) ──────────────────────┐ │
  │  │  create_pool_manager(backend="docker", lang="python",            │ │
  │  │                      libraries=["python-pptx"],                  │ │
  │  │                      config=PoolConfig(min=1, max=2))            │ │
  │  │  需要：/var/run/docker.sock（docker-compose backend volumes）     │ │
  │  │  工具：run_code(code) / list_files() / upload_file(path)         │ │
  │  └──────────────────────────────────────────────────────────────────┘ │
  │                                                                        │
  │  Agent 執行順序：                                                      │
  │  ① upload_file(slide_template_path)  → /sandbox/template.pptx        │
  │  ② run_code(python-pptx script)      → 生成 paper_summaries.pptx     │
  │  ③ download_file_to_local(remote)    → workflow_artifacts/            │
  │                                                                        │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ SlideGeneratedEvent(pptx_fpath)
                                                      ▼
  ┌─ @step  validate_slides ───────────────────────────────────────────────┐
  │  pptx2images(pptx_fpath)  → PNG per slide                             │
  │  new_vlm() + MultiModalLLMCompletionProgram                            │
  │  → SlideValidationResult(is_valid: bool, suggestion_to_fix: str)      │
  └───────────────────────┬────────────────────────────┬───────────────────┘
                          │                            │
                    全部 valid                   有問題（retry < 2）
                          │                            │ SlideValidationEvent
                          ▼                            ▼
             ┌─ @step  copy_final_slide ─┐   ┌─ @step  modify_slides ───────────────┐
             │  copy    → final.pptx     │   │  ReActAgent（同 sandbox 工具）        │
             │  soffice → final.pdf      │   │  修改現有 pptx → _v{n}.pptx          │
             └────────────┬──────────────┘   └──────────────────┬────────────────────┘
                          │                                      │ SlideGeneratedEvent
                          │                                      └──► [validate_slides]（loop）
                          │ StopEvent(pptx_path)
                          ▼
```

---

## HITL 三方互動時序

```
  SlideGenerationWorkflow        FastAPI (main.py)          Frontend (Streamlit)
          │                             │                           │
  gather_feedback_outline               │                           │
  write_event_to_stream()      ─────────►  SSE stream ────────────►
  {summary, outline}                   │                    顯示審核 UI
  await self.user_input_future          │                    st.json(outline)
  ↓ 阻塞暫停                           │                    st.feedback("thumbs")
          │                             │                           │
          │                             │◄── POST /submit_user_input│
          │                loop.call_soon_threadsafe(               │
          │◄─ future.set_result ─────── future.set_result, input)  │
          │                             │                           │
  json.loads(user_response)             │                           │
  thumb_up  → OutlineOkEvent            │                           │
  thumb_down→ OutlineFeedbackEvent      │                           │
          │                             │                           │
  reset_user_input_future()             │                           │
  （準備下一篇論文的 HITL）              │                           │
```

---

## 輸出路徑（wid 跨 Workflow 共享）

所有 Workflow 以**相同 `wid`** 初始化，輸出收斂至同一 `workflow_artifacts/` 目錄：

```
  workflow_artifacts/
  ├── SummaryGenerationWorkflow/{wid}/
  │   └── data/
  │       ├── papers/              ← download_papers：arXiv PDF
  │       ├── papers_images/       ← paper2summary：PDF 轉 PNG（VLM 輸入）
  │       └── papers_images/*.md   ← paper2summary：Markdown 摘要（傳入 SlideGen）
  │
  └── SlideGenerationWorkflow/{wid}/
      ├── slide_outlines.json      ← outlines_with_layout 輸出
      ├── paper_summaries.pptx     ← slide_gen 初版
      ├── paper_summaries_v1.pptx  ← modify_slides 第 1 次修改（若有）
      ├── final.pptx               ← GET /download_pptx/{wid}
      └── final.pdf                ← GET /download_pdf/{wid}
```

---

## Debug Stub — SummaryGenerationDummyWorkflow

跳過論文搜尋，直接以既有摘要測試 SlideGenerationWorkflow：

```python
# main.py — 取消以下注解，替換 SummaryGenerationWorkflow
wf.add_workflows(
    summary_gen_wf=SummaryGenerationDummyWorkflow(wid=workflow_id, timeout=800)
)
# 直接回傳固定路徑：
# workflow_artifacts/SummaryGenerationWorkflow/5sn92wndsx/data/paper_summaries
```

---

## 相關文件

- [SummaryGenerationWorkflow 詳細步驟](./summary-gen-workflow.md)
- [SlideGenerationWorkflow 詳細步驟](./slide-gen-workflow.md)
- [Event 定義與流向](./events.md)
- [Human-in-the-Loop 機制](./human-in-the-loop.md)
- [Backend API Reference](../backend/api-reference.md)
