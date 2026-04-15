---
## [2026-04-15] `FunctionCallingProgram` + Ollama `qwen3.5:2b` + 巢狀 array schema（`List[ParagraphItem]`）輸出 `{"argument_name": ..., "argument_value": ...}` 包裝，Pydantic validation fail `[版本: litellm 1.82.0 / 模型: qwen3.5:2b]`
原因：`SlideOutline.content` 從 `str` 改為 `List[ParagraphItem]`（巢狀 array of objects）後，`qwen3.5:2b` 的 function calling 無法正確處理複雜 nested schema，改以 `{"argument_name": "content", "argument_value": "[...]"}` 包裝格式輸出，導致 `title` 與 `content` 兩個 required fields 皆 missing。注意：同一模型在 `content: str`（簡單 schema）時 function calling 正常；schema 變複雜才觸發此問題，與 [2026-03-28] 的 `{"properties": {...}}` 格式是同類問題的不同表現。
修正：`slide_gen.py` 的 `summary2outline` step 將 `_fc_program`（`FunctionCallingProgram`）換為 `_text_program`（`LLMTextCompletionProgram`）；`LLMTextCompletionProgram` 將 JSON schema 嵌入 prompt text，不走 tool calling API，對任何 LLM 均相容。`_text_program` 預設使用 `_smart_llm`，比原本的 `_fast_llm` 慢，可視需求明確傳入 `llm=self._fast_llm`（須先確認該 model 能正確解析巢狀 schema）。
結論：Ollama 本地模型的 function calling 對簡單 schema（純 `str`/`int` fields）尚可用；含 nested array of objects 的 schema 請一律改用 `LLMTextCompletionProgram`。
---
## [2026-04-13] PPTX placeholder 的 `name` 欄位無語意，不可用字串比對識別用途 `[通用]`
原因：`placeholder.name` 是 template 工具的 display label（如 `"Google Shape;10;p36"`），命名慣例因工具而異，不含 "Title"/"Body" 等語意，字串比對在非標準 template 上失效。
修正：改用 `placeholder.placeholder_format.type`（`PP_PLACEHOLDER` enum，`TITLE=1` / `BODY=2`）過濾，此為 OpenXML 規格定義，跨所有 PPTX template 通用。
---
## [2026-04-09] pptx2images — MuPDF "No common ancestor in structure tree" 警告 `[通用]`
根本原因（版本升級問題，原作者程式碼本身沒有錯）：
1. LibreOffice 25.2.3（Debian 13）的 bug：Impress PDF export 生成格式不合規的 Tagged PDF，`/StructTreeRoot /K` 直接包含 16 個跨不同 page 的 structure elements，缺少共同根節點，違反 PDF/UA spec。MuPDF 每個 page 驗證一次，5 張投影片產生 5 次 error 後 fallback 到 content stream rendering。LibreOffice 7.4（Debian 12）無此 bug。
2. Dockerfile 未鎖版本：`FROM python:3.12-slim` 無 digest pinning，底層 Debian 從 12 (Bookworm) 升至 13 (Trixie)，LibreOffice 從 7.4.7 跳至 25.2.3，引入此 bug。
影響：Non-blocking warning。Smoke test 確認 PNG 輸出 byte-identical，Tagged PDF 結構樹僅用於 accessibility，不影響 rasterization。
修正方法：修改 `utils/file_processing.py` 的 `pptx2pdf()`，在 LibreOffice 指令加 JSON filter string 停用 Tagged PDF，從根本消除問題：
  修改前：`"--convert-to", "pdf",`
  修改後：`"--convert-to", 'pdf:impress_pdf_Export:{"UseTaggedPDF":{"type":"boolean","value":"false"}}',`
  說明：JSON filter string 語法非官方文件記載，但為 Gotenberg/unoconv/JODConverter 廣泛採用的 de-facto 標準，LibreOffice 7.4 與 25.x 均相容。UNO Python API 雖更標準但在 Docker subprocess 架構下複雜度過高。
