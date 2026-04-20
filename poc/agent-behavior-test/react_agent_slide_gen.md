# LLM Model & Prompt Style Evaluation for ReAct Agent (Slide Generation Pipeline)

**Report Date:** 2026-03-27
**Experiment Rounds:** 3
**Models Evaluated:** qwen3.5:4b, gemma3:4b, gemma3n:e2b, gemma3n:e4b (all via Ollama)

---

## TL;DR / Key Takeaways

1. **gemma3:4b is the clear winner** for ReAct + code generation tasks: it completes both `slide_gen` and `modify_slides` in a single `run_code` call, with clean execution and no errors.
2. **qwen3.5:4b works but is highly inefficient**: it required 16 `run_code` calls to complete the same `slide_gen` task that gemma3:4b finished in 1 call.
3. **gemma3n:e2b is unusable**: it timed out at 600 seconds without producing a single tool call.
4. **gemma3n:e4b is incompatible**: it outputs Gemini-style `tool_code` blocks instead of the ReAct `Action:` format required by LlamaIndex, causing the workflow to terminate immediately with no actual execution.
5. **Prompt style is task-dependent**: `slide_gen` requires an explicit `CRITICAL: You MUST use run_code` directive; `modify_slides` works best with a structured 5-step prose format. Applying the `CRITICAL` style to `modify_slides` causes a complete failure (20-round loop, no tool calls).
6. **Root cause of original failure was prompt ambiguity**, not a fundamental model limitation: the old prompt's phrasing "Respond user with the python code" caused models to output code as text rather than invoking the tool.

---

## 1. Background & Motivation

本報告記錄了一系列針對 ReAct Agent 行為的 Proof-of-Concept 實驗，實驗目的是在資源受限的本地環境（MacBook M1）上，找出最適合驅動 PPTX 生成與修改 pipeline 的 LLM 模型與 prompt 策略。

### System Architecture Overview

本專案的 slide 生成 pipeline 基於 **LlamaIndex ReAct Agent** 架構，Agent 透過以下工具與 Docker sandbox 互動：

| 工具 | 功能 |
|------|------|
| `run_code` | 在 sandbox 中執行 Python 程式碼（主要用於 python-pptx 操作） |
| `list_files` | 列出 sandbox 中的檔案，用於確認輸出結果是否存在 |
| `upload_file` | 上傳檔案至 sandbox |
| `get_all_layout` | 取得 PPTX 的版面配置資訊 |

Pipeline 中有兩個由 ReAct Agent 執行的核心步驟：

- **`slide_gen`**: 接收 `slide_outlines.json`，從零生成 PPTX 檔案
- **`modify_slides`**: 接收現有 PPTX 路徑與驗證 feedback，載入、修改並儲存新版本

### Motivation

在初期測試中，發現以 `qwen3.5:4b` 作為 agent model 時，`slide_gen` 步驟的 agent 有時不呼叫 `run_code` 工具，而是直接在回應文字中輸出 Python 程式碼，導致 pipeline 無法實際產生 PPTX 檔案。

此系列實驗旨在回答以下問題：
1. 這個問題是 prompt 歧義造成的，還是模型能力本身的限制？
2. 不同的 4b 量級模型在 ReAct agent 任務中表現有何差異？
3. 新發布的 gemma3n 系列模型是否可作為 gemma3:4b 的替代方案？
4. `modify_slides` 的現有 prompt 是否需要仿照更新後的 `slide_gen` prompt 進行調整？

---

## 2. Experiment Setup

### Common Configuration

| 配置項 | 設定 |
|--------|------|
| Agent 框架 | LlamaIndex ReAct Agent |
| 執行環境 | MacBook M1（本地 Ollama） |
| Sandbox | Docker container |
| PPTX 庫 | python-pptx |
| Timeout | 600 秒（Round 2）/ 依 max_iterations 限制（Round 3） |
| 測試腳本 | `poc/agent-behavior-test/modify_test.py`（Round 3） |

### Models Under Test

| 模型 | 系列 | 來源 |
|------|------|------|
| `qwen3.5:4b` | Qwen | Ollama |
| `gemma3:4b` | Gemma 3 | Ollama |
| `gemma3n:e2b` | Gemma 3n | Ollama |
| `gemma3n:e4b` | Gemma 3n | Ollama |

### Evaluation Metrics

每次執行記錄以下指標：

- 任務是否完成（task completion）
- `run_code()` 是否被呼叫、呼叫次數
- `list_files()` 呼叫次數
- 生成的 code 是否包含 `prs.save()`（確認有輸出檔案）
- Final Answer 是否含問句（避免模型反問使用者）
- 是否發生錯誤（timeout / max iterations）
- 總 tool call 次數
- 耗時（秒）
- Tool call 序列

---

## 3. Round 1 — qwen3.5:4b vs gemma3:4b: Prompt Fix Verification

**日期:** 2026-03-27（第一輪）

### Objective

驗證原始 `slide_gen` 失敗（agent 輸出說明文字而非呼叫工具）是否由 **prompt 歧義**造成，並比較兩個模型在更新後 prompt 下的行為差異。

### Setup

| 配置項 | 內容 |
|--------|------|
| 測試場景 | `slide_gen` step：給定 `slide_outlines.json`，用 python-pptx 生成 PPTX |
| Prompt | 更新後的 `SLIDE_GEN_PMT`（明確指示必須用 `run_code` 執行，不可只輸出文字） |
| 工具 | `run_code`, `list_files`, `upload_file`, `get_all_layout` |
| 模型 | `qwen3.5:4b`, `gemma3:4b` |

**Prompt 改動：** 舊版使用 "Respond user with the python code"，4b 模型將其解讀為「把 code 寫在回應文字裡」。新版明確要求「必須用 `run_code` tool 執行」。

### Results

| 指標 | qwen3.5:4b | gemma3:4b |
|------|-----------|-----------|
| 任務完成 | ✅ | ✅ |
| `run_code()` 有呼叫 | ✅ | ✅ |
| `run_code()` 呼叫次數 | 16 | 1 |
| 生成的 code 含 `prs.save()` | ✅ | ✅ |
| `list_files()` 呼叫次數 | 1 | 3 |
| Final Answer 含問句 | ❌ | ❌ |
| 發生錯誤 | 無 | 無 |
| 總 tool call 次數 | 17 | 4 |

