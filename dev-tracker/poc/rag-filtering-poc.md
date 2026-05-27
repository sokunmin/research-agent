# PoC: rag-filtering

## 狀態
- 目前狀態：`approved`
- 建立時間：2026-05-27
- 最後更新：2026-05-27
- PoC 程式碼：`poc/rag-filtering/`
- 來源 spec：自然語言輸入

---

## 背景與目的

這個 PoC 驗證：**在學術論文 PDF 進入 RAG pipeline 之前，能否用 heading-based filtering 有效過濾 boilerplate 章節（References、Acknowledgements 等），避免這些無意義內容影響向量搜尋品質。**

整個 research-agent 的 pipeline 是：
```
PDF → Docling 解析 → HybridChunker → [ChunkFilter] → Embed → Qdrant → RAG 查詢
```
`[ChunkFilter]` 是這個 PoC 要驗證的元件，目前尚未整合進 backend。

---

## Chunking Strategy 原理

### 為何不用 paragraph / semantic chunking？

本專案使用 **Docling HybridChunker**，是 structure-aware chunking，原因如下：

學術論文 PDF 是**數位文字檔**（非掃描圖片），PDF 內部儲存的是帶樣式的文字指令串：

```
BT /H1 18 Tf (3 Methodology) Tj ET      ← 字型 18，判定為 heading
BT /Body 11 Tf (We propose a...) Tj ET  ← 字型 11，body 內文
── page break ──
BT /Body 11 Tf (Formally, given...) Tj ET  ← 還是 body，掛在同一個 heading
BT /H1 18 Tf (4 Experiments) Tj ET      ← 字型變回 18，新 heading 出現
```

Docling 讀取這些樣式資訊，將 PDF 重組為 **Document Structure Tree**（與頁面邊界無關）：

```
PDF（原始多頁）           Docling 解析後的 Document Tree
─────────────            ──────────────────────────────
Page 3                   [H1] 3 Methodology
 3 Methodology             [P] "We propose a novel..."
 We propose a...           [P] "The encoder consists..."
 The encoder...            [P] "Formally, given input x..."  ← 跨頁仍在同一節點
Page 4
 Formally, given...      [H1] 4 Experiments
 4 Experiments             [P] "We evaluate on..."
 We evaluate on...
```

**跨頁的內文只要字型沒變（仍是 body），就繼續掛在上一個 heading 底下，直到下一個 heading 字型出現為止。Page break 在 document tree 中沒有語意意義。**

### HybridChunker 的兩個規則

```
Document Tree
│
▼ HybridChunker (max_tokens=512, tokenizer=nomic-embed-text)
│
│  Rule 1（Structure）：沿 heading 邊界切，不跨 section 合併
│  Rule 2（Token）：同一 section 若超過 512 tokens，切成多個 chunk
│                   每個 chunk 繼承所在 section 的 heading
│
▼
Chunk 1  heading="3 methodology"  tokens=498  text="We propose..."
Chunk 2  heading="3 methodology"  tokens=312  text="As shown in Figure 2..."
Chunk 3  heading="4 experiments"  tokens=445  text="We evaluate on..."
Chunk 4  heading="references"     tokens=200  text="[1] Vaswani... [2] Brown..."
Chunk 5  heading="references"     tokens=195  text="[3] Devlin... [4] Radford..."
```

「Hybrid」的語意：Structure（heading 邊界）× Token（長度上限）取交集。

### References section 為何有多個 chunk？

References 章節通常有數十筆引用，合計遠超 512 tokens。HybridChunker 依 token limit 把它切成多個 chunk，每個 chunk 都帶 `heading="references"`。這是 **paper_frequency 計算 bug 的根源**（見 dev-tracker/error-log.md [2026-05-27]）。

---

## 核心驗證問題

1. **用 heading 字串比對能否精準識別 boilerplate 章節？**  
   → ✅ 成立。`chunk.meta.headings[0]` 由 Docling 可靠提供，exact + keyword 兩層比對足夠。

2. **28 篇論文的 heading 分布是否支持建立可複用的 blacklist？**  
   → ✅ 成立。792 個 unique headings 中，`references`（freq=1.00）、`acknowledgements`（0.39）是高頻 boilerplate；低頻變體以 keyword_filter 覆蓋。

3. **drop rate 是否合理（不誤殺內容章節）？**  
   → ✅ 成立。28 篇 drop rate 21%（349/1670 chunks），其中 92% 是 `references` chunks；`introduction`、`related work`、`experiments`、`conclusion` 等內容章節無誤殺。

