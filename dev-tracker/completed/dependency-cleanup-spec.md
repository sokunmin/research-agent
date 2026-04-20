# Feature Spec: dependency-cleanup

## 專案資訊
| 項目 | 值 |
|------|-----|
| 專案類型 | Python (Poetry) monorepo |
| 分支名稱 | `feat/dependency-cleanup` |
| 基於分支 | `dev` |
| Worktree 路徑 | `/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev-dependency-cleanup` |
| 建立時間 | 2026-03-13 |

## 目標
整理三份 pyproject.toml 與 Dockerfile，移除未使用套件、補宣告隱性依賴、升級 Streamlit API，解決 docker-compose build 失敗問題。

## 實作範圍
- [x] sub-phase 1：刪除 root `pyproject.toml`（monolith 遺留）
- [x] sub-phase 2：`backend/Dockerfile` — 移除 unoconv + python3-uno
- [x] sub-phase 3：`backend/pyproject.toml` — 移除 5 個未用套件，補 3 個隱性依賴
- [x] sub-phase 4：`frontend/pyproject.toml` — 升級 streamlit，移除 requests（改用 httpx）、sseclient、streamlit-autorefresh
- [x] sub-phase 5：`frontend/pages/slide_generation_page.py` — 清理 import、替換 API

## 複雜度分析

| 維度 | 評估 |
|------|------|
| 任務數量 | 5 個 sub-phase |
| 跨模組 | backend Dockerfile + 2 pyproject.toml + 1 Python 檔案 |
| 外部依賴 | poetry lock 需重新產生 |
| 狀態管理 | 無 |

**結論：** 複雜（5 sub-phases）

## 驗收標準
- root pyproject.toml 不存在
- `docker-compose build backend` 不出現 unoconv 錯誤
- backend poetry 環境有 tiktoken、pyyaml、networkx，無 jupyter/fake-useragent/free-proxy/feedparser/arxiv2text
- frontend poetry 環境 streamlit >= 1.55，無 requests/sseclient/streamlit-autorefresh
- slide_generation_page.py 無 streamlit_autorefresh/requests import，使用 st.pdf() 與 httpx

## 技術約束
- unstructured 保留（有 comment 說明未來用途）
- base64 import 保留（其他地方仍使用）
- gather_outline_feedback 保留在 main() 直接呼叫，不放入 fragment

## 當前進度
- 停在：全部 sub-phase 完成
- 已完成：sub-phase 1, 2, 3, 4, 5
- 下一步：smoke test → commit → merge
- 遇到的問題：無

## Smoke Test
```bash
# Sub-phase 1
ls pyproject.toml 2>&1 | grep -q "No such file" && echo "✅ root pyproject.toml removed"

# Sub-phase 2（靜態確認）
grep -v "unoconv\|python3-uno" backend/Dockerfile | grep -q "libreoffice" && echo "✅ Dockerfile clean"

# Sub-phase 3（靜態確認）
python3 -c "
import tomllib
with open('backend/pyproject.toml', 'rb') as f:
    d = tomllib.load(f)
deps = d['tool']['poetry']['dependencies']
assert 'jupyter' not in deps
assert 'tiktoken' in deps
print('✅ backend pyproject.toml OK')
"

# Sub-phase 4（靜態確認）
python3 -c "
import tomllib
with open('frontend/pyproject.toml', 'rb') as f:
    d = tomllib.load(f)
deps = d['tool']['poetry']['dependencies']
assert 'sseclient' not in deps
assert 'requests' not in deps
print('✅ frontend pyproject.toml OK')
"

# Sub-phase 5
python3 -c "
src = open('frontend/pages/slide_generation_page.py').read()
assert 'streamlit_autorefresh' not in src
assert 'import requests' not in src
assert 'st.pdf(' in src
assert 'httpx.post' in src
print('✅ slide_generation_page.py OK')
"
```