### Tool Call Sequence

**qwen3.5:4b:**
```
run_code → run_code → run_code → run_code → run_code →
run_code → run_code → run_code → run_code → run_code →
run_code → list_files → run_code → run_code → run_code →
run_code → run_code
（16 次 run_code，反覆修正才成功）
```

**gemma3:4b:**
```
run_code → list_files → list_files → list_files
（1 次 run_code 即成功，後續 list_files 確認檔案存在）
```

### Efficiency Comparison

| 指標 | qwen3.5:4b | gemma3:4b | 差距 |
|------|-----------|-----------|------|
| 總 tool calls | 17 | 4 | 4.25× |
| `run_code` 呼叫次數 | 16 | 1 | 16.0× |
| 成功所需 LLM rounds | 17 | 4 | 4.25× |

### Prompt Fix Validation

| 模型 | 舊 Prompt | 新 Prompt |
|------|-----------|-----------|
| qwen3.5:4b | ❌ 輸出說明文字，不執行 code | ✅ 呼叫 `run_code` |
| gemma3:4b | 未測試 | ✅ 呼叫 `run_code` |

### Analysis

**qwen3.5:4b — 「多次嘗試收斂型」**

- 能理解任務目標，知道要呼叫 `run_code`
- 但第一次生成的 python-pptx code 不正確，需要反覆 debug
- 16 次 `run_code` 中大部分是在修正錯誤（import 問題、placeholder index 錯誤、save 路徑等）
- Code generation 能力較弱，需要大量嘗試才能寫出可執行的 python-pptx 程式碼
- 資源消耗高：17 次 LLM call ≈ gemma3:4b 的 4.25 倍

**gemma3:4b — 「一次到位型」**

- 第一次 `run_code` 就包含正確的 python-pptx 程式碼（含 `prs.save()`）
- 後續 3 次 `list_files` 是主動驗證結果（符合 prompt 要求的驗證步驟）
- 執行策略清晰：write → execute → verify
- Code generation 能力明顯較強，對 python-pptx API 的掌握比 qwen3.5:4b 好

**結論：** 問題根因為 prompt 歧義（已修正），而非純粹的模型能力問題。兩個模型在新 prompt 下均能完成任務，但 gemma3:4b 效率遠高於 qwen3.5:4b。

---

## 4. Round 2 — gemma3:4b vs gemma3n:e2b vs gemma3n:e4b

**日期:** 2026-03-27（第二輪）

### Objective

評估新發布的 gemma3n 系列模型（`gemma3n:e2b`、`gemma3n:e4b`）在相同 ReAct agent 設定下的表現，以判斷是否可替代 `gemma3:4b` 作為 `LLM_SMART_MODEL`。

### Setup

| 配置項 | 內容 |
|--------|------|
| 測試場景 | `slide_gen` step（與第一輪完全相同：相同 prompt、tools、user message） |
| 目的 | 評估 gemma3n 系列與 gemma3:4b 的 ReAct 能力對比 |

### Results

#### gemma3:4b（重測確認）

| 指標 | 結果 |
|------|------|
| 耗時 (s) | 46.1 |
| `run_code()` 有呼叫 | ✅ |
| `run_code()` 呼叫次數 | 1 |
| code 含 `prs.save()` | ✅ |
| Final Answer 含問句 | ❌ |
| 發生錯誤 | 無 |
| 總 tool call 次數 | 4 |

Tool call 序列：
```
run_code → list_files → list_files → list_files
（1 次 run_code 即成功，後續 list_files 確認檔案存在）
```

Final answer tail（最後 ~400 字元）：
```
...one didn't already exist.
4.  The code iterated through each outline item in the JSON.
5.  For each item, a new slide was created using the specified layout.
6.  The slide title was set to the item's title.
7.  The slide content was set to the item's content, using the placeholder indices provided.
```

解讀：行為一致，gemma3:4b 複測結果與第一輪相同，確認穩定。

---

#### gemma3n:e2b

| 指標 | 結果 |
|------|------|
| 耗時 (s) | 600.0 |
| `run_code()` 有呼叫 | ❌ |
| `run_code()` 呼叫次數 | 0 |
| code 含 `prs.save()` | ❌ |
| Final Answer 含問句 | ❌ |
| 發生錯誤 | ✅ TIMEOUT |
| 總 tool call 次數 | 0 |

Tool call 序列：
```
[]（無任何 tool call）
```

錯誤訊息：
```
Operation timed out after 600.0 seconds. Currently active steps: run_agent_step
```

Final answer tail：（空，因 timeout 未完成）

解讀：`gemma3n:e2b` 在 600 秒 timeout 內 `run_agent_step` 仍未回應，推測模型在生成 ReAct 格式 response 時卡住（可能輸出過長或格式不符導致 workflow 無法解析）。該模型不適合 ReAct agent 使用。

---

#### gemma3n:e4b

| 指標 | 結果 |
|------|------|
| 耗時 (s) | 19.3 |
| `run_code()` 有呼叫 | ❌ |
| `run_code()` 呼叫次數 | 0 |
| code 含 `prs.save()` | ❌ |
| Final Answer 含問句 | ❌ |
| 發生錯誤 | 無 |
| 總 tool call 次數 | 0 |

Tool call 序列：
```
[]（無任何 tool call）
```

Final answer tail（最後 ~400 字元）：
```
```tool_code
print(open('/sandbox/slide_outlines.json').read())
```
```

解讀：`gemma3n:e4b` 極快（19.3s）但完全未呼叫任何工具。模型輸出了 `tool_code` 格式的程式碼區塊，但這是 Google Gemini 特有的 function call 格式，不是 LlamaIndex ReAct 所期待的 `Action/Observation` 格式。模型可能被訓練為使用 Gemini-style function calling，與 ReAct prompt 不相容，導致 workflow 立即終止並把原始輸出當作 final answer。

---

### Cross-Model Comparison Table (Rounds 1 + 2)