---

## PoC 邊界（不做的事）

- 不處理 PDF 解析失敗（Docling OCR 錯誤）
- 不評估 filter 對 RAG retrieval 品質的實際改善（F1、MRR 等）
- 不整合進 backend pipeline（留給 git-feature）
- 不處理非英文論文的 heading

---

## 技術選擇

| 元件 | 選擇 | 理由 |
|---|---|---|
| PDF 解析 | Docling | 已在專案其他 PoC 驗證，M1 MPS 加速可用 |
| Chunker | Docling HybridChunker | 提供 `chunk.meta.headings`，可直接取 heading |
| Tokenizer | nomic-embed-text（HuggingFace） | 與 embed model 一致，token 計數準確 |
| max_tokens | 512 | 與 embed model 上限對齊 |
| Filter 設計 | exact_filter + keyword_filter 兩層 | exact 覆蓋高頻，keyword 覆蓋低頻變體 |

---

## Python 環境

- micromamba env：`py3.12`
- 主要 packages：`docling`、`docling-core`、`transformers`（nomic tokenizer）

---

## 產出檔案

```
poc/rag-filtering/
├── pdfs/                  # 28 篇 ArXiv PDF（用於統計與驗證）
├── run_analysis.py        # Phase 2A：統計 28 篇 heading 分布，輸出 analysis_stats.json
├── run_verify.py          # Phase 2C：驗證 ChunkFilter 對 28 篇的 drop 結果
├── chunk_filter.py        # Phase 2B：ChunkFilter class（可直接搬進 backend/tools/）
├── filter_config.json     # Blacklist 設定（exact_filter + keyword_filter + always_filter）
├── analysis_stats.json    # 792 個 unique headings 的 paper_frequency / mean_position
├── all_headings.txt       # 所有 heading 清單，供人工審查
├── run_analysis.log       # 上次 run_analysis.py 的輸出
└── run_verify.log         # 上次 run_verify.py 的輸出（含 drop 明細）
```

### filter_config.json 結構說明

```json
{
  "exact_filter": ["references", "acknowledgements", ...],
  "keyword_filter": ["acknowledgment", "broader impact", "ethic", ...],
  "always_filter": ["bibliography", "checklist", ...],
  "thresholds": {"paper_frequency": 0.4, "mean_position": 0.75},
  "n_papers": 28
}
```

- `exact_filter`：normalized heading 完全相符才 drop
- `keyword_filter`：normalized heading 包含任一關鍵字即 drop（覆蓋變體）
- `always_filter`：保留備查，原設計為 exact match，實際命中率低（見 error-log）
- Runtime：`normalized = heading.lower().strip()`

---

## 驗證結果

```
28 篇論文，共 1670 chunks

Total chunks : 1670
Kept         : 1321  (79.1%)
Dropped      :  349  (20.9%)

Top dropped headings:
  references           ×321  (exact)   ← 92% 的 drop
  acknowledgements     × 11  (exact)
  acknowledgments      ×  4  (exact)
  7. broader impacts   ×  3  (keyword)
  author contributions ×  2  (exact)
  + 8 more keyword hits ×1 each
```

---

## 整合建議

整合進 `backend/tools/filter_tools.py`，插入位置在 chunking 之後、embedding 之前：

```
download_papers → Docling parse → HybridChunker → ChunkFilter → embed → Qdrant
```

注意事項：
1. `chunk_filter.py` 無 Docling import，可直接搬進 backend，接受任何有 `.meta.headings` 的 chunk 物件
2. `filter_config.json` 路徑需更新為 `backend/` 下的路徑，或改為 `config.py` 的設定項
3. `always_filter` 欄位可考慮廢棄或改為 keyword_filter 的一部分，避免混淆
4. 未來新增論文語料時，重跑 `run_analysis.py` 更新 `analysis_stats.json`，再人工審查 `all_headings.txt` 決定是否擴充 blacklist

---

## 狀態歷程

- 2026-05-27：建立，in-progress
- 2026-05-27：Phase 2A 統計完成（792 headings，28 篇）
- 2026-05-27：修正 paper_frequency bug（per-paper dedup）
- 2026-05-27：Phase 2B ChunkFilter 實作完成
- 2026-05-27：Phase 2C 驗證完成（drop rate 21%，無誤殺）
- 2026-05-27：使用者確認，approved
