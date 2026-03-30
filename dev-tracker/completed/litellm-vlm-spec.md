# Feature Spec: litellm-vlm

## 專案資訊
| 項目 | 值 |
|------|-----|
| 專案類型 | Python (Poetry) |
| 分支名稱 | `feat/litellm-vlm` |
| 基於分支 | `dev` |
| Worktree 路徑 | `/Users/chunming/MyWorkSpace/agent_workspace/research-agent/research-agent-litellm-vlm` |
| 建立時間 | 2026-03-10 |

## 目標
用自製 `LiteLLMMultiModal` 取代 `AzureOpenAIMultiModal`，移除最後一個 Azure LLM 依賴，讓 VLM 也透過 LiteLLM 路由（預設 gemini/gemini-2.5-flash）。

## 實作範圍

- [x] sub-phase 1：新增 `backend/services/multimodal.py`
  - `LiteLLMMultiModal` 繼承 `MultiModalLLM`（llama-index-core 0.14）
  - 實作 9 個 abstract methods（streaming 方法 raise NotImplementedError）
  - 使用 `litellm.acompletion()` / `litellm.completion()` 作為 transport
  - helper: `_image_doc_to_content_block()`, `_image_block_to_content_block()`

- [x] sub-phase 2：Wire-up
  - `backend/services/model_factory.py`：新增 `vision_llm()` 方法
  - `backend/services/llms.py`：移除 `AzureOpenAIMultiModal`，改用 `model_factory.vision_llm()`
  - `backend/pyproject.toml`：移除 `llama-index-multi-modal-llms-azure-openai`

## 複雜度分析與 Sub-Phase 規劃

| 維度 | 評估 |
|------|------|
| 任務數量 | 4 個檔案 |
| 跨模組 | 跨 3 個模組（multimodal, model_factory, llms） |
| 外部依賴 | litellm（已安裝）、llama-index-core MultiModalLLM ABC |
| 狀態管理 | 無複雜狀態，主要是 ABC 介面實作 |

**結論：** 複雜（2 sub-phases）

**Sub-Phase 規劃：**

- [x] sub-phase 1：`multimodal.py`（LiteLLMMultiModal 核心實作）
  - smoke：`from services.multimodal import LiteLLMMultiModal; vlm = LiteLLMMultiModal(model='gemini/gemini-2.5-flash'); print(vlm.metadata)`
- [x] sub-phase 2：`model_factory.py` + `llms.py` + `pyproject.toml` wire-up
  - smoke Step A（純文字）：`from services.llms import new_vlm; vlm = new_vlm(); resp = vlm.complete('Say hello in one word', image_documents=[]); print('VLM text OK:', resp.text)`
  - smoke Step B（含圖片）：⛔ **先暫停，提醒 user 下載圖片到 `backend/data/test_image.jpg`，user 確認後再繼續**

## 技術約束

- **ImageBlock fields（llama-index-core 0.13.6+）**：`.url` / `.path` / `.image`（bytes）— 不是 `.image_url` / `.image_path`
- **`MultiModalLLMCompletionProgram`** 呼叫 `complete()` / `acomplete()`，不呼叫 `chat()`
- `getattr(m, "blocks", None)` 處理 ChatMessage 跨版本相容性
- 禁止 commit message 加 `Co-authored-by`
- `feature-spec.md` 不納入 commit（每次 commit 前 `git restore --staged feature-spec.md 2>/dev/null`）
- Merge 使用本地 `--no-ff`，不 push remote

## 9 個 abstract methods 實作清單

1. `metadata` property → `MultiModalLLMMetadata(model_name=..., num_output=...)`
2. `complete(prompt, image_documents, **kwargs)` → `CompletionResponse`（sync）
3. `stream_complete(...)` → raise `NotImplementedError`
4. `chat(messages, **kwargs)` → `ChatResponse`（sync）
5. `stream_chat(...)` → raise `NotImplementedError`
6. `acomplete(...)` → async `CompletionResponse`
7. `astream_complete(...)` → raise `NotImplementedError`
8. `achat(...)` → async `ChatResponse`
9. `astream_chat(...)` → raise `NotImplementedError`

## 驗收標準

```bash
# Step A — 純文字（不需圖片）
cd backend
python -c "
from services.llms import new_vlm
vlm = new_vlm()
resp = vlm.complete('Say hello in one word', image_documents=[])
print('VLM text OK:', resp.text)
"

# Step B — 含圖片（先提醒 user 下載圖片到 backend/data/test_image.jpg）
python -c "
import asyncio
from services.llms import new_vlm
from llama_index.core.schema import ImageDocument
async def test():
    vlm = new_vlm()
    doc = ImageDocument(image_path='data/test_image.jpg')
    resp = await vlm.acomplete('What is in this image? Answer in one sentence.', image_documents=[doc])
    print('VLM image OK:', resp.text)
asyncio.run(test())
"

# 確認無 Azure 殘留
grep -r 'AzureOpenAIMultiModal\|azure_openai.*multimodal\|multi_modal_llms.azure' services/ 2>/dev/null
# 應該沒有輸出
```

## 當前進度

- 停在：全部 sub-phase 完成，smoke test Step A + Step B 均通過
- 已完成：sub-phase 1（multimodal.py）、sub-phase 2（model_factory + llms + pyproject.toml）
- 下一步：評估 gen-test-cases 時機 → commit → merge → 歸檔
- 遇到的問題：MultiModalLLM 是 Pydantic BaseModel，需用 Field 宣告屬性（非 __init__ self._xxx）
