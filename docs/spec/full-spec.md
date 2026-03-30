# Academic Paper RAG — Multi-Agent System · 完整實作指南
> **版本：** v6.0 | **最後更新：** 2026-03-03 
> **用途：** 理解這個系統的所有設計決策（why & how）、知道哪些方向已經研究過且被否決。讀完此文件可以直接開始實作，不需要任何其他文件。
> **進度：** 未完成(有些細節尚未定案)
---

## 系統用途：一句話版本

使用者輸入一個 ML/AI 研究主題，系統自動從 ArXiv 搜尋相關論文、解析 PDF、建立知識庫，透過多個 AI agent 協作分析，最終輸出詳細版研究報告（`.docx`）和簡報（`.pptx`）。

---

## 完整 Pipeline 總覽

```
User Query
  ↓
[1] Planning Agent
    → 把 topic 拆成 N 個 sub-questions + ArXiv 搜尋策略
    → 輸出 ResearchPlan（Pydantic）
  ↓
[2] Orchestrator
    → 呼叫 ArXiv API 下載 PDF
    → 用 LlamaParse v2 解析每份 PDF
    → Content-Type Routing → 分類 chunks → 存入 Qdrant
  ↓
[3] Researcher Agents（N 個，asyncio 並行）
    → 每個 agent 負責一個 sub-question
    → Hybrid Search + BGE Reranker → 生成答案
  ↓
[4] Analyst Agent（ReflAct + Focused ReAct early stop）
    → 整合所有 Researcher 的結果
    → 跨論文比較、去重、找矛盾、歸納
    → 輸出 StructuredFindings（Pydantic）
  ↓
[5] Writer Agents × 2（asyncio 並行）
    → Writer A：生成詳細版 .docx
    → Writer B：生成簡報版 .pptx
  ↓
[6] Reviewer Agent（LLM-as-Judge）
    → coverage_score < 0.75？→ 生成 targeted guidance → retry（max 2×）
    → coverage_score >= 0.75？→ 輸出最終報告
```

---

## Tech Stack 速查表

| 層次 | 選擇 | 版本 / 設定 |
|------|------|------------|
| Framework | LlamaIndex | AgentWorkflow + @step |
| PDF Parser | LlamaParse v2 | `parse_tier` 參數化（預設 `agentic_plus`）；cache 命中不重計費 |
| Vector DB | Qdrant | 本地 Docker |
| Embedding | text-embedding-3-small / nomic-embed-text / bge-large-en-v1.5 / qwen3-embedding-8b | Stage 0 ablation 決定，四個候選代表不同維度（見 Feature 20） |
| Reranker | BGE-Reranker-v2-m3 | 本地推論，top-20 → top-5 |
| Agent Reasoning | ReflAct + Focused ReAct | Analyst Agent 使用 |
| LLM 統一介面 | **LiteLLM** | 單一介面串接所有 provider，換 model 只改一個字串 |
| LLM（Index-time）| gemini/gemini-2.5-flash-lite | Stage 0b contextual retrieval，free tier 1,000 RPD |
| LLM（Pipeline 2A）| ollama/qwen3:8b | Stage 2A pattern ablation 固定，本地免費 |
| LLM（Pipeline 2B）| qwen3:8b / openai/gpt-oss-20b / nvidia/nemotron-49b | Stage 2B 三個不同 family 對比，均透過 OpenRouter 或 Ollama |
| LLM（Eval）| gemini/gemini-2.5-flash | 所有 Stage 固定，**必須和所有 pipeline LLM 不同廠商** |
| Evaluation | RAGAS + RAGAS Agentic Metrics | 三層架構 |
| Observability | LlamaTrace / Arize Phoenix | 一行掛載自動 capture |
| Experiment Framework | PipelineConfig + 6-stage ablation framework | 單一控制點，每次只改一個變數 |
| Output | python-docx + python-pptx | — |

---

## Section 01：資料清洗

### 核心問題

ML/AI 學術論文 PDF 包含六種本質不同的內容類型，每種類型對 RAG 的挑戰截然不同。沒有任何單一 parser 能完美處理全部——這是整個 Data Cleaning 設計的出發點。

| 內容類型 | RAG 的挑戰 | 如果不處理會發生什麼 |
|---------|-----------|-------------------|
| 純文字段落 | 段落太長或太短 | LLM context 太長或 chunks 缺乏完整語意 |
| LaTeX 公式 | `$\mathcal{L}$` 的 embedding 和「cross-entropy loss」距離很遠 | 搜尋公式相關概念時完全找不到 |
| 實驗表格 | `84.2` 對 embedding 無意義 | 精確數字查詢（「GPT-4 的 BLEU score 是多少」）失敗 |
| 程式碼 | 不能在 function 中間切斷 | 程式邏輯不完整，LLM 無法理解 |
| CV 影像 / 訓練曲線 | 純圖片，沒有文字就進不了向量資料庫 | 這些圖片的資訊完全遺失 |
| NN 架構圖 | 資訊密度最高（一張圖可以代替 500 words）| 對論文核心貢獻一無所知 |

---

### Feature 1：LlamaParse v2 `agentic` — PDF 解析

**Why：** 需要 `type` 欄位 + VLM 圖片描述，這是整個 routing 架構的基礎

傳統 PDF parser（PyPDF2、Marker）輸出純文字或 Markdown，沒有 element type 標記。你不知道一段文字是「表格內容」還是「章節標題」還是「公式」，無法做差異化處理。

LlamaParse v2 的 JSON 輸出格式：
```json
{"type": "table",    "content": "| Method | BLEU |...", "page": 5}
{"type": "figure",   "content": "Figure 3: The self-attention mechanism...", "page": 3}
{"type": "equation", "content": "L = -sum(y_i * log(y_hat)) [cross-entropy loss]", "page": 2}
```

**Tier 選擇（由 `PipelineConfig.parse_tier` 控制）：**

| Tier | 官方建議用途 | 備注 |
|------|------------|------|
| `cost_effective` | 文字為主，結構簡單 | 不適合圖表密集的 ML 論文 |
| `agentic` | 有圖表，需要智慧推理 | 多數 ML 論文的合理選擇 |
| `agentic_plus` | **最複雜文件，含 scientific papers** | 官方明列 use case，預設值 |

預設使用 `agentic_plus`，理由：官方文件明確列出 scientific papers 為其適用場景。**實際 credits/頁的確切數字在官方文件找不到明確記載**，建議 PoC 跑完後到 LlamaCloud Dashboard 查看實際消耗，再決定是否降 tier。

**⚠️ LlamaParse Cache：** 相同 PDF 只有第一次 parse 扣 credit，後續重跑（調整 chunking、retrieval config）命中 cache 不再計費。開發期間的主要費用只發生在「新增論文」或「強制 bust cache 重跑」時。

```python
# 如何切換 tier（不需要改 code，只改 config）
config = PipelineConfig(name="poc_cost_test", parse_tier="agentic")      # 省 credit 測試
config = PipelineConfig(name="poc_quality",   parse_tier="agentic_plus") # 正式 corpus
```月在 Free Tier 內。同一文件 48 小時 cache，開發期間不重複計費。⚠️ 不要使用 `tier="scientific_papers"`——那是 90 credits/頁，功能完全一樣，貴一倍。

---

### Feature 2：Content-Type Routing — 六種 NodeParser

**Why：** 不同類型的最佳 chunk 策略截然不同，一刀切必定在某種 query 類型上系統性失敗

**How：** LlamaParse 輸出的每個 element 都有 `type` 欄位，根據這個欄位路由到對應處理邏輯：

```
LlamaParse JSON Output
  ├── type="text"     → chunking 策略（見 Stage 0a ablation，起點為 SentenceSplitter 512）
  ├── type="table"    → 雙重表示法（見 Feature 3）
  ├── type="figure"   → 直接建 TextNode（VLM 描述已是可 embed 的文字）
  │     └── 如果是 nn_architecture 且描述 < 100 words → 用 Claude 補強描述
  ├── type="code"     → CodeSplitter（language-aware，保留 function 邊界）
  └── type="equation" → 直接建 TextNode（LaTeX + 括號內自然語言描述）
```

每個 chunk 附帶 metadata：`arxiv_id`、`chunk_type`、`figure_type`、`section`、`section_priority`、`has_math`、`page_num`。Qdrant 可以用這些 metadata 做精確 filter（「只看 Results section 的 table 類型 chunks」）。

> ⚠️ **`type="text"` 的 chunking 策略是 Stage 0a ablation 的變數，不是已確定的選擇。** `SentenceSplitter 512` 是合理的起點，但 paragraph-aware / section-aware / semantic chunking 哪個最適合 ML 論文需要用數據決定。詳見 Feature 20 Stage 0a。

---

### Feature 3：表格雙重表示法

**Why：** 一個表格需要服務兩種本質不同的 query，單一格式必定有一種失敗

- **精確數字查詢**（「GPT-4 在 MMLU 的分數」）→ 需要 BM25 精確匹配 `84.2` 這個字串
- **語意比較查詢**（「哪個方法在低資源設定下效果最好」）→ 需要向量搜尋理解語意

**How：** 每個表格建立兩個 chunk：
1. `table_raw`：原始 Markdown 格式 → 供 BM25 sparse vector 使用
2. `table_summary`：LLM 生成的自然語言摘要 → 供 dense vector 語意搜尋

`MarkdownElementNodeParser.get_nodes_and_objects()` 內建此功能，不需要自己實作。

---

### Feature 4：Contextual Retrieval — Chunk 上下文補強

**Why：** 孤立的 chunk 失去了它在論文中的位置語意（decontextualized chunk）

一個 chunk「損失率下降了 3.2%」如果沒有上下文，不知道它在哪篇論文、哪個 section、比較的是什麼 baseline。

**介入點：Index Time，不是 Query Time。**
這是一個 **indexing 時的 LLM 前處理步驟**——費用在資料建立時就發生，不是每次 query 時發生。名稱雖然叫「Contextual Retrieval」，但它的本質是在 embedding 之前對 chunk 做 LLM 增強，和 Hybrid Search / Reranker 這些 query-time 技術本質不同。

