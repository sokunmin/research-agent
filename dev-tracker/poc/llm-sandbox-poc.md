# PoC: llm-sandbox

## 狀態
- 目前狀態：`approved`
- 建立時間：2026-03-11
- 最後更新：2026-03-11
- 確認時間：2026-03-11
- PoC 程式碼：`poc/llm-sandbox/`
- 來源 spec：無（自然語言輸入）

## 核心驗證問題
1. Q1：llm-sandbox 能否在本機 Docker 正常啟動 Python container 並執行程式？
2. Q2：copy_to_runtime / copy_from_runtime 能否正確上傳/下載檔案？
3. Q3：能否在 container 安裝 python-pptx 並操作 .pptx？
4. Q4：能否包裝成 LlamaIndex FunctionTool 讓 ReActAgent 呼叫（使用 pool manager）？
5. Q5：能否用 ThreadPoolExecutor + 共用 pool 並行生成 pptx & docx，各自取出 artifacts？
6. Q6：llama-index-core 0.14.x 的 ReActAgent step-by-step API（create_task/run_step/finalize_response）是否仍存在？若已移除，替代方案為何？

## PoC 邊界（不做的事）
- 不整合進 slide_gen.py
- 不完整的 slide 生成邏輯
- 不建立 LlamaIndex Workflow（只用 ReActAgent）
- container 安全性不在此範圍

## 技術選擇
- sandbox：llm-sandbox[docker]（Docker backend）
- 主類別：ArtifactSandboxSession（推薦）
- Q4 pool：create_pool_manager + ArtifactSandboxSession(pool=pool)
- Q5 並行：ThreadPoolExecutor(max_workers=2) + shared pool(min_pool_size=2)
- LLM：gemini/gemini-2.5-flash via LiteLLM
- agent framework：LlamaIndex ReActAgent + FunctionTool
- env：micromamba py3.12

## Python 環境
- micromamba env：`py3.12`
- py3.12 已有（不需重裝）：litellm==1.82.0, llama-index-core==0.14.15, python-dotenv==1.2.2
- 新增的 packages：
  - llm-sandbox[docker]（pip）
  - python-pptx（conda-forge）
  - python-docx（conda-forge）← Q5 新增
  - llama-index-llms-litellm（pip）

## 當前進度
- 停在：Step 9（等待使用者確認）
- 已完成：全部 Q1~Q5 PASS
- 下一步：使用者確認後更新狀態為 approved
- 遇到的問題：
  - llama-index-core 0.14.x API 重大變更：`ReActAgent.from_tools()` 不存在、`agent.chat()` 改為 `await agent.run()`、import 路徑改為 `llama_index.core.agent.workflow`

## 驗證結果
- Q1：✅ — `ArtifactSandboxSession` 成功啟動 Docker container，執行 `print("hello from sandbox")`，exit_code=0
- Q2：✅ — `copy_to_runtime` / `copy_from_runtime` 正確上傳/下載，內容完全吻合
- Q3：✅ — container 內安裝 python-pptx，建立 .pptx（title="Hello PoC"），下載後本機驗證通過
- Q4：✅ — `create_pool_manager` + `ReActAgent`（0.14.x 新 API）+ `FunctionTool` 端到端成功，agent 自主建立並下載 hello.pptx
- Q5：✅ — PPTX 和 DOCX 並行生成，wall-clock ~26s（非串行 ~52s），各自 filesystem 完全隔離，plots=0（enable_plotting=False 符合預期）
- Q6：✅ — `create_task`/`run_step`/`finalize_response` 全部已從 0.14.x 移除；`update_prompts()` 仍存在但簽名不同（`{"react_header": PromptTemplate(...)}`）；streaming 替代方案 `handler = agent.run(...) → stream_events() → await handler` 端到端驗證通過，觀察到 AgentStream/ToolCall/ToolCallResult/AgentOutput 等事件

## 整合建議

### API 對應關係（AzureCodeInterpreterToolSpec → llm-sandbox）
| AzureCodeInterpreterToolSpec | llm-sandbox 等效 |
|---|---|
| `AzureCodeInterpreterToolSpec(pool_management_endpoint=...)` | `create_pool_manager(backend="docker", lang="python", libraries=[...])` |
| `to_tool_list()` | 手動建立 `[FunctionTool.from_defaults(fn=...)]` list |
| `code_interpreter(code)` | `session.run(code)` → `result.stdout` |
| `upload_file(local, remote)` | `session.copy_to_runtime(local, remote)` |
| `list_files(dir)` | `session.run("import os; print(os.listdir(dir))")` → `result.stdout` |
| `download_file_to_local(remote, local)` | `session.copy_from_runtime(remote, local)` |

