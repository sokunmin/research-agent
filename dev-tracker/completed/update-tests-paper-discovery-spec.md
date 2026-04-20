# Feature Spec: update-tests-paper-discovery

## 專案資訊
| 項目 | 值 |
|------|-----|
| 專案類型 | `Python (Poetry)` |
| 分支名稱 | `feature/update-tests-paper-discovery` |
| 基於分支 | `dev` |
| Worktree 路徑 | `/Users/chunming/MyWorkSpace/agent_workspace/research-agent/research-agent-update-tests-paper-discovery` |

## 目標
Update test suite to match the new paper discovery pipeline API (PaperDownloader, PaperRelevanceFilter) — old tests import deleted symbols causing ImportError at collection time.

## 實作範圍
- [x] conftest.py: remove TAVILY_API_KEY stub; widen LLM key check; add _skip_marker_by_default
- [x] test_mlflow_v3_upgrade.py → deleted (user decided unnecessary); test_mlflow_config.py deleted
- [x] test_hitl_workflow_autolog.py → test_hitl_workflow.py: TestHitlWorkflowAutolog removed, TestEmitMessage kept
- [x] test_imports.py: remove test_no_azure_in_services; add 3 residue checks
- [x] test_1_download.py: full rewrite for PaperDownloader
- [x] test_2_filter.py: full rewrite for PaperRelevanceFilter
- [x] test_3_marker.py: fix papers_dir fixture
- [x] test_multimodal.py: replace cloud VLM with ollama/qwen3.5:2b; use fixture image bytes; remove URL dead code from multimodal.py
- [x] dev/.env: remove stale fields (TAVILY_MAX_RESULTS, NUM_MAX_CITING_PAPERS); add required infra fields

## 複雜度分析與 Sub-Phase 規劃

| 維度 | 評估 |
|------|------|
| 任務數量 | 9 個 checkbox |
| 跨模組 | 跨 conftest + unit + integration (3 sub-dirs) |
| 外部依賴 | 無新依賴 |
| 狀態管理 | 無 |

**結論：** 複雜（2 sub-phases）

**Sub-Phase 規劃：**

- [x] sub-phase 1：conftest + hitl + imports + test_3_marker + test_multimodal
- [x] sub-phase 2：test_1_download + test_2_filter + .env fix

## 驗收標準
```bash
cd backend/
poetry run pytest tests/unit/ \
    tests/integration/test_paper_scraping/test_imports.py \
    tests/integration/test_paper_scraping/test_1_download.py \
    tests/integration/test_paper_scraping/test_2_filter.py \
    tests/integration/test_hitl_workflow.py \
    -m "not network and not llm" -v
```
✅ 51 passed, 0 failed, 4.87s

## 技術約束
- No new dependencies
- Patch at import site: `agent_workflows.paper_scraping.<symbol>`
- `@pytest.fixture` for Paper objects (composable with tmp_path)
- `_make_filter()` factory helper in test_2 (eliminates repeated MagicMock setup)
- test_multimodal: `_TEST_IMAGE_BYTES` loaded once from fixtures/test_image.jpg; no URL-based image testing

## 當前進度
- 停在：全部 sub-phase 完成
- 已完成：sub-phase 1、sub-phase 2、smoke test 51 passed
- 下一步：wip commit → feat commit → merge → worktree remove
- 遇到的問題：litellm fetches external https:// URLs before mock intercepts; fixed by using image bytes
