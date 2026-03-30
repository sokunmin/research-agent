# LLMs in Workflows

各 Workflow step 使用哪種 LLM、並行度、以及目前的 fallback 狀態。

---

## 全局架構

```
User: "attention mechanism"
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│            SummaryAndSlideGenerationWorkflow                        │
│                    (no LLM calls)                                   │
└──────────────┬──────────────────────────────────────────────────────┘
               │
       ┌───────┴────────┐
       ▼                ▼
  [Sub-wf 1]       [Sub-wf 2]
SummaryGen       SlideGen
```

---

## Sub-workflow 1：SummaryGenerationWorkflow

```
StartEvent (user_query)
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  tavily_query                                            │
│  [No LLM]  → Tavily API 搜尋 ArXiv paper titles         │
└──────────────────────────────┬───────────────────────────┘
                               │ TavilyResultsEvent
                               ▼
┌──────────────────────────────────────────────────────────┐
│  get_paper_with_citations                                │
│  [No LLM]  → OpenAlex API 取得 paper + 引用             │
│  → ctx.send_event(PaperEvent) × N 篇                    │
└──────────────────────────────┬───────────────────────────┘
                               │ PaperEvent × N (fan-out)
                               ▼
┌──────────────────────────────────────────────────────────┐
│  filter_papers  @step(num_workers=4)  ← 4 個並行！       │
│                                                          │
│  🔵 FAST LLM × 4 並行                                   │
│     new_fast_llm(temperature=0.0)                        │
│     用途：判斷 paper 是否與 research topic 相關           │
│     輸入：paper title + abstract                         │
│     輸出：IsCitationRelevant(score, reason)              │
│                                                          │
│  ⚠️  Rate Limit 高風險點！                               │
│     4 workers 同時打 → 秒超 Gemini 5 RPM 上限           │
└──────────────────────────────┬───────────────────────────┘
                               │ FilteredPaperEvent × N (fan-in)
                               ▼
┌──────────────────────────────────────────────────────────┐
│  download_papers                                         │
│  [No LLM]  → ArXiv 下載 top-5 PDF                       │
└──────────────────────────────┬───────────────────────────┘
                               │ Paper2SummaryDispatcherEvent
                               ▼
┌──────────────────────────────────────────────────────────┐
│  paper2summary_dispatcher                                │
│  [No LLM]  → PDF → images (pdf2images)                  │
│  → ctx.send_event(Paper2SummaryEvent) × PDF 數           │
└──────────────────────────────┬───────────────────────────┘
                               │ Paper2SummaryEvent × M (fan-out)
                               ▼
┌──────────────────────────────────────────────────────────┐
│  paper2summary  @step(num_workers=4)                     │
│                                                          │
│  🔴 VISION LLM × 4 並行                                 │
│     new_vlm()  (LiteLLMMultiModal)                       │
│     用途：把 PDF 頁面截圖 → 逐頁閱讀 → 產生摘要文字      │
│     輸入：PDF 轉成的圖片                                 │
│     輸出：paper summary markdown                         │
│                                                          │
│  ✅ 已有 fallback_models 設定                            │
└──────────────────────────────┬───────────────────────────┘
                               │ SummaryStoredEvent (*.md paths)
                               ▼
                          StopEvent → summary_dir
```

---

## Sub-workflow 2：SlideGenerationWorkflow

