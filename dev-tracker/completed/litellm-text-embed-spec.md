# Feature Spec: litellm-text-embed

## 專案資訊
| 項目 | 值 |
|------|-----|
| 專案類型 | Python (Poetry) |
| 分支名稱 | `feat/litellm-text-embed` |
| 基於分支 | `dev` |
| Worktree 路徑 | `/Users/chunming/MyWorkSpace/agent_workspace/research-agent/research-agent-litellm-text-embed` |
| 建立時間 | 2026-03-10 |

## 目標
用 LiteLLM 取代 Azure text LLM + embedding，讓 LLM provider 可透過 .env 切換而不需改 code。
VLM（multimodal）暫留 Azure 到 Phase 4（litellm-vlm）。

## 實作範圍
- [x] 新增 `backend/services/model_factory.py`（ModelConfig dataclass + ModelFactory class）
- [x] 改寫 `backend/services/llms.py`（保留 Azure VLM，text LLM 改用 model_factory）
- [x] 改寫 `backend/services/embeddings.py`（embedder = model_factory.embed_model()）
- [x] 修改 `backend/config.py`（新增 LiteLLM 欄位；Azure 改為 optional）
- [x] 修改 `backend/utils/tokens.py`（tiktoken fallback for non-OpenAI model names）
- [x] 修改 `backend/workflows/summary_using_images.py`（改用 setup_token_counter()）
- [x] 修改 `backend/pyproject.toml`（新增 litellm 套件，移除 azure embedding）
- [x] 修改 `.env.example`（新增 LiteLLM 欄位）

## 複雜度分析與 Sub-Phase 規劃

| 維度 | 評估 |
|------|------|
| 任務數量 | 8 個檔案 |
| 跨模組 | 跨 5 個層（config, services, utils, workflows, pyproject） |
| 外部依賴 | 新增 litellm + llama-index-llms-litellm + llama-index-embeddings-litellm |
| 狀態管理 | 無複雜狀態 |

**結論：複雜（3 sub-phases）**

**Sub-Phase 規劃：**

- [x] sub-phase 1：Dependencies + Config
      修改 `backend/pyproject.toml`、`backend/config.py`、`.env.example`
      smoke: `cd backend && poetry run python -c "from config import settings; print('LLM_SMART_MODEL:', settings.LLM_SMART_MODEL)"`

- [x] sub-phase 2：Model Factory + Token Utils
      新增 `backend/services/model_factory.py`、修改 `backend/utils/tokens.py`
      smoke: `cd backend && poetry run python -c "from services.model_factory import model_factory; print('Factory OK:', model_factory._config)"`

- [x] sub-phase 3：Services Wire-up + Workflow fix
      改寫 `backend/services/llms.py`、`backend/services/embeddings.py`、`backend/workflows/summary_using_images.py`
      smoke (需 GEMINI_API_KEY):
        `cd backend && poetry run python -c "from services.llms import new_fast_llm; r = new_fast_llm().complete('Say hello in one word'); print('LLM OK:', r.text)"`
        `cd backend && poetry run python -c "from services.embeddings import embedder; v = embedder.get_text_embedding('test'); print('Embedding OK: dim =', len(v))"`

> 每個 sub-phase 完成後執行 smoke test + wip commit，不是每改一個檔案就 commit。

## 驗收標準
- `settings.LLM_SMART_MODEL` 可讀取（預設 `gemini/gemini-2.5-flash`）
- `model_factory.smart_llm()` / `fast_llm()` / `embed_model()` 可建立實例
- `new_fast_llm().complete(...)` 回傳文字（需 GEMINI_API_KEY）
- `embedder.get_text_embedding('test')` 回傳非空向量
- `setup_token_counter('gemini/gemini-2.5-flash')` 不 crash（fallback to cl100k_base）

## 技術約束
- `LiteLLMEmbedding` 參數用 `model_name=`（不是 `model=`）
- `LiteLLM` 參數用 `model=`
- VLM 暫留 Azure（`llama-index-multi-modal-llms-azure-openai` 不動）
- `llama-index-embeddings-azure-openai` 在此 phase 移除
- Azure 欄位改為 optional（`= ""`），不再是必填
- commit message 禁止加 `Co-authored-by`
- `feature-spec.md` 不納入 commit

## Smoke Test（各 sub-phase 完成後執行）
見各 sub-phase 的 smoke 指令（上方）。
- 不通過 → 修復，修復後呼叫 Error Log skill，user 確認後才繼續下一個 sub-phase
- 通過 → 更新當前進度，wip commit，繼續

## 當前進度
- 停在：全部完成
- 已完成：sub-phase 1, 2, 3 全部完成；embed model 修正為 gemini/gemini-embedding-001；merge 到 dev；backlog → done
- 下一步：歸檔 feature-spec.md，移除 worktree
- 遇到的問題：LiteLLM 1.80 embed model 路由錯誤（見 error-log.md）

## 完成後步驟（所有 sub-phase 完成後）
1. 讀 backlog 評估 gen-test-cases 時機（litellm-vlm 尚未完成 → 建議選 2 或 3）
2. ⛔ 停止，詢問使用者選 1/2/3
3. 使用者確認後：`git add . && git restore --staged feature-spec.md 2>/dev/null; git commit -m "feat: replace Azure text LLM + embedding with LiteLLM"`
4. `git checkout dev && git merge --no-ff feat/litellm-text-embed -m "merge: feat/litellm-text-embed into dev"`
5. Backlog skill UPDATE：狀態 → done
6. `git worktree remove ../research-agent-litellm-text-embed`
7. `git branch -d feat/litellm-text-embed`