| 指標 | qwen3.5:4b | gemma3:4b | gemma3n:e2b | gemma3n:e4b |
|------|-----------|-----------|-------------|-------------|
| 耗時 (s) | N/A | 46.1 | 600.0（超時） | 19.3 |
| `run_code()` 有呼叫 | ✅ | ✅ | ❌ | ❌ |
| `run_code()` 呼叫次數 | 16 | 1 | 0 | 0 |
| code 含 `prs.save()` | ✅ | ✅ | ❌ | ❌ |
| `list_files()` 呼叫次數 | 1 | 3 | 0 | 0 |
| Final Answer 含問句 | ❌ | ❌ | ❌ | ❌ |
| 發生錯誤 | 無 | 無 | TIMEOUT | 無（但無效） |
| 總 tool call 次數 | 17 | 4 | 0 | 0 |
| ReAct 相容性 | ✅（勉強） | ✅（優秀） | ❌ | ❌ |

### Analysis

1. **gemma3:4b** 仍是最佳選擇：ReAct 格式相容、code generation 品質高、一次成功，且複測行為穩定。

2. **gemma3n:e2b** 不可用於 ReAct agent：600 秒內無法完成一個 agent step，推測為模型本身生成速度過慢或 context 處理問題導致 `run_agent_step` 卡住。

3. **gemma3n:e4b** 不可用於 ReAct agent（以 LlamaIndex ReAct workflow 為前提）：模型使用 Gemini-style `tool_code` 格式而非標準 ReAct `Action:` 格式，導致 workflow 將 tool call 解析為 StopEvent 並直接輸出原始 code 作為 final answer。若使用 Gemini function calling API 可能表現不同，但在本測試設定下不適用。

4. **gemma3n 系列**在 Ollama + LlamaIndex ReAct 組合下均失敗，不建議替換 gemma3:4b。

---

## 5. Round 3 — modify_slides Prompt Style Comparison

**日期:** 2026-03-27（第三輪）

### Objective

評估現有 `SLIDE_MODIFICATION_PMT` 是否需要像更新後的 `SLIDE_GEN_PMT` 一樣，加入明確的 `CRITICAL` 禁止行為指示；或者現有的 prose 格式在 `modify_slides` 情境下已足夠有效。

### Setup

| 配置項 | 內容 |
|--------|------|
| 測試場景 | `modify_slides` step：給定現有 PPTX 路徑與驗證 feedback，要求 agent 載入、修改並儲存為新版本 |
| 測試腳本 | `poc/agent-behavior-test/modify_test.py` |
| 模型 | `ollama/gemma3:4b`（前兩輪確認最佳 ReAct 模型） |

**用戶訊息格式**（與實際 `modify_slides` 完全一致）：
```
The latest version of the slide deck is at `/sandbox/paper_summaries.pptx`.
The feedback is: '{"results": [{"slide_idx": 2, "suggestion_to_fix": "..."},
                               {"slide_idx": 4, "suggestion_to_fix": "..."}]}'
Save the modified slide deck as `paper_summaries_v1.pptx`.
```

**比較的兩個 Prompt：**
- **Prompt A**：現行 `SLIDE_MODIFICATION_PMT`（5 步驟 prose 格式，無 CRITICAL 指示）
- **Prompt B**：仿照新版 `SLIDE_GEN_PMT` 風格改寫（加入 `CRITICAL: You MUST use run_code`、`ONLY job`、明確完成條件）

### Results

| 指標 | Prompt A (current) | Prompt B (improved) |
|------|-------------------|---------------------|
| 耗時 (s) | 39.7 | 336.8（達上限） |
| `run_code()` 有呼叫 | ✅ | ❌ |
| `run_code()` 呼叫次數 | 1 | 0 |
| `list_files()` 呼叫次數 | 1 | 0 |
| Code 儲存修改版檔案 | ✅ | ❌ |
| Final Answer 含問句 | ❌ | ❌ |
| 發生錯誤 | 無 | Max iterations (20) |
| 總 tool call 次數 | 2 | 0 |

### Tool Call Sequence

```
Prompt A: run_code → list_files
          （1 次即成功，list_files 確認新檔案存在）

Prompt B: []（無任何 tool call，20 輪迴圈後 timeout）
```

### Analysis

**Prompt A（現行）— 已達最佳表現**

- gemma3:4b 對現有的 5 步驟 prose 格式理解正確
- 第一次 `run_code` 即包含正確修改邏輯（降低 font size、調整 placeholder）
- 後續 `list_files` 主動確認新檔案存在
- 執行策略清晰：load → modify → save → verify
- 無需修改

**Prompt B（CRITICAL 風格）— 對此任務有害**

- gemma3:4b 在 CRITICAL 式 prompt 下完全未呼叫任何工具
- 20 次 `run_agent_step` 均產生非工具呼叫的輸出，workflow 無法解析為 Stop 或 ToolCall
- 推測原因：`ONLY job`、`Do NOT explain` 等強限制語言與 modification 任務的上下文（需要理解 feedback 再規劃修改）產生衝突，導致模型陷入無法決策的迴圈

### Deep Dive: Why Does the Same Model Respond So Differently?

從深度學習與 prompt engineering 兩個角度分析：

**核心差異：任務的「歧義度」**

`slide_gen`（從零生成）的模型 context 是：「你有工具，請生成投影片」。這個任務是**高歧義**的——「生成」可以是輸出程式碼文字（text generation 模式），也可以是呼叫工具執行程式碼（agent 模式）。gemma3:4b 在 pretraining 中見過大量「解釋/說明/展示程式碼」的對話，statistical prior 更偏向 text generation 模式。舊版 prose prompt 沒有強制打斷這個 prior，模型就滑向了「輸出說明文字」。CRITICAL 強指令（`ONLY job / Do NOT explain / MUST use run_code`）的作用是強行覆蓋這個 prior，把模型從 text generation 模式拉到 agent action 模式。

`modify_slides`（有具體 feedback）的模型 context 是：「這個檔案有問題：slide 2 文字溢出、slide 4 標題被截斷。儲存為 `paper_summaries_v1.pptx`」。這個任務是**低歧義**的——feedback 的存在提供了強烈的 action signal（有具體問題 → 需要修復；有具體路徑 → 需要存檔；有具體新檔名 → 知道目標）。Feedback 本身就是一種隱性的 CRITICAL 指令，它天然把模型拉到「執行修復」的 frame。模型不需要額外的強制語言來決定要做什麼。

**為什麼 Prompt B 反而讓 modify_slides 卡死？**

從 Transformer attention 的角度：

