# Project Backlog
> 最後更新：2026-03-12 (mlflow-v3-upgrade #08 新增)

## 開發進度

| # | Feature | 子 Spec | Branch | 狀態 | PoC | 測試 | 更新時間 |
|---|---------|---------|--------|------|-----|------|---------|
| 01 | deps-version-upgrade | - | refactor/dependency-upgrade | ✅ done | - | - | 2026-03-10 |
| 02 | openalex-cleanup | - | refactor/openalex-cleanup | ✅ done | - | - | 2026-03-10 |
| 03 | naming | - | refactor/naming | ✅ done | - | - | 2026-03-10 |
| 04 | litellm-text-embed | - | feat/litellm-text-embed | ✅ done | ✅ approved | - | 2026-03-10 |
| 05 | litellm-vlm | - | feat/litellm-vlm | ✅ done | - | - | 2026-03-10 |
| 06 | azure-cleanup | - | feat/azure-cleanup | ✅ done | - | - | 2026-03-11 |
| 07 | gen-test-cases | - | feat/gen-test-cases | ✅ done | - | ✅ passed | 2026-03-12 |
| 08 | mlflow-v3-upgrade | - | feat/mlflow-v3-upgrade | ✅ done | - | ✅ passed | 2026-03-12 |

## 狀態說明
- ⬜ `todo`：尚未開始
- 🔵 `in-progress`：開發中（branch 已建立）
- ✅ `done`：已 merge 回 dev
- 🔴 `blocked`：相依未完成或遇到問題
- 🗃️ `abandoned`：放棄，未 merge

## PoC 欄位說明
- `-`：無 PoC 或尚未開始
- `✅ approved`：PoC 驗證通過
- `✅ integrated`：PoC 已整合進 feature

## 測試欄位說明
- `-`：尚未執行
- `✅ passed`：全部通過
- `❌ failed`：有失敗案例

## Context 接手說明
接手的新 AI agent：
1. 讀此檔案確認全局狀態
2. 找到 `in-progress` 的 feature，讀對應子 spec 繼續
3. 找到 `todo` 的下一個，讀子 spec 開始實作
