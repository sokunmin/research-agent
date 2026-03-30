# LLMs in Workflows

各 Workflow step 使用哪種 LLM、並行度、以及 rate limit 狀態。

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
│  discover_candidate_papers                               │
│                                                          │
│  🔵 FAST LLM（查詢改寫）                                │
│     new_fast_llm(temperature=0.0)                        │
│     用途：將 user_query 改寫為 BM25 學術搜尋語           │
│     輸入：user_query                                     │
│     輸出：reformulated search query string               │
│                                                          │
│  [No LLM] OpenAlex 全文搜尋 → fan-out PaperEvent × N    │
└──────────────────────────────┬───────────────────────────┘
                               │ PaperEvent × N (fan-out)
                               ▼
┌──────────────────────────────────────────────────────────┐
│  filter_papers  @step(num_workers=NUM_WORKERS_FAST=2)    │
│                                                          │
│  Stage 1：Embedding 相似度 [No remote LLM]              │
│     ollama/nomic-embed-text（本地，無 API 費用）          │
│     對每篇 paper 計算 cosine similarity                  │
│     < 0.500  → 直接拒絕                                  │
│     ≥ 0.610  → 直接接受                                  │
│     0.500–0.610 → Stage 2                               │
│                                                          │
│  Stage 2：LLM 驗證（僅 borderline，實測約 41%）         │
│  🔵 FAST LLM（選擇性）                                  │
│     new_fast_llm(temperature=0.0)                        │
│     Survey heuristic 提示判斷邊界論文相關性              │
│                                                          │
│  ✅ Rate limit 風險低：Stage 1 本地，Stage 2 僅 ~41%    │
└──────────────────────────────┬───────────────────────────┘
                               │ FilteredPaperEvent × N (fan-in)
                               ▼
┌──────────────────────────────────────────────────────────┐
│  download_papers                                         │
│  [No LLM]  → 4-strategy fallback 下載 top-N PDF         │
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
│  paper2summary  @step(num_workers=NUM_WORKERS_VISION=2)  │
│  + asyncio.sleep(DELAY_SECONDS_VISION=12.0)              │
│                                                          │
│  🔴 VISION LLM × 2 並行                                 │
│     new_vlm()  (LiteLLMMultiModal)                       │
│     用途：把 PDF 頁面截圖 → 逐頁閱讀 → 產生摘要文字      │
│     輸入：PDF 轉成的圖片                                 │
│     輸出：paper summary markdown                         │
│                                                          │
│  ✅ 已有 fallback_models 設定                            │
│  ✅ 12s delay（Gemini RPM=10，2 workers 安全值）         │
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
│  summary2outline  @step(num_workers=NUM_WORKERS_FAST=2)  │
│  + asyncio.sleep(DELAY_SECONDS_FAST=2.0)                 │
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
│  validate_slides  @step(num_workers=NUM_WORKERS_VISION=2)│
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

| LLM 類型 | 使用位置 | Workflow | num_workers | Delay | Fallback 狀態 |
|---------|---------|---------|-------------|-------|--------------|
| 🔵 FAST LLM | `discover_candidate_papers`（查詢改寫） | SummaryGen | 1 | 0s | ❌ 無 fallback |
| 🔵 FAST LLM | `filter_papers` Stage-2（borderline 約 41%） | SummaryGen | NUM_WORKERS_FAST=2 | 0s | ❌ 無 fallback |
| 🔵 FAST LLM | `summary2outline` | SlideGen | NUM_WORKERS_FAST=2 | 2.0s | ❌ 無 fallback |
| 🟢 SMART LLM | `outlines_with_layout` | SlideGen | 1 | 0s | ❌ 無 fallback |
| 🟢 SMART LLM | `slide_gen` (ReActAgent) | SlideGen | 1 | 0s | ❌ 無 fallback |
| 🟢 SMART LLM | `modify_slides` (ReActAgent) | SlideGen | 1 | 0s | ❌ 無 fallback |
| 🔴 VISION LLM | `paper2summary` | SummaryGen | NUM_WORKERS_VISION=2 | 12.0s | ✅ 有 fallback |
| 🔴 VISION LLM | `validate_slides` | SlideGen | NUM_WORKERS_VISION=2 | — | ✅ 有 fallback |
| 🏠 LOCAL EMBED | `filter_papers` Stage-1（全部論文） | SummaryGen | — | — | N/A（本地） |