1. **指令衝突（Instruction Conflict）：** Prompt B 同時存在兩組互相競爭的信號：「Do NOT explain」（抑制 language generation）和「ONLY use run_code」（強制 action）。加上 user message 裡的 feedback 文字（本身就帶有敘述性語言），模型在 attention 層面同時接收到「抑制說明」和「有大量說明性 feedback 需要理解」的矛盾信號。結果：模型無法找到一個一致的 next token distribution，在 ReAct loop 裡不斷生成既不是 `Action:` 也不是 `Answer:` 的輸出，workflow 無法解析，陷入迴圈。

2. **Over-specification 問題：** 5 步驟 prose（Prompt A）的寫法讓模型可以把步驟當成狀態機來執行：每完成一步就有明確的下一步。CRITICAL 風格（Prompt B）的 `ONLY / MUST / Do NOT / Task is complete ONLY when...` 是全域約束，不是步驟指引。對於 4b 這種較小的模型，全域約束比局部步驟更難整合進 autoregressive generation。模型需要在每個 token 生成時都維持這些約束，認知負荷過高，容易在 ReAct format 的嚴格結構下失敗。

**Prompt Engineering 原則：**

這個實驗體現了一個重要原則：**Prompt 的最佳風格取決於任務的「prior 對齊程度」**。

| 情境 | Prior 對齊 | 最佳 Prompt 策略 |
|------|-----------|-----------------|
| `slide_gen`，高歧義任務 | 任務 prior 與 agent 模式不對齊 | 需要強覆蓋：CRITICAL 式語言打斷默認行為 |
| `modify_slides`，有具體 feedback | 任務 prior 天然對齊 agent 模式 | 強覆蓋反而破壞：prose 步驟指引維持模型在正確軌道 |

類比於人類行為：一個新員工不知道該做什麼，需要明確強硬的指令；但一個員工面對具體問題，給太多「你只能做這個、不能做那個」的限制，反而讓他不知所措。

**對小模型的深層意義：**

gemma3:4b 這類模型的 RLHF/instruction tuning 訓練數據中，helpfulness 的主要表現是「回應語言、解釋概念」，而非「執行工具」。所以：

- 任務歧義高 → 模型回歸 helpfulness prior → 說明文字
- 任務歧義低（有具體 feedback）→ 模型的 problem-solving prior 被激活 → 執行動作
- 加了 CRITICAL 但任務已經低歧義 → 兩套 prior 互相干擾 → 崩潰

這也解釋了為什麼更大的模型（如 70b）通常對 prompt 風格不那麼敏感——它們有足夠的 capacity 同時維持多個 prior，並在 context 中找到最合適的行為模式。

---

## 6. Overall Conclusions

| 結論 | 說明 |
|------|------|
| 原始失敗根因是 prompt 歧義 | 舊版 "Respond user with the python code" 被 4b 模型解讀為文字輸出，新版明確指定工具呼叫後問題消失 |
| gemma3:4b 是最佳 ReAct 模型 | 唯一在所有測試中均正確完成任務，且效率最高（最少 tool calls） |
| gemma3n 系列在本架構下不可用 | e2b timeout、e4b 使用不相容的 function call 格式 |
| Prompt 風格必須因任務而異 | slide_gen 需要 CRITICAL 指令；modify_slides 需要 prose 步驟格式；兩者不可互換 |
| 任務歧義度決定 prompt 策略 | 高歧義任務需要強制性語言覆蓋模型的 text generation prior；低歧義任務依賴 feedback 的 action signal |

### Prompt Style Compatibility Matrix

| Step | Prompt 風格 | gemma3:4b 表現 |
|------|------------|---------------|
| `slide_gen` | CRITICAL 強指令 | ✅ 一次成功 |
| `slide_gen` | 舊版 prose | ❌ 輸出說明文字 |
| `modify_slides` | 5 步驟 prose | ✅ 一次成功 |
| `modify_slides` | CRITICAL 強指令 | ❌ 無工具呼叫，timeout（20 iterations, 336.8s） |

**兩個 agent step 的 prompt 風格刻意保持不同，這是正確設計，不應統一。**

---

## 7. Actionable Recommendations

### 7.1 Model Configuration

```
LLM_FAST_MODEL=ollama/qwen3.5:4b
# 適合：filter_papers（分類）、summary2outline（壓縮摘要）
# 這類任務不需要寫 code，qwen3.5:4b 足夠且速度快

LLM_SMART_MODEL=ollama/gemma3:4b
# 適合：slide_gen / modify_slides（ReAct + code generation）
# gemma3:4b 在 code 生成上明顯更可靠且高效
# gemma3n 系列在本測試架構下不可用，維持使用 gemma3:4b
```

### 7.2 Prompt Strategy

| Step | Prompt 策略 | 狀態 |
|------|------------|------|
| `slide_gen` | CRITICAL 強指令式（含 `MUST use run_code`, `Do NOT explain`） | ✅ 已更新，保持現狀 |
| `modify_slides` | 5 步驟 prose 格式 | ✅ 保持現狀，不需修改 |
| 其他 LLM step | FunctionCallingProgram | 不適用（非 ReAct） |

### 7.3 Model Evaluation Checklist for Future Models

當評估新 LLM 模型是否可用於 ReAct agent 時，應確認：

- [ ] 模型的 function call 格式是否相容於 LlamaIndex ReAct（`Action:` / `Action Input:`）
- [ ] 模型是否使用 Gemini-style `tool_code` 或其他私有格式（若是，則不相容）
- [ ] 模型是否能在合理時間內（建議 < 120s）完成一個 `run_agent_step`
- [ ] 使用 `slide_gen` 任務作為基準測試：1 次 `run_code` 即成功為優秀；> 5 次為低效
- [ ] 複測確認行為穩定性（gemma3:4b 複測結果一致，符合生產使用要求）

### 7.4 Generalizable Prompt Engineering Principles

1. **在引入新 agent step 時，先判斷任務歧義度：** 若任務可被解讀為「說明文字」或「執行動作」，則需要 CRITICAL 式強指令。
2. **當任務已有具體 feedback 或明確輸入時，不要引入 CRITICAL 式全域約束**，改用步驟式 prose 格式作為狀態機指引。
3. **小模型（4b 量級）對 prompt 風格高度敏感**，不同任務類型可能需要截然不同的 prompt 結構；不可假設一種風格適用所有情境。
4. **不要僅因 prompt 統一性的工程考量而讓所有 agent step 使用相同 prompt 風格**，正確做法是根據每個 step 的任務特性設計專屬 prompt。