詳細分析：`dev-tracker/poc/problem2_mupdf_analysis.md`、`dev-tracker/poc/problem2_libreoffice_api_research.md`
---
## [2026-04-09] Frontend — workflow error 後 NoneType 警告 `[通用]`
原因：Backend workflow 在 validate_slides crash 後，最後一個 event 為 `None`；Frontend 的 workflow info 格式化函式未對 `None` 做防守性檢查，直接呼叫 `.get()` 導致 `'NoneType' object has no attribute 'get'`。
修正方法：兩層修正並行實施。(1) **Backend 根本原因**：`main.py` 的 event_generator() 在 workflow crash 時發送的 error event 格式為 `{"event": "error", "message": "..."}` — 缺少 `event_content` key，不符合標準 `WorkflowStreamingEvent` 結構；改為以 `WorkflowStreamingEvent(event_type="server_message", event_sender="system", event_content={"message": error_message})` 格式發送，確保所有 event 都有 `event_content`。(2) **Frontend 防禦**：`slide_generation_page.py` 的 `format_workflow_info()` 第 89 行 `event_content.get('message')` 在取得 `event_content` 之前加 `None` guard：`if event_content is None: return json.dumps(info_json)`，避免任何非標準 event 格式造成 AttributeError。
---
## [2026-04-09] Agent 產生無效 python-pptx API 呼叫 — add_slide() 不接受 position argument `[通用]`
原因：`SLIDE_GEN_PMT` 的 code pattern 示範了標準 slide 建立，但未明確說明 `add_slide()` 只接受 `SlideLayout` 一個參數。Agent 根據 prompt 要求「若缺少 front/thank-you slide 需補上」，自行推測出不存在的 `prs.slides.add_slide(layout, 0)` API（position argument），此次因條件未觸發未爆炸，但屬潛在 runtime error。
修正方法：兩層修正。(1) **立即修（prompt 層）**：`SLIDE_GEN_PMT` 的模糊指示 `"If there is no front page or 'thank you' slide, add them using the appropriate layout"` 替換為明確的 pre/post loop 模式並加 CRITICAL 禁止語句：在 loop 之前先 `add_slide()` 封面（使得它成為第一張），在 loop 之後再 `add_slide()` 感謝頁；並明確標注 `prs.slides.add_slide(layout, 0)  # WRONG — raises TypeError`，python-pptx 無任何 insert-at-position API（context7 查詢確認，`Slides` 只有 `add_slide`、無 `insert_slide`/`move_slide`；`_sldIdLst` 為 private XML，無公開 API）。(2) **長期根本解（workflow 層，Option D）**：在 `slide_gen.py` 的 `outlines_with_layout` 步驟，Python code 直接向 `slides_w_layout` list 的首尾注入封面與感謝頁的 `SlideOutlineWithLayout` 物件（layout 名稱與 placeholder index 從 `self.pptx_spec.all_layout` 動態查詢），使 JSON 已包含所有 slides；`SLIDE_GEN_PMT` 改為 `"The JSON already contains ALL slides in order. Loop through EVERY item — do NOT add extra slides."`，完全消除 LLM 的條件判斷與 hallucination 空間。
---
## [2026-03-31] `template-en.pptx` 含三個中文 layout 名稱（項目符號、照片-一頁三張、空白），英文模型於 layout selection 時視而不見 `[環境: template-en.pptx 初始版本]`
原因：template 命名暗示全英文，但三個 layout 仍為中文，英文 LLM 無法將這些名稱與 slide 語意對應，實驗中從未被選中，導致準確率被低估。
修正：以 python-pptx 修改 XML 將三個 layout 重命名：項目符號 → BULLET_LIST、照片-一頁三張 → THREE_PHOTO、空白 → BLANK；實驗 prompt 與 expected set 同步更新。
---
## [2026-03-31] `SlideOutlineWithLayout` schema 強制 `idx_title_placeholder` / `idx_content_placeholder` 為必填 `str`，導致 THREE_PHOTO、FULL_PHOTO、BLANK 永遠 Pydantic validation fail `[通用]`
原因：這三個 layout 在 template 裡沒有 title/content placeholder，LLM 即使正確選出 layout name，仍因無法填入有效 idx 而輸出 null，Pydantic 拒絕 null → FAIL，appropriate rate 被低估。
修正：將 schema 的兩個 idx 欄位改為 `Optional[str] = None`，並同步更新 `slide_gen` agent 處理 idx 為 None 的情況。
---
## [2026-03-28] `FunctionCallingProgram` + Ollama 模型（via LiteLLM）回傳 `{"properties": {...}}` 包裝，Pydantic 5 fields missing，success rate 0% `[版本: litellm 1.82.0 + llama-index-llms-litellm 0.6.3 / 模型: gemma3:4b, qwen3.5:4b]`
原因：Ollama 模型在 function calling 呼叫中將 JSON Schema 的 `"properties"` 結構原樣輸出（schema 定義層），而非填入實際值（arguments 層）；即使透過 `litellm.register_model()` 宣告 `supports_function_calling=True` 使呼叫能到達 API，模型行為本身仍輸出錯誤格式，導致 LlamaIndex Pydantic 解析時所有 required fields 皆 missing。
修正：`slide_gen.py` 的 `outlines_with_layout` step 將 `FunctionCallingProgram` 換為 `LLMTextCompletionProgram`（不走 tool/function calling API，改走 prompt 內嵌 JSON schema 路徑，對任何 LLM 均相容）；若僅使用 Ollama，可改在 `LiteLLM` 的 `additional_kwargs` 傳入 `{"format": SlideOutlineWithLayout.model_json_schema()}`（Ollama server-side constrained generation），兩者均可達 100% success rate；cloud provider（Groq、Gemini）的 `FunctionCallingProgram` 呼叫不受影響，可透過 `config.py` flag 區分路徑。
---
## [2026-03-27] `ArtifactSandboxSession` init noise 污染 LLM tool observations，ReActAgent 無限 loop `[通用: llm-sandbox + ReActAgent]`
原因：`ArtifactSandboxSession` 預設 `enable_plotting=True`，在每個 `session.run()` 的 stdout 前插入 "Python plot detection setup complete\n"；同時每次 `run()` 都在 `/sandbox/` 建立 UUID 命名的 `.py` 執行檔但從不清除，導致 `list_files` 回傳大量 UUID 殘檔。兩者共同污染 LLM tool observations，ReActAgent 誤判環境狀態後無限呼叫 `list_files`。
修正：(1) `run_code()` 與 `list_files()` 中的 `ArtifactSandboxSession` 呼叫均加 `enable_plotting=False`；(2) 在 `list_files()` 加 `_SANDBOX_ARTIFACT_RE = re.compile(r'^[0-9a-f]{32}\.[a-z]+$')` 過濾器，從結果中移除所有 UUID 執行產物。驗證：`run_code` 回傳乾淨 stdout；空 sandbox 時 `list_files_str` 回傳 `'(no files in /sandbox)'`。
影響檔案：`backend/services/sandbox.py`
---
## [2026-03-27] SSE 格式不符 W3C spec 且 `"Reasoning: "` prefix 重複拼接，Streamlit 顯示亂碼 `[通用: FastAPI SSE + Streamlit]`
原因：`run_react_agent()` 對每個 streaming token delta 都拼接 `"Reasoning: "` prefix，前端收到後 concatenate 成 "Reasoning: ThoughtReasoning: :Reasoning:  I..." 亂碼；同時 SSE yield 格式為裸 JSON 字串，不符 W3C SSE `data: ...\n\n` 規格，與 Vercel AI SDK 不相容。
修正：(1) `main.py` 所有 SSE yield 改為 `f"data: {msg_str}\n\n"`；(2) `slide_gen.py` 移除 `"Reasoning: "` prefix，改用 `_emit_message()` helper 直接傳遞 `ev.delta`；(3) `slide_generation_page.py` SSE 解析改為先 strip `data:` prefix 再 JSON.loads。戰略理由：對齊 W3C SSE 規格為未來遷移至 Vercel AI SDK 鋪路（Vercel AI SDK 是唯一同時支援 HITL 與自訂 workflow progress event 的前端選項）。
影響檔案：`backend/main.py`、`backend/agent_workflows/slide_gen.py`、`frontend/pages/slide_generation_page.py`
---
## [2026-03-27] Ollama 本地 LLM token-by-token streaming 在 Streamlit st.status 造成逐字顯示 `[環境: Ollama local LLM + Streamlit ≥1.55]`
原因：Ollama 以單 token 為單位 streaming（`AgentStream.delta` 每次一個詞），Streamlit 升級後 `st.expander`（收合）換成 `st.status(expanded=True)`，每個 token 各佔一行並帶分隔線，數百行暴露給使用者；cloud LLM（Gemini/Groq）以詞組為單位送 chunk 故舊版無此問題。
修正：frontend `get_stream_data()` 將 `event_sender == "react_agent"` 的事件改送 `("reasoning", msg)` 至 queue；`process_messages()` 以 `+=` concatenate 到 `current_reasoning`（而非 append 至 `received_lines`）；`workflow_display()` 新增獨立 `st.code` 區塊顯示累積 reasoning，每 2s rerun 時呈現完整句子而非逐字。
---
## [2026-03-26] `run_subworkflow` 轉發 StopEvent 至 parent context，main.py 無 guard 導致 SSE 連線中斷 `[通用]`
原因：`handler.stream_events()` 設計上會 yield `StopEvent` 作為終止信號；`run_subworkflow` 無條件 `ctx.write_event_to_stream(event)` 將其注入 parent stream，`main.py` 又無條件存取 `ev.msg`（`StopEvent` 無此欄位），拋出 `AttributeError`，SSE generator 進入 except block → workflow 從 dict 移除，前端連線中斷
修正：`run_subworkflow` 加 `if isinstance(event, StopEvent): continue` 過濾非 user-facing event；`main.py` event loop 加 `hasattr(ev, 'msg')` guard，避免單一 event 異常炸掉整條 SSE 連線
---
## [2026-03-26] Ollama qwen3.5 觸發 `FunctionCallingProgram` "does not support function calling API" `[版本: litellm 1.82.0 + llama-index-llms-litellm 0.6.3]`
原因：LiteLLM 以 `/api/show` 回傳的 Modelfile template 是否含 `"tools"` 字串判斷 function calling 支援；qwen3.5 的 template 只有 `{{ .Prompt }}`，不含 `tools`，導致 `is_function_calling_model=False`，LlamaIndex 的 `FunctionCallingProgram.from_defaults()` 在發 API 前就 raise。
修正：`model_factory.py` 的 `_build()` 呼叫 `_register_ollama_function_calling()`，用 `OllamaModelInfo().get_models()` 動態列出所有本地 Ollama models，透過 `litellm.register_model()` 顯式宣告 `supports_function_calling=True`；過濾掉已有 `ollama/` prefix 的 fallback entries 避免 offline 時雙重 prefix。
---
## [2026-03-26] `OllamaModelInfo.get_models()` Ollama offline 時靜默回傳 `['ollama/llama2']` 而非空 list `[通用]`
原因：LiteLLM 刻意設計 graceful degradation，`/api/tags` 失敗時 fallback 到 `litellm.models_by_provider["ollama"]`（hardcoded `["llama2"]`）並加 `ollama/` prefix；不 raise exception，有 unit test 驗證此行為。
修正：呼叫後過濾掉已帶 `ollama/` prefix 的項目（`if not name.startswith("ollama/")`），offline 時 register 空 dict，避免注入錯誤的 `ollama/ollama/llama2`。
---
## [2026-03-26] `LiteLLMMultiModal` AttributeError: rate_limiter，llama-index-core 版本漂移所致 `[版本: llama-index-core>=0.14.19]`
原因：`llms/callbacks.py` wrapper 在 0.14.19 新增 `if _self.rate_limiter is not None:`，同時套用到 `BaseLLM`（有此 field）和 `MultiModalLLM`（無此 field）；Dockerfile 缺 `poetry.lock`，docker build 自由解析到 0.14.19，本地 lock 鎖在 0.14.15，環境不一致使問題只在 docker 觸發。
修正：`LiteLLMMultiModal` 加 `rate_limiter: Optional[Any] = Field(default=None, exclude=True)`；Dockerfile 改為 `COPY pyproject.toml poetry.lock /app/` 鎖定版本。
---
## [2026-03-26] litellm 在 mock 攔截前嘗試 fetch 外部 https:// image URL，導致 pytest hang `[通用: litellm + unittest.mock]`
原因：`patch("services.multimodal.litellm.completion")` 對純文字 call 有效，但訊息含 `image_url` 且為外部 URL 時，litellm 內部先 fetch 該 URL，此行為發生在 mock 接手之前；`example.com` 無回應導致 test 無限 hang。
修正：測試中一律改用 image bytes（`image=raw_bytes, image_mimetype="image/jpeg"`），完全不使用外部 URL；fixture 圖片放 `tests/fixtures/`，一次載入為 `_TEST_IMAGE_BYTES` 共用。
---
## [2026-03-26] config.py 必填欄位（MLFLOW_TRACKING_URI 等）無 default，本機測試缺值直接 ValidationError `[環境: 無 docker-compose]`
原因：`MLFLOW_TRACKING_URI`、`WORKFLOW_ARTIFACTS_ROOT`、`SLIDE_TEMPLATE_PATH` 由 docker-compose 環境變數注入，無 default；本機跑 pytest 時 `.env` 未包含這些欄位，`Settings()` 在 import 時直接拋 `ValidationError`，所有 import 該模組的 test 全部 collection error。
修正：在 `.env` 加入本機 stub 值（`MLFLOW_TRACKING_URI=http://localhost:8080` 等），或在 `conftest.py` 以 `os.environ.setdefault` 補設。
---
## [2026-03-26] pydantic BaseSettings v2 對 .env 裡已移除的欄位拋 `extra_forbidden` `[版本: pydantic-settings>=2.0]`
原因：config.py 移除舊欄位（如 `TAVILY_MAX_RESULTS`、`NUM_MAX_CITING_PAPERS`）後，`.env` 若仍保留這些 key，pydantic v2 預設行為為拒絕並報 `Extra inputs are not permitted`；錯誤訊息不直觀，容易誤判為欄位格式問題。
修正：每次移除 config 欄位後，同步清理 `.env` 中對應的舊 key；`.env.example` 可作為 canonical reference 確認哪些 key 仍有效。
---
## [2026-03-20] pyalex `work.get("abstract")` 永遠回傳 None，需從 `abstract_inverted_index` 手動重建 `[通用]`
原因：OpenAlex API 以倒排索引格式儲存 abstract（`{word: [pos, ...]}`），`abstract` 欄位本身為空；pyalex 文件所述的自動重建在 list/singleton 呼叫中均未生效。
修正：從 `work["abstract_inverted_index"]` 反轉為 `{pos: word}`，按 key 排序後 join 成純文字；約 20% paper 在 OpenAlex 本身無 abstract（資料源限制，非 API 問題）。
---
## [2026-03-19] pyalex 預設 max_retries=0，similar() endpoint 偶發 HTTP 500 直接 crash `[通用]`
原因：pyalex 預設 `max_retries=0`，similar() 語義搜尋 endpoint 偶發 HTTP 500，直接 raise 不重試
修正：config 區設定 `pyalex.config.max_retries = 5` 與 `pyalex.config.retry_backoff_factor = 0.5`
---
## [2026-03-19] OpenAlex `work["ids"]` 不含 ArXiv ID，必須從 `locations` 解析 `[通用: pyalex]`
原因：OpenAlex 設計上 ArXiv 不列入 `ids` 欄位，只出現在 `locations[*]["landing_page_url"]`（如 `http://arxiv.org/abs/1706.03762`）。
修正：掃描 `work["locations"]`，找含 `"arxiv.org"` 的 `landing_page_url`，切最後一段取 ID；`pdf_url` 缺席時用 `f"https://arxiv.org/pdf/{arxiv_id}"` 構造。
---
## [2026-03-19] OpenAlex title search 拿到無 ArXiv 的出版版，ArXiv preprint 是未合併的獨立 record `[通用: pyalex title search]`
原因：同一篇論文的 publisher 版（如 AAAI）與 ArXiv preprint 有時是兩個未 dedup 的 OpenAlex record；`search_filter(title=).get(per_page=1)` 優先回傳引用數高的出版版，其 `locations` 無 `arxiv.org`，preprint record 被忽略。
修正：改為 `get(per_page=3)`，逐一掃描每個 record 的 `locations`，優先回傳含 `arxiv.org` 的 record；全無時 fallback 回第一筆。
---
## [2026-03-19] 學術出版商（AAAI OJS 等）對 `python-requests` User-Agent 回 403 `[通用]`
原因：AAAI OJS 伺服器黑名單封鎖 `python-requests/x.x.x` UA；`requests.get()` 預設不帶 browser UA，伺服器直接拒絕，curl 同 URL 無此問題。
修正：統一定義 `_BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 ... Chrome/120.0.0.0 ..."}` 並套用至所有 `requests.get(url, headers=_BROWSER_HEADERS)`。
---
## [2026-03-16] Breaking API change 修改時未全面搜尋 codebase，導致同一問題多處重複出現 `[通用]`
原因：修改 `run_subworkflow` 的 `stream_events()` 時，只修了當前報錯的地方，未搜尋 `main.py` 等其他使用相同舊 API 的位置，導致下次測試又出現相同錯誤。
修正：任何 breaking API change，先用 Grep 全面搜尋 codebase 所有使用位置，再用 context7 查最新 API，列出完整影響清單後一次修改完畢。
---
## [2026-03-16] llama-index-core 0.14.x `@step(pass_context=True)` 移除 `[版本: llama-index-core>=0.13.0]`
原因：0.14.x 的 `ctx: Context` 透過 type annotation 自動注入，`pass_context=True` 參數不再需要且已移除，使用會造成 `unexpected keyword argument`。
修正：所有 `@step(pass_context=True)` 改為 `@step`；有 `num_workers` 的改為 `@step(num_workers=N)`。
---
## [2026-03-16] llama-index-core 0.14.x `self.send_event()` 改為 `ctx.send_event()` `[版本: llama-index-core>=0.13.0]`
原因：0.14.x 將事件發送從 Workflow 實例方法改為 Context 方法，`self.send_event(ev)` 不再存在（會靜默失敗或 AttributeError）。
修正：所有 step 內的 `self.send_event(ev)` 改為 `ctx.send_event(ev)`。
---
## [2026-03-16] llama-index-core 0.14.x `Context.data` dict 完全移除 `[版本: llama-index-core>=0.13.0]`
原因：0.14.x 將 `ctx.data` dict 改為 async store API，舊的 `ctx.data["key"]` 拋出 `AttributeError: 'Context' object has no attribute 'data'`。
修正：寫入改為 `async with ctx.store.edit_state() as state: state["key"] = value`；讀取改為 `await ctx.store.get("key")`；concurrent step 的累加用 `edit_state()` 保證 atomic。
---
## [2026-03-16] llama-index-core 0.14.x 移除 `Workflow.add_workflows()` `[版本: llama-index-core>=0.13.0]`
原因：0.13.x 起 sub-workflow 注入改為 `Annotated[T, Resource(factory)]` DI 模式，`add_workflows()` 方法完全移除，呼叫時拋出 `AttributeError: object has no attribute 'add_workflows'`。
修正：改用 constructor injection——在 orchestrator `__init__` 接收 sub-workflow 實例為參數，存成 `self.xxx_wf`；`@step` 簽名移除 sub-workflow 參數，改用 `self.xxx_wf`；`main.py` 改為在建構時傳入。
---
## [2026-03-16] llama-index-core 0.14.x `stream_events()` 從 Workflow 實例移至 Handler `[版本: llama-index-core>=0.13.0]`
原因：`Workflow.run()` 改為同步回傳 `Handler` 物件，`stream_events()` 移到 Handler 上，Workflow 實例本身不再有此方法，呼叫 `sub_wf.stream_events()` 拋出 `AttributeError`。
修正（Approach A）：在 `run_subworkflow` 中直接呼叫 `Workflow.run(sub_wf, **kwargs)` 取得 Handler，改用 `handler.stream_events()` 與 `await handler`；並手動補設 `sub_wf.loop = asyncio.get_running_loop()`，因為繞過了 `HumanInTheLoopWorkflow.run()`。完整 Approach B 重構方案見 `BACKUP_PLAN.md`。
---
## [2026-03-16] `HumanInTheLoopWorkflow.run()` 為 `async def`，內部 `await Handler` 導致外部無法取得 Handler `[版本: llama-index-core>=0.13.0]`
原因：`HumanInTheLoopWorkflow.run()` override 為 `async def`，內部執行 `result = await super().run()`，將 `Workflow.run()` 回傳的 Handler 立即消化並回傳最終結果；呼叫端拿到 coroutine 而非 Handler，`handler.stream_events()` 無從取得。`SlideGenerationWorkflow` 的 HITL 步驟另依賴 `self.loop`（`self.loop.create_future()`），繞過此方法需手動補設。
修正：Approach A 繞過 `HumanInTheLoopWorkflow.run()`，直接呼叫 `Workflow.run(sub_wf)`；Approach B 將 `run()` 改為 sync def 並加 `MLflowAwareHandler` wrapper，詳見 `BACKUP_PLAN.md`。
---
## [2026-03-16] MLflow v3 security middleware 拒絕 Docker 容器間 Host header，回傳 403 `[版本: mlflow>=3.x]`
原因：MLflow v3 新增 security middleware，預設只允許 `localhost` 作為 Host header；backend 容器以 `http://mlflow:8080` 為 tracking URI，Host header 為 `mlflow:8080`，被 middleware 拒絕，log 顯示 `Rejected request with invalid Host header: mlflow:8080`，MLflow API 回傳 403。
修正：在 `docker-compose.yml` 的 mlflow `command` 加入 `--allowed-hosts mlflow,localhost,127.0.0.1`，允許 Docker 內部網路容器名稱作為合法 Host。
---
## [2026-03-16] LiteLLM model 字串必須帶 `{provider}/{model}` 前綴，否則報 LLM Provider NOT provided `[通用]`
原因：LiteLLM 以 model 字串的第一段作為 provider 識別（如 `groq/`、`gemini/`、`openrouter/`），若只寫 `model_name`（如 `qwen/qwen3-32b`，其中 `qwen` 不是合法 provider）則拋出 `BadRequestError: LLM Provider NOT provided`；唯一例外是 OpenAI（預設 provider）。
修正：所有 model 字串改為 `{provider}/{model}` 格式（如 `groq/moonshotai/kimi-k2-instruct`）；可用 `litellm.provider_list` 確認合法 provider 名稱。
---
## [2026-03-15] `draw_all_possible_flows` 從 `llama_index.core.workflow` 移至 `llama_index.utils.workflow` `[版本: llama-index-workflows>=2.9.0]`
原因：llama-index-workflows 2.9.0 起，`drawing.py` 中的舊函數 raise error，且 `llama_index.core.workflow.__init__.py` 不再 export `draw_all_possible_flows`，造成頂層 import 時 `ImportError`。
修正：從 `[tool.poetry.dependencies]` 新增 `llama-index-utils-workflow = ">=0.9.5"`；將 `draw_all_possible_flows` 的 import 從模組頂層移入 `if __name__ == "__main__":` 區塊，改用 `from llama_index.utils.workflow import draw_all_possible_flows`。
影響檔案：`backend/agent_workflows/summarize_and_generate_slides.py`、`backend/agent_workflows/summary_gen.py`。

