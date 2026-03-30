# Workflow 串接全覽

> **讀圖說明**
> - `┌─ [@step name] ─┐` 框 = 一個 LlamaIndex `@step` 函式
> - `│` → `▼` 箭頭 = Event 傳遞方向
> - ⚠️ = HITL 暫停點，workflow 阻塞等待 user 輸入
> - 兩個子 workflow 都 extends `HumanInTheLoopWorkflow`，提供 `_emit_message()` + MLflow-wrapped `run()`

---

## 架構總覽

```
  User Browser
       │  POST /run-slide-gen  {"query": "..."}
       ▼
  ┌─ FastAPI (main.py) ──────────────────────────────────────────────────┐
  │  建立 SummaryAndSlideGenerationWorkflow（Orchestrator）              │
  │  子 workflow 以 constructor 注入，透過 SSE stream 持續推送進度給前端 │
  └──────────────────────────────┬───────────────────────────────────────┘
                                 │
                                 ▼
  ┌─ SummaryAndSlideGenerationWorkflow  (Orchestrator) ──────────────────┐
  │  summarize_and_generate_slides.py  ·  extends Workflow               │
  │                                                                      │
  │  self.user_input_future = asyncio.Future()  ← 共享 Future            │
  │  reset_user_input_future() — 每次 HITL 後重建新 Future               │
  │  run_subworkflow() — 注入 Future + loop，stream 子 wf events         │
  │                                                                      │
  │   step ①                                  step ②                    │
  │  ┌────────────────────────────┐   ──►   ┌────────────────────────┐  │
  │  │  SummaryGenerationWorkflow │         │ SlideGenerationWorkflow │  │
  │  │  搜尋論文 → 生成摘要       │         │ 生成投影片 + HITL 審核  │  │
  │  │  summary_gen.py            │         │ slide_gen.py            │  │
  │  └────────────────────────────┘         └────────────────────────┘  │
  │                                                                      │
  │  兩個子 workflow 都 extends HumanInTheLoopWorkflow：                 │
  │  └── _emit_message() 輔助方法                                        │
  │  └── run() 包裹 mlflow.start_run() + llama_index/litellm.autolog()  │
  │      （run_subworkflow 繞過此 run()，LLM calls 記錄在 parent run 下）│
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
       │  wf = SummaryAndSlideGenerationWorkflow(
       │      summary_gen_wf = SummaryGenerationWorkflow(wid=workflow_id, timeout=800),
       │      slide_gen_wf   = SlideGenerationWorkflow(wid=workflow_id, timeout=1200),
       │      wid=workflow_id,
       │      timeout=2000,
       │  )
       │
       │  wf.loop = asyncio.get_running_loop()
       │  handler = Workflow.run(wf, user_query=topic.query)   # base Workflow.run()
       │
       │  async for ev in handler.stream_events():   # SSE 持續推送進度至前端
       │      yield f"{ev.msg}\n\n"
       │  final_result = await handler
       │
       ▼
  SummaryAndSlideGenerationWorkflow 執行
```

> **設計說明**：使用 `Workflow.run(wf, ...)` 而非 `wf.run(...)` 是為了取得 Handler 物件（0.14.x API），讓 `stream_events()` 可用。`HumanInTheLoopWorkflow.run()` 是 `async def` 且內部 `await` Handler，會消耗它使 `stream_events()` 無法存取。

---

## ② Orchestrator — SummaryAndSlideGenerationWorkflow

**summarize_and_generate_slides.py  ·  extends Workflow**