---

## 8. Round 4 — outlines_with_layout FunctionCallingProgram Prompt Comparison

**日期:** 2026-03-27（第四輪）

### Objective

測試 4 個 prompt 變體，以修正 `gemma3:4b` 在 `outlines_with_layout` 步驟使用 `FunctionCallingProgram` 時觀察到的 `{"properties": ...}` 包裝 bug：模型回傳 JSON Schema 格式而非實際欄位值，導致 Pydantic 驗證失敗（production log 2026-03-27 觀察到）。

### Setup

| 配置項 | 設定 |
|--------|------|
| Model | `ollama/gemma3:4b` |
| 測試 slide 類型 | 3（學術內容投影片、議程投影片、結語投影片） |
| Runs per combo | 3 |
| Total LLM calls | 36（4 prompts × 3 slides × 3 runs） |
| 測試腳本 | `poc/agent-behavior-test/augment_test.py` |

### Prompt Variants

| Prompt | 說明 |
|--------|------|
| **Prompt 1 (current)** | 現行 `AUGMENT_LAYOUT_PMT` 逐字版本，含挪威語「Plassholder for innhold」，無欄位定義 |
| **Prompt 2 (typo fix + field desc)** | 修正挪威語 typo，新增各輸出欄位的明確說明 |
| **Prompt 3 (+ few-shot)** | 同 Prompt 2，外加一個完整 worked example 示範正確輸出格式 |
| **Prompt 4 (Round2 no-wrap directive)** | 根據 Round 2 發現（明確禁止行為指示對 gemma3:4b 有效），直接加入 `CRITICAL: Do NOT wrap your answer inside a "properties" key` 指示 |

### 實驗結果

#### 腳本執行錯誤

腳本在第一個 LLM call 即發生以下 fatal error，全部 36 次 LLM call 均未執行：

```
ValueError: Model name ollama/gemma3:4b does not support function calling API.
```

**完整 traceback：**
```
File "augment_test.py", line 435, in <module>
    asyncio.run(main())
File "augment_test.py", line 350, in main
    result = await run_prompt_test(label, prompt)
File "augment_test.py", line 303, in run_prompt_test
    result = await run_single(prompt_template, slide)
File "augment_test.py", line 241, in run_single
    program = FunctionCallingProgram.from_defaults(
ValueError: Model name ollama/gemma3:4b does not support function calling API.
```

**觸發位置：** `llama_index.core.program.function_program.FunctionCallingProgram.from_defaults()` — 在嘗試建立 `FunctionCallingProgram` 實例時，LlamaIndex 會於建構期驗證底層 LLM 是否支援 function calling API。`ollama/gemma3:4b` 透過 LiteLLM 接入時，未被識別為支援 native function calling API 的模型，因此在任何 LLM 呼叫發出前即拋出 ValueError。

### 量化結果

由於腳本在 run=1/3（Prompt 1, slide "Attention Is All You Need"）時即中止，所有 prompt variant 均無任何執行數據：

| 指標 | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|------|----------|----------|----------|----------|
| Success rate | N/A | N/A | N/A | N/A |
| Layout valid rate | N/A | N/A | N/A | N/A |
| Both idx valid rate | N/A | N/A | N/A | N/A |
| Avg elapsed (s) | N/A | N/A | N/A | N/A |
| 'properties'-wrap errors | N/A | N/A | N/A | N/A |

### Per-Slide Breakdown

無數據（腳本未能完成任何一次 LLM call）。

### Analysis

**錯誤根因：FunctionCallingProgram 與 Ollama 模型的相容性問題**

`FunctionCallingProgram` 依賴 LLM 的 native function calling / tool use API（即 OpenAI-style tool call schema），而 `ollama/gemma3:4b` 透過 LiteLLM 介接時，LlamaIndex 的能力偵測邏輯判斷此模型不支援該 API，因此在 `from_defaults()` 建構期即拒絕初始化。

這意味著：
1. 原始 production bug（`{"properties": ...}` 包裝錯誤）不可能來自 `FunctionCallingProgram` + `ollama/gemma3:4b` 的組合——因為這個組合根本無法成功建立。
2. 若 production 中 `outlines_with_layout` 步驟曾正常運作（並在某次 log 中回傳 `{"properties": ...}`），表示實際使用的不是 `FunctionCallingProgram`，或是使用了不同的 LLM 介面（例如直接呼叫 `llm.complete()` 並以 prompt 要求 JSON 輸出，或使用了支援 function calling 的雲端模型）。
3. 4 個 prompt variant 均無法在此技術組合下進行比較。

**對原始 `{"properties": ...}` bug 的重新解讀：**

既然 `FunctionCallingProgram` 在 `ollama/gemma3:4b` 下無法啟動，production log 中的 `{"properties": ...}` wrapping 現象可能來自：
- 模型以 pure text generation 方式輸出 JSON，且直接把 Pydantic schema 的 `properties` 結構誤以為是輸出格式（常見於 structured output prompt 設計不清晰時）
- 使用了另一個 program 類型（如 `LLMTextCompletionProgram`）而非 `FunctionCallingProgram`
- 模型介面為支援 function calling 的雲端模型，而非本地 Ollama

### Recommendation

**短期（診斷為主）：**
- 確認 production 中 `outlines_with_layout` 步驟實際使用的 LLM program 類型（`FunctionCallingProgram` vs `LLMTextCompletionProgram` vs 其他）
- 確認 production LLM 模型是否為支援 native function calling 的版本（如 OpenAI GPT-4、Anthropic Claude，或 Ollama 中有 tool use 能力的模型）
- 若 production 確實在使用 `LLMTextCompletionProgram` + `ollama/gemma3:4b`，則 Prompt 4 的 `CRITICAL: Do NOT wrap in "properties"` 指示方向正確，值得在正確的 program 類型下重新測試

**中期（替代方案）：**
- 若需在本地 Ollama 環境使用 structured output，應改用 `LLMTextCompletionProgram`（以 prompt 引導 JSON 輸出）而非 `FunctionCallingProgram`
- 或評估使用支援 function calling 的本地模型（如 `ollama/llama3.1` 系列，部分版本支援 tool use）

