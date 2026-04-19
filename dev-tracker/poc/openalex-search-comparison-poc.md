# PoC: openalex-search-comparison

## 狀態
- 目前狀態：`approved`
- 建立時間：2026-03-16
- 最後更新：2026-03-24
- 確認時間：2026-03-24
- PoC 程式碼：`poc/openalex-search-comparison/`
- 來源 spec：無（自然語言輸入）

## 核心驗證問題
1. OpenAlex standalone（無 Tavily）搜尋後，E14 能否過濾出相關學術論文？（取代 Tavily + citation expansion 路徑）
2. E14 two-stage filter（nomic-embed-text + qwen3.5:2b）能否有效過濾出相關論文，取代 cloud LLM？
3. 跨 5 個不同 domain 是否均能找到相關論文？（empirical validation across 5 diverse domains）
4. PDF 下載：OpenAlex OA 論文（diamond/gold/green）能否透過 fallback chain 穩定下載？

> **注意**：Q3 的目標是驗證「各 domain 均能找到相關論文」，≥10 是整合時的 sizing 參數，不是核心假設的評判門檻。

## PoC 邊界（不做的事）
- 不處理錯誤邊界
- 不寫測試
- 不考慮效能優化
- 不整合現有 codebase 架構

## 技術選擇
- pyalex（OpenAlex Python wrapper）
- E14 two-stage filter：nomic-embed-text (Stage-1) + qwen3.5:2b Strict (Stage-2)，透過 Ollama 本地執行
- PDF download：4 策略 fallback chain（arxiv_api → constructed_arxiv_url → pyalex_pdf_get → openalex_url）
- 相關性判斷共用 filter（E14）以隔離搜尋路徑品質差異

## Python 環境
- micromamba env：`py3.12`
- 新增的 packages：pyalex, python-dotenv, arxiv, requests, matplotlib, numpy, llama-index-embeddings-litellm, llama-index-llms-litellm, click

## 當前進度
- 停在：Step 6a（已 approved）
- 已完成：
  - [x] 初期 4 種搜尋方法比較（Exp 01–04）
  - [x] Tavily vs OpenAlex 比較（Exp 05–07）
  - [x] E14 ablation study（relevant-test.py，120 篇 ground truth，F1=0.974）→ `ablation-study-relevant.md`
  - [x] Threshold analysis（production-threshold-analysis.md，band=[0.500,0.610)）
  - [x] PDF download fallback chain 驗證（extract-id.py，5/5 成功）→ `extract-id.md`
  - [x] main.py 重構（10 個實驗，語意化命名，WorksResult class，Path A/B pipeline）
  - [x] Exp 08 per_page sensitivity（Path B filter，RESEARCH_TOPIC）
  - [x] Exp 09 Path A 生產路徑模擬（5 topics，含 Tavily 非確定性量化）
  - [x] Exp 10 Path B 替換路徑（5 topics，deterministic）
  - [x] 搜尋實驗報告 ablation-study-search.md（subagent 交叉驗證，1 處事實錯誤已修正）
- 下一步：整合進正式專案（`backend/agent_workflows/paper_scraping.py`）

## 驗證結果

### Q1：OpenAlex standalone 搜尋後，E14 能否過濾出相關論文？
**✅ 成立**

Path B（OpenAlex only）在全部 5 個 domain 均找到相關論文，無一失敗：

| Topic | Path A relevant | Path B relevant | Path B 有相關論文？ |
|-------|:--------------:|:---------------:|:------------------:|
| RESEARCH_TOPIC | 0 | 4 | ✓ |
| TOPIC_Q | 4 | 12 | ✓ |
| TOPIC_R | 1 | 2 | ✓ |
| TOPIC_S | 11 | 6 | ✓ |
| TOPIC_NEW | 37 | 40 | ✓ |

核心假設成立：不依賴 Tavily，OpenAlex search() + E14 filter 在所有 5 個 domain 均能找到相關論文。

**Path A（Tavily dependent）的結構性問題**，作為替換動機的直接證據：
- RESEARCH_TOPIC 完全失敗（0 candidates）：Tavily 三次均返回同一 seed "Local Attention Mechanism"，此論文在 OpenAlex filter(cites=50) 後無引用論文
- TOPIC_R seed 品質錯誤：Tavily 返回不相關的 "Leviathan: A Bio-Inspired Marine AGI" 作為 seed
- Path B 在 RESEARCH_TOPIC 仍找到 4 篇相關論文，Path A 為 0 — OpenAlex standalone 在此 topic 表現優於 Tavily+cites

**關於 Path B RESEARCH_TOPIC 和 TOPIC_R 的 relevant 數量偏低（4 和 2）**：原因是 `cited_by_count > 50` + `publication_year > 2023` 的組合對這兩個 topic 過嚴，屬於 integration sizing 的參數調整問題，不影響核心假設的成立。E14 正確排除了高引用但不相關的論文（如 MizAR 類）——這是系統按設計運作，非問題。

**Path B candidate pool 穩定性**：所有 topic 均取到 92–100 篇候選（Path A 最低 0 篇），結果 deterministic，任何人可重現。

### Q2：E14 能否取代 cloud LLM？
**✅ 成立**（獨立 ablation study 驗證）

- F1 = 0.974，Precision = 1.000，Recall = 0.950（120 篇 balanced ground truth）
- 詳見 `ablation-study-relevant.md`
- 生產路徑配置：nomic-embed-text threshold=0.500，band=[0.500,0.610)，見 `production-threshold-analysis.md`

### Q3：跨 5 個 domain 均能找到相關論文？
**✅ 成立**（5/5 domains）

Path B 在全部 5 個不同 domain（NLP/RL/CV/distributed/biomedical）均能找到相關論文。
≥10 的數量目標屬於整合 sizing 參數，RESEARCH_TOPIC（4）和 TOPIC_R（2）需放寬 `cited_by_count` 或 `year` filter 即可改善，不影響假設本身。

### Q4：PDF 下載可行性
**✅ 成立**（extract-id.py 驗證）

- 5/5 論文透過 arxiv_api strategy 下載成功
- Path B 的 oa_status filter（diamond/gold/green）確保候選論文的下載可行性
- ArXiv ID 需從 `locations[].landing_page_url` 解析（非 `work["ids"]`）
- 版本號必須 strip（避免舊版本）
- 詳見 `extract-id.md`

## 整合建議
1. **移除 Tavily 依賴**：改用 `Works().search(topic)` + quality filters，Path A 的 seed-dependent 方式脆弱
2. **Path B filter 參數調整**：`CITED_THRESHOLD_MED=50` + `YEAR_WINDOW=3` 對 ML 核心 topic 過嚴，建議試驗 `cited>10` + `year>today-5`
3. **E14 整合**：使用 nomic-embed-text (Stage-1) + qwen3.5:2b Strict (Stage-2)，band=[0.500,0.610)；`hi` 需依 topic 重新校準
4. **PDF 下載**：使用 extract-id.py 的 fallback chain，棄用 `arxiv.download_pdf()`（已 deprecated）
5. **oa_status filter**：確保 diamond/gold/green 才加入候選池，保障下載可行性

## 狀態歷程
- 2026-03-16：建立，in-progress（初期 4 種搜尋方法比較）
- 2026-03-17：E14 ablation study 完成（F1=0.974），threshold analysis 完成
- 2026-03-18：extract-id.py PDF 驗證完成（5/5），main.py 重構
- 2026-03-24：Exp 09/10 執行完成，搜尋報告 ablation-study-search.md 完成並交叉驗證，進度更新