```
[Index Time]
chunk 原文：「損失率下降了 3.2%」
    ↓ LLM call（在這裡發生成本）
prepend 後：「這是 LoRA（Hu et al., 2021）論文 Experiments section 中
             比較不同 rank 設定效果的段落。損失率下降了 3.2%」
    ↓ embed → 存入 Qdrant

[Query Time]
搜尋「LoRA rank 對損失的影響」→ 能正確找到這個 chunk
```

Anthropic 研究數據：最高提升 retrieval 準確率 49%。

**成本結構：** 每個 HIGH_VALUE chunk 需要一次 LLM call。這是固定的 index-time 成本，論文重新 index 時才重新發生，不影響 query latency。

**成本控制：** 只套用在 `section_priority = "HIGH_VALUE"` 的 chunks（Abstract / Methodology / Experiments / Results）。References / Background 的 ROI 低，不處理。**這個「HIGH_VALUE only vs 全部 chunks」的 trade-off 是 Stage 0b ablation 的核心問題。** 詳見 Feature 20 Stage 0b。

**評估方式：** 和 chunking 一樣在 retrieval layer 評估（不需要跑完整 pipeline），主要指標是 ContextRecall。但評估時必須把 LLM call 成本一起納入 ROI 計算。

---

### Feature 5：Chunk 品質過濾

**Why：** 低品質 chunks 進入 Qdrant 後，搜尋時成為噪音

兩個硬性規則，不符合直接丟棄：
1. **最小長度：** 30 words 以下通常是 header、figure label、page number
2. **符號比例：** 特殊符號（`@`, `#`, `\`, `|`）佔比超過 15% 通常是解析失敗的 LaTeX 殘渣

---

## Section 02：Multi-Agent 架構

### 核心設計原則

**Orchestrated pipeline，不是 open-ended agent loop。** 每個 agent 有明確的輸入輸出，pipeline 有確定的執行順序。Deep research 的任務結構是確定的，不需要 LLM 即時決定「下一步要哪個 agent」。

**Pydantic 強制結構化通訊。** Agent 之間傳遞的所有 data 都是 Pydantic model，不允許 free-form string。Schema 不符在 validation 階段立刻報錯，不會讓錯誤靜默地傳遞到下游。

---

### Feature 6：Planning Agent — 研究計畫生成

**Why：** 模糊的 topic 直接送進 RAG，搜尋品質會很低

**How：** Planning Agent 輸出 `ResearchPlan`（Pydantic model），包含：
- `sub_questions`：把 topic 分解成 3–5 個具體、可被文獻回答的問題
- `priority_sections`：對這個 topic 哪些論文 section 最重要
- `arxiv_queries`：對應的 ArXiv API search queries

這個 `ResearchPlan` 是整個 pipeline 的「合約」——Reviewer Agent 用它評估 coverage，`AgentGoalAccuracy` 指標也以它作為 reference。

---

### Feature 7：並行執行 — asyncio

**Why：** N 個 Researcher Agent 的搜尋任務彼此獨立，沒有理由序列執行

**How：** Researcher Agents 和 Writer Agents 都用 `asyncio.gather()` 並行。N 個 Researcher 並行讓 latency 從 N× 降為 1×；Writer Docx + Pptx 並行讓寫作階段不額外增加時間。

---

### Feature 8：Analyst Agent — ReflAct + Focused ReAct

這是 v6.0 最關鍵的升級。

**ReAct 的失敗模式（尤其在 local LLM）：**

ReAct 每步問「下一步應該做什麼」。問題：不強制 LLM 確認當前狀態和原始目標的 alignment。幾步後容易出現：
1. **Context drift：** 回應偏離原始 sub-question，越走越遠
2. **Infinite loop：** 重複呼叫相同 tool + 相同參數，永遠不結束

**ReflAct 的解法（EMNLP 2025）：**

每步問法改為「**當前狀態 vs 目標的 gap 是什麼，為了縮小這個 gap，下一步應該做什麼？**」

```
每步 ReflAct prompt 核心結構：
任務目標：{原始 query}
當前狀態：{到目前為止知道什麼}
已觀察到：{上一步的 tool 結果}

反思：目標和當前狀態之間的差距是什麼？
為了縮小這個差距，下一步應該做什麼？
```

實驗數據（EMNLP 2025，Llama-3.1-8B）：平均比 ReAct 高 **27.7%**；hallucination rate 更低（hallucination 根源是 unguided reasoning，不是 verbosity）；ReflAct 無任何補強的情況下勝過「ReAct + Reflexion + WKM」組合——強化推理骨幹 > 疊加補丁。

**Focused ReAct 的兩個補充機制（零架構成本，只改 prompt）：**

1. **Reiteration（防 context drift）：** 每次 LLM call 都把原始 query 放在 prompt 最前面的 system message。一行修改，強制 LLM 每步都「重讀」目標。

2. **Early Stop（防 infinite loop）：** 維護一個 `Set`，記錄已執行過的 `(tool_name, args)` pair。偵測到重複時立刻停止，呼叫 `_force_final_answer()`。

Focused ReAct 在 Gemma 2B / Phi-3.5-mini / Llama 3.1 8B 上：+530% accuracy，−34% runtime。

---

### Feature 9：Reviewer Agent — Reflexion-Style Targeted Guidance

**Why：** 盲目 retry ≠ 有效 retry

舊版：`coverage < 0.75 → retry`。Researcher / Analyst 不知道為什麼被 retry，重新執行一遍完全一樣的操作，浪費 LlamaParse credits。

**How：** `coverage_score < 0.75` 時，Reviewer 先生成 **targeted guidance**（2–3 句），說明：
- 為什麼上一輪沒有找到缺失內容
- 下一輪 Researcher 應該用什麼不同策略
- Analyst 在哪個 tool 的參數上需要調整

這段 guidance 作為 context 傳給下一輪。這是 Reflexion 論文的核心機制：把失敗軌跡壓縮成 episodic memory，讓 agent 從失敗中學習，不是無記憶重試。

Retry 限制：`max 2×`（避免費用失控），`coverage 閾值 0.75`（0.9 這種高閾值會導致 2–3× 成本增加）。

---

### Feature 10：ReasoningModule — 可注入介面

**Why：** Ablation study 需要「只換 reasoning pattern，其他全部一致」

**How：** `ReasoningModule` 是 abstract base class，`AnalystAgent` 初始化時接受注入：

```python
# 換 reasoning pattern 不需要修改任何 Agent 邏輯
agent_react         = AnalystAgent(ReActModule(),        tools)
agent_focused_react = AnalystAgent(FocusedReActModule(), tools)
agent_reflact       = AnalystAgent(ReflActModule(),      tools)
```

Stage 2 ablation study 真正做到「只改一個變數」。

---

## Section 03：RAG Pipeline

### Feature 11：Hybrid Search（BM25 + Dense Vector）+ RRF

**Why：** 兩種搜尋模式各有盲點，缺任何一個都有系統性失敗場景

- BM25 盲點：不理解語意。「memory-efficient fine-tuning」和「parameter-efficient training」BM25 不知道是同一件事。
- Dense Vector 盲點：不精確。`84.2`、`LoRA`、`BLEU score` 精確匹配比語意 embedding 可靠。

**RRF（Reciprocal Rank Fusion）融合：** `score = Σ 1/(60 + rank_i)`。不需要調兩者 score 係數，對不同 query 類型都穩定。

搜尋時也做 chunk-type routing：`table_raw` 優先走 BM25；`figure` 純走 dense vector。

---

### Feature 12：Query Transformation — 三層策略

**Why：** 單一 query embedding 無法覆蓋所有相關文件的語意空間

三層策略互補，覆蓋不同 query 類型：

**Multi-Query（基礎，全 query 類型）：** 用 LLM 生成 4 個語意相近但表達不同的 query 變體，各自搜尋，RRF 合併。擴大語意覆蓋範圍。

**Step-Back Prompting（Why / How / Explain 類型）：** 把具體問題抽象化到更高層次原理。「LoRA 為什麼效果好」→「什麼是 low-rank approximation 的理論基礎」。找到理論支撐的文獻。

**HyDE — Hypothetical Document Embedding（What / Which / How many 類型）：** LLM 先生成一段假設性回答，用這段**回答**的 embedding 去搜尋（而非問題本身）。答案的 embedding 更接近論文裡真實答案的表達方式。設定 `include_original=True` 防止 HyDE 偏離主題。

---

### Feature 13：BGE Reranker — 兩個動機

**動機一（精準化）：** Bi-encoder（BM25/vector）快但不精準；cross-encoder 同時看 query + document，精準但慢。方案：bi-encoder 快速取 top-20，cross-encoder 精準從 20 裡選 top-5。

**動機二（Lost in the Middle，Stanford 2023）：** LLM 對 context 中間位置的資訊記憶力最差。最相關的 chunk 排在第 10 位，LLM 很可能沒有有效利用它。Reranker 確保最相關的 chunks 排在最前面。

選 BGE-Reranker-v2-m3：本地推論（零 API cost），BEIR 學術領域 benchmark 領先。實驗數據：Faithfulness 0.71 → 0.87（+0.16）。

---

### Feature 14：Qdrant 作為 Vector DB

**Why：** 原生 Sparse + Dense Hybrid Search；本地 Docker 開發與 cloud production 無縫切換

Qdrant 原生支援 Hybrid Search，不需要自己維護 BM25 index 並手動做 RRF fusion（ChromaDB 需要）。Payload filtering 能力強：「只找 cs.LG 分類、2023 年後、chunk_type 為 figure、figure_type 為 nn_architecture 的 chunks」——精確 filter。

---

## Section 04：Evaluation 體系

### 為什麼不能只用 RAGAS

RAGAS 設計給線性 RAG pipeline。Multi-Agent 有 6 個 agent，失敗可以發生在任何節點，錯誤會放大並傳遞給下游。RAGAS 完全看不到 agent 層面的問題。

三層評估架構：

```
Layer 1（黑盒）：最終報告有沒有解決問題？
  → RAGAS AgentGoalAccuracy + Reviewer LLM-as-Judge

