# LLM, Embedding & Sandbox Services

`backend/services/` 封裝了所有 LLM、Embedding 和 Docker sandbox 的初始化邏輯，各 workflow 直接 import 使用。

## 模組結構

```
backend/services/
├── model_factory.py  # ModelFactory — provider-agnostic LLM/Embedding 工廠
├── llms.py           # LLM 全域 singleton + factory 函式
├── embeddings.py     # Embedding singleton
├── multimodal.py     # LiteLLMMultiModal — 自訂 VLM class
└── sandbox.py        # LlmSandboxToolSpec — Docker-based code execution
```

---

## ModelFactory (`services/model_factory.py`)

所有 LLM/Embedding 實例都透過 `ModelFactory` 建立，provider 由 `.env` 中的 `LLM_*_MODEL` 決定，不需改程式碼即可切換。

```python
from services.model_factory import model_factory

llm  = model_factory.smart_llm()              # LiteLLM（高能力模型）
fast = model_factory.fast_llm()               # LiteLLM（快速/低成本模型）
vlm  = model_factory.vision_llm()             # LiteLLMMultiModal（視覺模型）
emb  = model_factory.embed_model()            # LiteLLMEmbedding（通用）
rel  = model_factory.relevance_embed_model()  # LiteLLMEmbedding（論文相關性用，本地 Ollama）
```

`ModelConfig` 欄位（對應 config.py）：

| 欄位 | 對應 env var | 說明 |
|------|-------------|------|
| `smart_model` | `LLM_SMART_MODEL` | 主力 LLM |
| `fast_model` | `LLM_FAST_MODEL` | 快速/低成本 LLM |
| `vision_model` | `LLM_VISION_MODEL` | 視覺模型 |
| `vision_fallback_model` | `LLM_VISION_FALLBACK_MODEL` | VLM 備援模型，空字串則停用 |
| `embed_model` | `LLM_EMBED_MODEL` | 通用嵌入模型（LlamaIndex Settings.embed_model） |
| `relevance_embed_model` | `LLM_RELEVANCE_EMBED_MODEL` | 論文相關性 Stage-1 embedding，與通用 embed_model 隔離 |
| `max_tokens` | `MAX_TOKENS` | 最大輸出 token |

---

## LLM Service (`services/llms.py`)

提供全域 singleton 和 factory 函式，所有 workflow 直接 import。

```python
from services.llms import llm, vlm, new_llm, new_fast_llm, new_vlm
```

### 可用實例 / 工廠函式

| 名稱 | 類型 | 說明 |
|------|------|------|
| `llm` | 模組級 singleton | 主力 LLM（`LLM_SMART_MODEL`），掛到 `Settings.llm` |
| `vlm` | 模組級 singleton | 視覺模型（`LLM_VISION_MODEL`，`LiteLLMMultiModal`） |
| `new_llm(temperature)` | factory | 建立新的主力 LLM 實例 |
| `new_fast_llm(temperature)` | factory | 建立新的快速 LLM 實例（`LLM_FAST_MODEL`） |
| `new_vlm(temperature, callback_manager)` | factory | 建立新的 VLM 實例 |

**各 workflow 的 LLM 使用策略：**

| Step | LLM | 理由 |
|------|-----|------|
| 查詢改寫（`discover_candidate_papers`） | `new_fast_llm` | 改寫 user query 為學術搜尋語 |
| 論文過濾 Stage-2（`filter_papers`） | `new_fast_llm`（選擇性） | 僅 borderline 論文（約 41%）；Stage-1 使用本地 embedding |
| Outline 生成（`summary2outline`） | `new_fast_llm` | 結構化輸出，token 量適中 |
| Layout 選擇（`outlines_with_layout`） | `new_llm` | 需要較強推理 |
| Slide 生成 ReAct Agent（`slide_gen`） | `new_llm` | 複雜工具呼叫 |
| 投影片視覺驗證（`validate_slides`） | `new_vlm` | 需要視覺理解 |
| 論文摘要（`paper2summary`） | `new_vlm` | 圖片轉摘要 |

### LlamaIndex Settings 全域綁定

在 `summary_gen.py` 和 `slide_gen.py` 啟動時：

```python
from llama_index.core import Settings
Settings.llm = llm
Settings.embed_model = embedder
```

這讓所有未明確指定 LLM 的 LlamaIndex 元件（如 `FunctionCallingProgram`）自動使用 smart LLM。

---

## Embedding Service (`services/embeddings.py`)

```python
from services.embeddings import embedder
```

`embedder` 是 `LiteLLMEmbedding` 實例，模型由 `LLM_EMBED_MODEL` 決定（預設 `gemini/gemini-embedding-001`，dim=3072）。

---

## LiteLLMMultiModal (`services/multimodal.py`)

