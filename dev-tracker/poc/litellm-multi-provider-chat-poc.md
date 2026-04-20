# PoC: litellm-multi-provider-chat

## 狀態
- 目前狀態：`approved`
- 建立時間：2026-03-05T14:57:00+08:00
- 最後更新：2026-03-05T20:25:00+08:00
- PoC 程式碼：`poc/litellm-multi-provider-chat/`
- 來源 spec：無（自然語言輸入）

## 核心驗證問題
1. LiteLLM 能否以統一介面對 OpenRouter/Gemini/Mistral/Groq/Ollama 完成 chat 呼叫？

## PoC 邊界（不做的事）
- 不處理 retry/fallback
- 不寫測試
- 不考慮 streaming
- 不整合現有 codebase

## 技術選擇
- `litellm.completion()` 統一入口
- 各 provider model 前綴：`openrouter/`、`gemini/`、`mistral/`、`groq/`、`ollama/`
- Ollama 額外傳入 `api_base="http://localhost:11434"`
- API keys 從 `.env.local`（poc 目錄）讀取

## 驗證結果

| Provider | 結果 | 延遲 | 備註 |
|---|---|---|---|
| OpenRouter qwen/qwen3-4b:free | ❌ | - | upstream rate limit (free tier)，非 LiteLLM 問題 |
| Gemini gemini-2.5-flash | ✅ | 1.29s | 正常 |
| Mistral mistral-small-2506 | ✅ | 0.46s | 正常 |
| Groq openai/gpt-oss-20b | ✅ | 0.30s | 正常 |
| Ollama gemma3:4b | ✅ | 5.27s | 本機推理正常 |

**4/5 通過**。OpenRouter 失敗是 free model upstream 限流，與 LiteLLM 介面無關。

## 整合建議
1. LiteLLM `completion()` 介面統一可行，僅需切換 model 字串前綴即可換 provider
2. Ollama 需額外傳 `api_base="http://localhost:11434"`
3. OpenRouter free tier model 建議加 retry 或換付費 model
4. 各 provider API key 建議集中管理於環境變數，不寫死在程式碼
5. 主專案若要引入 litellm，注意與 `llama-index<0.12` 有版本衝突，需評估升級策略

## 狀態歷程
- 2026-03-05T14:57:00+08:00：建立，in-progress
- 2026-03-05T16:24:00+08:00：執行驗證，4/5 通過，等待使用者確認
- 2026-03-05T20:25:00+08:00：使用者確認，approved（改用 google/gemma-3n-e4b-it:free，5/5 全過）
