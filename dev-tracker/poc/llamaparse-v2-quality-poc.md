# PoC: llamaparse-v2-quality

## 狀態
- 目前狀態：`completed · 未採用`
- 建立時間：2026-03-05T23:32:51+08:00
- 最後更新：2026-05-06
- PoC 程式碼：`poc/llamaparse-v2-quality/`

## 核心驗證問題
1. LlamaParse v2 能否正確分類 ML 學術論文的 element types（text/table/figure/equation）？
2. Section 標題（Abstract、Introduction、Method 等）是否完整保留？
3. 數學公式是被保留成 LaTeX、unicode 還是截斷？
4. Table 的數字（BLEU score、WikiSQL 數據等）是否完整？
5. Figure 描述品質如何（長度、內容完整性）？
6. 是否有 cache 機制，第二次 parse 是否明顯更快？
7. 能否透過 presigned URL 真正下載圖片 binary（embedded image 提取）？

## PoC 邊界（不做的事）
- 不處理所有 edge case
- 不寫正式測試
- 不整合至現有 RAG codebase
- 不建立新分支或 worktree

## 技術選擇
- 使用 `llama-cloud >= 1.0` 套件（v2 API）
- 使用 `AsyncLlamaCloud` client 作兩段式呼叫：`files.create()` → `parsing.parse()`
- 使用 `asyncio.Semaphore(2)` 控制並發
- 結果存取方式：`result.markdown` / `result.text` / `result.items.pages[].items`

## 驗證結果（最終版，2026-03-06）

### 測試論文
- `attention.pdf`（Attention Is All You Need，15 頁）
- `lora.pdf`（LoRA，26 頁）
- `flashattention.pdf`（FlashAttention-2，14 頁）

### Tier 效能比較

| Tier | 每篇耗時 |
|---|---|
| `cost_effective` | 10~25s |
| `agentic` | 30~55s |
| `agentic_plus` | 60~150s+ |

### 測試結果（cost_effective / 最終版含 Test 7）

| Test | attention.pdf | lora.pdf | flashattention.pdf |
|---|---|---|---|
| 1 Element 分佈 | ✅ PASS | ✅ PASS | ✅ PASS |
| 2 Section 標題 | ⚠️ WARN (5/6) | ⚠️ WARN (5/6) | ✅ PASS (6/6) |
| 3 數學公式 | ✅ PASS | ✅ PASS | ✅ PASS |
| 4 Table 數字 | ✅ PASS | ✅ PASS | ✅ PASS |
| 5 Figure 品質 | ✅ PASS | ✅ PASS | ✅ PASS |
| 6 Cache 行為 | ⚠️ WARN | ⚠️ WARN | ⚠️ WARN |
| 7 圖片提取 | ✅ PASS | ✅ PASS | ✅ PASS |

> Test 2 WARN 說明：attention 缺 Experiment（論文用「Training」替代）；lora 缺 Result（結果分散在子節）。這是論文節名不照傳統，並非 API 解析問題。

### 各 Test 說明

**Test 1 Element 分佈**：三種 tier 皆能正確解析出 `heading`, `text`, `table`, `image`, `list`, `code` 等元素。

**Test 2 Section 標題**：三種 tier 皆能找到 30~45 個 heading 節點，階層結構完整保留。

**Test 3 數學公式**：三種 tier 均以 `$...$` / `$$...$$` 的 LaTeX 格式保留公式，未轉成 unicode。

**Test 4 Table 完整性**：關鍵數據（BLEU 28.4, 41.8, WikiSQL, TFlops 等）皆完整出現在對應的 table 節點或全文中。

**Test 5 Figure 品質**：三種 tier 的 Figure 取得狀況有明顯差異：
- `cost_effective`：穩定切分出獨立 `image` 節點（attention: 2 張, lora: 4 張, flash: 1 張）
- `agentic`：部份圖片被整併入文字，獨立節點減少
- `agentic_plus`：三篇論文之架構圖**全數被轉成文字/表格**，`image` 節點數量歸零——這是反直覺的。越智能反而越把圖吃掉，不適合需要依賴原圖理解的場景。

