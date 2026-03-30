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
