---
## [2026-03-10] LiteLLM 1.80 gemini/text-embedding-004 路由錯誤，正確 model 為 gemini/gemini-embedding-001 `[版本: litellm==1.80]`
原因：LiteLLM 1.80 對 `gemini/` prefix 的 embedding model 統一使用 `batchEmbedContents` endpoint；但 `text-embedding-004` 已從 Google AI Studio API 移除，只剩 `gemini-embedding-001` 支援 `embedContent`。
修正：將 `LLM_EMBED_MODEL` 預設值改為 `gemini/gemini-embedding-001`（dim=3072）。
---
## [2026-03-10] poetry install 時 lock file 與 pyproject.toml 不同步需先執行 poetry lock `[通用]`
原因：直接修改 pyproject.toml 後執行 `poetry install`，lock file 版本不匹配導致 install 失敗並提示 "pyproject.toml changed significantly"。
修正：先執行 `poetry lock`（無需 `--no-update`），再執行 `poetry install --no-root`。
---
## [2026-03-09] macOS Python 3.12 spawn 模式導致 marker test script crash `[環境: macOS Python 3.12]`
原因：Python 3.12 on macOS 預設 `multiprocessing` 使用 `spawn`，子進程重新 import 主模組時執行 module-level 的 `paper2md()` 呼叫，觸發 `RuntimeError: bootstrapping phase`。
修正：將所有測試執行邏輯包進 `main()` 函數，並加上 `if __name__ == '__main__': main()`。
---
## [2026-03-09] `paper2md()` 每次呼叫重新載入模型，Test 1/2 各花 20-25 分鐘 `[版本: marker >= 1.0.0]`
原因：`paper2md()` 內部每次都呼叫 `create_model_dict()`，導致 5 個 surya 模型（共 3GB+）重複載入，MPS Metal shader 也需重新 warm up。
修正：在 `paper2md()` 加 `artifact_dict=None` 參數，外部統一建立後傳入重用；Test 2 可省下 ~5 分鐘模型重載時間。
---
## [2026-03-09] surya `Recognizing Text` 在 M1 MPS 上每次轉換耗時 12–18 分鐘 `[環境: Apple M1 / PyTorch MPS]`
原因：surya text recognition 使用 autoregressive encoder-decoder，PyTorch MPS 對此架構支援不完整（缺 FlashAttention、`torch.compile` 仍 early stage），MPS cold start 第一個 chunk 需 238s。
修正（緩解）：(1) 重用 `artifact_dict` 避免重複 warm up；(2) 設 `RECOGNITION_BATCH_SIZE=32~64`（預設 256 對 M1 16GB 可能造成 memory pressure）；(3) 繼承 `OcrBuilder` 並擴大 `skip_ocr_blocks`，跳過已有 pdftext 的 block types（`Text`、`SectionHeader` 等），保留 `TextInlineMath`；根本解需等 PyTorch MPS 成熟或改用 Apple MLX 框架。
---
## [2026-03-09] `RECOGNITION_BATCH_SIZE` 預設 256 可能造成 M1 memory pressure `[環境: Apple M1 16GB unified memory]`
原因：每個 batch item 佔 50MB，預設 256 = 12.8GB；M1 CPU/GPU 共用記憶體，surya 模型本身已佔 ~11GB，幾乎無剩餘空間，導致頻繁記憶體交換拖慢速度。
修正：設環境變數 `RECOGNITION_BATCH_SIZE=32` 或 `64` 執行；搭配 `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0` 可解除 PyTorch MPS 記憶體上限（注意：設 0.0 有系統崩潰風險）。
---
## [2026-03-06] LlamaParse v2 images_to_save 加在主流程使所有論文 parse 時間暴增 10x `[通用]`
原因：`output_options.images_to_save=["embedded"]` 讓 server 對每篇論文額外裁圖、編碼、上傳 S3，圖片多的論文（lora 6 張、flash 4 張）從 ~15s 暴增至 ~220s。
修正：`images_to_save` 只放在專門驗證圖片的 Test 7（只跑 1 篇 attention.pdf），主流程 parse 不加，保持快速。
---
## [2026-03-06] LlamaParse v2 expand=images_content_metadata 未搭配 images_to_save 導致 jobs 永遠 RUNNING `[通用]`
原因：`expand=["images_content_metadata"]` 讓 server 嘗試產出圖片 metadata，但未設定 `output_options.images_to_save`，server 無圖可回卻不 FAIL，job 永遠卡在 RUNNING；SDK 無 timeout，client 無限 poll。
修正：必須同時設定 `output_options={"images_to_save": ["embedded"]}` 才能搭配 `images_content_metadata` expand；或完全不加此 expand。
---
## [2026-03-06] LlamaParse v2 output_options.embedded_images 格式錯誤導致 422 `[版本: llama-cloud>=1.0]`
原因：官方部分範例寫 `output_options={"embedded_images": {"enable": True}}`，但實際 API schema 不接受此欄位，回傳 422 `extra_forbidden`。
修正：正確格式為 `output_options={"images_to_save": ["embedded"]}`，對應官方 cURL 文件。
---
## [2026-03-06] LlamaParse 開發誤用 v1 舊版 API 導致無聲卡死 `[版本: llama-cloud-services < 1.0]`
原因：誤將棄用的舊版套件 (`llama-cloud-services`) 當作 v2 API，其 async poll 機制遇到無額度 (如 agentic_plus) 會因為沒有 timeout 而無限卡死。
修正：全面改用新版官方 SDK `llama-cloud >= 1.0`，並使用 `AsyncLlamaCloud` client 的兩段式呼叫 (`files.create` -> `parsing.parse`)。
## [2026-03-05] litellm>=1.82 與 llama-index<0.12 版本衝突，無法裝進主 poetry 環境 `[版本: litellm>=1.82 + llama-index<0.12]`
原因：llama-index<0.12 鎖定 llama-index-llms-openai<0.3.0，而 litellm>=1.82 要求更新版本，poetry dependency resolver 直接 fail
修正：在 poc 目錄建立獨立 venv（`python3 -m venv .venv && .venv/bin/pip install litellm`），不動主專案；正式整合需評估升級 llama-index 至 >=0.12
---
