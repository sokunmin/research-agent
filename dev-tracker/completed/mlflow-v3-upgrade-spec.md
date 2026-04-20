# Feature Spec: mlflow-v3-upgrade

## 專案資訊
| 項目 | 值 |
|------|-----|
| 專案類型 | `Python (Poetry)` |
| 分支名稱 | `feat/mlflow-v3-upgrade` |
| 基於分支 | `dev` |
| Worktree 路徑 | `/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev-mlflow-v3-upgrade` |
| 建立時間 | `2026-03-12` |

## 目標
MLflow v2.16.0 → v3.x 升級，修正 docker-compose 配置問題，加入 `mlflow.litellm.autolog()`。

## 實作範圍
- [x] sub-phase 1：四個檔案修改（docker-compose, pyproject.toml, main.py, hitl_workflow.py）+ poetry lock & install + smoke test

## 複雜度分析與 Sub-Phase 規劃

| 維度 | 評估 |
|------|------|
| 任務數量 | 4 個修改點 |
| 跨模組 | 跨 docker-compose + Python 依賴 + 2 個 Python 檔案 |
| 外部依賴 | 更新 mlflow major version |
| 狀態管理 | 無 |

**結論：** 簡單（1 sub-phase）— 所有修改互相獨立，可一次完成

**Sub-Phase 規劃：**
- [x] sub-phase 1：所有程式碼修改 + poetry update + smoke test

## 驗收標準
- `python -c "import mlflow; print(mlflow.__version__)"` 顯示 3.x
- `mlflow.litellm.autolog()` import 成功
- `docker-compose up mlflow` 啟動，http://localhost:8080 可開啟

## 技術約束
- 所有現有 MLflow Python 呼叫與 v3 完全相容，零破壞性修改
- docker-compose 使用 `sqlite:////`（四斜線）確保絕對路徑
- 不引入新的 Python 依賴

## 當前進度
- 停在：全部 sub-phase 完成
- 已完成：sub-phase 1（docker-compose, pyproject.toml, main.py, hitl_workflow.py + poetry lock + smoke test）
- 下一步：commit + merge
- 遇到的問題：（無）

## Smoke Test
```bash
cd /Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev-mlflow-v3-upgrade/backend
python -c "import mlflow; print('mlflow version:', mlflow.__version__)"
python -c "
import os; os.environ.setdefault('TAVILY_API_KEY', 'dummy')
import mlflow
mlflow.llama_index.autolog()
mlflow.litellm.autolog()
print('All autolog imports OK')
"
```