```
StartEvent (file_dir: summary_dir)
    │
    ▼
┌──────────────────────────────────────────────────────────┐
│  get_summaries  @step(num_workers=1)                     │
│  [No LLM]  → 讀取 *.md 檔案內容                         │
│  → ctx.send_event(SummaryEvent) × M (fan-out)           │
└──────────────────────────────┬───────────────────────────┘
                               │ SummaryEvent × M
                               ▼
┌──────────────────────────────────────────────────────────┐
│  summary2outline  @step(num_workers=1)                   │
│                                                          │
│  🔵 FAST LLM                                            │
│     new_fast_llm(0.1)                                    │
│     用途：摘要 → 精簡成投影片 outline（bullet points）   │
│     輸入：paper summary 全文                             │
│     輸出：SlideOutline (title, bullets)                  │
└──────────────────────────────┬───────────────────────────┘
                               │ OutlineEvent
                               ▼
┌──────────────────────────────────────────────────────────┐
│  gather_feedback_outline  (HITL)                         │
│  [No LLM]  → 展示 outline → 等待 user 輸入              │
│  → approve → OutlineOkEvent                             │
│  → reject  → OutlineFeedbackEvent → 回 summary2outline  │
└──────────────────────────────┬───────────────────────────┘
                               │ OutlineOkEvent × M (fan-in 等全部)
                               ▼
┌──────────────────────────────────────────────────────────┐
│  outlines_with_layout                                    │
│                                                          │
│  🟢 SMART LLM                                           │
│     new_llm(0.1)                                         │
│     用途：為每個 outline 選擇最適合的 PPTX layout        │
│     輸入：outline + 所有可用 layout 清單                 │
│     輸出：SlideOutlineWithLayout                         │
└──────────────────────────────┬───────────────────────────┘
                               │ OutlinesWithLayoutEvent
                               ▼
┌──────────────────────────────────────────────────────────┐
│  slide_gen                                               │
│                                                          │
│  🟢 SMART LLM (ReActAgent)                              │
│     new_llm(0.1)                                         │
│     用途：ReAct Agent 在 Docker sandbox 寫 Python code   │
│           用 python-pptx 生成投影片檔案                  │
│     輸入：SlideOutlineWithLayout JSON                    │
│     輸出：*.pptx 檔案                                    │
└──────────────────────────────┬───────────────────────────┘
                               │ SlideGeneratedEvent
                               ▼
┌──────────────────────────────────────────────────────────┐
│  validate_slides  @step(num_workers=4)                   │
│                                                          │
│  🔴 VISION LLM                                          │
│     new_vlm()                                            │
│     用途：逐頁截圖 → 視覺驗證投影片是否排版正確          │
│     輸入：pptx 轉成的圖片                               │
│     輸出：SlideValidationResult (is_valid, suggestion)   │
│                                                          │
│  ✅ 已有 fallback_models 設定                            │
└──────────────────────────────┬───────────────────────────┘
          ┌────────────────────┴──────────────────┐
          │ needs fix                              │ all valid
          ▼                                        ▼
┌─────────────────────────┐              ┌──────────────────┐
│  modify_slides          │              │   StopEvent      │
│                         │              │   → final.pptx   │
│  🟢 SMART LLM (ReAct)  │              └──────────────────┘
│     new_llm(0.1)        │
│     用途：依 feedback   │
│     修改投影片           │
│  → SlideGeneratedEvent  │
│  → 回到 validate_slides │
└─────────────────────────┘
```

---

## 彙整表

| LLM 類型 | 使用位置 | Workflow | num_workers | Fallback 狀態 |
|---------|---------|---------|-------------|--------------|
| 🔵 FAST LLM | `filter_papers` | SummaryGen | 4 並行 ⚠️ | ❌ 無 fallback |
| 🔵 FAST LLM | `summary2outline` | SlideGen | 1 | ❌ 無 fallback |
| 🟢 SMART LLM | `outlines_with_layout` | SlideGen | 1 | ❌ 無 fallback |
| 🟢 SMART LLM | `slide_gen` (ReActAgent) | SlideGen | 1 | ❌ 無 fallback |
| 🟢 SMART LLM | `modify_slides` (ReActAgent) | SlideGen | 1 | ❌ 無 fallback |
| 🔴 VISION LLM | `paper2summary` | SummaryGen | 4 並行 | ✅ 有 fallback |
| 🔴 VISION LLM | `validate_slides` | SlideGen | 4 並行 | ✅ 有 fallback |

---

## Rate Limit 風險分析

### 最高風險：`filter_papers`（FAST LLM × 4 並行）