Layer 2（打開黑盒）：哪個 agent 在哪個環節出問題？
  → RAGAS ToolCallAccuracy（Analyst）
  → RAGAS Faithfulness / ContextRecall / ContextPrecision（Researcher）
  → 自訂 Quantitative Exact Match（數字精確度）

Layer 3（推理軌跡）：推理路徑合不合理？有沒有無限迴圈？
  → LlamaTrace（Arize Phoenix）視覺化瀑布圖
```

---

### Feature 15：LlamaTrace（Arize Phoenix）— Observability

**Why：** LlamaIndex 官方合作夥伴，對 `@step` 有原生語意理解。LangFuse 是通用 span，看不出 step 語意。

掛載（一行程式碼）：
```python
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
LlamaIndexInstrumentor().instrument(tracer_provider=tracer_provider)
# 之後所有 LlamaIndex 呼叫自動被 capture
```

能找到：Analyst tool call 在重複同樣的查詢（無限迴圈前兆）、Researcher retrieval 耗時異常、哪個 agent 消耗最多 token。

**Phoenix → pandas → RAGAS 資料橋接：** `px.Client().query_spans()` 匯出成 pandas DataFrame → 餵給 RAGAS 評分 → `px.Client().log_evaluations()` 寫回 Phoenix Dashboard，統一在一個地方看。

---

### Feature 16：RAGAS Agentic Metrics

**`AgentGoalAccuracy`（Layer 1）：** 用 `ResearchPlan.sub_questions` 作為 reference，評估最終報告是否涵蓋所有 sub-questions，輸出 binary 0/1。

**`ToolCallAccuracy`（Layer 2）：** 評估 Analyst 的 ReflAct 迴圈每次 tool call 有沒有選對工具、用對參數。需要在 test set 建構時手動標注「理想的 tool call 序列」。一次性人工投入，之後每次 pipeline 改動自動回歸測試。

**`TopicAdherence`（Layer 2）：** 評估 agent 有沒有在被問到超出 scope 的問題時正確拒絕。

---

### Feature 17：自訂 Quantitative Exact Match

**Why：** LLM-as-Judge 對精確數字判斷不可靠——「84.2 vs 84.8%」LLM 可能認為「接近就算對」

提取 response 中所有數字，和 ground truth 做精確比較。閾值：差距 < 0.1% 才算正確。

---

### Feature 18：Test Set 建構（55 個固定 queries）

**Why：** 每次 pipeline 改動都需要可重現的評估

| 類型 | 數量 | 設計目的 |
|------|------|---------|
| Factual | 15 | 精確事實查詢 |
| Quantitative | 15 | 表格數字精確匹配，驗證 Quantitative EM |
| Multi-paper synthesis | 15 | 跨論文比較，驗證 Analyst tool call 序列 |
| Out-of-scope detection | 10 | 驗證 TopicAdherence（正確拒絕不相關問題）|

每個 query 都有：ground truth answer、reference tool call sequence、expected paper IDs。

---

## Section 05：Modular Experiment Framework

**核心設計哲學：** 每次只改一個變數，用數據決定每個技術是否值得加入。

**六個 Stage 的完整執行順序：**

```
Stage 0 ：Embedding Model           → 零 LLM cost，retrieval layer 評估
Stage 0a：Chunking Strategy         → 零 LLM cost，retrieval layer 評估
Stage 0b：Contextual Retrieval ROI  → 有 index-time LLM cost，retrieval layer 評估
Stage 1 ：RAG Pipeline              → 零 LLM cost，retrieval layer 評估
Stage 2A：Agent Pattern             → 需要跑完整 pipeline（固定 Qwen3 8B）
Stage 2B：LLM Scale                 → 需要跑完整 pipeline（固定最佳 pattern）
```

Stage 0、0a、0b、1 的共同特性：**不需要跑 LLM generation**，只需要評估 retrieval layer。這讓四個 stage 合計的執行成本極低，可以快速迭代找到最佳 indexing + retrieval config，再固定給 Stage 2 使用。

**Stage 2 拆成 2A 和 2B 的原因：** 「agent pattern」和「LLM 規模」是兩個獨立變數。如果同時換 pattern 和 LLM（原本的 `s2_full_system` 設計），你無法回答「結果提升是因為 pattern 更好，還是因為 70B 更強」。拆開之後兩個問題都能獨立回答。

**評估指標分層：**

| Stage | 核心指標 | 為什麼這些指標 |
|-------|---------|--------------|
| 0（embedding）| ContextRecall、ContextPrecision、QuantEM | 不同 model 的 tokenizer 對 ML 術語的 fragmentation 程度不同，直接影響 recall |
| 0a（chunking）| ContextRecall、ContextPrecision、QuantEM | Chunking 切壞了會讓相關資訊散在 chunk 邊界兩側 |
| 0b（ctx retrieval）| ContextRecall 提升 vs index LLM calls | ROI 問題：花多少 LLM call 換來多少 recall 提升 |
| 1（RAG）| ContextRecall、ContextPrecision、QuantEM | 和 0a 相同指標，但現在改的是 query-time 決策 |
| 2A（agent pattern）| AgentGoalAccuracy、ToolCallAccuracy、Latency | 固定 Qwen3 8B，只看 pattern 的貢獻 |
| 2B（LLM family × scale）| AgentGoalAccuracy、ToolCallAccuracy、Latency | 固定最佳 pattern，比較三個不同 family |

---

### Feature 19：PipelineConfig — 單一控制點

**Why：** 每個技術決策的貢獻必須可以被獨立量化

```python
@dataclass
class PipelineConfig:
    name: str
    # ── Indexing 層（Stage 0 前置 + Stage 0a/0b，index-time 決策）──
    embedding_model: Literal[
        "text-embedding-3-small",  # OpenAI，業界 baseline，有 API cost
        "nomic-embed-text",        # Ollama 本地，8192 token，測試去 API 依賴的代價
        "bge-large-en-v1.5",       # 本地，BEIR 學術領域強，⚠️ 512 token 上限
        "qwen3-embedding-8b",      # 本地/OpenRouter，MTEB Multilingual #1（2025/06），32K token
    ] = "text-embedding-3-small"
    chunk_strategy: Literal[
        "sentence_512",      # 起點：SentenceSplitter + 512 token 上限
        "paragraph_aware",   # 優先在 paragraph 邊界切，超過才繼續切
        "section_aware",     # 不跨 section 切，利用 LlamaParse metadata
        "semantic",          # embedding 偵測語意轉折點，SemanticSplitterNodeParser
    ] = "sentence_512"
    contextual_retrieval_scope: Literal[
        "none",              # 不做 contextual retrieval
        "high_value_only",   # 只套用 HIGH_VALUE sections（現有設定）
        "all_chunks",        # 套用全部 chunks（成本最高）
    ] = "none"
    parse_tier: Literal[
        "cost_effective",  # 文字為主，圖表少的論文
        "agentic",         # 有圖表，能 VLM 描述
        "agentic_plus",    # 最高精度，scientific papers 官方建議用途
    ] = "agentic_plus"     # 預設：官方 use case 吻合，PoC 後根據實際 credit 消耗調整
    index_llm: str = "gemini/gemini-2.5-flash-lite"  # Stage 0b index-time LLM，固定
    # ── RAG 層（Stage 1，query-time 決策）──
    retrieval_mode: Literal["vector", "hybrid"] = "vector"
    query_transform: Literal["none", "multi_query", "hyde", "step_back", "all"] = "none"
    use_reranker: bool = False
    # ── Agent 層（Stage 2A：固定 Qwen3 8B；Stage 2B：固定最佳 pattern）──
    agent_pattern: Literal["none", "react", "focused_react", "reflact"] = "none"
    use_multi_agent: bool = False
    use_reviewer: bool = False
    # ── 模型（Stage 2B 的控制變數）──
    llm_model: Literal[
        "ollama/qwen3:8b",                                      # 本地，Stage 2A/2B baseline
        "openrouter/openai/gpt-oss-20b",                        # OpenAI open-weight，MoE，16GB RAM
        "openrouter/nvidia/llama-3.3-nemotron-super-49b-v1",    # NVIDIA RAG fine-tune，免費
    ] = "ollama/qwen3:8b"
    eval_llm: str = "gemini/gemini-2.5-flash"  # 固定裁判，必須和所有 pipeline LLM 不同廠商
```

**欄位分層的邏輯：**

| 層次 | 欄位 | 介入點 | 成本結構 | 對應 Stage |
|------|------|--------|---------|-----------|
| Indexing | `parse_tier` | Index time | LlamaParse credits（一次性，cache 後不重收）| Pre-Stage 0，固定後不再變動 |
| Indexing | `embedding_model` | Index time | 本地免費或 OpenAI API | Stage 0 |
| Indexing | `chunk_strategy` | Index time | 無額外 LLM cost | Stage 0a |
| Indexing | `contextual_retrieval_scope` | Index time | 每個 chunk 一次 `index_llm` call | Stage 0b |
| RAG | `retrieval_mode`, `query_transform`, `use_reranker` | Query time | 每次 query 發生 | Stage 1 |
| Agent | `agent_pattern`, `use_reviewer` | Query time | 每次 query 發生 | Stage 2A |
| Model | `llm_model` | Query time | 每次 query 發生 | Stage 2B |

**`embedding_model` 的 token 上限 tension：** `bge-large-en-v1.5` 的 512 token 上限剛好等於 `chunk_size=512`，overlap 部分可能被截斷。Stage 0 ablation 完成後如果 bge 勝出，需要把 `chunk_size` 調降至 ~440 確保 overlap 不被截掉。`qwen3-embedding-8b` 的 32K 上限完全沒有這個問題。

---

### Feature 20：完整 Ablation Framework — 四階段

**完整執行順序：**

```
Stage 0 ：Embedding Model Ablation
    → 找到最佳 embedding model（tokenizer 對 ML 術語的 fragmentation 最少）
    ↓ 固定最佳 embedding_model
