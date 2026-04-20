# Feature Spec: azure-cleanup

## 專案資訊
| 項目 | 值 |
|------|-----|
| 專案類型 | Python (Poetry) |
| 分支名稱 | `feat/azure-cleanup` |
| 基於分支 | `dev` |
| Worktree 路徑 | `/Users/chunming/MyWorkSpace/agent_workspace/research-agent/research-agent-azure-cleanup` |
| 建立時間 | 2026-03-11 |

## 目標
完全移除專案中所有 Azure 相關程式碼與設定，以 llm-sandbox（Docker-based）替換 Azure Dynamic Sessions，
更新至 llama-index 0.14.x 新 API，並將 `workflows/` 改名為 `agent_workflows/` 消除與 `llama-index-workflows`
套件的 namespace 衝突。確保邏輯正確性、高可讀性與低冗碼。

## 實作範圍

- [x] sub-phase 1：移除 6 個 AZURE_OPENAI_* 欄位（config.py + .env.example）
- [x] sub-phase 2a：建立 `services/sandbox.py`（LlmSandboxToolSpec）
- [x] sub-phase 2b：全面更新 `slide_gen.py` + `research_agent.py`
- [x] sub-phase 2c：Config + deps 清理（config.py、.env.example、pyproject.toml + poetry lock/install）
- [x] sub-phase 2d：修正其他檔案的 Azure 殘留（multimodal.py、model_factory.py 的 docstring/comments）
- [x] sub-phase 2e：rename `workflows/` → `agent_workflows/`（解決 namespace 衝突）
- [x] sub-phase 2f：移除 project root 的 Azure 殘留（docker-compose.yml、root pyproject.toml、backend/Dockerfile）
- [x] sub-phase 2g：修正 `summary_gen_w_qe.py` 的 0.14.x API（ReActAgent import + from_tools → constructor + update_prompts key + agent.chat → asyncio.run(agent.run)）

## 根本原因（sub-phase 2e 背景）

`llama-index-core` 0.14.x 引入 `llama-index-workflows` v2.15.1，在 site-packages 安裝了同名的
`workflows/` package（含 `__init__.py`）。本地 `backend/workflows/`（無 `__init__.py`，namespace package）
被 site-packages 版本覆蓋，導致 `from workflows.events import *` 取到 LlamaIndex 內部事件而非專案
自定義事件（SummaryEvent 等），smoke test 報 NameError。

改名為 `agent_workflows/` 永久消除衝突，無副作用。

## 完整 Azure 殘留清單（audit 結果）

| 位置 | 殘留內容 | 處理方式 |
|------|---------|---------|
| `config.py` | `AZURE_DYNAMIC_SESSION_MGMT_ENDPOINT` | ✅ 已移除 |
| `.env.example` | Azure 區塊 + endpoint | ✅ 已移除 |
| `pyproject.toml` | `llama-index-tools-azure-code-interpreter`, `azure-cli` | ✅ 已移除，加 `llm-sandbox` |
| `slide_gen.py` | ReActAgent 舊 import + AzureCodeInterpreterToolSpec | ✅ 已替換 |
| `research_agent.py` | ReActAgent 舊 import + Azure dead import | ✅ 已修正 |
| `services/multimodal.py` docstring | "AzureOpenAIMultiModal" 字樣 | ✅ 已更新 |
| `services/model_factory.py` comment | "Azure OpenAI via LiteLLM" | ✅ 已改用中性措辭 |
| `docker-compose.yml` | `~/.azure:/root/.azure` volume mount | ✅ 已移除 |
| root `pyproject.toml` | 3 個 llama-index-azure 套件 + root `poetry.lock` | ✅ 已移除並重新生成 lock |
| `backend/Dockerfile` | 已 comment-out 的 Azure CLI 安裝區塊 | ✅ 已移除 dead code |

## sub-phase 2e 實作範圍

**目標**：將 `backend/workflows/` 改名為 `backend/agent_workflows/`，更新所有 import。

**需更新的 import 位置**（共 6 個檔案，約 15 行）：

| 檔案 | 更新內容 |
|------|---------|
| `backend/main.py` | `from workflows.xxx` → `from agent_workflows.xxx` |
| `backend/agent_workflows/events.py` | `from workflows.paper_scraping` → `from agent_workflows.paper_scraping`、`from workflows.schemas` → `from agent_workflows.schemas` |
| `backend/agent_workflows/slide_gen.py` | `from workflows.events` → `from agent_workflows.events`、`from workflows.hitl_workflow` → `from agent_workflows.hitl_workflow` |
| `backend/agent_workflows/summary_gen.py` | `from workflows.events` → `from agent_workflows.events`、其他內部 import |
| `backend/agent_workflows/research_agent.py` | `from workflows.events` → `from agent_workflows.events`、其他內部 import |
| `backend/agent_workflows/summarize_and_generate_slides.py` | `from workflows.xxx` → `from agent_workflows.xxx` |