### llama-index-core 0.14.x API 重大變更（整合時必知）
| 舊 API (pre-0.14) | 新 API (0.14.x) |
|---|---|
| `from llama_index.core.agent import ReActAgent` | `from llama_index.core.agent.workflow import ReActAgent` |
| `ReActAgent.from_tools(tools, llm=llm)` | `ReActAgent(tools=tools, llm=llm)` |
| `agent.chat("...")` — 同步 | `await agent.run("...")` — async |
| `max_iterations=20` | `timeout=120`（秒） |
| `agent.create_task("...")` | 不存在，整個 step loop 改為 `handler = agent.run(...)` |
| `agent.run_step(task_id)` | 不存在，改為 `async for ev in handler.stream_events()` |
| `agent.finalize_response(task_id)` | 不存在，改為 `await handler` |
| `agent.update_prompts({"system_prompt": p})` | 改為 `agent.update_prompts({"react_header": PromptTemplate(...)})` |

### 整合到 slide_gen.py 的注意事項
1. **Pool 取代 Azure session pool**：
   `create_pool_manager(libraries=["python-pptx"])` 建立後，傳給
   `SlideGenerationWorkflow.__init__`，整個 workflow 共用一個 pool。
   workflow 結束時 `pool.close()`。

2. **Session 生命週期**：pool 模式下每次 tool call 可獨立 `with ArtifactSandboxSession(pool=pool) as session`，
   container 歸還 pool 後不銷毀，filesystem 狀態持續存在。

3. **套件預裝**：`create_pool_manager(libraries=["python-pptx"])` 預裝，
   避免每次 session 重裝（每次重裝約 26 秒）。

4. **result 屬性**：`result.stdout`、`result.stderr`、`result.exit_code`（不是 `.text`）。
   `result.plots`（ArtifactSandboxSession 專屬）可捕捉 matplotlib 圖表。

5. **本機 Docker 依賴**：需要 Docker Desktop 運行，無 Azure 費用，但需本機資源。

6. **`local_save_path` 等效**：`copy_from_runtime(remote, local_save_path/filename)` 自行指定。

8. **`run_react_agent()` 改寫方案**（Q6 驗證）：

   舊式 step-by-step loop（slide_gen.py 現有寫法）：
   ```python
   # ❌ 0.14.x 已完全移除
   task = agent.create_task("...")
   step_output = agent.run_step(task.task_id)
   while not step_output.is_last:
       step_output = agent.run_step(task.task_id)
   response = agent.finalize_response(task.task_id)
   agent.update_prompts({"system_prompt": PromptTemplate(...)})
   ```

   新式 event streaming（0.14.x 替代寫法）：
   ```python
   # ✅ 0.14.x 正確寫法
   from llama_index.core.agent.workflow import (
       ReActAgent, AgentStream, ToolCall, ToolCallResult
   )
   from llama_index.core.workflow import Context
   from llama_index.core import PromptTemplate

   agent = ReActAgent(tools=tools, llm=llm, verbose=True, timeout=300)
   agent.update_prompts({"react_header": PromptTemplate("...your system prompt...")})
   ctx = Context(agent)  # 多輪對話保留 context

   async def run_agent(prompt: str):
       handler = agent.run(prompt, ctx=ctx)  # 不先 await！
       async for ev in handler.stream_events():
           if isinstance(ev, AgentStream) and ev.delta:
               yield ev.delta  # streaming token
           elif isinstance(ev, ToolCall):
               print(f"[Tool] {ev.tool_name}({ev.tool_kwargs})")
           elif isinstance(ev, ToolCallResult):
               print(f"[Result] {ev.tool_output}")
       return await handler  # 最終結果

   # 同步腳本中：asyncio.run(run_agent("..."))
   ```

7. **並行執行**（Q5 驗證）：
   - llm-sandbox **無 async API**，不可用 asyncio。
   - 官方唯一並行模式：`ThreadPoolExecutor`（thread-safe pool 加持）。
   - 若未來 slide_gen.py 需同時生成多份文件，可用 `min_pool_size=N` 預熱 N 個 container 並行執行。
   - 每個 container 的 filesystem 完全隔離，無競爭條件。

## 狀態歷程
- 2026-03-11：建立，in-progress
- 2026-03-11：Q1~Q5 全部 PASS，等待使用者確認
- 2026-03-11：使用者確認，approved
- 2026-03-11：新增 Q6（step-by-step API 可用性），PASS，更新整合建議