Stage 0a：Chunking Strategy Ablation
    → 找到最佳 text chunking 策略（不需要跑 LLM，純 retrieval 評估）
    ↓ 固定最佳 chunk_strategy
Stage 0b：Contextual Retrieval Ablation
    → 量化 LLM 補強的 ROI（index-time cost vs ContextRecall 提升）
    ↓ 固定最佳 contextual_retrieval_scope
Stage 1 ：RAG Pipeline Ablation
    → 找到最佳 query-time retrieval 組合
    ↓ 固定最佳 RAG config
Stage 2A：Agent Pattern Ablation（固定 Qwen3 8B）
    → 在控制模型規模的情況下，量出每個 pattern 的獨立貢獻
    ↓ 固定最佳 agent_pattern
Stage 2B：LLM Family × Scale Ablation（固定最佳 pattern）
    → 在控制 pattern 的情況下，量出模型規模的獨立貢獻
    → 同時可以觀察 pattern × scale 的 interaction effect
```

每個 stage 都固定上一個 stage 的最佳結果，確保每次只有一個變數在改變。

---

#### Stage 0 — Embedding Model Ablation（前置，所有 stage 的基礎）

**評估點：** Retrieval layer（不需要跑 LLM generation）
**固定：** `sentence_512` chunking（最快的起點，用來做初篩）
**主要指標：** ContextRecall（最重要）、ContextPrecision、QuantEM

**為什麼 Embedding Model 要獨立成一個 stage：**

大多數 RAG 專案把 embedding model 當成固定的基礎設施，選了就不再碰。但對 ML 學術論文，這個假設是危險的。不同 model 的 tokenizer 對下列類型文本的處理方式截然不同：

```
LaTeX 公式：「∇θL = Σ yi log(ŷi)」
  好的 tokenizer：[∇θ][L][=][Σ][yi][log][ŷi]   → 7 tokens，語意完整
  差的 tokenizer：[â][ˆ][‡][θ][L][=]...          → fragment，embedding 語意劣化

ML 術語：「PEFT」
  好的 tokenizer：[PEFT]                          → 1 token
  差的 tokenizer：[P][EF][T]                      → 3 tokens，embedding 分散

精確數字：「84.2% on MMLU」
  token 上限短的 model（512）：長 chunk 可能截掉這個數字
```

**四個候選 model 的對比：**

| Config | Model | Token 上限 | 費用 | 選入維度 |
|--------|-------|-----------|------|---------|
| `s0_embed_openai` | `text-embedding-3-small` | 8192 | OpenAI API | **業界 baseline**，多數 RAG 專案預設選擇，必須作為對照組 |
| `s0_embed_nomic` | `nomic-embed-text` | 8192 | Ollama 本地，免費 | **本地長 context**，MTEB 高分，測試「去 API 依賴是否有代價」|
| `s0_embed_bge` | `bge-large-en-v1.5` | 512 ⚠️ | 本地，免費 | **BEIR 學術 domain 強**，刻意保留以量化「學術強但 context 短」的 trade-off |
| `s0_embed_qwen3` | `qwen3-embedding-8b` | 32768 | Ollama 本地 / OpenRouter | **MTEB Multilingual #1（2025/06）**，32K 無截斷疑慮，取代原 mxbai（相同 512 限制但 MTEB 分數不如 qwen3）|

**⚠️ `bge` 的 512 token 上限注意事項：**
`chunk_size=512` 剛好等於 bge 的上限，overlap（64 tokens）部分會被截掉。如果 bge 在 Stage 0 勝出，後續所有 stage 的 `chunk_size` 需要調降至 ~440（512 - 64 - 8 buffer）。`qwen3-embedding-8b` 的 32K 上限完全沒有此問題。

**快速驗證 tokenizer fragmentation（執行 Stage 0 前的 5 分鐘篩選）：**

```python
from llama_index.embeddings.litellm import LiteLLMEmbedding

sample_texts = [
    "LoRA: Low-Rank Adaptation of Large Language Models",
    "∇θL = Σ yi log(ŷi)",                     # LaTeX 公式
    "BLEU score of 84.2% on WMT14 En-De",     # 精確數字
    "parameter-efficient fine-tuning methods",  # ML 術語
    "self-attention mechanism with O(n²) complexity",
]

model_names = [
    "text-embedding-3-small",   # LiteLLM → OpenAI
    "ollama/nomic-embed-text",  # LiteLLM → Ollama local
    "ollama/bge-large-en-v1.5", # LiteLLM → Ollama local
    "ollama/qwen3-embedding-8b",# LiteLLM → Ollama local
]

for model_name in model_names:
    model = LiteLLMEmbedding(model_name=model_name)
    token_counts = [len(model._tokenizer.encode(t)) for t in sample_texts]
    print(f"{model_name}: avg={mean(token_counts):.1f} tokens")
    # tokens 數越少 = tokenizer 對這類文本效率越高
```

這個快速測試能在 5 分鐘內篩掉對 ML 術語 fragmentation 最嚴重的 model，再用 ContextRecall 做最終決定。

**預估結果：**

| Config | ContextRecall | ContextPrecision | QuantEM | Index Cost |
|--------|-------------|-----------------|---------|------------|
| s0_embed_openai | 0.78 | 0.73 | 0.63 | OpenAI API |
| s0_embed_nomic | 0.76 | 0.71 | 0.60 | 零 |
| s0_embed_bge | 0.80 | 0.77 | 0.66 | 零（⚠️ chunk_size 需調降）|
| s0_embed_qwen3 | 0.82 | 0.79 | 0.68 | 零（Ollama）/ 極低（OpenRouter）|

⚠️ 上表為預估值，以實際執行結果為準。

**解讀規則：**
- 本地免費 model（nomic / bge / qwen3）的 ContextRecall 和 OpenAI 差距 < 0.03：換本地 model，長期節省 API cost
- bge 勝出但 chunk_size 需調降：調降後重跑一次確認 ContextRecall 不下降才固定
- 所有 model 差距 < 0.03：embedding model 不是這個 corpus 的瓶頸，選最便宜的（nomic 本地）

---

#### Stage 0a — Chunking Strategy Ablation

**評估點：** Retrieval layer（不需要跑 LLM generation）
**主要指標：** ContextRecall（最重要）、ContextPrecision、QuantitativeEM
**額外成本：** 零（chunking 本身不需要 LLM call）

**四個策略的 trade-off：**

| Config | 策略 | 核心邏輯 | ML 論文的潛在問題 |
|--------|------|---------|-----------------|
| `s0a_sentence_512` | SentenceSplitter，token 上限 512 | 在最近的句子邊界切，但不超過 512 tokens | 不感知 paragraph 邊界；一個討論三個概念的 paragraph 可能被切成兩個不完整的 chunk |
| `s0a_paragraph_aware` | paragraph_separator="

"，超過才繼續切 | 優先在 paragraph 邊界切；只有段落 > 512 tokens 時才繼續往下切 | ML 論文 paragraph 長度差異大（8 tokens ～ 800 tokens），短的太碎，長的還是要繼續切 |
| `s0a_section_aware` | group_by_section → 在 section 內部切 | 保證不跨 section 邊界；利用 LlamaParse `section` metadata | section 太長時（Results 可能 3,000 tokens）還是要在 section 內切，但至少不跨 section 混 |
| `s0a_semantic` | SemanticSplitterNodeParser，cosine similarity 偵測轉折 | 在語意真正改變的地方切，不受 token 數量驅動 | 需要 embed 整份文件才能決定怎麼切（額外 embedding cost）；chunk size 非常不均勻（30 ～ 600 tokens） |

**LlamaIndex 實作對應：**

```python
# s0a_sentence_512（現有起點）
SentenceSplitter(chunk_size=512, chunk_overlap=64)

# s0a_paragraph_aware
SentenceSplitter(
    chunk_size=512,
    chunk_overlap=64,
    paragraph_separator="

",  # 優先在 paragraph 邊界切
)

# s0a_section_aware
for section_blocks in group_by_section(llama_output):   # 利用 LlamaParse metadata
    splitter = SentenceSplitter(
        chunk_size=512, chunk_overlap=64, paragraph_separator="

"
    )
    chunks = splitter.get_nodes_from_documents(section_blocks)
    # 每個 chunk 的 metadata 必定包含相同的 section 欄位，不跨 section