**Test 7 圖片提取（presigned URL）**：`cost_effective` tier 完全支援 embedded image 提取。
- 正確用法：`output_options={"images_to_save": ["embedded"]}` + `expand=["images_content_metadata"]`
- attention.pdf 取得 3 張圖片（img_p3_1.png 134KB、img_p4_1.png 23KB、img_p4_2.png 46KB）
- presigned URL GET → HTTP 200，binary 有效，圖片正常儲存
- 注意：僅加 `expand=["images_content_metadata"]` 而不加 `images_to_save` 會導致 job 永遠 RUNNING

**Test 6 Cache 行為**：三次對照實測（attention.pdf, cost_effective tier）：

| 條件 | 耗時 |
|---|---|
| 第一次（固定 file_id）| 7.53s |
| 第二次（複用同一 file_id）| 8.31s |
| 第三次（全新 upload，新 file_id）| 7.69s |

三次幾乎相同，`file_id` 複用無加速效果，全新 upload 也不更慢。**LlamaCloud API 無論何種條件，每次都經由 cloud queue 處理，不存在即時 cache 命中。**

## 整合建議

- **必須使用 v2 API (`llama-cloud >= 1.0` + `AsyncLlamaCloud`)**：舊版 SDK 在額度不足時會無限死等，無法用於生產系統。
- **C/P 值首選 `cost_effective`**：在文字、表格、公式的解析品質上與高階層幾乎一致，速度最快，圖片切分最符合直覺。
- **圖片處理策略**：`cost_effective` 支援 embedded image binary 提取（`images_to_save: ["embedded"]` + `images_content_metadata` expand），可直接下載圖片 PNG 至本地，再送 VLM pipeline 分析。切勿依賴 `agentic_plus` 的自動圖文轉換。
- **必須自建 cache 層**：LlamaCloud API 無即時快取（每次都需 7~25s），Backend 必須在本地/DB 層快取已解析的 JSON 結構，才能達到可接受的 UX 響應速度。
- **`items` JSON 結構適合 RAG chunking**：依 `type` 屬性（`heading`, `table`, `text`, `image` 等）將文件切割成具語意的 chunk，比純文字切割更精確。

## 最終決策：未採用

**LlamaParse v2 PoC 驗證完成，但最終未整合至 pipeline。** 以下是放棄的兩個具體原因。

---

### 放棄原因 1：Credits 成本 — 無真正 cache，開發迭代費用無法控制

**來源：** 本文件 Test 6 實測數據

Test 6 對同一份 PDF（attention.pdf, cost_effective tier）進行三次對照：

| 條件 | 耗時 |
|---|---|
| 複用同一 file_id | 8.31s |
| 全新 upload | 7.69s |

三次耗時幾乎相同。**LlamaCloud API 每次都走 cloud queue，不存在即時 cache 命中**，`file_id` 複用沒有任何加速效果。

這代表：**每次 parse 都扣 credits，無論是否已解析過相同 PDF。**

在 pipeline 主動開發期間，因為調整 chunking 策略、retrieval config、prompt 等，同一批論文會被反覆重跑。LlamaParse 的計費模型讓這種迭代方式的成本無法預測也無法控制。雖然可以自建 cache 層來避免重複 API call，但這增加了額外的基礎建設複雜度，且對已付費的首次 parse 沒有幫助。

---

### 放棄原因 2：圖片 Bounding Box 缺失 — 無法做精準 figure-to-VLM 傳圖

**來源：** 本文件 Test 5（Figure 品質）+ Test 7（圖片提取）+ pipeline 需求

Pipeline 的 VLM 分析步驟需要能夠**針對特定圖片**（NN 架構圖、實驗曲線）單獨傳給 VLM，而非傳入整頁。要做到這件事，必須知道每張圖在原始 PDF 頁面上的 **bounding box 座標**（page_num, x, y, width, height），才能裁切並傳給 VLM。