自訂的 LlamaIndex `MultiModalLLM` 實作，以 LiteLLM 為 transport，支援任何 vision-capable 模型。

```python
from services.multimodal import LiteLLMMultiModal

vlm = LiteLLMMultiModal(model="gemini/gemini-2.5-flash")
# 或透過 model_factory.vision_llm()

# sync
resp = vlm.complete(prompt, image_documents=[doc1, doc2])

# async
resp = await vlm.acomplete(prompt, image_documents=[doc1, doc2])

# chat（直接呼叫，支援 ChatMessage.blocks 格式）
resp = await vlm.achat(messages)
```

**Pydantic Fields：**

| Field | 預設值 | 說明 |
|-------|--------|------|
| `model` | — | LiteLLM model ID，例如 `gemini/gemini-2.5-flash` |
| `temperature` | `0.0` | 採樣溫度 |
| `max_tokens` | `4096` | 最大輸出 token |
| `extra_kwargs` | `{}` | 額外傳給 LiteLLM 的 kwargs |
| `fallback_models` | `[]` | 備援模型列表，於 429/error 重試後依序嘗試，例如 `["openrouter/google/gemma-3-27b-it:free"]` |

**Rate limit 保護：**

所有 litellm 呼叫（`complete`, `chat`, `acomplete`, `achat`）統一透過 `_litellm_kwargs()` 設定，包含：

- `num_retries=3`：遇到 429/transient error 自動 retry，指數退避（`min(1 × 2^n, 60)` 秒 + 10% jitter）
- `fallbacks=fallback_models`：retry 耗盡後依序切換備援模型（`fallback_models` 非空時啟用）

**相容性：**
- `MultiModalLLMCompletionProgram.from_defaults(multi_modal_llm=vlm)` — 使用 `complete()`/`acomplete()`
- 支援 LlamaIndex 0.13+ `ImageBlock`（`.url`, `.path`, `.image` 欄位）
- 支援 `ImageDocument`（`.image_url`, `.image_path`, `.image`）
- 支援 `ChatMessage.blocks` 格式（`TextBlock` + `ImageBlock`）
- streaming 方法（`stream_complete`, `stream_chat` 等）未實作，呼叫會 raise `NotImplementedError`

---

## Docker Sandbox (`services/sandbox.py`)

Docker-based Python 代碼執行環境，供 `SlideGenerationWorkflow` 的 ReAct Agent 使用。

```python
from services.sandbox import LlmSandboxToolSpec, RemoteFile

sandbox = LlmSandboxToolSpec(local_save_path="/path/to/artifacts")
```

### 方法

**Agent-facing（透過 `to_tool_list()` 暴露給 ReActAgent）：**

| 方法 | 說明 | 回傳 |
|------|------|------|
| `run_code(code: str)` | 在 container 執行 Python，`python-pptx` 預裝。失敗時回傳 `"ERROR (exit_code=N):\n{stderr}"` | `str`（stdout 或 error） |
| `list_files_str(remote_dir)` | 列出 sandbox 目錄下的檔案，換行分隔路徑 | `str` |
| `upload_file(local_file_path)` | 上傳本地檔案到 `/sandbox/<filename>` | `"Uploaded {src} → {dst}"` |

**Workflow-facing（直接呼叫）：**

| 方法 | 說明 |
|------|------|
| `list_files(remote_dir)` | 回傳 `list[RemoteFile]`（每個有 `.filename`, `.file_full_path`） |
| `download_file_to_local(remote, local)` | 從 container 下載檔案到本地 |
| `to_tool_list()` | 回傳 3 個 `FunctionTool`（`run_code`, `list_files`, `upload_file`） |
| `close()` | 關閉 container pool，釋放 Docker 資源 |

**Container Pool 設定：**

| 參數 | 值 | 說明 |
|------|-----|------|
| `min_pool_size` | 1 | 最少保持 1 個 container |
| `max_pool_size` | 2 | 最多 2 個並行 container |
| `idle_timeout` | 300s | 閒置超時自動回收 |
| `enable_prewarming` | `True` | 預先啟動 container，降低首次延遲 |
| 預裝套件 | `python-pptx` | 預裝至 container |

> **需要 Docker Desktop 在背景執行。**

---

## MLflow 追蹤整合

所有 `HumanInTheLoopWorkflow` 的子類（`SummaryGenerationWorkflow`、`SlideGenerationWorkflow`）在 run 時會自動啟動 MLflow 追蹤：

```python
mlflow.set_experiment(self.__class__.__name__)
mlflow.llama_index.autolog()
with mlflow.start_run():
    result = await super().run(*args, **kwargs)
```

Experiment 名稱 = class 名稱，可在 MLflow UI（http://localhost:8080）查看每次 run 的詳細 trace。