# s0a_semantic
SemanticSplitterNodeParser(
    buffer_size=1,
    breakpoint_percentile_threshold=95,  # 語意距離超過第 95 百分位才切
    embed_model=embed_model,
)
```

**預估結果與解讀邏輯：**

| Config | ContextRecall | ContextPrecision | QuantEM | Index Cost |
|--------|-------------|-----------------|---------|------------|
| s0a_sentence_512 | 0.73 | 0.69 | 0.58 | 零 |
| s0a_paragraph_aware | 0.79 | 0.74 | 0.62 | 零 |
| s0a_section_aware | 0.75 | 0.80 | 0.61 | 零 |
| s0a_semantic | 0.82 | 0.76 | 0.64 | embedding cost × 文件總 tokens |

⚠️ 上表為預估值，以實際執行結果為準。

**解讀規則（執行後用這個框架判斷）：**
- ContextRecall 差距 < 0.03：BGE Reranker 已消化了 chunking 差異，不值得換策略
- ContextRecall 差距 ≥ 0.05：chunking 策略對這個 corpus 有實質影響，選最高的
- section_aware 的 ContextPrecision 明顯高但 ContextRecall 明顯低：說明它找得精準但找得少——deep research 場景中漏資訊比多噪音更嚴重，這個 trade-off 通常不划算
- semantic 的 ContextRecall 最高但 chunk size 差異極大：搭配 Reranker 時效果較好，因為 Reranker 可以處理 size 不均的問題

---

#### Stage 0b — Contextual Retrieval Ablation

**評估點：** Retrieval layer（和 Stage 0a 相同，不需要跑 LLM generation）
**固定：** Stage 0a 的最佳 `chunk_strategy`
**主要指標：** ContextRecall（提升幅度）、Index LLM Cost（每次重新 index 的費用）

**Index-time LLM：`gemini/gemini-2.5-flash-lite`（固定，不是 ablation 變數）**

這個 stage 的 LLM 只做一件事：替每個 chunk 生成上下文前綴（「這個 chunk 在整篇論文的哪個位置、討論什麼」）。任務非常簡單，不需要強推理力。選 Flash-Lite 的理由：
- Free tier 1,000 RPD，`all_chunks` scope 約 2,400 calls 分兩天跑完，零成本
- 速度快，indexing 時間短
- 和 eval LLM（`gemini-2.5-flash`）不同 model，不會混用
- Fallback：如果 free tier 仍不夠，改用 `ollama/qwen3:8b` 本地跑（一次性工作，速度慢點沒關係）

**為什麼要把 contextual retrieval 從 Stage 1 拆出來：**

原本的 Stage 1 最後一個 config `s1_full_rag` 是「+ Contextual Retrieval」——但這樣混在 query-time retrieval ablation 裡是有問題的。Contextual Retrieval 的費用在 **index time** 發生，和 Hybrid Search / Reranker 這些 **query-time** 技術的成本結構根本不同。如果兩者混在一起，你無法分開回答：「搜尋策略有沒有效」和「花 LLM call 補強 chunk context 值不值得」。

**三個 scope 選項：**

| Config | 套用範圍 | 預估 Index LLM Calls（10 篇論文）| 預估 ContextRecall 提升 |
|--------|---------|-------------------------------|------------------------|
| `s0b_none` | 不做（對照組）| 0 | — |
| `s0b_high_value_only` | Abstract / Methodology / Experiments / Results | ~800 calls | +0.06 ～ +0.12 |
| `s0b_all_chunks` | 所有 chunks | ~2,400 calls | +0.08 ～ +0.15 |

**ROI 判斷框架：**

```
ROI = ContextRecall 提升幅度 / Index LLM Cost

如果 s0b_high_value_only vs s0b_none：
  ContextRecall +0.08，花 800 LLM calls → 值得（每次重新 index 才發生）

如果 s0b_all_chunks vs s0b_high_value_only：
  ContextRecall 再 +0.03，多花 1,600 LLM calls → 通常不值得

判斷標準：
  邊際提升 < 0.03 → 不值得增加 scope
  邊際提升 ≥ 0.05 → 值得擴大 scope
```

**Gemini free tier 是否足夠：** 10 篇論文的 `high_value_only` 約 800 LLM calls，Gemini 2.5 Flash-Lite free tier 每天 1,000 requests，完全足夠在一天內完成 index。`all_chunks` 的 2,400 calls 分兩天跑完。

---

#### Stage 1 — RAG Pipeline Ablation（固定：Stage 0 最佳 indexing）

**評估點：** Retrieval layer（不需要跑 LLM generation）
**固定：** Stage 0a 的最佳 `chunk_strategy` + Stage 0b 的最佳 `contextual_retrieval_scope`
**主要指標：** ContextRecall、ContextPrecision、QuantitativeEM

| Config | 只改這一個 | 量化這個技術的貢獻 |
|--------|-----------|-------------------|
| `s1_naive` | vector-only 基線 | — |
| `s1_hybrid` | + Hybrid Search | BM25 的貢獻 |
| `s1_hybrid_mq` | + Multi-Query transform | Query transform 的貢獻 |
| `s1_hybrid_mq_rerank` | + BGE Reranker | Reranker 的貢獻（同時解決 Lost in the Middle）|
| `s1_full_rag` | + Step-Back + HyDE | 剩餘 query transform 的貢獻 |

---

#### Stage 2A — Agent Pattern Ablation（固定：Qwen3 8B）

**評估點：** 完整 pipeline（需要跑 LLM generation）
**固定：** Stage 0 最佳 embedding + Stage 0a/0b 最佳 indexing + Stage 1 最佳 RAG + `llm_model="ollama/qwen3:8b"`
**主要指標：** AgentGoalAccuracy（Layer 1）、ToolCallAccuracy（Layer 2）、Latency

**為什麼固定 Qwen3 8B 跑 pattern ablation，而不是 Llama 3.1 8B：**
用最強的 small model 做 pattern 對比，讓 pattern 差異最清晰地顯現。Llama 3.1 8B 的問題：本身 STEM reasoning + tool calling 能力上限低，容易讓「model 太弱無法執行 pattern」的效應掩蓋 pattern 本身的貢獻——你看到的可能是 model 限制，不是 pattern 限制。Qwen3 8B 比 Llama 3.1 8B 更能充分執行 ReflAct/Reflexion pattern，且完全不同 family（Alibaba），讓 Stage 2B 的 family 對比有意義。Ollama 本地跑，零 API cost。

| Config | 只改這一個 | 量化這個技術的貢獻 |
|--------|-----------|-------------------|
| `s2a_no_agent` | 對照組（純 RAG，無 agent）| — |
| `s2a_react` | + ReAct multi-agent | Agent 框架的基礎貢獻 |
| `s2a_focused_react` | ReAct → Focused ReAct | Early stop + reiteration 的貢獻 |
| `s2a_reflact` | → ReflAct backbone | Goal-state reflection 的貢獻 |
| `s2a_reflact_review` | + Targeted guidance Reviewer | Reflexion-style retry 的貢獻 |

---

#### Stage 2B — LLM Family × Scale Ablation（固定：最佳 pattern）

**評估點：** 完整 pipeline
**固定：** Stage 2A 的最佳 `agent_pattern`（預期是 `reflact_review`）
**主要指標：** AgentGoalAccuracy、ToolCallAccuracy、Latency、Cost per query

**核心問題：** 在固定最佳 pattern 的情況下，不同 family 和規模的 LLM 表現差距有多大？提升幅度是否值得 API 成本？

**為什麼是三個 model，而不是原本的 7B vs 70B Llama：**
原設計同時換了 family（都是 Llama）和 scale，無法分辨「是因為更大還是因為 Llama 更好」。新設計讓三個 config 各自回答一個不同的問題：

| Config | Model | Family | 來源 | 選入原因 |
|--------|-------|--------|------|---------|
| `s2b_qwen3_8b` | `ollama/qwen3:8b` | Alibaba Qwen | Ollama 本地 | **Stage 2A baseline 繼承**，確保對比基準一致 |
| `s2b_gptoss_20b` | `openrouter/openai/gpt-oss-20b` | OpenAI（首批 open-weight）| OpenRouter / Ollama | **同 size class，不同 family**：MoE 架構，3.6B active params，benchmark ≈ o3-mini，Apache 2.0，可本地跑（16GB RAM）|
| `s2b_nemotron_49b` | `openrouter/nvidia/llama-3.3-nemotron-super-49b-v1` | NVIDIA（RAG fine-tune）| OpenRouter 免費 | **中型，專為 agentic RAG 後訓練**：RAG + tool calling SFT + RL，128K context，測試「domain-specific post-training 的 ROI」|

**這個設計能回答的四種情境（執行後對號入座）：**

```
情境 A：qwen3_8b ≈ gptoss_20b ≈ nemotron_49b（差距 < 0.05）
→ Pattern 是主要驅動力，LLM family 和 scale 影響有限
→ 實務意義：用最便宜的本地 8B 就夠，省下所有 API 成本

情境 B：nemotron_49b >> qwen3_8b，但 gptoss_20b ≈ qwen3_8b
→ RAG-specific post-training（而非純 scale）是關鍵
→ 實務意義：值得用 nemotron 的 free tier；下一步可考慮 fine-tune 8B on RAG tasks

情境 C：gptoss_20b >> qwen3_8b，nemotron_49b 居中
→ OpenAI 的 reasoning 訓練方式有額外優勢，超出 scale 解釋
→ 實務意義：gpt-oss-20b 是最佳 cost-performance 選擇

情境 D：nemotron_49b 全面最強，差距顯著（> 0.08）
→ Scale + domain post-training 是主要驅動力
→ 實務意義：production 用 nemotron，開發 / prototype 用 qwen3 8B
```
不管是哪種情境，都有數據支撐的結論。這是 ablation study 的核心價值：**不是為了驗證預期，而是讓數據說話。**

---

#### 各 Stage 的評估指標對照

| Stage | 需要跑 LLM generation？ | 評估層 | 核心指標 |
|-------|------------------------|--------|---------|
| Stage 0（embedding）| **否** | Retrieval layer | ContextRecall、ContextPrecision、QuantEM |
| Stage 0a（chunking）| **否** | Retrieval layer | ContextRecall、ContextPrecision、QuantEM |
| Stage 0b（ctx retrieval）| **否** | Retrieval layer | ContextRecall 提升 vs LLM cost ROI |
| Stage 1（RAG）| **否** | Retrieval layer | ContextRecall、ContextPrecision、QuantEM |
| Stage 2A（agent pattern）| **是** | Full pipeline | AgentGoalAccuracy、ToolCallAccuracy、Latency |
| Stage 2B（LLM family × scale）| **是** | Full pipeline | AgentGoalAccuracy、ToolCallAccuracy、Latency、Cost |

Stage 0、0a、0b、1 都只需要評估到 retrieval layer，**不需要跑完整 pipeline**——這讓四個 stage 的執行成本極低，可以快速迭代。只有 Stage 2A 和 2B 才需要完整跑 6 個 agent。

---

**完整預估結果（所有 stage 合併，實際執行後以 CSV 為準）：**

| Config | ContextRecall | QuantEM | GoalAccuracy | Latency |
|--------|-------------|---------|-------------|---------|
| s0_embed_openai（baseline）| 0.78 | 0.63 | — | — |
| s0_embed_bge（最佳預估）| 0.80 | 0.66 | — | — |
| s0a_sentence_512 | 0.73 | 0.58 | — | — |
| s0a_paragraph_aware | 0.79 | 0.62 | — | — |
| s0a_semantic（最佳預估）| 0.82 | 0.64 | — | — |
| s0b_none | 0.82 | 0.64 | — | — |
| s0b_high_value_only | 0.89 | 0.68 | — | — |
| s1_naive | 0.73 | 0.58 | — | 4s |
| s1_full_rag | 0.89 | 0.74 | — | 8s |
| s2a_no_agent | 0.89 | 0.74 | — | 8s |
| s2a_react | 0.87 | — | 0.62 | 31s |
| s2a_focused_react | 0.88 | — | 0.74 | 28s |
| s2a_reflact | 0.89 | — | 0.85 | 35s |
| s2a_reflact_review（最佳預估）| 0.90 | — | 0.89 | 44s |
| s2b_qwen3_8b（baseline）| 0.90 | — | 0.89 | 44s |
| s2b_gptoss_20b | 0.91 | — | 0.91 | 38s |
| s2b_nemotron_49b | 0.93 | — | 0.93 | 55s |

⚠️ 上表為預估值，以實際執行結果為準。三個 config 代表三個不同 family，執行後對號入座四種情境（見 Stage 2B 說明）。

---

### Feature 21：LLM Provider 架構 — LiteLLM + OpenRouter

**核心設計：用 LiteLLM 作為統一介面，OpenRouter 作為 cloud model 入口，Ollama 負責本地。**

換 provider 或 model 只需改 `PipelineConfig` 裡的一個字串，不需要維護多個 SDK。

```python
from llama_index.llms.litellm import LiteLLM
from llama_index.embeddings.litellm import LiteLLMEmbedding
import os