**搜尋方式**：`grep -rn "from workflows\." backend/ --include="*.py"`

## 技術決策（基於 PoC Q1-Q6）

### llm-sandbox 對應關係
| AzureCodeInterpreterToolSpec | LlmSandboxToolSpec |
|---|---|
| `AzureCodeInterpreterToolSpec(pool_management_endpoint=...)` | `LlmSandboxToolSpec(local_save_path=...)` |
| `to_tool_list()` | `to_tool_list()` — 回傳 [run_code, list_files, upload_file] |
| `upload_file(local_file_path=...)` | `upload_file(local_file_path=...)` — copy_to_runtime |
| `list_files()` | `list_files()` — 回傳 `list[RemoteFile]` |
| `download_file_to_local(remote, local)` | `download_file_to_local(remote, local)` — copy_from_runtime |

### llama-index 0.14.x API 變更
| 舊 | 新 |
|---|---|
| `from llama_index.core.agent import ReActAgent` | `from llama_index.core.agent.workflow import ReActAgent` |
| `ReActAgent.from_tools(tools, llm=llm, max_iterations=50)` | `ReActAgent(tools=tools, llm=llm, timeout=300)` |
| `agent.update_prompts({"agent_worker:system_prompt": p})` | `agent.update_prompts({"react_header": p})` |
| `task = agent.create_task(prompt)` + `agent.run_step()` | `handler = agent.run(prompt)` + `async for ev in handler.stream_events()` |
| `agent.finalize_response(task_id)` | `response = await handler` |
| Sandbox path `/mnt/data/` | `SANDBOX_DIR = "/sandbox"` |

## 驗收標準
```bash
cd backend

# 無任何 Azure 字樣殘留
grep -rn "azure\|Azure\|AZURE" . --include="*.py" --include="*.toml" | grep -v __pycache__
# 期望：0 筆

# config 正常載入
poetry run python -c "from config import settings; print('OK:', settings.LLM_SMART_MODEL)"

# sandbox 可 import
poetry run python -c "from services.sandbox import LlmSandboxToolSpec, SANDBOX_DIR; print('sandbox OK')"

# workflows（改名後）可 import
poetry run python -c "
from agent_workflows.slide_gen import SlideGenerationWorkflow
from agent_workflows.research_agent import ResearchAgentWorkflow
print('agent_workflows OK')
"
```

## 技術約束
- 容器工作目錄統一使用 `SANDBOX_DIR = "/sandbox"`，從 `services/sandbox.py` import
- llm-sandbox 無 async API，並行須用 ThreadPoolExecutor（本 phase 不需並行，pool size=1 即可）
- commit message 不加 Co-authored-by
- `feature-spec.md` 不納入任何 commit

## 當前進度
- 停在：全部 sub-phase 完成，待收尾（gen-test-cases 評估 → commit → merge）
- 已完成：sub-phase 1, 2a, 2b, 2c, 2d, 2e, 2f, 2g（全部完成，audit 零殘留，smoke test 全部通過）
- 下一步：評估 gen-test-cases 時機，詢問使用者，執行收尾流程
- 遇到的問題：`llama-index-workflows` v2.15.1 與本地 `workflows/` namespace 衝突 → 已透過 rename 解決

## Smoke Test（各 sub-phase 完成後執行）
- 2e：
  ```bash
  poetry run python -c "
  from agent_workflows.slide_gen import SlideGenerationWorkflow
  from agent_workflows.research_agent import ResearchAgentWorkflow
  print('OK')
  " # ✅ PASSED
  ```
- 2f：
  ```bash
  # Azure audit — 期望 0 筆（含 root 目錄）
  grep -rn "azure\|Azure\|AZURE" . | grep -v __pycache__ | grep -v poetry.lock
  # ✅ PASSED（0 results）
  ```

## 完成後步驟
見 git-worktree-sequential skill 完成後步驟。

gen-test-cases 已獨立為 **Phase 07**（backlog #07，plan: PHASE 7 節），
在 Phase 06 merge 完成後另行執行，不在本 feature 的 commit 範圍內。
