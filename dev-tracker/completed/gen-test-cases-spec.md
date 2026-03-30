# Feature Spec: gen-test-cases

## 專案資訊
| 項目 | 值 |
|------|-----|
| 專案類型 | Python (Poetry) |
| 分支名稱 | `feat/gen-test-cases` |
| 基於分支 | `dev` |
| Worktree 路徑 | `/Users/chunming/MyWorkSpace/agent_workspace/research-agent/research-agent-gen-test-cases` |
| 建立時間 | 2026-03-12 |

## 目標
將 4 個散落的 script-style 測試轉為 pytest，補充 multimodal/sandbox 單元測試，統一組織至 `backend/tests/`

## 實作範圍

- [ ] sub-phase 1：測試基礎設施
  - [ ] `pyproject.toml` 加入 test group（pytest, pytest-asyncio）
  - [ ] `backend/pytest.ini` 新建
  - [ ] `backend/tests/conftest.py` 新建
- [ ] sub-phase 2：Unit tests
  - [ ] `backend/tests/unit/test_multimodal.py` — mock litellm，無需 API key
- [ ] sub-phase 3：Integration tests
  - [ ] `backend/tests/integration/test_paper_scraping/test_imports.py` — import + 無 Azure 殘留
  - [ ] `backend/tests/integration/test_paper_scraping/test_1_download.py` — 轉換（修正 import）
  - [ ] `backend/tests/integration/test_paper_scraping/test_2_filter.py` — 轉換（修正 import + new_fast_llm）
  - [ ] `backend/tests/integration/test_paper_scraping/test_3_marker.py` — 轉換（修正 import）
- [ ] sub-phase 4：E2E tests
  - [ ] `backend/tests/e2e/__init__.py` 確認存在
  - [ ] `backend/tests/e2e/test_sandbox.py` — Docker 需求

## 複雜度分析與 Sub-Phase 規劃

| 維度 | 評估 |
|------|------|
| 任務數量 | 9 個檔案 |
| 跨模組 | 跨 services/、agent_workflows/、tests/ |
| 外部依賴 | pytest, pytest-asyncio（新增） |
| 狀態管理 | 無 |

**結論：** 複雜（4 sub-phases）

**Sub-Phase 規劃：**

- [x] sub-phase 1：測試基礎設施（pyproject.toml + pytest.ini + conftest.py）
- [x] sub-phase 2：Unit tests（test_multimodal.py）
- [x] sub-phase 3：Integration tests（4 個測試檔）
- [x] sub-phase 4：E2E tests（test_sandbox.py）

## 驗收標準
- `pytest tests/unit -v` 全部通過（無需任何 API key）
- `pytest tests/integration/test_paper_scraping/test_imports.py -v` 全部通過
- 無任何 `from workflows.` 殘留
- 無任何 Azure 相關 import

## 技術約束
- `pythonpath = .` 讓 `from agent_workflows.` import 正確解析（pytest >= 7.0）
- 只用 `unittest.mock`，不加 `pytest-mock` 依賴
- `TAVILY_API_KEY` 是唯一必填欄位，conftest 設 dummy
- LiteLLMMultiModal Pydantic Fields：`model`, `temperature`, `max_tokens`, `extra_kwargs`（用 `self.model`，非 `self._model`）
- `config.py` 無 Azure 欄位，conftest 不設 Azure dummy vars
- `run_code` error 格式：`"ERROR (exit_code=N):\n{stderr}"`
- `upload_file` 成功回傳：`"Uploaded {src} → {dst}"`

## 當前進度
- 停在：全部 sub-phase 完成
- 已完成：sub-phase 1, 2, 3, 4 全部完成
- 下一步：feat commit → merge → 歸檔
- 遇到的問題：
  1. LlamaIndex 0.13.6 `ImageDocument` URL validation + `ChatMessage.content` blocks format（已修復）
  2. macOS SSL cert 問題 (`certificate verify failed`) — 修復：conftest 載入 certifi + dotenv
  3. conftest 在 config 模組前執行，`GEMINI_API_KEY` 從 .env 讀不到 — 修復：conftest 主動 `load_dotenv`

## 測試執行結果（2026-03-12）
| 測試 | 結果 |
|------|------|
| `tests/unit/test_multimodal.py` | ✅ 21/21 通過 |
| `tests/integration/test_paper_scraping/test_imports.py` | ✅ 3/3 通過 |
| `tests/integration/test_paper_scraping/test_1_download.py` | ✅ 4/4 通過 |
| `tests/integration/test_paper_scraping/test_2_filter.py` | ✅ 6/6 通過 |
| `tests/e2e/test_sandbox.py` | ✅ 11/11 通過 |
| `tests/integration/test_paper_scraping/test_3_marker.py` | ⏭️ 未執行（需 ~3-5GB marker 模型，耗時）|

## Smoke Test（各 sub-phase 完成後執行）

**Sub-phase 1 smoke test：**
```bash
cd backend && poetry run pytest --collect-only 2>&1 | head -20
```

**Sub-phase 2 smoke test：**
```bash
cd backend && poetry run pytest tests/unit -v
```

**Sub-phase 3 smoke test：**
```bash
cd backend && poetry run pytest tests/integration/test_paper_scraping/test_imports.py -v
```

**Sub-phase 4 smoke test：**
```bash
cd backend && poetry run pytest tests/e2e -v --collect-only
```

## 完成後步驟（所有 sub-phase 完成後）

1. 評估 gen-test-cases 時機（此 feature 本身就是測試，直接繼續）
2. git commit "feat: add pytest test suite for backend"
3. git checkout dev && git merge --no-ff feat/gen-test-cases
4. 歸檔 feature-spec.md → dev-tracker/completed/gen-test-cases-spec.md
5. Backlog UPDATE → done
6. git worktree remove ../research-agent-gen-test-cases
7. git branch -d feat/gen-test-cases