## [2026-03-15] `docker-compose build` 通過不代表 backend runtime import 正常 `[驗收流程盲點]`
原因：`docker-compose build` 只建立 image（執行 Dockerfile），不執行 Python import。Backend 的 `ImportError` 只會在 container 啟動執行 `uvicorn main:app` 時才觸發。若 `.env` 未設定導致 backend 也 crash，容易誤判為「env 問題」而忽略真正的 `ImportError`。
修正：驗收流程改為 `docker-compose up --build`（全服務啟動），確認 backend log 出現 `Uvicorn running` 且無 `ImportError`，再以 `curl http://localhost:8000/` 驗證健康狀態。不可只跑 `docker-compose build`。

---
## [2026-03-12] LlamaIndex `Workflow` base class 無法直接實例化 — `WorkflowConfigurationError: no @step accepts StartEvent` `[版本: llama-index-workflows>=2.x]`
原因：`Workflow.__init__` 驗證至少要有一個 `@step` 接受 `StartEvent`，直接實例化 base class（如 `HumanInTheLoopWorkflow`）沒有任何 step，立即拋出 `WorkflowConfigurationError`。
修正：測試中建立 concrete subclass，加入 dummy `@step async def handle_start(self, ev: StartEvent) -> StopEvent`，再實例化 subclass 執行測試。
---
## [2026-03-12] macOS Python pytest 執行時 `ssl.SSLCertVerificationError` — HTTPS 下載失敗 `[環境: macOS + python.org Python + poetry venv]`
原因：python.org 安裝的 Python 不連結 macOS Keychain 憑證，poetry venv 執行時 `SSL_CERT_FILE` 為空，`urllib` 無法驗證任何 HTTPS 憑證（包含 arxiv.org）。
修正：在 `tests/conftest.py` 最頂端加 `import certifi; os.environ.setdefault("SSL_CERT_FILE", certifi.where())`，讓所有測試繼承 certifi CA bundle。
---
## [2026-03-12] LlamaIndex `ChatMessage(content="text").content` 回傳 content blocks list 而非字串 `[版本: llama-index-core>=0.13（含 0.14.x）]`
原因：0.13+ 統一用 content blocks 格式儲存訊息，即使只傳 plain string，`ChatMessage.content` 也回傳 `[{"type": "text", "text": "..."}]`，而非原始字串，導致 `assert sent["content"] == "ping"` 失敗。
修正：測試中用 `isinstance(content, list)` 判斷後取出 text block 再比對，或改為 `assert "ping" in str(sent["content"])`。
---
## [2026-03-12] LlamaIndex `ImageDocument(image_url=...)` 建構子發 HTTP 請求驗證 URL 可存取性 `[版本: llama-index-core>=0.13（含 0.14.x）]`
原因：0.13+ 的 `ImageDocument.__init__` 對 `image_url` 欄位執行 validator，實際發 HTTP request 確認 URL 回傳圖片，假 URL（如 `https://example.com/img.jpg`）直接拋出 `ValueError: The specified URL is not an accessible image`，unit test 無法使用假 URL。
修正：unit test 改用 `types.SimpleNamespace(image_url=..., image=None, image_path=None, image_mimetype=None)` mock interface，完全繞過 LlamaIndex validator。
---
## [2026-03-11] `llama-index-core>=0.14` 附帶 `llama-index-workflows`，本地 `workflows/` 被 site-packages 覆蓋 `[版本: llama-index-core>=0.14]`
原因：`llama-index-workflows` v2.15.1 在 site-packages 安裝同名的 `workflows/` package（含 `__init__.py`），本地 `backend/workflows/`（無 `__init__.py`，namespace package）優先順序低，`from workflows.events import *` 實際取到 LlamaIndex 內部事件，自定義 `SummaryEvent` 等不存在，拋出 `NameError`。`__init__.py` 補救無效（會破壞 `llama_index.core` 自身對 `workflows.context` 的 import）。
修正：將本地 `workflows/` 改名為不衝突的名稱（本專案改為 `agent_workflows/`），並全局替換所有 `from workflows.` import。
---
## [2026-03-11] context7 MCP 不同查詢對同一 API 描述不一致，需多次查詢交叉驗證 `[通用]`
原因：不同 subagent 查詢 context7 MCP 得到矛盾結果（例如 `update_prompts()` 在第一次查詢被描述為已移除，第二次查詢才確認仍存在），原因可能是搜尋 token 不同導致命中不同文件段落。
修正：對關鍵 API 存在性有疑問時，至少發起兩次不同角度的 context7 查詢，或直接用 `hasattr()` 在實際環境中驗證，以實際執行結果為準。
---
## [2026-03-11] `ReActAgent.update_prompts({"react_header": PromptTemplate(...)})` template 不可含 `{context_str}` `[版本: llama-index-core>=0.14]`
原因：`react_header` 是固定 header prompt，agent 渲染時不傳入 `context_str` 這個 key，若 PromptTemplate 字串含 `{context_str}` 佔位符則拋出 `KeyError: 'context_str'`。
修正：`react_header` 的 PromptTemplate 只寫純文字 system prompt，不加任何 `{...}` 佔位符；若需動態變數，改在 `agent.run(prompt, ctx=ctx)` 的 prompt 字串中組合。
---
## [2026-03-11] `ReActAgent.from_tools()` / `agent.chat()` 在 llama-index-core 0.14.x 不存在 `[版本: llama-index-core>=0.14]`
原因：0.14.x 將 ReActAgent 重構為 Workflow-based，`from_tools()` classmethod 與同步 `chat()` 均移除；import 路徑、建構方式、執行方式全部改變，AttributeError 不直觀。
修正：`from llama_index.core.agent.workflow import ReActAgent`；建構改為 `ReActAgent(tools=tools, llm=llm, timeout=120)`（`max_iterations` → `timeout` 秒）；執行改為 `await agent.run("...")`，腳本層用 `asyncio.run(async_fn())` 包裝；多輪對話需傳入 `ctx=Context(agent)` 保留歷史。
---
## [2026-03-10] LiteLLM 1.80 gemini/text-embedding-004 路由錯誤，正確 model 為 gemini/gemini-embedding-001 `[版本: litellm==1.80]`
原因：LiteLLM 1.80 對 `gemini/` prefix 的 embedding model 統一使用 `batchEmbedContents` endpoint；但 `text-embedding-004` 已從 Google AI Studio API 移除，只剩 `gemini-embedding-001` 支援 `embedContent`。
修正：將 `LLM_EMBED_MODEL` 預設值改為 `gemini/gemini-embedding-001`（dim=3072）。
---
## [2026-03-10] poetry install 時 lock file 與 pyproject.toml 不同步需先執行 poetry lock `[通用]`
原因：直接修改 pyproject.toml 後執行 `poetry install`，lock file 版本不匹配導致 install 失敗並提示 "pyproject.toml changed significantly"。
修正：先執行 `poetry lock`（無需 `--no-update`），再執行 `poetry install --no-root`。
---
## [2026-03-09] macOS Python 3.12 spawn 模式導致 marker test script crash `[環境: macOS Python 3.12]`
原因：Python 3.12 on macOS 預設 `multiprocessing` 使用 `spawn`，子進程重新 import 主模組時執行 module-level 的 `paper2md()` 呼叫，觸發 `RuntimeError: bootstrapping phase`。
修正：將所有測試執行邏輯包進 `main()` 函數，並加上 `if __name__ == '__main__': main()`。
---
## [2026-03-09] `paper2md()` 每次呼叫重新載入模型，Test 1/2 各花 20-25 分鐘 `[版本: marker >= 1.0.0]`
原因：`paper2md()` 內部每次都呼叫 `create_model_dict()`，導致 5 個 surya 模型（共 3GB+）重複載入，MPS Metal shader 也需重新 warm up。
修正：在 `paper2md()` 加 `artifact_dict=None` 參數，外部統一建立後傳入重用；Test 2 可省下 ~5 分鐘模型重載時間。
---
## [2026-03-09] surya `Recognizing Text` 在 M1 MPS 上每次轉換耗時 12–18 分鐘 `[環境: Apple M1 / PyTorch MPS]`
原因：surya text recognition 使用 autoregressive encoder-decoder，PyTorch MPS 對此架構支援不完整（缺 FlashAttention、`torch.compile` 仍 early stage），MPS cold start 第一個 chunk 需 238s。
修正（緩解）：(1) 重用 `artifact_dict` 避免重複 warm up；(2) 設 `RECOGNITION_BATCH_SIZE=32~64`（預設 256 對 M1 16GB 可能造成 memory pressure）；(3) 繼承 `OcrBuilder` 並擴大 `skip_ocr_blocks`，跳過已有 pdftext 的 block types（`Text`、`SectionHeader` 等），保留 `TextInlineMath`；根本解需等 PyTorch MPS 成熟或改用 Apple MLX 框架。
---
## [2026-03-09] `RECOGNITION_BATCH_SIZE` 預設 256 可能造成 M1 memory pressure `[環境: Apple M1 16GB unified memory]`
原因：每個 batch item 佔 50MB，預設 256 = 12.8GB；M1 CPU/GPU 共用記憶體，surya 模型本身已佔 ~11GB，幾乎無剩餘空間，導致頻繁記憶體交換拖慢速度。
修正：設環境變數 `RECOGNITION_BATCH_SIZE=32` 或 `64` 執行；搭配 `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0` 可解除 PyTorch MPS 記憶體上限（注意：設 0.0 有系統崩潰風險）。
---
## [2026-03-06] LlamaParse v2 images_to_save 加在主流程使所有論文 parse 時間暴增 10x `[通用]`
原因：`output_options.images_to_save=["embedded"]` 讓 server 對每篇論文額外裁圖、編碼、上傳 S3，圖片多的論文（lora 6 張、flash 4 張）從 ~15s 暴增至 ~220s。
修正：`images_to_save` 只放在專門驗證圖片的 Test 7（只跑 1 篇 attention.pdf），主流程 parse 不加，保持快速。
---
## [2026-03-06] LlamaParse v2 expand=images_content_metadata 未搭配 images_to_save 導致 jobs 永遠 RUNNING `[通用]`
原因：`expand=["images_content_metadata"]` 讓 server 嘗試產出圖片 metadata，但未設定 `output_options.images_to_save`，server 無圖可回卻不 FAIL，job 永遠卡在 RUNNING；SDK 無 timeout，client 無限 poll。
修正：必須同時設定 `output_options={"images_to_save": ["embedded"]}` 才能搭配 `images_content_metadata` expand；或完全不加此 expand。
---
## [2026-03-06] LlamaParse v2 output_options.embedded_images 格式錯誤導致 422 `[版本: llama-cloud>=1.0]`
原因：官方部分範例寫 `output_options={"embedded_images": {"enable": True}}`，但實際 API schema 不接受此欄位，回傳 422 `extra_forbidden`。
修正：正確格式為 `output_options={"images_to_save": ["embedded"]}`，對應官方 cURL 文件。
---
## [2026-03-06] LlamaParse 開發誤用 v1 舊版 API 導致無聲卡死 `[版本: llama-cloud-services < 1.0]`
原因：誤將棄用的舊版套件 (`llama-cloud-services`) 當作 v2 API，其 async poll 機制遇到無額度 (如 agentic_plus) 會因為沒有 timeout 而無限卡死。
修正：全面改用新版官方 SDK `llama-cloud >= 1.0`，並使用 `AsyncLlamaCloud` client 的兩段式呼叫 (`files.create` -> `parsing.parse`)。
## [2026-03-05] litellm>=1.82 與 llama-index<0.12 版本衝突，無法裝進主 poetry 環境 `[版本: litellm>=1.82 + llama-index<0.12]`
原因：llama-index<0.12 鎖定 llama-index-llms-openai<0.3.0，而 litellm>=1.82 要求更新版本，poetry dependency resolver 直接 fail
修正：在 poc 目錄建立獨立 venv（`python3 -m venv .venv && .venv/bin/pip install litellm`），不動主專案；正式整合需評估升級 llama-index 至 >=0.12
---