```
  ┌─ 共用機制 ─────────────────────────────────────────────────────────────┐
  │                                                                        │
  │  self.user_input_future = asyncio.Future()  # 共享給子 workflow        │
  │                                                                        │
  │  async def run_subworkflow(sub_wf, ctx, **kwargs):                    │
  │      sub_wf.user_input_future = self.user_input_future  # 注入 Future │
  │      sub_wf.parent_workflow   = self                                   │
  │      sub_wf.loop = asyncio.get_running_loop()  # HITL step 需要       │
  │                                                                        │
  │      # base Workflow.run() 取得 Handler（不走 HumanInTheLoopWorkflow） │
  │      handler = Workflow.run(sub_wf, **kwargs)                         │
  │      async for event in handler.stream_events():                      │
  │          ctx.write_event_to_stream(event)   # 轉發所有 SSE 事件       │
  │      return await handler                                              │
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
  ┌─ @step  discover_candidate_papers ────────────────────────────────────┐
  │  1. new_fast_llm: 將 user_query 改寫為 BM25 學術搜尋語               │
  │  2. fetch_candidate_papers(search_query)                              │
  │     OpenAlex 全文搜尋（is_oa, citations>50, 近 3 年，排除撤稿）       │
  │     最多取 PAPER_CANDIDATE_LIMIT=100 篇，排除重複                     │
  │  → ctx.store["n_all_papers"] = len(papers)                           │
  │  → ctx.send_event(PaperEvent) × N（fan-out）                         │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ PaperEvent × N（fan-out）
                                                      ▼
  ┌─ @step  filter_papers ──────── num_workers=NUM_WORKERS_FAST=2 ─────────┐
  │  PaperRelevanceFilter.assess_relevance(paper, research_topic)          │
  │                                                                        │
  │  Stage 1 — Embedding 相似度（ollama/nomic-embed-text，本地）           │
  │    sim < 0.500  → is_relevant=False（直接拒絕）                        │
  │    sim ≥ 0.610  → is_relevant=True（直接接受）                         │
  │    0.500–0.610  → Stage 2                                             │
  │                                                                        │
  │  Stage 2 — LLM 驗證（僅 borderline，約 41%）                          │
  │    new_fast_llm(temperature=0.0)，survey heuristic prompt              │
  │                                                                        │
  │  → PaperRelevanceResult(is_relevant: bool, similarity_score: float)   │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ FilteredPaperEvent × N
                                                      │ collect all N（fan-in）
                                                      │ 過濾 is_relevant=True
                                                      │ sort by similarity_score DESC
                                                      │ keep top NUM_MAX_FINAL_PAPERS=5
                                                      ▼
  ┌─ @step  download_papers ───────────────────────────────────────────────┐
  │  PaperDownloader 4-strategy fallback chain（每篇）：                   │
  │    1. arxiv_api       → arxiv.Client()（3s rate-limit delay）         │
  │    2. arxiv_direct_url → arxiv.org/pdf/{id}（3s delay）               │
  │    3. pyalex_pdf      → Works()[openalex_id].pdf.get()                │
  │    4. openalex_oa_url → open_access.oa_url（browser headers）         │
  │  PDF 命名：ArXiv ID（如 1706.03762.pdf）或 OpenAlex ID（W...pdf）     │
  │  → workflow_artifacts/SummaryGenerationWorkflow/{wid}/papers/         │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ Paper2SummaryDispatcherEvent(papers_path)
                                                      ▼
  ┌─ @step  paper2summary_dispatcher ─────────────────────────────────────┐
  │  for pdf in Path(papers_path).glob("*.pdf"):                          │
  │      ctx.store["n_pdfs"] += 1                                        │
  │      ctx.send_event(Paper2SummaryEvent(pdf_path, ...))  # fan-out   │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ Paper2SummaryEvent × M（fan-out）
                                                      ▼
  ┌─ @step  paper2summary ─── num_workers=NUM_WORKERS_VISION=2 ───────────┐
  │  asyncio.sleep(DELAY_SECONDS_VISION=12.0)  # Gemini RPM=10 保護       │
  │  pdf2images(pdf_path, image_output_dir)    # PDF → PNG per page       │
  │  summary = await summarize_paper_images()  # new_vlm().acomplete()    │
  │  save_summary_as_markdown(summary, path)   # → .md 檔                 │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ SummaryStoredEvent × M
                                                      │ collect all M（fan-in）
                                                      ▼
  ┌─ @step  finish ────────────────────────────────────────────────────────┐
  │  缺少 .md 的項目 → log warning（不 raise，允許部分下載失敗）           │
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
  ┌─ @step  get_summaries  num_workers=1 ─────────────────────────────────┐
  │  for md in Path(file_dir).glob("*.md"):                               │
  │      ctx.store["n_summaries"] = len(markdown_files)                  │
  │      ctx.send_event(SummaryEvent(summary=md.read_text()))  # fan-out │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ SummaryEvent × N（fan-out）
                          ┌───────────────────────────┘
                          │  也接收 OutlineFeedbackEvent（HITL 不通過時的重試路徑）
                          ▼
  ┌─ @step  summary2outline ─── num_workers=NUM_WORKERS_FAST=2 ───────────┐
  │  asyncio.sleep(DELAY_SECONDS_FAST=2.0)  # Groq RPM=60 保護           │
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
  │     （或直接建立新 Future，若無 parent_workflow）                       │
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
  │  new_llm(0.1) + FunctionCallingProgram → SlideOutlineWithLayout × N   │
  │  寫出 slide_outlines.json                                              │
  │  → workflow_artifacts/SlideGenerationWorkflow/{wid}/                   │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ OutlinesWithLayoutEvent
                                                      ▼
  ┌─ @step  slide_gen ────────────────── ReActAgent ───────────────────────┐
  │                                                                        │
  │  ReActAgent(llm=new_llm(0.1), tools=sandbox.to_tool_list()+[layout])  │
  │                                                                        │
  │  ┌─ LlmSandboxToolSpec  (services/sandbox.py) ──────────────────────┐ │
  │  │  create_pool_manager(backend="docker", lang="python",            │ │
  │  │                      libraries=["python-pptx"],                  │ │
  │  │                      config=PoolConfig(min=1, max=2))            │ │
  │  │  需要：/var/run/docker.sock（docker-compose backend volumes）     │ │
  │  │  工具：run_code(code) / list_files() / upload_file(path)         │ │
  │  └──────────────────────────────────────────────────────────────────┘ │
  │                                                                        │
  │  Agent 執行順序（透過 run_react_agent + stream_events）：              │
  │  ① upload_file(slide_template_path)  → /sandbox/template.pptx        │
  │  ② run_code(python-pptx script)      → 生成 paper_summaries.pptx     │
  │  ③ download_all_files_from_session() → workflow_artifacts/            │
  │                                                                        │
  └───────────────────────────────────────────────────┬────────────────────┘
                                                      │ SlideGeneratedEvent(pptx_fpath)
                                                      ▼
  ┌─ @step  validate_slides ─── num_workers=NUM_WORKERS_VISION=2 ─────────┐
  │  asyncio.sleep(DELAY_SECONDS_VISION=12.0)  # Gemini RPM=10 保護       │
  │  pptx2images(pptx_fpath)  → PNG per slide                             │
  │  new_vlm() + MultiModalLLMCompletionProgram                            │
  │  → SlideValidationResult(is_valid: bool, suggestion_to_fix: str)      │
  │                                                                        │
  │  n_retry += 1（存入 ctx.store）                                       │
  └───────────────────────┬────────────────────────────┬───────────────────┘
                          │                            │
                    全部 valid                   有問題
                    或 n_retry ≥ 2               且 n_retry < 2
                          │                            │ SlideValidationEvent
                          ▼                            ▼
             copy_final_slide()           ┌─ @step  modify_slides ───────────────┐
             → final.pptx / final.pdf     │  ReActAgent（同 sandbox 工具）        │
             StopEvent(pptx_path)         │  修改現有 pptx → _v{n_retry}.pptx    │
                                          └──────────────────┬────────────────────┘
                                                             │ SlideGeneratedEvent
                                                             └──► [validate_slides]（loop）
```

> `copy_final_slide()` 不是獨立 `@step`，是 `validate_slides` 內部呼叫的 method。

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
          │                loop = wf.user_input_future.get_loop()   │
          │◄─ future.set_result ─────── loop.call_soon_threadsafe(  │
          │                             future.set_result, input)   │
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
  │   ├── papers/              ← download_papers：PDF（以 ArXiv ID 或 OpenAlex ID 命名）
  │   └── papers_images/       ← paper2summary：PNG + .md 摘要（傳入 SlideGen）
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
wf = SummaryAndSlideGenerationWorkflow(
    summary_gen_wf=SummaryGenerationDummyWorkflow(wid=workflow_id, timeout=800),
    slide_gen_wf=SlideGenerationWorkflow(wid=workflow_id, timeout=1200),
    wid=workflow_id,
    timeout=2000,
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