---

## Rate Limit 風險分析

### `filter_papers`（2-stage，風險大幅降低）

新 pipeline 將 `filter_papers` 改為 2-stage 設計，大幅降低 LLM call 頻率：

```
舊架構（已替換）：
  每篇 paper → 1 次 fast_llm call
  100 篇候選 → 100 次 LLM calls ← ⚠️ 高 rate limit 風險

新架構：
  每篇 paper → Stage 1 (Ollama local, no API cost)
               ├── sim < 0.500  → 直接拒絕（no LLM）
               ├── sim ≥ 0.610  → 直接接受（no LLM）
               └── borderline   → Stage 2 fast_llm（僅 ~41%）
  100 篇候選 → 約 41 次 LLM calls  ← ✅ 風險降低 ~60%
```

Stage-1 使用 Ollama 本地服務（`ollama/nomic-embed-text`），無 API rate limit 限制。

### `paper2summary`（Vision LLM × 2 workers + 12s delay）

- `NUM_WORKERS_VISION=2` + `DELAY_SECONDS_VISION=12.0`
- 適用 Gemini RPM=10：`60 / 10 × 2 = 12.0s`
- 有 fallback model 保護（`LLM_VISION_FALLBACK_MODEL`）

### Provider Free Tier RPM 比較

| Provider | Model | RPM | TPM | RPD |
|---------|-------|-----|-----|-----|
| Groq | gpt-oss-120b / gpt-oss-20b | 60 | — | — |
| Gemini | gemini-2.5-flash | 10 | 250,000 | 250 |
| OpenRouter | gemma-3-27b-it:free | 20 | N/A | 50 |
| Mistral | mistral-small-2506 | 2 | 500,000 | — |
| Ollama | nomic-embed-text (local) | ∞ | ∞ | ∞ |

---

## num_workers 設計動機

### `filter_papers`：embedding 本地，LLM 選擇性

新 pipeline 的 `filter_papers` 主要工作量在 Stage-1 embedding（本地），Stage-2 LLM 只處理 borderline 論文：

```
100 篇候選論文
  ├── Stage 1 (Ollama local)：100 次 embedding ← 快速，無 API 費用
  └── Stage 2 (fast_llm)   ：約 41 次 LLM calls
      │
      NUM_WORKERS_FAST=2, DELAY_SECONDS_FAST=2.0s
      → Groq RPM=60 下安全：60/60×2=2s
```

### `paper2summary`：Vision LLM 並行，有 delay 保護

```
Vision LLM（Gemini，RPM=10）
NUM_WORKERS_VISION=2, DELAY_SECONDS_VISION=12.0s
→ 60/10×2=12s delay → 安全不爆 429

若切換到 Groq（RPM=60）：
  DELAY_SECONDS_VISION=2.0 → 顯著加快
```

---

## Delay 安全值速查

```
公式：delay_per_call = 60秒 / RPM × num_workers

┌────────────────┬───────┬──────────────────┬──────────────────┐
│ Provider       │  RPM  │ 1 worker delay   │ 2 workers delay  │
├────────────────┼───────┼──────────────────┼──────────────────┤
│ Groq           │  60   │   1.0 秒         │   2.0 秒         │
│ OpenRouter     │  20   │   3.0 秒         │   6.0 秒         │
│ Gemini         │  10   │   6.0 秒         │  12.0 秒         │
│ Mistral        │   2   │  30.0 秒         │  60.0 秒         │
└────────────────┴───────┴──────────────────┴──────────────────┘
```

換 provider 時，更新 `.env` 的 `DELAY_SECONDS_*` 對應到新的安全值即可。

---

## 建議：為 fast_llm / smart_llm 加入 fallback

目前 fast_llm 和 smart_llm 無 fallback，429 時會直接失敗。長期建議：

1. **`config.py`** — 新增 `LLM_FAST_FALLBACK_MODEL`、`LLM_SMART_FALLBACK_MODEL`
2. **`model_factory.py`** — `fast_llm()` / `smart_llm()` 加上 `additional_kwargs={"fallbacks": [...]}`

Fallback 優先序建議（RPM 高 → 低，Ollama 本地保底）：
```
Groq (RPM=60) → OpenRouter (RPM=20) → Gemini (RPM=10) → Ollama (∞)
```

詳見 `poc/litellm-multi-provider-chat/main.py` 的多 provider 驗證結果。
