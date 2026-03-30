# Frontend Overview

Frontend 使用 **Streamlit** 建置，提供研究主題輸入與投影片生成的操作介面。

## 目錄結構

```
frontend/
├── Home.py                          # App 進入點，頁面路由設定
├── pages/
│   ├── main_page.py                 # Home 頁（目前為空白頁）
│   └── slide_generation_page.py     # 主要功能頁面
├── utils/
│   └── layout.py                    # set_streamlit_page_config_once()（防重複呼叫的包裝）
├── Dockerfile
└── pyproject.toml
```

## 頁面路由

`Home.py` 用 Streamlit 的 `st.navigation()` 定義多頁面導覽：

```python
main_page = st.Page("pages/main_page.py", title="🏠 Home")
slide_gen_page = st.Page("pages/slide_generation_page.py", title="🧾 Slide Generation")
pg = st.navigation([main_page, slide_gen_page])
pg.run()
```

| 頁面 | 路徑 | 說明 |
|------|------|------|
| 🏠 Home | `/` | 首頁（預留） |
| 🧾 Slide Generation | `/slide_generation_page` | 主要功能：輸入主題、監看進度、審核 outline、下載結果 |

## App 設定

```python
st.set_page_config(
    page_title="Paper research and slide generation",
    page_icon="🤖",
    layout="wide",             # 寬版佈局
    initial_sidebar_state="expanded",
)
```

## Session State 變數清單

Streamlit 的 `session_state` 跨 rerun 保持狀態。以下是 `slide_generation_page.py` 使用的所有變數：

| 變數名稱 | 型別 | 初始值 | 說明 |
|---------|------|--------|------|
| `workflow_complete` | `bool` | `False` | workflow 是否完成，控制 auto-refresh 開關 |
| `received_lines` | `List[str]` | `[]` | 從 SSE 接收到的所有進度訊息 |
| `workflow_id` | `str \| None` | `None` | 當前執行的 workflow UUID |
| `workflow_thread` | `Thread \| None` | `None` | 背景 SSE 消費 thread |
| `user_input_required` | `bool` | `False` | 是否正在等待 user 審核 outline |
| `user_input_prompt` | `dict \| None` | `None` | 當前需審核的 outline 資料 |
| `message_queue` | `Queue` | `Queue()` | 背景 thread → 主 thread 的訊息佇列 |
| `user_input_event` | `threading.Event` | `Event()` | 通知背景 thread user 已提交回應 |
| `user_response_submitted` | `bool` | `False` | 防止重複提交 |
| `download_url_pptx` | `str \| None` | `None` | 完成後的 PPTX 下載 URL |
| `download_url_pdf` | `str \| None` | `None` | 完成後的 PDF 下載 URL |
| `pdf_data` | `bytes \| None` | `None` | 快取的 PDF 二進位內容 |
| `expander_label` | `str` | `"🤖⚒️Agent is working..."` | 進度 expander 的標題文字 |
| `user_feedback` | `str` | `""` | 當前 outline 的文字 feedback |
| `approval_state` | `int \| None` | `None` | thumbs feedback 狀態（0=👎, 1=👍） |
| `pending_user_inputs` | `deque` | `deque()` | 排隊中尚未顯示的 outline 審核請求 |
| `prompt_counter` | `int` | `0` | 用於生成唯一 widget key，避免 Streamlit key 衝突 |
| `final_result` | `dict \| None` | *(未初始化)* | workflow 完成時由 `process_messages()` 寫入，含 `download_pptx_url` 和 `download_pdf_url` |

## 相關文件

- [Slide Generation Page 詳細說明](./slide-generation-page.md)
- [Backend API Reference](../backend/api-reference.md)
- [Human-in-the-Loop 機制](../agent_workflows/human-in-the-loop.md)
