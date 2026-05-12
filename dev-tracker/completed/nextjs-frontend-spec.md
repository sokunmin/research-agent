# Feature Spec: nextjs-frontend

## 專案資訊
| 項目 | 值 |
|------|-----|
| 專案類型 | Python (backend) + Node.js/TypeScript (frontend) |
| 分支名稱 | `feature/nextjs-frontend` |
| 基於分支 | `dev` |
| 完成時間 | 2026-05-12 |

## 目標
以 Next.js + Vercel AI SDK 取代 Streamlit 前端，實現真正的即時 SSE streaming（消除 5 秒 polling），並採用 Gemini Canvas 雙欄佈局（左聊天 / 右畫布）支援 HITL outline 審核與 PDF 預覽。

## 實作範圍
- [x] backend/main.py：CORS 改為 localhost:3001，SSE 格式改為 AI SDK UIMessageStream v5（start / data-* / finish / [DONE]）
- [x] backend/agent_workflows/slide_gen.py：`gather_feedback_outline` 加 `num_workers=1`，修正多 paper 同時進 HITL 時 shared future broadcast bug
- [x] backend/agent_workflows/schemas.py：`WorkflowStreamingEvent.event_type` Literal 新增 `"paper_total"`
- [x] frontend/（Next.js）：取代舊 Streamlit frontend/，含完整 canvas 佈局、chat thread、HITL inline form、PDF iframe 預覽
- [x] docker-compose.yml：移除舊 Streamlit service，新增 Next.js frontend service（build arg 傳 NEXT_PUBLIC_BACKEND_URL）
- [x] README.md：更新 demo 影片連結（新 YouTube ID ZnDdceQaVOg）與高解析縮圖（maxresdefault.jpg）

## 複雜度分析與 Sub-Phase 規劃

| 維度 | 評估 |
|------|------|
| 任務數量 | 6 個主要變更，跨 backend + frontend |
| 跨模組 | backend（main.py、slide_gen.py、schemas.py）+ frontend（全新 Next.js app） |
| 外部依賴 | Vercel AI SDK（`ai`、`@ai-sdk/react`）、shadcn/ui、react-resizable-panels |
| 狀態管理 | 複雜：SSE stream → useWorkflow hook → canvas phase state machine |

**結論：** 複雜（3 sub-phases）

**Sub-Phase 規劃：**

- [x] sub-phase 1：backend SSE 格式重寫（main.py CORS + event_generator + StreamingResponse headers）
- [x] sub-phase 2：Next.js 前端（scaffold + useWorkflow hook + canvas 佈局 + chat thread + HITL form + PDF preview）
- [x] sub-phase 3：HITL serial fix（slide_gen.py num_workers=1）+ frontend 取代（刪舊 Streamlit、docker-compose 更新）

## 驗收標準
- 提交 query → step progress 即時出現（無 5 秒延遲）
- HITL form 在 chat thread 內 inline 顯示（非 modal）
- 右側畫布依 phase 切換：空白 → 進度卡 → outline viewer → PDF iframe
- Approve / Reject + feedback 均可正確送出，workflow 繼續執行
- 多篇 paper 的 HITL 逐一串行出現，不互相覆蓋（num_workers=1 修正）
- PDF iframe 正確渲染，PPTX / PDF 下載按鈕可用
- Docker `make up` 後 http://localhost:3001 可存取

## 技術約束
- `NEXT_PUBLIC_*` 變數必須透過 Docker build arg 傳入（不可用 environment:），因為 Next.js 在 build time 嵌入
- SSE 下載 URL 使用 `http://localhost:8000`（非 `http://backend:80`），瀏覽器無法解析 Docker 內部 hostname
- Vercel AI SDK `transient: true` 的 data part 不出現在 `message.parts`，只透過 `onData` callback 處理，不可從 messages array 讀取
- `--ff-only` merge 確保 dev history 線性，`clean-merge-to-main.yml` cherry-pick 才能正常運作

## 當前進度
- 停在：全部 sub-phase 完成
- 已完成：sub-phase 1、2、3
- 下一步：無，feature 已 merge 回 dev
- 遇到的問題：詳見 dev-tracker/error-log.md（shadcn ToggleGroup 型別、ResizablePanelGroup prop、ScrollArea min-h-0、WorkflowStreamingEvent Literal 未同步）

## Smoke Test 結果
- 端對端完整 workflow 驗證：通過（錄製 demo 影片為憑：https://youtu.be/ZnDdceQaVOg）
- HITL 多 paper 串行：通過（num_workers=1 修正後）
- Docker build + `make up`：通過
