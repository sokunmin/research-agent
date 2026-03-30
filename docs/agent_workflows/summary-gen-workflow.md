# SummaryGenerationWorkflow

負責從研究主題出發，自動搜尋、過濾、下載論文並生成 Markdown 摘要。

## 完整流程

```
  StartEvent  user_query: str
       │
       ▼
  [discover_candidate_papers]
  1. fast_llm 將 user_query 改寫為 BM25 學術搜尋語
  2. OpenAlex 全文搜尋（is_oa, citations>50, 近 3 年）
       │ fan-out，每篇論文各一個
       ├──► PaperEvent (paper 1)
       ├──► PaperEvent (paper 2)
       └──► PaperEvent (paper N)
            │
            ▼  (num_workers=NUM_WORKERS_FAST 並行)
       [filter_papers]
       PaperRelevanceFilter 2-stage 評估相關性：
         Stage 1 — 本地 embedding 相似度（Ollama nomic-embed-text）
         Stage 2 — fast_llm 驗證（僅 borderline 論文，約 41%）
            │
            ▼
       FilteredPaperEvent × N
       (relevance: PaperRelevanceResult{is_relevant, similarity_score})
            │ collect all N
            │ 過濾 is_relevant=True，依 similarity_score 排序，取前 NUM_MAX_FINAL_PAPERS 篇
            ▼
       [download_papers]
       PaperDownloader 4-strategy 下載（ArXiv API → ArXiv direct → PyAlex → OA URL）
            │
            ▼
       Paper2SummaryDispatcherEvent
       papers_path: str
            │ fan-out，每個 PDF 各一個
            ├──► Paper2SummaryEvent (pdf 1)
            ├──► Paper2SummaryEvent (pdf 2)
            └──► Paper2SummaryEvent (pdf M)
                 │
                 ▼  (num_workers=NUM_WORKERS_VISION 並行, delay=DELAY_SECONDS_VISION)
            [paper2summary]
            1. PDF → images（每頁一張）
            2. VLM 從圖片生成摘要
            3. 儲存為 .md 檔案
                 │
                 ▼
            SummaryStoredEvent × M
            fpath: Path
                 │ collect all M
                 ▼
            [finish]
            確認所有 .md 存在，回傳摘要目錄路徑
                 │
                 ▼
            StopEvent
            result: summary_dir (str)
```

## Step 詳細說明

### `discover_candidate_papers`

取代舊的 Tavily + OpenAlex 引用展開方式，改為直接全文搜尋。

1. **查詢改寫**：呼叫 `fast_llm`，依 `ACADEMIC_QUERY_REFORMULATION_PMT` 將 user_query 改寫為 BM25-optimized 學術搜尋語。
2. **OpenAlex 全文搜尋**：呼叫 `fetch_candidate_papers(search_query)`，套用以下過濾條件：
   - `is_oa=True`（開放存取）
   - `oa_status=diamond|gold|green`（可下載 PDF）
   - `cited_by_count > PAPER_CANDIDATE_MIN_CITATIONS`（預設 >50 引用）
   - `publication_year > today - PAPER_CANDIDATE_YEAR_WINDOW`（預設近 3 年）
   - `type != retraction`（排除撤稿）
   - 依 `cited_by_count DESC` 排序
   - 最多取 `PAPER_CANDIDATE_LIMIT` 篇（預設 100）
3. **去重**：以 `entry_id` 去重後，fan-out 發出 `PaperEvent`。
4. **`n_all_papers`** 存入 workflow state，供 `download_papers` fan-in 計數。

```python
# agent_workflows/summary_gen.py
search_query = await _generate_search_query(topic, new_fast_llm(temperature=0.0))
papers = fetch_candidate_papers(search_query)
papers = list({p.entry_id: p for p in papers}.values())  # deduplicate
```

### `filter_papers`（並行 num_workers=NUM_WORKERS_FAST）

使用 `PaperRelevanceFilter` 進行 2-stage 相關性評估，每篇論文獨立進行：

**Stage 1 — Embedding 相似度**（本地，無 API 費用）
- Embed: `title + abstract + keywords + topics` 組合成單一字串
- 模型：`LLM_RELEVANCE_EMBED_MODEL`（預設 `ollama/nomic-embed-text`，本地 Ollama）
- Cosine similarity 與 research topic embedding 比較（topic embedding 有 cache）
- `sim < 0.500`：直接拒絕（明顯不相關）
- `sim >= 0.610`：直接接受（明顯相關）
- `0.500 ≤ sim < 0.610`：進入 Stage 2