LlamaParse 在這個需求上的實際狀況：

**`agentic_plus` tier（官方推薦用於 scientific papers）：**
- Test 5 確認：三篇論文的架構圖**全數被轉成文字/表格**，`image` 節點數量歸零
- 連圖片本身都沒有，bbox 座標問題根本不存在——因為圖已經消失了

**`cost_effective` tier：**
- Test 5 確認：能穩定切出獨立 `image` 節點（attention: 2 張，lora: 4 張，flash: 1 張）
- Test 7 確認：可透過 presigned URL 下載 PNG binary（HTTP 200，binary 有效）
- **但是：** 下載回來的是 LlamaCloud server 端預先裁切好的 PNG，`items` JSON 中沒有返回該圖在原始頁面上的 page-level bounding box 座標（x, y, width, height）
- 因此無法回推「這張圖是在第幾頁的哪個位置」，也無法與 PDF 頁面座標系對齊，做不到針對特定圖片位置的精準傳圖

> **注意：** Test 7 只驗證了「能否下載 presigned URL 圖片 binary」，並未驗證 bbox 座標是否存在於 `items` JSON 中。這個 gap 在 PoC 結束後才被識別為問題。

---

### 採用的替代方案

**`pdf2images()` (PyMuPDF) + VLM 整頁分析**

- 用 PyMuPDF 將每頁 PDF 轉為 PNG，在本地執行，零 API cost，零 credits
- 將全頁圖片送進 VLM（`paper2summary` step）進行整頁分析
- 繞過 bbox 需求：不做精準 figure 裁切，改為 VLM 讀整頁、自行從頁面圖片中理解圖表內容
- 實作位置：`backend/tools/paper_tools.py` → `pdf2images()`；`backend/agent_workflows/summary_gen.py` → `paper2summary` step

**未來規劃（Roadmap）：** 改用 Docling 取代 PyMuPDF。Docling 使用 Apple MLX 框架本地推論，並且提供每個 image block 的完整 bounding box 座標，屆時可回頭實作精準 figure-to-VLM 傳圖。詳見 `README.md` → Roadmap。

---

## 狀態歷程

| 時間 | 事件 |
|---|---|
| 2026-03-05T23:32 | 建立，in-progress |
| 2026-03-06T10:55 | 發現卡死原因為誤用舊版 SDK，改寫為 v2 API |
| 2026-03-06T11:05 | 完成初版測試（cost_effective），取得六大面向結果 |
| 2026-03-06T11:15 | 實測 `agentic` tier |
| 2026-03-06T11:20 | 實測 `agentic_plus` tier，三種模式對照完成 |
| 2026-03-06T11:40 | 修正 Test 6 程式缺陷（每次都建新 file_id），改為固定 file_id 重複測試 |
| 2026-03-06T11:50 | 修正 Test 2/4/5 邏輯缺陷（同義詞、錯誤庫數、閾值），重跑後結果更準確 |
| 2026-03-06T12:00 | 新增第三次全新 upload 對照組，確認 file_id 複用無效能影響，最終文件全面更新 |
| 2026-03-06T14:30 | 新增 Test 7 圖片提取驗證（presigned URL），cost_effective 支援 embedded images，PASS |
| 2026-03-06T15:30 | OOP 重構 `main.py`：新增 `ParseResult` dataclass（取代 4-tuple）、`PaperTestSuite` class（封裝 test1–5）、`QualityRunner` class（管理 client/semaphore 生命週期，取代 `try/finally`），`run_tests` 縮減為 7 行；測試結果與輸出格式完全不變，驗證通過 |
| 2026-05-06 | 補記最終決策：LlamaParse v2 未採用。原因：(1) cloud queue 每次都計費，無真正 cache，開發迭代成本無法控制；(2) `cost_effective` tier 的提取圖片不附帶 page-level bbox 座標，無法精準傳圖給 VLM；`agentic_plus` 更差，直接把所有圖轉成文字。採用替代方案：pdf2images（PyMuPDF）+ VLM 整頁分析。 |
