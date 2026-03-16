# SummaryGenerationWorkflow

負責從研究主題出發，自動搜尋、過濾、下載論文並生成 Markdown 摘要。

## 完整流程

```
  StartEvent  user_query: str
       │
       ▼
  [tavily_query]
  Tavily 搜尋 arXiv 相關論文
       │
       ▼
  TavilyResultsEvent
  results: List[TavilySearchResult]
       │
       ▼
  [get_paper_with_citations]
  對每個 Tavily 結果從 OpenAlex 取得論文與其引用
       │ fan-out，每篇論文各一個
       ├──► PaperEvent (paper 1)
       ├──► PaperEvent (paper 2)
       └──► PaperEvent (paper N)
            │
            ▼  (num_workers=4 並行)
       [filter_papers]
       new_fast_llm 評估每篇論文與研究主題的相關性
            │
            ▼
       FilteredPaperEvent × N (含 score + reason)
            │ collect all N
            │ 依 score + ArXiv 可用性排序，取前 n_max_final_papers=5 篇
            ▼
       [download_papers]
       透過 ArXiv 下載論文 PDF
            │
            ▼
       Paper2SummaryDispatcherEvent
       papers_path: str
            │ fan-out，每個 PDF 各一個
            ├──► Paper2SummaryEvent (pdf 1)
            ├──► Paper2SummaryEvent (pdf 2)
            └──► Paper2SummaryEvent (pdf M)
                 │
                 ▼  (num_workers=4 並行)
            [paper2summary]
            1. PDF → images（每頁一張）
            2. VLM (new_vlm) 從圖片生成摘要
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

### `tavily_query`

- 查詢語句格式：`"arxiv papers about the state of the art of {user_query}"`
- `tavily_max_results = 2`（預設）
- 輸出：`TavilyResultsEvent`，含標題與 URL

### `get_paper_with_citations`

- 對每個 Tavily 結果，呼叫 **OpenAlex**（`pyalex`）的 `search_papers()` + `get_citing_papers()`
- OpenAlex module-level config：`pyalex.config.email = settings.OPENALEX_EMAIL`（設一次，不重複）
- 自動去重（以 `entry_id` 為 key）
- 每篇論文 fan-out 發出一個 `PaperEvent`

```python
# agent_workflows/paper_scraping.py
paper = search_papers(query, limit=1)[0]
citations = get_citing_papers(paper, limit=50)
```

### `filter_papers`（並行 num_workers=4）

- 用 `new_fast_llm(temperature=0.0)` + `FunctionCallingProgram` 輸出結構化評分

```python
class IsCitationRelevant(BaseModel):
    score: int    # 相關性分數
    reason: str   # 判斷理由
```

### `download_papers`

- 等待所有 `FilteredPaperEvent`（fan-in）
- 依 `(score DESC, ArXiv 可用 DESC)` 排序，取前 5 篇
- 透過 `arxiv` Python 套件下載 PDF（最多重試 3 次）
- 無 ArXiv ID 的論文跳過

### `paper2summary_dispatcher`

- 掃描 `papers_path` 目錄下所有 `.pdf`
- 為每個 PDF 建立圖片輸出目錄與摘要路徑
- fan-out 發出 `Paper2SummaryEvent`

### `paper2summary`（並行 num_workers=4）

1. `pdf2images(pdf_path, image_output_dir)` — PDF 每頁轉 PNG
2. `summarize_paper_images(image_output_dir)` — 呼叫 `new_vlm().acomplete()` 逐頁分析並生成摘要
3. `save_summary_as_markdown(summary_txt, summary_path)` — 儲存 `.md`

### `finish`

- 等待所有 `SummaryStoredEvent`（fan-in）
- 斷言所有 `.md` 確實存在
- 回傳摘要目錄路徑（傳給 SlideGenerationWorkflow）

## 產出物

```
workflow_artifacts/
└── SummaryGenerationWorkflow/
    └── {wid}/
        └── data/
            ├── papers/
            │   ├── Paper Title A.pdf
            │   └── Paper Title B.pdf
            ├── papers_images/
            │   ├── Paper Title A/
            │   │   ├── page_1.png
            │   │   └── page_2.png
            │   └── ...
            └── papers_images/         # summary_path 指向 papers_images/
                ├── Paper Title A.md
                └── Paper Title B.md
```

## 設定參數

| 參數 | 預設值 | 說明 |
|------|--------|------|
| `tavily_max_results` | `2` | Tavily 回傳最多幾筆結果 |
| `n_max_final_papers` | `5` | 最多下載幾篇論文 |

## CLI 執行（獨立運行）

```bash
cd backend
python -m agent_workflows.summary_gen --user-query "powerpoint slides automation"
```