**下一輪實驗（Round 5 建議）：**
- 將 `FunctionCallingProgram` 改為 `LLMTextCompletionProgram` 並重新執行 4 個 prompt variant 比較
- 或使用支援 function calling 的模型（如 `ollama/llama3.1:8b`）以正確觸發 `FunctionCallingProgram` 路徑

---

## 9. Round 5 — gemma3:4b vs qwen3.5:4b: outlines_with_layout Prompt Comparison

**日期:** 2026-03-27（第五輪）

### Objective

以雙模型並行方式，重新執行 Round 4 的 4 個 `AUGMENT_LAYOUT_PMT` prompt variant 比較實驗。本輪新增 `qwen3.5:4b` 作為候選模型（並停用 think mode），同時在程式建構層級捕捉 `FunctionCallingProgram` capability error，讓腳本在 error 下仍能完整執行而不中途崩潰。

### Background

Round 4 發現 `FunctionCallingProgram` 在 `ollama/gemma3:4b` 下於 `from_defaults()` 建構期即拋出 `ValueError`，導致全部 36 次 LLM call 均未執行。本輪實驗目的：

1. 加入 `ollama/qwen3.5:4b` 測試，確認是否有任何本地 4b 模型支援 `FunctionCallingProgram`
2. 以 graceful error handling（`capability_error` 類別）取代直接 crash，使結果可量化記錄
3. 對 qwen3.5:4b 加入 `additional_kwargs={"extra_body": {"think": False}}` 停用 think mode，避免額外推理 overhead 干擾測試

### Setup

| 配置項 | 設定 |
|--------|------|
| Models | `ollama/gemma3:4b`（無 additional_kwargs）、`ollama/qwen3.5:4b`（`think: False`） |
| 測試 slide 類型 | 3（學術內容投影片、議程投影片、結語投影片） |
| Runs per combo | 3 |
| Total LLM calls (max) | 72（2 models × 4 prompts × 3 slides × 3 runs） |
| 測試腳本 | `poc/agent-behavior-test/augment_test.py`（本輪更新版） |
| Error handling | `FunctionCallingProgram.from_defaults()` 建構期 exception 被捕捉為 `capability_error`，不中斷整體執行 |

### Prompt Variants（同 Round 4）

| Prompt | 說明 |
|--------|------|
| **Prompt 1 (current)** | 現行 `AUGMENT_LAYOUT_PMT` 逐字版本，含挪威語「Plassholder for innhold」，無欄位定義 |
| **Prompt 2 (typo fix + field desc)** | 修正挪威語 typo，新增各輸出欄位的明確說明 |
| **Prompt 3 (+ few-shot)** | 同 Prompt 2，外加一個完整 worked example 示範正確輸出格式 |
| **Prompt 4 (Round2 no-wrap directive)** | 直接加入 `CRITICAL: Do NOT wrap in "properties"` 指示 |

### 實驗結果

#### gemma3:4b 結果表

| 指標 | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|------|----------|----------|----------|----------|
| Success rate | 0% | 0% | 0% | 0% |
| Layout valid rate | 0% | 0% | 0% | 0% |
| Both idx valid rate | 0% | 0% | 0% | 0% |
| Avg elapsed (s) | 0.1 | 0.1 | 0.0 | 0.1 |
| 'properties'-wrap errors | 0 | 0 | 0 | 0 |
| Capability errors | 9/9 | 9/9 | 9/9 | 9/9 |

Per-slide success（runs per prompt = 3，全為 capability error）：

| Slide | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|-------|----------|----------|----------|----------|
| Attention Is All You Need | 0/3 | 0/3 | 0/3 | 0/3 |
| Agenda | 0/3 | 0/3 | 0/3 | 0/3 |
| Thank You | 0/3 | 0/3 | 0/3 | 0/3 |

#### qwen3.5:4b 結果表

| 指標 | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|------|----------|----------|----------|----------|
| Success rate | 0% | 0% | 0% | 0% |
| Layout valid rate | 0% | 0% | 0% | 0% |
| Both idx valid rate | 0% | 0% | 0% | 0% |
| Avg elapsed (s) | 0.1 | 0.0 | 0.0 | 0.0 |
| 'properties'-wrap errors | 0 | 0 | 0 | 0 |
| Capability errors | 9/9 | 9/9 | 9/9 | 9/9 |

Per-slide success（runs per prompt = 3，全為 capability error）：

| Slide | Prompt 1 | Prompt 2 | Prompt 3 | Prompt 4 |
|-------|----------|----------|----------|----------|
| Attention Is All You Need | 0/3 | 0/3 | 0/3 | 0/3 |
| Agenda | 0/3 | 0/3 | 0/3 | 0/3 |
| Thank You | 0/3 | 0/3 | 0/3 | 0/3 |

#### 實際錯誤訊息（以獨立腳本確認）

兩個模型均拋出完全相同的錯誤：

```
ValueError: Model name ollama/gemma3:4b does not support function calling API.
ValueError: Model name ollama/qwen3.5:4b does not support function calling API.
```

觸發位置：`llama_index.core.program.function_program.FunctionCallingProgram.from_defaults()` 建構期，LiteLLM capability check 拒絕初始化。

### Cross-Model Comparison

| 模型 | 最佳 Prompt | 最佳 Success rate | Capability errors | 'properties'-wrap errors |
|------|------------|------------------|-------------------|--------------------------|
| `ollama/gemma3:4b` | N/A（全部 cap_err） | 0% | 36/36 | 0 |
| `ollama/qwen3.5:4b` | N/A（全部 cap_err） | 0% | 36/36 | 0 |

**結論：兩個模型均無法通過 `FunctionCallingProgram` 能力驗證，沒有任何 model×prompt 組合可以執行。**

### Analysis

**qwen3.5:4b 是否支援 function calling？**

不支援。`ollama/qwen3.5:4b` 透過 LiteLLM 介接時，與 `ollama/gemma3:4b` 同樣被 LiteLLM 的 capability check 拒絕，拋出相同的 `ValueError`。雖然 Qwen 系列部分模型（如 `qwen2.5:7b-instruct-fp16`）在 Ollama 中透過 `/api/chat` 支援 tool call，但在 LiteLLM 的 `ollama/` provider 路由下，capability 判斷邏輯以模型名稱字串比對為主，`qwen3.5:4b` 未被識別為 function calling 相容模型。