def build_pipeline_llm(config: PipelineConfig) -> LiteLLM:
    """LiteLLM 統一入口：換 model = 換字串，code 不動"""
    if config.llm_model.startswith("ollama/"):
        # 本地：不需要 API key，直接走 localhost:11434
        return LiteLLM(model=config.llm_model)
    else:
        # Cloud（OpenRouter）：一個 API key 搞定所有 cloud model
        return LiteLLM(
            model=config.llm_model,
            api_base="https://openrouter.ai/api/v1",
            api_key=os.environ["OPENROUTER_API_KEY"],
        )

def build_index_llm() -> LiteLLM:
    """Stage 0b index-time LLM，固定，不跟 PipelineConfig 走"""
    return LiteLLM(
        model="gemini/gemini-2.5-flash-lite",
        api_key=os.environ["GEMINI_API_KEY"],
    )

def build_eval_llm() -> LiteLLM:
    """Eval LLM，所有 stage 固定，必須和所有 pipeline model 不同廠商"""
    return LiteLLM(
        model="gemini/gemini-2.5-flash",
        api_key=os.environ["GEMINI_API_KEY"],
    )

def build_embed_model(config: PipelineConfig) -> LiteLLMEmbedding:
    """Stage 0 ablation 的 embedding 入口：換 model = 換字串，Qdrant 重新 index"""
    if config.embedding_model == "text-embedding-3-small":
        return LiteLLMEmbedding(
            model_name="text-embedding-3-small",
            api_key=os.environ["OPENAI_API_KEY"],
        )
    else:
        # nomic-embed-text / bge-large-en-v1.5 / qwen3-embedding-8b
        # 全部走 Ollama local，不需要 API key
        return LiteLLMEmbedding(model_name=f"ollama/{config.embedding_model}")
```

**五個角色的完整分工：**

| 角色 | Model | Family | Provider | Stage | 理由 |
|------|-------|--------|----------|-------|------|
| Embedding（ablation）| 見 Stage 0 | 多個 | Ollama / OpenAI | Stage 0 | 四個候選代表不同維度 |
| Index-time LLM | `gemini-2.5-flash-lite` | Google | Gemini direct | Stage 0b 固定 | 簡單任務，1,000 RPD free tier，夠用 |
| Pipeline LLM（2A）| `ollama/qwen3:8b` | Alibaba | Ollama 本地 | Stage 2A 固定 | 最強 small model，充分執行 pattern |
| Pipeline LLM（2B）| `qwen3:8b` / `gpt-oss-20b` / `nemotron-49b` | Alibaba / OpenAI / NVIDIA | Ollama / OpenRouter | Stage 2B | 三個 family 各回答一個不同問題 |
| Eval LLM | `gemini-2.5-flash` | Google | Gemini direct | 所有 Stage 固定 | 見下方詳細說明 |

**Eval LLM 為什麼必須是 Gemini，且只能是 Gemini：**

Eval LLM 是裁判，必須同時滿足三個條件，Gemini 是唯一的選擇：

1. **Self-serving bias 排除**：eval LLM 不能和任何 pipeline LLM 來自同一個 family。Qwen3（Alibaba）在 Stage 2A/2B，gpt-oss（OpenAI）在 Stage 2B，Nemotron（NVIDIA）在 Stage 2B——三個 family 全部排除。Gemini 是 Google，和所有 pipeline model 完全無 overlap。
2. **固定裁判原則**：所有 stage 用同一個 eval LLM，跨 stage 的分數才有可比性。如果裁判中途換人，分數差異可能來自標準改變，不是 pipeline 改善。
3. **⚠️ Gemini 2.0 Flash 已廢棄**：舊 spec 裡的 `gemini-2.0-flash` 於 2026 年 3 月 3 日正式下線，已更新為 `gemini-2.5-flash`。
4. **Rate limit 夠用**：55 queries × 所有 config ≈ 1,100 次 eval，Gemini 2.5 Flash free tier 250 RPD，分 5 天跑完，零成本。Claude / GPT-5 無 free tier API，eval 成本高，排除。

**為什麼不用 OpenRouter 路由 Gemini eval LLM：**
OpenRouter 多一層中間商，增加 latency 和 debug 難度。Gemini eval LLM 固定不換，直連 Gemini API 最乾淨。只有需要多 provider 選擇的 pipeline LLM 才有 OpenRouter 的必要。

---

## 已研究且否決的方向（不要再做）

> 這個 section 記錄所有已評估過但被否決的技術選項。每一條都有評估結論。不要因為「看起來合理」就重新研究——這些路已經走過了。

### PDF 解析相關

**Marker（本地 Python library）— ❌ 否決**
輸出純 Markdown 字串，沒有 element type 標記，無法做 Content-Type Routing。對圖片的處理能力為零，NN 架構圖資訊完全遺失。在 ML 論文 RAG 場景是致命缺陷。

**LlamaParse `tier="scientific_papers"` Preset — ❌ 不使用**
90 credits/頁，功能和 `agentic_plus` 完全相同。沒有任何額外好處，只是貴一倍。

**LlamaSplit — ❌ 不適用**
設計給「一個大 PDF 裡混著多份不同文件」的場景。ArXiv 論文每篇都是獨立 PDF，沒有需要「分割」的場景。

**LlamaExtract — ❌ 不適用**
設計給 field extraction（提取結構化欄位存入資料庫）。RAG 需要完整語意 context，不是欄位提取。疊加在 LlamaParse 上另外花 5–60 credits/頁，ROI 極低。

**UnstructuredElementNodeParser — ❌ 錯誤配對**
設計給原始 HTML 輸入。接在 LlamaParse 後面是錯誤配對——LlamaParse 輸出的是帶有 `type` 欄位的結構化 JSON，不是 HTML。這是很常見的誤用。

---

### Agent 架構相關

**純 ReAct（Analyst Agent）— ❌ 已被 ReflAct 取代**
不強制 goal-state alignment，在 multi-hop academic queries 中系統性地出現 context drift 和 infinite loop。已被 ReflAct + Focused ReAct early stop 取代。如果程式碼裡有 `ReActModule` 作為 Analyst 的 reasoning backend，那是舊版。

**Full Reflexion（整個 trial 重跑）— ❌ 成本過高**
Reflexion 論文設計目標是便宜的 trial（coding benchmark、game environment）。本專案每個 trial 涉及 LlamaParse credits + 6 個 agent 呼叫，全 trial 重跑費用可觀。解決方案：只在 Analyst 層用 Lightweight Reflexion（Reviewer 生成 targeted guidance 傳給下一輪），不重跑整個 pipeline。

**ReflAct 用在 Researcher Agent — ❌ 不適合**
Researcher Agent 是 single-hop RAG query，不是 multi-step reasoning task。ReflAct 的額外 LLM call 在這裡是浪費，Focused ReAct 的 reiteration 即已足夠。

**Open-ended agent loop（AutoGPT 風格）— ❌ 不適合此場景**
讓 LLM 即時決定「下一步要哪個 agent」，對有確定流程的 deep research 是過度設計。Orchestrated pipeline 更可靠、更便宜、更容易 debug。

**LangChain — ❌ 替換為 LlamaIndex**
LlamaIndex 提供 LlamaParse、NodeParser、VectorStoreIndex、Hybrid Search、Reranker 的原生整合。LangChain 偏向 reasoning chain，對 RAG 資料層的整合不如 LlamaIndex 細緻。

---

### RAG Pipeline 相關

**純 Vector Search — ❌ 已被 Hybrid Search 取代**
ML 論文有大量精確術語和數字，純語意 embedding 對精確匹配不可靠。Hybrid Search + RRF 已確認更優，Quantitative Exact Match +0.17。

**Cohere Rerank API — ❌ 替換為 BGE 本地推論**
有 API cost。BGE-Reranker-v2-m3 本地推論效果相當，完全免費。

**ChromaDB — ❌ 替換為 Qdrant**
需要自己維護 BM25 index 並手動做 RRF fusion，維護成本高。Qdrant 原生支援。

**Pinecone — ❌ 不適用於開發期**
需要 API，開發期間有費用。Qdrant 本地 Docker 完全免費，且 API 與 cloud version 相同，無縫升級。

**FLARE（Forward-Looking Active Retrieval）— ❌ 不適用**
設計給 streaming text generation（邊生成邊 retrieve）。本專案是 batch deep research。

**Knowledge Graph — ❌ 工程成本過高**
建立和維護 KG 需要大量工程投入。Hybrid Search + Multi-Query 已能覆蓋跨論文比較需求。

**Information Compression（LongLLMLinguaPostprocessor）— ⚠️ 備用，現階段不啟用**
Top-5 reranking 讓 context 維持在合理大小，現階段不需要。如果 Analyst Agent context 超過 50K tokens 才考慮。過早優化。

---

### Evaluation 相關

**TruLens + RAG Triad — ❌ 否決**
RAG Triad 三個指標沒有 **Context Recall**（是否遺漏重要資訊）。對學術 RAG 是致命缺失——一篇論文只用了一半的重要結論，三個指標都可以很高但品質其實很差。TruLens observability 功能和 LlamaTrace 重疊，且 LlamaTrace 對 LlamaIndex `@step` 有原生理解。

**LangFuse — ⚠️ 降為選用（不作為主力）**
通用 observability 工具，trace 是通用 span，不理解 LlamaIndex AgentWorkflow 的 `@step` 語意，難以做 step-level debug。如果團隊已熟悉可保留做 cost dashboard，但 agent debug 主力換 LlamaTrace。

**純 LLM-as-Judge 做數字評估 — ❌ 不可靠**
LLM 對精確數字（84.2% vs 84.8%）傾向認為「接近就算對」。必須用自訂 Quantitative Exact Match。

**Pipeline LLM 和 Eval LLM 用同一個 — ❌ self-serving bias**
同一個 LLM 評估自己的輸出，傾向給自己高分。Pipeline 和 Eval 必須來自不同廠商。

---

### Model 相關

**Generator Fine-Tuning（LoRA / full fine-tune）— ❌ 不具備條件**
需要大量標注資料和算力。ReflAct + Reflection Pattern 已達到「動態判斷品質並改進」的效果，不需要 fine-tune。

**Self-RAG — ❌ 不具備條件**
需要 fine-tune 讓 LLM 學會在生成中插入 retrieval token。

**Embedding Fine-Tuning — ❌ 不具備條件**
需要大量 QA pair 做對比學習。`text-embedding-3-small` 在未 fine-tune 的情況下已足夠。

**Monolithic Fine-Tuning（RA-DIT）/ Retrieval Foundational Models（RETRO）— ❌ 超出範圍**
聯合訓練 retriever + generator、或從頭預訓練，超出個人專案的規模。

---

## Section 06：測試策略

### 核心問題：這個專案的測試和一般專案不同

大部分邏輯是 LLM call，不是純函數。傳統 unit test（輸入 → 預期輸出）只適用於一部分。需要分三個層次思考要測什麼、用什麼工具。

**前端框架是 Streamlit，不需要 Mock Service Worker（MSW）。** MSW 是給 JavaScript frontend 用的——它在瀏覽器裡攔截 `fetch` / `XHR` 請求。Streamlit 的所有邏輯（LlamaParse、Qdrant、LLM call）都在 Python 層發生，不是在 browser 的 JS 層，MSW 攔截不到。Streamlit UI 測試用官方的 `AppTest` framework。

---

### 測試分層總覽

```
tests/
  unit/           pytest + mock，push 到任何 branch 都跑，< 30 秒
  ui/             Streamlit AppTest，push 到 dev 時跑，< 60 秒
  integration/    Ollama local LLM，PR to dev 時跑，< 3 分鐘
  e2e/            Ollama local LLM，PR to main 時跑，< 10 分鐘
