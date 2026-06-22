# Feature Spec: docling-rag-pipeline

## 專案資訊
| 項目 | 值 |
|------|-----|
| 專案類型 | Python (Poetry / micromamba py3.12) |
| 分支名稱 | `feat/docling-rag-pipeline` |
| 基於分支 | `dev` |
| 來源 | PoC 整合（`dev-tracker/poc/docling-qdrant-poc.md`、`dev-tracker/poc/rag-filtering-poc.md`） |
| PoC 程式碼參考 | `poc/docling-qdrant/`、`poc/rag-filtering/` |

## PoC 核心驗證結論
- **docling-qdrant**：Docling M1 解析 ✅、HybridChunker + contextualize ✅、Qdrant local file ✅、RAG 摘要 ✅
- **rag-filtering**：ChunkFilter 兩層比對 ✅、28 篇 drop rate 21% 無誤殺 ✅

## 目標
將 Docling PDF 解析、HybridChunker、ChunkFilter、Qdrant local vector store、RAG-based 摘要整合進正式 pipeline，取代原有的 marker-pdf + VLM image-based 摘要路徑。

## 實作範圍
- [x] sub-phase 1：`slide_gen.py` content_fix（standalone bug fix）
- [x] sub-phase 2：filter_tools + config + pyproject
- [x] sub-phase 3：events + smart_llm + multimodal + model_factory
- [x] sub-phase 4：docling_chunker + rag_index_builder + vector_store（新增 service files）
- [x] sub-phase 5：paper_scraping（Docling 取代 marker-pdf）
- [x] sub-phase 6：summary_gen（主要改寫，新增 check_paper_status step）
- [x] sub-phase 7：docker-compose volumes

## 複雜度分析與 Sub-Phase 規劃

| 維度 | 評估 |
|------|------|
| 任務數量 | 7 個 sub-phases，15 個檔案異動 |
| 跨模組 | 跨 services/、agent_workflows/、tools/、config |
| 外部依賴 | docling、qdrant-client、pypdf（新增）；marker-pdf、pymupdf、tavily（移除） |
| 狀態管理 | 有複雜非同步邏輯（check_paper_status + n_pdfs race condition fix） |

**結論：** 複雜（7 sub-phases）

## 已知修正點（驗證時發現）
1. `_summarize_with_rag`：prompt 需帶入 `context`（`f"\n\n{context}"`）
2. `.env.example`：同時移除 `LLM_EMBED_MODEL` 和 `LLM_RELEVANCE_EMBED_MODEL`
3. `pyproject.toml`：`qdrant-client >= 1.17.0`（Gridstore 需 1.17+）
4. `pyproject.toml`：移除 `llama-index-storage-docstore-redis`、`llama-index-storage-index-store-redis`、`llama-index-vector-stores-qdrant`
5. `docling_chunker.py`：`BaseTokenizer` 正確 import 路徑為 `docling_core.transforms.chunker.tokenizer.base`
6. `tests/integration/test_2_filter.py`：`relevance_embed_model()` → `embed_model()`
7. `nemotron-3-super:cloud` 開啟 thinking mode 時回傳空 content：`extra_body={"think": False}` 解決
8. `ImageDocument(image=bytes)` crash：改用 `ImageDocument(image_path=...)` 解決
9. tiktoken vs BERT tokenizer 不一致 → HTTP 400：NFKC normalize + 截斷至 1900 BERT tokens 解決
10. `SemanticSplitterNodeParser` HTTP 400：用 `TruncatingEmbeddingWrapper` wrap embed model 解決
11. `MarkdownElementNodeParser(llm=None)` 回退 OpenAI：改傳 `LiteLLM(model="ollama/ministral-3:14b-cloud")` 解決
12. `QueryFusionRetriever` async + Qdrant local file lock：`use_async=False` 解決

## 技術約束
- 測試用 `micromamba run -n py3.12`，不用 `poetry run`
- `normalize()` 在 `filter_tools.py` 中不得更動（`@staticmethod` 保留、inline comments 保留）
- `summary_gen_w_qe.py` 已在 dev 刪除（commit: cffbdda）
- 注意：`backend/tools/filter_tools.py` 未 commit 至 dev，feat worktree 中不存在（將在 sub-phase 2 全新寫入）
- 所有 comments 禁止包含內部 project 代號（Stage N、Exp N/N 等）
- git commit 禁止加 `Co-authored-by` trailer

## 驗收標準
- `make test`（unit tests）全數通過
- `micromamba run -n py3.12 python -c "from backend.services.smart_llm import SmartLiteLLM; print('ok')"` 可 import
- docker-compose build 無 error

## 當前進度
- 停在：全部 sub-phase 完成
- 已完成：sub-phase 1–7（backend 整合）+ Phase 0–3 RAG 實驗（PoC 驗證）
- 下一步：squash merge feat → dev，寫 experiments/03-rag-summarization-pipeline/ 報告
- 遇到的問題：詳見 dev-tracker/error-log.md

## Smoke Test（各 sub-phase 完成後執行）
- 實際 import 剛完成的模組，確認無 ImportError
- sub-phase 6 完成後：`micromamba run -n py3.12 python -c "from agent_workflows.summary_gen import SummaryGenerationWorkflow; print('ok')"`
- **不通過 → 修復 → 繼續**

## 完成後步驟
（執行 Completion Steps）