**prompt variant 是否能修正此問題？**

不能。`FunctionCallingProgram` 的 capability error 發生在 `from_defaults()` 建構期，在任何 prompt 被送出給 LLM 之前。因此無論 Prompt 1～4 的措辭為何，均無法影響此驗證結果。Prompt 設計對於 `FunctionCallingProgram` capability check 失敗的情境完全無效。

**根本原因確認（與 Round 4 一致）：**

`FunctionCallingProgram` 依賴 LiteLLM 對模型的 native tool_call 能力識別。Ollama 的 `/v1/` 相容層雖然提供 OpenAI-style API，但 LiteLLM 的能力判斷邏輯不信任 `/v1/` 的 capability 自報（已知 Ollama 的 json_schema passthrough 有 bug），因此對 `ollama/` 路由下的多數模型一律拒絕。這是 Ollama 整合層的系統性限制，與個別模型能力無關。

**think mode 停用（qwen3.5:4b 的 `extra_body: {think: false}`）是否有影響？**

在本輪無法觀察其效果，因為 capability error 在 LLM call 發出前即觸發。`additional_kwargs` 的設定對 LiteLLM capability check 邏輯無影響。

### Recommendation

**本輪確立的核心結論：`FunctionCallingProgram` + Ollama 本地模型的組合，在現有 LiteLLM 整合層下是系統性不可行的。**

此限制與 prompt 設計、模型版本、think mode 均無關，是 LiteLLM capability check 機制對 `ollama/` provider 的一致性拒絕。

**短期行動方向（改用不依賴 native function calling 的 structured output 方法）：**

1. **方案 A：`LLMTextCompletionProgram` + JSON prompt**
   - 以 prompt 明確要求模型輸出符合 schema 的 JSON 字串，再以 Pydantic `.model_validate_json()` 解析
   - 不依賴 LiteLLM capability check，可在所有 Ollama 模型上運作
   - 需要設計清晰的 JSON 輸出指示（Prompt 4 的 CRITICAL 指示方向適用此方案）
   - **建議 Round 6 實驗**：以此方案重新執行 4 個 prompt variant 比較

2. **方案 B：`ollama` Python library 直接呼叫 + `format=schema`**
   - 使用 Ollama 的 structured output API（`format` 參數傳入 JSON schema），繞過 LiteLLM
   - Ollama 自身的 structured output 實作（grammar-based decoding）可強制輸出符合 schema，不依賴模型的 tool_call 能力
   - 缺點：需要脫離 LlamaIndex 生態，或以 custom LLM wrapper 包裝

3. **方案 C：改用支援 function calling 的雲端模型**
   - 若 production 環境可接受 API cost，使用 OpenAI GPT-4o-mini 或 Anthropic Claude Haiku
   - 這些模型通過 LiteLLM capability check，`FunctionCallingProgram` 可正常運作

**不建議的方向：**
- 繼續嘗試更多 Ollama 模型（如 `llama3.1:8b`）——即使部分模型支援 tool_call，也面臨 M1 記憶體壓力（8b 模型在 M1 8GB 下運行受限）
- 繼續在 `FunctionCallingProgram` 框架內調整 prompt——問題在底層 capability check，不在 prompt 設計

**下一輪實驗（Round 6 建議）：**
- 改用 `LLMTextCompletionProgram`，重新執行相同的 4 prompt × 2 model × 3 slide × 3 runs 矩陣
- 重點觀察：是否出現 `{"properties": ...}` wrapping bug（production log 中觀察到的根本問題）；若出現，哪個 prompt variant 能有效消除它

---
Function calling 不是一個統一標準，各家實作方式不同：                                                      
                                                                                                               
    OpenAI GPT-4 / GPT-4o                                                                                      
      → 原生支援 tool_calls API                                                                                
      → LiteLLM 直接識別，FunctionCallingProgram 可用                                                          
      → 原作者用這個，所以沒問題 ✅                                                                            
                                                                                                               
    Ollama (本地模型)                                                                                          
      → 要看模型有沒有 tools tag                                                                               
      → gemma3:4b / qwen3.5:4b 都沒有 → LiteLLM 拒絕建立 FunctionCallingProgram ❌                             
      → 就算有 tools tag，走的是 Ollama 自己的 /api/chat format 參數                                           
        不一定等於 OpenAI tool_calls schema                                                                    
                                                                                                               
    各家差異                                                                                                   
                                                                                                               
    ┌──────────────────┬──────────────────────────────────────────────────────────────────┐                    
    │     Provider     │                      Function Calling 機制                       │                    
    ├──────────────────┼──────────────────────────────────────────────────────────────────┤                    
    │ OpenAI           │ tool_calls 欄位，原生支援，LiteLLM 完整支援                      │                    
    ├──────────────────┼──────────────────────────────────────────────────────────────────┤                    
    │ Anthropic Claude │ tool_use 區塊，格式不同，LiteLLM 有轉換層                        │                    
    ├──────────────────┼──────────────────────────────────────────────────────────────────┤                    
    │ Ollama           │ 依模型而定：有 tools tag 的走 /api/chat format，沒有的完全不支援 │                    
    ├──────────────────┼──────────────────────────────────────────────────────────────────┤                    
    │ Groq             │ 支援 OpenAI 相容格式，LiteLLM 可用                               │                    
    ├──────────────────┼──────────────────────────────────────────────────────────────────┤                    
    │ Gemini           │ 自己的 function calling 格式，LiteLLM 有轉換層                   │                    
    └──────────────────┴──────────────────────────────────────────────────────────────────┘ 