```

| Layer | 工具 | 測什麼 | 不測什麼 |
|-------|------|--------|---------|
| unit | pytest + unittest.mock | 確定性邏輯（routing、過濾、RRF、retry 觸發條件） | LLM 輸出品質 |
| ui | Streamlit AppTest | UI 互動、session state、error handling | Pipeline 業務邏輯 |
| integration | pytest + Ollama | LLM 輸出有沒有符合 Pydantic schema | 輸出品質（那是 RAGAS 的工作）|
| e2e | pytest + Ollama | 完整 pipeline 能不能跑完不 crash | 輸出品質 |

---

### Layer 1：Unit Tests — pytest + unittest.mock

**原則：** 所有昂貴的外部依賴（LlamaParse、LLM、Qdrant）全部 mock 掉，只測你寫的邏輯。

**Data Cleaning 層：**

```python
# tests/unit/test_routing.py
def test_table_routing_produces_dual_representation():
    element = {"type": "table", "content": "| Method | BLEU |\n| LoRA | 94.2 |"}
    nodes = content_type_router.route(element)
    assert len(nodes) == 2
    types = {n.metadata["chunk_type"] for n in nodes}
    assert types == {"table_raw", "table_summary"}

def test_figure_routing_produces_single_node():
    element = {"type": "figure", "content": "Figure 3: Self-attention architecture..."}
    nodes = content_type_router.route(element)
    assert len(nodes) == 1
    assert nodes[0].metadata["chunk_type"] == "figure"

# tests/unit/test_quality_filter.py
def test_filter_rejects_short_chunks():
    node = TextNode(text="See Figure 1.")          # 3 words，低於 30 words 閾值
    assert quality_filter(node) is False

def test_filter_rejects_symbol_heavy_chunks():
    node = TextNode(text="\\ @ # | \\ @ # | \\")  # 符號比例 > 15%
    assert quality_filter(node) is False

def test_filter_accepts_valid_chunk():
    node = TextNode(text="LoRA reduces the number of trainable parameters " +
                         "by decomposing weight matrices into low-rank factors.")
    assert quality_filter(node) is True
```

**RAG Pipeline 層：**

```python
# tests/unit/test_rrf.py
def test_rrf_fusion_ranking():
    bm25_ranks  = {"doc_A": 1, "doc_B": 3, "doc_C": 2}
    dense_ranks = {"doc_A": 2, "doc_B": 1, "doc_C": 3}
    fused = rrf_fusion(bm25_ranks, dense_ranks, k=60)
    # doc_A: 1/61 + 1/62 ≈ 0.0326  ← 應該排第一
    # doc_B: 1/63 + 1/61 ≈ 0.0321
    assert list(fused.keys())[0] == "doc_A"

def test_qdrant_filter_builder():
    f = build_qdrant_filter(chunk_type="table_raw", section_priority="HIGH_VALUE")
    assert f.must[0].key == "chunk_type"
    assert f.must[0].match.value == "table_raw"
    assert f.must[1].key == "section_priority"
```

**Agent 控制邏輯層（最重要的一層）：**

```python
# tests/unit/test_agent_control.py
def test_focused_react_detects_duplicate_action():
    module = FocusedReActModule()
    module.action_history = {("search_paper", "LoRA rank")}
    action = ToolCall(tool="search_paper", args="LoRA rank")
    assert module.is_duplicate(action) is True

def test_focused_react_allows_different_args():
    module = FocusedReActModule()
    module.action_history = {("search_paper", "LoRA rank")}
    action = ToolCall(tool="search_paper", args="LoRA training stability")
    assert module.is_duplicate(action) is False

def test_reviewer_triggers_retry_below_threshold():
    review = ReviewResult(coverage_score=0.74, retry=True,
                          missing_topics=["ablation study"])
    assert should_retry(review, attempt=0) is True

def test_reviewer_stops_at_max_attempts():
    review = ReviewResult(coverage_score=0.50, retry=True,
                          missing_topics=["ablation study"])
    assert should_retry(review, attempt=2) is False    # 硬性上限 max 2×

def test_reviewer_v6_retry_includes_guidance():
    # v6.0 要求：retry 時必須帶 targeted guidance，不能是 None
    review = ReviewResult(coverage_score=0.60, retry=True,
                          missing_topics=["quantitative results"],
                          guidance="Previous search missed the Experiments section tables.")
    assert review.guidance is not None
    assert len(review.guidance) > 10

# tests/unit/test_pydantic_schemas.py
def test_research_plan_rejects_empty_sub_questions():
    with pytest.raises(ValidationError):
        ResearchPlan(topic="LLMs", sub_questions=[], arxiv_queries=["LLM survey"])

def test_pipeline_config_defaults():
    config = PipelineConfig(name="test")
    assert config.chunk_strategy == "sentence_512"
    assert config.contextual_retrieval_scope == "none"
    assert config.agent_pattern == "none"
```

---

### Layer 2：Streamlit UI Tests — AppTest

Streamlit 1.18+ 的官方 `AppTest` framework，不需要開瀏覽器，直接在 pytest 裡跑。

**測什麼：** UI 互動邏輯、session state 有沒有正確更新、error handling 有沒有觸發。
**不測什麼：** Pipeline 業務邏輯（那是 unit/integration test 的工作）。

```python
# tests/ui/test_streamlit_app.py
from streamlit.testing.v1 import AppTest

def test_app_loads_without_error():
    at = AppTest.from_file("app.py").run()
    assert not at.exception

def test_empty_query_shows_warning():
    at = AppTest.from_file("app.py").run()
    at.button[0].click().run()                        # 空 query 直接送出
    assert len(at.warning) > 0
    assert "請輸入研究主題" in at.warning[0].value

def test_valid_query_triggers_pipeline():
    at = AppTest.from_file("app.py").run()
    at.text_input[0].set_value("parameter-efficient fine-tuning").run()

    # mock pipeline，避免 unit test 觸發真實 LLM call
    with patch("app.run_pipeline") as mock_pipeline:
        mock_pipeline.return_value = MockPipelineResult()
        at.button[0].click().run()
        mock_pipeline.assert_called_once()

def test_session_state_persists_results():
    at = AppTest.from_file("app.py").run()
    # 確認 session state 有正確儲存結果，讓用戶重新訪問時不重跑
    at.session_state["last_result"] = MockPipelineResult()
    at.run()
    assert at.session_state.get("last_result") is not None

def test_error_state_shows_user_friendly_message():
    at = AppTest.from_file("app.py").run()
    at.text_input[0].set_value("valid query").run()
    with patch("app.run_pipeline", side_effect=Exception("Qdrant connection failed")):
        at.button[0].click().run()
    # 不應該把 raw exception 直接顯示給用戶
    assert len(at.error) > 0
    assert "Qdrant connection failed" not in at.error[0].value  # raw error 不暴露
    assert len(at.exception) == 0                               # 沒有 unhandled exception