`filter_papers` 有 `@step(num_workers=4)`，會同時對多篇 paper 呼叫 `new_fast_llm()`。
目前 `LLM_FAST_MODEL = "gemini/gemini-2.5-flash"`，free tier 上限為 **5 RPM**，
4 個 workers 瞬間打出 4 個請求，極易超過上限觸發 429。

### Provider Free Tier RPM 比較

| Provider | Model | RPM | TPM | RPD |
|---------|-------|-----|-----|-----|
| Groq | qwen/qwen3-32b | 60 | 6,000 | 1,000 |
| OpenRouter | gemma-3-27b-it:free | 20 | N/A | 50 |
| Gemini | gemini-2.5-flash | 5–10 | 250,000 | 250 |
| Mistral | mistral-small-2506 | 2 | 500,000 | 未公開 |
| Ollama | (local) | ∞ | ∞ | ∞ |

### 建議修正方向

為 `fast_llm` 和 `smart_llm` 加入 fallback，當 Gemini 回傳 429 時自動切換至備用 provider：

1. **`config.py`** — 新增 `LLM_FAST_FALLBACK_MODEL`、`LLM_SMART_FALLBACK_MODEL`
2. **`model_factory.py`** — `fast_llm()` / `smart_llm()` 加上 `additional_kwargs={"fallbacks": [...]}`

Fallback 優先序建議（RPM 高 → 低，Ollama 本地保底）：
```
Groq (RPM=60) → OpenRouter (RPM=20) → Gemini (RPM=5) → Ollama (∞)
```

詳見 `poc/litellm-multi-provider-chat/main.py` 的多 provider 驗證結果。

---

## num_workers 設計動機與 Rate Limit 權衡

### 為何作者用 4 個 workers？

`filter_papers` 的任務是對每篇 paper 個別呼叫一次 LLM 判斷相關性。
實際執行時，`get_paper_with_citations` 會從 Tavily 搜尋結果展開引用，產出 **20–40 篇** paper 需要過濾：

```
tavily_max_results = 2 筆搜尋結果
每筆 → OpenAlex citations 展開 → 共 ~40 篇 paper

若 num_workers=1（循序）：40 篇 × ~2秒/次 = 80 秒
若 num_workers=4（並行）：40 篇 ÷ 4   = ~20 秒  ← 快 4 倍
```

**設計動機**：filter_papers 的每次呼叫彼此獨立，天然適合並行，4 workers 是速度與資源的折衷。
**代價**：同時打出 4 個 LLM 請求，在 free tier（Gemini RPM=5）下必然超限。

---

### 為什麼 Tavily 搜尋 2 筆，最終卻有 20–40 篇 paper？

程式碼中有三層展開邏輯，導致 paper 數量大幅放大：

```
Step 1：Tavily 搜尋（tavily_max_results = 2）
─────────────────────────────────────────────
  輸入：user_query = "attention mechanism"
  輸出：2 個 paper title
    結果 1: "Attention Is All You Need"
    結果 2: "BERT: Pre-training of Deep Bidirectional Transformers"


Step 2：OpenAlex 展開「被引用論文」（★ 數量爆炸在這裡）
─────────────────────────────────────────────────────
  對每個 Tavily 結果呼叫 get_paper_with_citations()：

    def get_paper_with_citations(query, limit=1):
      papers = search_papers(query, limit=1)     # 找到 1 篇種子論文
      citations = get_citing_papers(papers[0])   # ← limit=50（hardcoded！）
      citations.append(papers[0])                # 把種子論文也加入
      return citations                           # 最多回傳 51 篇

  2 個 Tavily 結果 × 最多 51 篇 = 最多 102 篇
                                      │
                                      ▼
                          deduplicate（entry_id 去重）
                                      │
                                      ▼
                          實際約 20–40 篇（有重疊）


Step 3：filter_papers 需要過濾全部
──────────────────────────────────
  n_all_papers ≈ 20–40 篇，每篇都要一次 LLM call
  → 20–40 次 fast_llm 呼叫
```

**設計意圖**：「先廣撒網（引用網路），再用 LLM 精篩，最後只取 top-5 下載」。