原作者用 ChatGPT 為何可以

    FunctionCallingProgram 在 LiteLLM 底層走的是 OpenAI tool call API：

    LlamaIndex FunctionCallingProgram
        │
        ▼
    LiteLLM  →  POST /v1/chat/completions
                body: { "tools": [...schema...], "tool_choice": "auto" }
        │
        ▼
    OpenAI API → GPT-4o / GPT-4o-mini

    OpenAI 的模型原生支援這個格式，回傳：
    { "tool_calls": [{ "function": { "name": "SlideOutlineWithLayout", "arguments": "{...}" } }] }

    LlamaIndex 解析 arguments 字串 → Pydantic validate → 完成。

    原作者用 OpenAI 模型，這條路全程通。

    ---
    換成 Ollama 為何不行

    每家 provider 的 function calling 實作方式不同：

    ┌───────────┬─────────────────────────────────┬──────────────────────────────────┐
    │ Provider  │              機制               │              相容性              │
    ├───────────┼─────────────────────────────────┼──────────────────────────────────┤
    │ OpenAI    │ 原生 tool_calls API，有訓練支援 │ ✅ FunctionCallingProgram 直接用 │
    ├───────────┼─────────────────────────────────┼──────────────────────────────────┤
    │ Anthropic │ tool_use block，格式不同        │ LiteLLM 會轉換，通常可用         │
    ├───────────┼─────────────────────────────────┼──────────────────────────────────┤
    │ Ollama    │ 兩條路，見下方                  │ 視模型而定                       │
    └───────────┴─────────────────────────────────┴──────────────────────────────────┘

    Ollama 的情況最複雜：
    - /api/chat（原生端點）：支援 tools 參數，但只有 modelfile 裡有 tools 設定的模型才有效
    - /v1/chat/completions（OpenAI 相容端點）：接受 tools 參數格式，但轉換不完整，有已知 bug

    LiteLLM 呼叫 Ollama 時，先做 capability check：查 Ollama 回報的模型資訊裡有沒有 tools 支援。gemma3:4b 和
    qwen3.5:4b 都沒有 → 直接在建構期拋出 ValueError，程式碼根本不執行。

    ---
    Ollama 的 tools tag 是什麼

    Ollama 的 modelfile（模型配置）裡有一個 chat template，定義了怎麼格式化對話。

    有 tools tag 的模型，代表它的 chat template 裡有處理 tool call 的 token 和格式，例如：

    <|start_header_id|>ipython<|end_header_id|>   ← Llama3.1 的 tool result token

    這表示模型在訓練時就看過 tool call 格式的資料，知道怎麼產生正確的 function call 輸出。

    沒有 tools tag（如 gemma3:4b）= chat template 裡沒有 tool 相關 token = 模型沒有被訓練成做 function calling
    = 就算你送 tools schema 給它，它也不知道該怎麼回應，可能輸出普通文字、或原樣 echo schema。

    ---
    一句話總結

    ▎ Function calling 不是一個通用標準，而是每家廠商各自實作的能力。原作者用 OpenAI
    模型走的是有原生支援的路。換成 Ollama 本地模型後，必須先確認模型有 tools tag，且 LiteLLM
    能偵測到，FunctionCallingProgram 才能運作。否則要換用其他結構化輸出方式（如 Ollama 的 format 參數做
    constrained decoding）。


1. llm.structured_predict() / llm.astructured_predict()
                                                                                                               
    直接在 LLM 物件上呼叫，LlamaIndex 內部自動決定走哪條路：                                                   
                                                                                                               
    result = await llm.astructured_predict(                                                                    
        SlideOutlineWithLayout,                                                                                
        prompt=PromptTemplate("...{slide_content}..."),                                                        
        slide_content="..."                                                                                    
    )                                                                                                          
                                                                                                               
    內部邏輯由 pydantic_program_mode 控制：                                                                    
    - PydanticProgramMode.DEFAULT → 有 function calling 就用，沒有就 fallback                                  
    - PydanticProgramMode.LLM → 強制走 text completion 路徑                                                    
                                                                                                               
    ---                                                                                                        
    2. llm.as_structured_llm(OutputClass)                                                                      
                                                                                                               
    把 LLM 包裝成一個 StructuredLLM，然後用一般 chat 介面操作：                                                
                                                                                                               
    sllm = llm.as_structured_llm(SlideOutlineWithLayout)                                                       
    response = await sllm.achat(messages)                                                                      
    result = response.raw  # SlideOutlineWithLayout instance                                                   
                                                                                                               
    同樣內部自動選擇機制，對呼叫端透明。                                                                       

    ---                                                                                                       
    3. MultiModalLLMCompletionProgram                                                                          
                                                                                                               
    你的 codebase 裡 validate_slides 已經在用：                                                                

    from llama_index.core.program import MultiModalLLMCompletionProgram

    專門用於 VLM（有圖片輸入的情境），概念上是 LLMTextCompletionProgram 的多模態版本，不走 function calling。

    ---
    4. 手動 JSON parse（無框架）

    文件也提到的最底層方式：

    schema = MyModel.model_json_schema()
    prompt = f"Output JSON matching this schema: {schema}\n\n{user_content}"
    response = await llm.acomplete(prompt)
    result = MyModel.model_validate_json(response.text)

    ---
    整體對比

    ┌────────────────────────────────┬─────────────────────┬──────────────────────────┬──────────────────────┐
    │              方法              │   需要 function     │        跨模型相容        │       使用情境       │
    │                                │       calling       │                          │                      │
    ├────────────────────────────────┼─────────────────────┼──────────────────────────┼──────────────────────┤
    │ FunctionCallingProgram         │ ✅ 必須             │ ❌ 僅支援 tool-capable   │ GPT-4, Claude 等     │
    │                                │                     │ 模型                     │                      │
    ├────────────────────────────────┼─────────────────────┼──────────────────────────┼──────────────────────┤
    │ LLMTextCompletionProgram       │ ❌                  │ ✅                       │ 任何文字 LLM         │
    ├────────────────────────────────┼─────────────────────┼──────────────────────────┼──────────────────────┤
    │ structured_predict()           │ 自動選擇            │ ✅                       │ 懶人首選，讓框架決定 │
    ├────────────────────────────────┼─────────────────────┼──────────────────────────┼──────────────────────┤
    │ as_structured_llm()            │ 自動選擇            │ ✅                       │ 需要 chat 介面的場合 │
    ├────────────────────────────────┼─────────────────────┼──────────────────────────┼──────────────────────┤
    │ MultiModalLLMCompletionProgram │ ❌                  │ ✅                       │ 有圖片輸入           │
    ├────────────────────────────────┼─────────────────────┼──────────────────────────┼──────────────────────┤
    │ 手動 JSON parse                │ ❌                  │ ✅                       │ 需要最大控制權       │
    └────────────────────────────────┴─────────────────────┴──────────────────────────┴──────────────────────┘