```

---

### Layer 3：Integration Tests — Ollama local LLM

**原則：** 不測 LLM 輸出品質，只測「LLM 輸出的結構有沒有符合 Pydantic schema」和「agent 的控制邏輯有沒有正確觸發」。用 Ollama local model，不消耗 API credits。

```python
# tests/integration/test_agent_schemas.py
@pytest.mark.integration
def test_planning_agent_produces_valid_schema():
    agent = PlanningAgent(llm=LiteLLM("ollama/qwen3:8b"))
    plan = agent.run("parameter-efficient fine-tuning")

    assert isinstance(plan, ResearchPlan)            # schema 正確
    assert 2 <= len(plan.sub_questions) <= 6         # 合理範圍
    assert len(plan.arxiv_queries) >= 1
    assert all(len(q) > 5 for q in plan.arxiv_queries)  # query 不是空字串

@pytest.mark.integration
def test_reviewer_guidance_present_on_low_coverage():
    # v6.0 核心行為：coverage < 0.75 時必須帶 targeted guidance
    reviewer = ReviewerAgent(llm=LiteLLM("ollama/qwen3:8b"))
    result = reviewer.evaluate(
        findings=minimal_findings_fixture,   # 刻意做一個 coverage 很低的 findings
        plan=test_plan_fixture
    )
    if result.retry:
        assert result.guidance is not None
        assert len(result.guidance) > 20     # guidance 不能是空字串

@pytest.mark.integration
def test_analyst_reflact_does_not_loop():
    # 確認 FocusedReAct early stop 在真實 LLM call 下也能觸發
    agent = AnalystAgent(FocusedReActModule(), tools=minimal_tools)
    result = agent.run("What is LoRA?", max_steps=10)
    assert result is not None                # 有結果（沒有無限迴圈）
    assert agent.reasoning_module.loop_count < 10
```

---

### Layer 4：E2E Tests — 完整 Pipeline

**跑的時機：** 只在 PR to main 時跑。目標是確認整個 pipeline 不 crash，不測輸出品質。

```python
# tests/e2e/test_full_pipeline.py
@pytest.mark.e2e
def test_full_pipeline_completes_without_crash(tmp_path):
    config = PipelineConfig(
        name="e2e_smoke_test",
        llm_model="ollama/qwen3:8b",        # Ollama local，零 API cost
        chunk_strategy="sentence_512",   # 最快的 chunking
        retrieval_mode="vector",         # 最簡單的 retrieval（不跑 BM25）
    )
    pipeline = PipelineFactory.build(config)
    result = pipeline.run(
        topic="LoRA fine-tuning",        # 最小的 test case
        max_papers=1,                    # 只抓一篇論文
        output_dir=tmp_path
    )
    assert (tmp_path / "report.docx").exists()
    assert result.coverage_score >= 0    # 有跑完就好，不驗品質
    assert result.retry_count <= 2       # retry 沒有超過上限
```

---

## Section 07：Git Workflow & Branch Protection

### Branch 結構

```
main          ← production-ready。只接受 PR，絕對不能直接 push
  └── dev     ← integration branch。feature branches 合併到這裡
        ├── feature/stage-0a-chunking
        ├── feature/stage-1-hybrid-search
        ├── experiment/reflact-vs-react   ← ablation study 用的臨時 branch
        └── fix/reviewer-guidance
```

`experiment/*` branch 是 ablation study 專用。跑完之後 CSV 結果 commit 進來，再 merge 回 dev——不直接進 main，因為實驗結果可能會修改 PipelineConfig 的 default 值，需要先在 dev 驗證。

---

### GitHub Branch Protection Rules

**`main` 的設定（Settings → Branches → Add rule）：**

```
Branch name pattern: main

✅ Require a pull request before merging
    ✅ Require approvals: 1
       （個人 repo 可設 0，但保留 PR 流程讓自己 review 再 merge）
✅ Require status checks to pass before merging
    → 勾選 CI job: "unit-tests"
    → 勾選 CI job: "ui-tests"
    → 勾選 CI job: "integration-tests"
    → 勾選 CI job: "e2e-tests"
✅ Require branches to be up to date before merging
✅ Do not allow bypassing the above settings
```

**`dev` 的設定：**

```
Branch name pattern: dev

✅ Require status checks to pass before merging
    → 勾選 CI job: "unit-tests"
    → 勾選 CI job: "ui-tests"
❌ Require approvals（個人 dev branch 不需要）
```

---

### GitHub Actions CI

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [dev, "feature/**", "experiment/**", "fix/**"]
  pull_request:
    branches: [main, dev]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pytest tests/unit/ -v --timeout=30

  ui-tests:
    runs-on: ubuntu-latest
    needs: unit-tests           # unit 過了才跑 ui
    # push 到 dev 或 PR to any 才跑，feature push 只跑 unit
    if: |
      github.ref == 'refs/heads/dev' ||
      github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pytest tests/ui/ -v --timeout=60

  integration-tests:
    runs-on: ubuntu-latest
    needs: [unit-tests, ui-tests]
    # 只在 PR to dev 或 PR to main 時跑
    if: github.event_name == 'pull_request'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      # CI 環境沒有 Ollama，用 OpenRouter 最小 free model 跑 integration test
      - run: pytest tests/integration/ -v -m integration --timeout=120
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}

  e2e-tests:
    runs-on: ubuntu-latest
    needs: [unit-tests, ui-tests, integration-tests]
    # 只在 PR to main 時跑
    if: |
      github.event_name == 'pull_request' &&
      github.base_ref == 'main'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -r requirements.txt
      - run: pytest tests/e2e/ -v -m e2e --timeout=600
        env:
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

**每個 branch 的 CI 觸發矩陣：**

| 事件 | unit | ui | integration | e2e |
|------|------|----|-----------|----|
| push to `feature/*` | ✅ | ❌ | ❌ | ❌ |
| push to `dev` | ✅ | ✅ | ❌ | ❌ |
| PR to `dev` | ✅ | ✅ | ✅ | ❌ |
| PR to `main` | ✅ | ✅ | ✅ | ✅ |

---

### .gitignore 設定

```gitignore
# API keys（絕對不能 commit）
.env
.env.*

# 原始資料（可以重新下載）
data/pdfs/
data/raw/

# Qdrant index（可以重建）
data/indexes/
qdrant_storage/

# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/
.ruff_cache/

# 應該 commit 的（不要加進 gitignore）
# configs/experiments/   ← PipelineConfig YAML 記錄
# results/               ← Ablation study CSV 結果（有版控才能比較不同 run）
# prompts/               ← Prompt YAML（prompt versioning 的一部分）
```

**`results/` 要 commit 的理由：** Ablation study 的 CSV 是實驗記錄，版控之後可以比較「這次改了 chunk_strategy 之後，ContextRecall 有沒有真的提升」。這個記錄的價值和程式碼一樣高。

---

## 版本演進 Changelog

| 版本 | 核心改變 |
|------|---------|
| v1.0 | 初始設計。Parser: Marker；NodeParser: UnstructuredElementNodeParser；LaTeX: 純 regex |
| v2.0 | 完整重設計 Data Cleaning。LlamaParse v2 + Content-Type Routing |
| v3.0 | LlamaParse pricing 確認。`agentic_plus` 在 Free Tier 可用，"Scientific papers preset" 是 90 credits/頁陷阱 |
| v4.0 | RAG 技術全景評估。新增 HyDE。明確否決 LlamaSplit / LlamaExtract / 6 項 Fine-tuning 技術 |
| v4.1 | Multi-Agent 三層評估架構。LlamaTrace 取代 LangFuse。RAGAS Agentic Metrics。Phoenix → pandas → RAGAS 橋接 |
| v5.0 | Reflexion vs Focused ReAct vs ReflAct 深度分析。設計針對 Analyst 的混合 reasoning 架構 |
| **v6.0** | **Analyst Agent → ReflAct + Focused ReAct early stop。Reviewer → Reflexion-style targeted guidance。PipelineConfig 單一控制點 + 11 ablation configs。LLM 支援 Ollama / Groq / Gemini free tier** |
| **v6.1** | **Ablation framework 從四階段擴充為六階段：新增 Stage 0（Embedding Model 選擇，含 tokenizer fragmentation 分析）、Stage 2 拆成 2A（Agent Pattern，固定 7B）+ 2B（LLM Scale，固定最佳 pattern）。修正原本 `s2_full_system` 同時改 pattern 和 LLM 的設計缺陷。PipelineConfig 新增 `embedding_model` 欄位。測試策略（Section 06）及 Git Workflow（Section 07）** |
| **v6.2** | **LiteLLM + OpenRouter 統一 API 架構，涵蓋 LLM 與 Embedding。** Model 全面更新：Stage 0 將 mxbai-embed-large 換成 qwen3-embedding-8b（MTEB Multilingual #1，32K token）；Stage 0b 補上 index-time LLM（gemini-2.5-flash-lite）；Stage 2A 從 Llama 3.1 8B 換成 Qwen3 8B；Stage 2B 從 7B/70B Llama 改為三個不同 family（Qwen3 8B / gpt-oss-20b / Nemotron 49B）；Eval LLM 從已廢棄的 gemini-2.0-flash 更新為 gemini-2.5-flash。Feature 21 完整重寫：新增 build_embed_model（LiteLLMEmbedding）、build_index_llm、build_eval_llm factory functions，所有 provider 統一透過 LiteLLM 管理。Feature 1 重寫：LlamaParse tier 改為 `parse_tier` 參數（PipelineConfig 新增欄位），預設 `agentic_plus`（官方明列 scientific papers 適用場景），移除第三方定價數字（官方文件無確切記載），新增 cache 說明與切換範例。 |

---

*v6.2 — 2026-03-05。此文件是唯一需要讀的文件：涵蓋所有決策、所有否決方向、完整 pipeline 設計。*
