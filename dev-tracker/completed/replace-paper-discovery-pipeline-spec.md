# Feature Spec: replace-paper-discovery-pipeline

## 專案資訊
| 項目 | 值 |
|------|-----|
| 專案類型 | `Python (Poetry)` |
| 分支名稱 | `feature/replace-paper-discovery-pipeline` |
| 基於分支 | `dev` |
| Worktree 路徑 | `/Users/chunming/MyWorkSpace/agent_workspace/research-agent/research-agent-replace-paper-discovery-pipeline` |

## 目標
用直接 OpenAlex BM25 搜尋 + 兩階段相關性過濾 + 四策略 PDF 下載，取代原本基於 Tavily + citation graph 的論文發現流程。

## 實作範圍
- [x] Phase 1a: hitl_workflow.py — 加入 _emit_message helper
- [x] Phase 1b: config.py — 移除 Tavily 設定，新增搜尋與過濾 config
- [x] Phase 1c: model_factory.py — ModelConfig 改 Pydantic，加 relevance_embed_model()
- [x] Phase 1d: prompts.py — 替換相關性 prompt，新增 query reformulation prompt
- [x] Phase 2: paper_scraping.py — 大幅重寫（搜尋、過濾、下載）
- [x] Phase 3a: events.py — 移除 TavilyResultsEvent，更新 FilteredPaperEvent
- [x] Phase 3b: summary_gen.py — 重寫 workflow steps

## 複雜度分析與 Sub-Phase 規劃

| 維度 | 評估 |
|------|------|
| 任務數量 | 7 個 checkbox |
| 跨模組 | 跨 5 個模組 |
| 外部依賴 | pyalex, requests, llama-index embedding |
| 狀態管理 | 有（workflow ctx.store） |

**結論：** 複雜（3 sub-phases）

**Sub-Phase 規劃：**

- [x] sub-phase 1：Phase 1（Foundation）— hitl_workflow + config + model_factory + prompts
- [x] sub-phase 2：Phase 2（paper_scraping.py 重寫）
- [x] sub-phase 3：Phase 3（events.py + summary_gen.py workflow 整合）

## 驗收標準
- TAVILY_API_KEY 可從 .env 省略不導致啟動失敗
- ModelConfig 是 Pydantic BaseModel（無 @dataclass import）
- paper.summary 非空（abstract 重建正確）
- paper.primary_category 含 topic-level 名稱
- PDF 檔名為 ArXiv ID 或 OpenAlex ID（非標題）
- 三個 phase smoke test 全通過

## 技術約束
- Python/Poetry，llama-index-core 0.14.x API
- litellm <= 1.82.0（版本限制）
- pyalex，requests

## 當前進度
- 停在：全部 sub-phase 完成
- 已完成：sub-phase 1、sub-phase 2、sub-phase 3
- 下一步：feat commit + merge 回 dev
- 遇到的問題：無

## Smoke Test（各 sub-phase 完成後執行）
### sub-phase 1 smoke test
```bash
cd backend
python -c "
from config import settings
print('PAPER_CANDIDATE_LIMIT:', settings.PAPER_CANDIDATE_LIMIT)
print('LLM_RELEVANCE_EMBED_MODEL:', settings.LLM_RELEVANCE_EMBED_MODEL)
from services.model_factory import model_factory
emb = model_factory.relevance_embed_model()
print('relevance embed model:', emb.model_name)
from prompts.prompts import RELEVANCE_SURVEY_HEURISTIC_PMT, ACADEMIC_QUERY_REFORMULATION_PMT
print('prompts OK')
from agent_workflows.hitl_workflow import HumanInTheLoopWorkflow
print('_emit_message:', hasattr(HumanInTheLoopWorkflow, '_emit_message'))
"
```

### sub-phase 2 smoke test
```bash
cd backend
python -c "
from agent_workflows.paper_scraping import (
    fetch_candidate_papers, PaperRelevanceFilter,
    PaperRelevanceResult, download_paper_pdfs, _reconstruct_abstract
)
inv = {'Attention': [0], 'is': [1], 'all': [2], 'you': [3], 'need': [4]}
assert _reconstruct_abstract(inv) == 'Attention is all you need'
assert _reconstruct_abstract({}) == ''
print('abstract reconstruction OK')
papers = fetch_candidate_papers('attention mechanism transformer')
assert len(papers) > 0
p = papers[0]
print(f'title: {p.title}')
print(f'summary (first 80): {p.summary[:80]}')
print(f'primary_category: {p.primary_category}')
print(f'keywords: {p.keywords}')
print(f'topics: {p.topics}')
"
```

### sub-phase 3 smoke test
Verify in logs (no live run needed — import check):
```bash
cd backend
python -c "
from agent_workflows.events import FilteredPaperEvent, PaperEvent
from agent_workflows.summary_gen import SummaryGenerationWorkflow
print('imports OK')
"
```