**Stage 2 — LLM 驗證**（僅 borderline 論文，實測約 41%）
- Survey heuristic 提示：「這篇論文是否會出現在 {topic} 的 survey 中？」
- 使用 `fast_llm`，輸入 title + abstract + keywords + topics + primary_category + concepts
- 回傳 `yes` / `no`

```python
class PaperRelevanceResult(BaseModel):
    is_relevant: bool
    similarity_score: float  # Stage-1 cosine similarity，用於下游排序
```

### `download_papers`

- 等待所有 `FilteredPaperEvent`（fan-in）
- 過濾 `is_relevant=True`，依 `similarity_score DESC` 排序，取前 `num_max_final_papers` 篇
- 呼叫 `download_paper_pdfs()`，使用 `PaperDownloader` 的 4-strategy fallback chain：
  1. **arxiv_api**：`arxiv.Client()` 取得 canonical URL（3s rate-limit delay）
  2. **arxiv_direct_url**：`https://arxiv.org/pdf/{arxiv_id}`（3s delay）
  3. **pyalex_pdf**：`Works()[openalex_id].pdf.get()`
  4. **openalex_oa_url**：`open_access.oa_url`（browser headers，支援 AAAI 等出版社）
- 無 ArXiv ID 的論文跳過 Strategy 1 & 2，仍可嘗試 Strategy 3 & 4
- 下載失敗的論文跳過（記錄 warning），不中斷流程
- PDF 命名規則：優先用 ArXiv ID（`1706.03762.pdf`），無則用 OpenAlex ID（`W2741809807.pdf`）

### `paper2summary_dispatcher`

- 掃描 `papers_path` 目錄下所有 `.pdf`
- 將 `n_pdfs` 存入 state
- 為每個 PDF 建立圖片輸出目錄與摘要路徑
- fan-out 發出 `Paper2SummaryEvent`

### `paper2summary`（並行 num_workers=NUM_WORKERS_VISION）

1. `asyncio.sleep(DELAY_SECONDS_VISION)` — rate limit 保護（Gemini RPM=10 時建議 12s）
2. `pdf2images(pdf_path, image_output_dir)` — PDF 每頁轉 PNG
3. `summarize_paper_images(image_output_dir)` — 呼叫 VLM（`LiteLLMMultiModal`）逐頁分析並生成摘要
4. `save_summary_as_markdown(summary_txt, summary_path)` — 儲存 `.md`

### `finish`

- 等待所有 `SummaryStoredEvent`（fan-in）
- 缺少 .md 的項目只 warning，不 raise（允許部分下載失敗）
- 回傳摘要目錄路徑（傳給 `SlideGenerationWorkflow`）

## 產出物

```
workflow_artifacts/
└── SummaryGenerationWorkflow/
    └── {wid}/
        ├── papers/
        │   ├── 1706.03762.pdf           # ArXiv ID 命名
        │   └── W2741809807.pdf          # OpenAlex ID 命名（無 ArXiv ID 時）
        └── papers_images/
            ├── 1706.03762/
            │   ├── page_1.png
            │   └── page_2.png
            ├── 1706.03762.md            # paper summary（summary_path 指向此目錄）
            └── W2741809807.md
```

## 設定參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `NUM_MAX_FINAL_PAPERS` | `5` | 最多下載幾篇論文（過濾後取 top-N） |
| `PAPER_CANDIDATE_LIMIT` | `100` | OpenAlex 最多搜尋幾篇候選論文 |
| `PAPER_CANDIDATE_MIN_CITATIONS` | `50` | 論文最少引用次數門檻 |
| `PAPER_CANDIDATE_YEAR_WINDOW` | `3` | 最近幾年的論文（publication recency） |
| `LLM_RELEVANCE_EMBED_MODEL` | `ollama/nomic-embed-text` | Stage-1 embedding 模型（本地 Ollama） |
| `NUM_WORKERS_FAST` | `2` | filter_papers 並行度 |
| `DELAY_SECONDS_FAST` | `2.0` | filter_papers 每次呼叫間隔（Groq RPM=60） |
| `NUM_WORKERS_VISION` | `2` | paper2summary 並行度 |
| `DELAY_SECONDS_VISION` | `12.0` | paper2summary 每次呼叫間隔（Gemini RPM=10） |

## CLI 執行（獨立運行）

```bash
cd backend
python -m agent_workflows.summary_gen --user-query "powerpoint slides automation"
```
