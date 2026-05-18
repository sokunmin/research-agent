# PoC: query-transformation

## 狀態
- 目前狀態：`approved`
- 建立時間：2026-05-12
- 最後更新：2026-05-14
- PoC 程式碼：`poc/openalex-search-comparison/query-transformation.py`
- 來源 spec：`query-transformation-plan.md`

## 核心驗證問題
1. LLM topic-only transformation (Strategy B) 是否比 raw query (Strategy A) 在 OpenAlex BM25 搜尋中產生更高的 mean_sim@20？
2. SearchParams 完整提取 (Strategy C: clean_topic + year_window + min_citations) 是否在 B 的基礎上再提升 mean_sim@20？
3. 改善是否在 25-query 集合上達到統計顯著 (Wilcoxon p < 0.05)？

## PoC 邊界（不做的事）
- 不修改任何 backend 檔案
- 不寫測試
- 不處理錯誤邊界
- 不整合現有 codebase 架構
- 不建立新分支或 worktree

## 技術選擇
- OpenAlex BM25 via pyalex `Works().search()`
- Embedding: `nomic-embed-text` via `LiteLLMEmbedding` (Ollama local)
- Transformation LLM: `LLM_SMART_MODEL` from .env (`ollama/ministral-3:14b-cloud`)
- LLM-as-judge: `LLM_VISION_FALLBACK_MODEL` from .env (`ollama_chat/gemma4:31b-cloud`)
- Metric: mean cosine similarity @ 20, precision@5 (LLM judge), Wilcoxon signed-rank

## Python 環境
- micromamba env：`py3.12`
- 新增的 packages：（不需要，所有 packages 已在 py3.12 env 中）

## 當前進度
- 停在：Step 6a（Approved）
- 已完成：實驗執行、結果分析、整合建議確認
- 下一步：整合至 agent-workflow-plan.md（已完成）
- 遇到的問題：無

## 驗證結果
Q1：✅ 成立 — Strategy B (LLM topic-only) mean_sim@20 從 0.439 提升至 0.465（+6%），Wilcoxon p=0.021 < 0.05
Q2：✅ 成立 — Strategy C (clean_topic + year_window + min_citations) mean_sim@20 進一步提升至 0.471（+7%），p=0.011
Q3：✅ 成立 — 25-query 集合上 B、C 皆達統計顯著（p < 0.05）

關鍵發現：
- BM25 正向 prompt（只保留 topic 關鍵字）優於負向 prompt（列舉要移除的條件）
- precision@5 B 略降（0.230→0.190）但 mean_sim@20 提升，整體 recall 更好
- search_filter() AND-logic 太嚴格，不適合作為主要搜尋策略
- clean_topic 保留 domain-specific 術語效果最佳（不做 step-back abstraction）

## 整合建議
1. 採用 Strategy C 的 `SEARCH_PARAMS_EXTRACTION_PMT`，使用正向 prompt 設計
2. 在 `supervisor_search` 步驟中呼叫，以 `LLMTextCompletionProgram` 搭配 `SearchParams` Pydantic schema
3. `clean_topic` 作為 `Works().search()` 的輸入；`year_window` / `min_citations` 作為 filter 參數
4. Prompt 中必須包含 `{user_query}` template variable 以確保 LLMTextCompletionProgram 正確傳入查詢
5. 移除舊的 `ENABLE_QUERY_REFORMULATION` / `_generate_search_query()` 邏輯

## 狀態歷程
- 2026-05-12：建立，in-progress
- 2026-05-14：實驗完成，結果驗證，approved