```
Tavily  →  2 篇種子論文
             │
OpenAlex →  展開引用網路（誰引用了這 2 篇？）
             │  邏輯：引用了 BERT 的論文，很可能與相同主題相關
             ▼
filter_papers → LLM 一一判斷相關性
             │
             ▼  n_max_final_papers = 5
           取 top-5 下載
```

### 根本原因：`limit=50` 寫死在程式碼中

```python
# paper_scraping.py line 95
def get_citing_papers(paper: Paper, limit: int = 50):  ← 沒有對外暴露此參數
    results = Works().filter(cites=paper.entry_id).get(per_page=limit)
```

`limit=50` 沒有連接到任何 workflow 設定，無法從外部調整。

**最直接的減量方式**：把 `limit` 降為 10，paper 數從 40 篇降至約 10–15 篇：

```
limit=10：
  2 × (10 + 1) = 22 篇上限 → 去重後約 10–15 篇
  → filter_papers 只需 10–15 次 LLM call
  → num_workers=2 + delay=12s 變得可行
```

### 可調整的參數一覽

| 參數 | 位置 | 目前值 | 說明 |
|------|------|--------|------|
| `tavily_max_results` | `summary_gen.py` class 屬性 | `2` | 種子論文數量 |
| `limit` | `paper_scraping.py:95` | `50`（hardcoded） | 每篇種子論文的引用展開上限 |
| `n_max_final_papers` | `summary_gen.py` class 屬性 | `5` | 最終下載數量上限 |
| `num_workers` | `summary_gen.py:119` | `4` | filter_papers 並行度 |

---

## Delay 方案分析

### 各 Provider 安全 Delay 計算

```
公式：delay_per_call = 60秒 / RPM × num_workers

┌────────────────┬───────┬──────────────────┬──────────────────┐
│ Provider       │  RPM  │ 2 workers delay  │ 4 workers delay  │
├────────────────┼───────┼──────────────────┼──────────────────┤
│ Groq           │  60   │   2.0 秒         │   4.0 秒         │
│ OpenRouter     │  20   │   6.0 秒         │  12.0 秒         │
│ Gemini         │  10   │  12.0 秒         │  24.0 秒         │
│ Mistral        │   2   │  60.0 秒         │ 120.0 秒         │
└────────────────┴───────┴──────────────────┴──────────────────┘
```

### 對使用者體驗的影響（以 40 篇 paper 為例）

```
┌──────────────────────┬──────────┬────────────┬──────────────┐
│ 方案                 │ workers  │ delay/call │ 總過濾時間   │
├──────────────────────┼──────────┼────────────┼──────────────┤
│ 原本 4w, no delay    │    4     │    0 秒    │ ~20 秒 ❌爆限│
│ 2w + 12s delay       │    2     │   12 秒    │ ~280 秒 (~5分)│
│ 4w + 24s delay       │    4     │   24 秒    │ ~260 秒      │
│ Fallback Router      │    4     │    0 秒    │ ~20 秒 ✅    │
└──────────────────────┴──────────┴────────────┴──────────────┘
```

### Delay 方案優缺點

```
優點：
  ✅ 修改極簡單（改 num_workers + 加一行 asyncio.sleep）
  ✅ 確保不超過 RPM，穩定不爆 429

缺點：
  ❌ 嚴重拖慢流程（5 分鐘 vs 原本 20 秒）
  ❌ delay 值與 provider 綁定，換 provider 要重新計算
  ❌ Mistral (RPM=2) 完全不適用（需 delay 60 秒）
  ❌ 即使當下 RPM 有餘裕，仍無條件等待
```

---

## 建議：分兩步走

```
短期（立即可做）：
  num_workers: 4 → 2
  filter_papers step 加 asyncio.sleep(12)   ← Gemini (RPM=10) 安全值
  → 不爆 429，代價是過濾時間約 5 分鐘

長期（下一步）：
  LiteLLM Router + Fallback
  Groq (RPM=60) 為主力 → OpenRouter → Gemini → Ollama 本地保底
  → 不需要 delay，速度回到原本 ~20 秒
  → 換 provider 只需改 .env，不動程式碼
```
