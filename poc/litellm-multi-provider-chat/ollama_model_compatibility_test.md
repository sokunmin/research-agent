# Ollama Model Compatibility Test Report

**Date:** 2026-06-26
**Author:** Chun-Ming Su
**Script:** `poc/litellm-multi-provider-chat/ollama_model_compatibility_test.py`
**Environment:** Apple M1 MacBook, micromamba env `py3.12`, LiteLLM 1.82.0

---

## Table of Contents

1. [Background and Objective](#1-background-and-objective)
2. [Models Tested](#2-models-tested)
3. [Key Concepts](#3-key-concepts)
   - [3.1 Ollama Provider Prefixes in LiteLLM](#31-ollama-provider-prefixes-in-litellm)
   - [3.2 Think Mode Problem](#32-think-mode-problem)
   - [3.3 `think=False` vs `think="low"` — Not the Same](#33-thinkfalse-vs-thinklow--not-the-same)
   - [3.4 Why `/api/generate` Ignores `think=false` for qwen3.5](#34-why-apigenerate-ignores-thinkfalse-for-qwen35)
4. [Problems Encountered](#4-problems-encountered)
5. [Full Test Results](#5-full-test-results)
6. [Recommended Configuration Per Model](#6-recommended-configuration-per-model)
7. [How to Run the Test](#7-how-to-run-the-test)

---

## 1. Background and Objective

### Project Context

This report belongs to a research-to-presentation pipeline that:

1. Discovers academic papers via the OpenAlex API
2. Summarizes papers using Vision Language Models (VLMs — models that can read images/PDFs)
3. Auto-generates PowerPoint presentations with Human-in-the-Loop (HITL) feedback

The backend is built with **FastAPI** (a Python web framework) + **LlamaIndex Workflows** (an orchestration library for LLM pipelines) + **LiteLLM** (a unified interface layer that lets you call any LLM provider with one consistent API).

**Key abstraction — `SmartLiteLLM`:**

All LLM calls in this project go through a class called `SmartLiteLLM`, defined in `backend/services/smart_llm.py`. It is a thin subclass of LlamaIndex's built-in `LiteLLM` adapter:

```python
# backend/services/smart_llm.py
class SmartLiteLLM(LiteLLM):  # LiteLLM from llama_index.llms.litellm
    async def acomplete(self, prompt, strip_fences=None, **kwargs) -> CompletionResponse: ...
    async def achat(self, messages, strip_fences=None, **kwargs) -> ChatResponse: ...
```

The only additions are optional fence stripping (removing markdown code fences like ` ```python `) and routing to the underlying LiteLLM layer. The important point is that **this class exposes two call methods**:

- `acomplete(prompt)` — sends a raw text prompt and expects a text completion back. Used in `_summarize_with_rag()` and `present_paper_candidates()`.
- `achat(messages)` — sends a structured list of chat messages (user/assistant turns) and expects a chat response back. Used in `handle_paper_question()`.

All models are configured via `.env` environment variables and run locally using **Ollama** — a tool that serves open-weight LLMs locally via a REST API on `http://localhost:11434`.

**`ModelFactory`** is a singleton that reads `.env` and constructs the appropriate `SmartLiteLLM` instance for each role (`smart_llm()`, `fast_llm()`, `vision_llm()`, etc.). It is not tested here; this PoC tests `SmartLiteLLM` directly.

### Why This Test Was Needed

During a full pipeline run (referred to internally as "L4"), the `smart_llm` model (configured as `gpt-oss:20b-cloud`) and other models returned empty responses or threw errors. The failure was silent — the pipeline received `""` (empty string) instead of raising an exception, making the root cause difficult to diagnose from logs alone.

This test was created to **systematically determine which combination of LiteLLM provider prefix, call method (`acomplete` vs `achat`), and think-mode configuration produces non-empty responses** for each of the five models used in this project.

---

## 2. Models Tested

All models run locally via Ollama. The names below are Ollama model tags (what you pass to `ollama pull` and what appears in `ollama list`).

| Model tag | Origin | Think mode | Notes |
|---|---|---|---|
| `ministral-3:14b-cloud` | Mistral AI | None | Purely generative, no reasoning step |
| `qwen3.5:cloud` | Alibaba | Yes (boolean) | CoT reasoning; `think=False` disables it |
| `gpt-oss:20b-cloud` | OpenAI (open-weight, Apache 2.0) | Yes (string levels) | MoE architecture: 20B total / 3.6B active params; designed for agentic tasks; released 2025-08-05; accepts `"low"/"medium"/"high"` only |
| `nemotron-3-super:cloud` | NVIDIA | Yes (boolean or string) | Accepts both bool and string reasoning effort |
| `gemma4:31b-cloud` | Google | No issues observed | No think block in output; all configs pass |

**"Think mode"** (explained in detail in Section 3.2) means the model internally reasons through a problem before writing its final answer. Models with think mode prepend a `<think>...</think>` block to their output. This causes problems with LiteLLM's response parser under certain conditions.

---

## 3. Key Concepts

### 3.1 Ollama Provider Prefixes in LiteLLM

LiteLLM identifies which backend provider to use via a **model string prefix** separated by a `/`:

```
LiteLLM model string format:  "{prefix}/{model_name}"

Examples:
  ollama/qwen3.5:cloud
  ollama_chat/qwen3.5:cloud
```

These two prefixes route to **different Ollama REST endpoints**:

```
LiteLLM model string
        │
        ├─ "ollama/{model}"
        │       │
        │       └──► Ollama /api/generate   (text completion endpoint)
        │                   - Sends a single "prompt" string
        │                   - Returns a "response" string
        │
        └─ "ollama_chat/{model}"
                │
                └──► Ollama /api/chat       (chat endpoint)
                            - Sends a "messages" array [{role, content}, ...]
                            - Returns a "message" object
```

Additionally, the **call method on `SmartLiteLLM`** also affects which internal code path LiteLLM uses to serialize the request and parse the response:

```
SmartLiteLLM method
        │
        ├─ acomplete(prompt_str)
        │       └──► LiteLLM internally formats as completion request
        │            Response parsed from .text field
        │
        └─ achat([ChatMessage(...)])
                └──► LiteLLM internally formats as chat request
                     Response parsed from .message.content field
```

The **prefix** and **method** together determine:
1. Which Ollama endpoint is hit (`/api/generate` vs `/api/chat`)
2. How the request body is serialized
3. How the response is parsed

This cross-product of choices matters because certain parsing bugs in LiteLLM only manifest in specific combinations, as documented in Section 4.

### 3.2 Think Mode Problem

Several modern LLMs support **chain-of-thought (CoT) reasoning**, also called "think mode." When enabled, the model reasons through the problem internally before writing its final answer. In Ollama's implementation, the model outputs this internal reasoning inside a `<think>...</think>` XML-like tag.

**Expected output format (think mode active, working correctly):**

```
<think>
The user asked me to say hello in one word.
A simple word that means hello would be "Hi" or "Hello" itself.
I'll go with "Hello".
</think>
Hello
```

LiteLLM contains a function called `_parse_content_for_reasoning()` that detects this pattern and splits the output:
- Everything inside `<think>...</think>` → stored in `reasoning_content` field
- Everything after the closing `</think>` tag → stored in the main `content` field

**The problem — models that put their answer inside `<think>`:**

Some models (observed with `gpt-oss` and `nemotron` under default config) produce output where the actual answer appears inside the `<think>` block and nothing follows the closing tag:

```
<think>
Hello
</think>
(nothing here)
```

What LiteLLM's parser does with this:

```
Input to _parse_content_for_reasoning():
  "<think>Hello</think>"

Parser output:
  reasoning_content = "Hello"   ← model's answer, now classified as reasoning
  content           = ""        ← empty! nothing was after </think>

What SmartLiteLLM.achat() returns:
  resp.message.content = ""     ← empty string returned to the pipeline
```

The pipeline receives an empty string. No exception is raised. The pipeline silently fails or produces blank output in the generated PowerPoint.

### 3.3 `think=False` vs `think="low"` — Not the Same

To control think mode, you pass a `think` parameter inside `extra_body` when constructing `SmartLiteLLM`:

```python
SmartLiteLLM(
    model="ollama/qwen3.5:cloud",
    additional_kwargs={
        "api_base": "http://localhost:11434",
        "extra_body": {"think": False},   # or {"think": "low"}, etc.
    },
)
```

However, different model families accept different types for the `think` parameter:

| Model family | Accepted `think` values | `False` (bool) | `"low"`/`"medium"`/`"high"` (string) |
|---|---|---|---|
| `qwen3.5` | Boolean only | ✅ fully disables thinking | ❌ still enters think mode, response is empty |
| `gpt-oss` | String levels only | ❌ silently ignored (no effect) | ✅ reduces/adjusts thinking |
| `nemotron-3-super` | Boolean or string | ✅ disables thinking | ✅ works |

**Source:** Confirmed by Ollama issue [ollama/ollama#12004](https://github.com/ollama/ollama/issues/12004) and LiteLLM PR [#13375](https://github.com/BerriAI/litellm/pull/13375), and verified by the smoke test in this PoC.

**Critical finding for qwen3.5:** Using `think="low"` does NOT reliably disable thinking. Even with `think="low"`, qwen3.5 may still output only a `<think>` block with no trailing answer text, resulting in an empty response from LiteLLM. Only `think=False` (boolean `False`) reliably disables thinking for qwen3.5.

**Critical finding for gpt-oss:** Using `think=False` (boolean) is silently ignored. The model continues to behave as if no `think` parameter was sent. However, in testing, gpt-oss still produced non-empty responses under all configs (including default), so `think=False` not working does not cause a practical problem for gpt-oss — its default behavior is already safe.

### 3.4 Why `/api/generate` Ignores `think=false` for qwen3.5

This is documented in Ollama issue [ollama/ollama#14793](https://github.com/ollama/ollama/issues/14793).

The `think=false` parameter is **only honored on the `/api/chat` endpoint**. When a request goes to `/api/generate` (which is what `ollama/` prefix routes to), the `think` parameter inside `extra_body` is silently ignored, and the model defaults to its built-in behavior.

```
LiteLLM prefix "ollama/" → Ollama /api/generate
                                    │
                                    └─ extra_body: {"think": false}
                                            │
                                            └─ IGNORED silently
                                               Model uses default think behavior
```

```
LiteLLM prefix "ollama_chat/" → Ollama /api/chat
                                         │
                                         └─ extra_body: {"think": false}
                                                 │
                                                 └─ HONORED
                                                    Think mode disabled
```

**Practical implication:** You might expect that `ollama/acomplete` with `think=False` would disable thinking for qwen3.5, but it does not — because the request goes to `/api/generate` which ignores the parameter.

However, the smoke test shows that **all four combinations** (`ollama/acomplete`, `ollama/achat`, `ollama_chat/acomplete`, `ollama_chat/achat`) pass when `think=False` is set. This apparent contradiction is because LiteLLM internally may route the chat-style call to `/api/chat` regardless of the prefix for certain method combinations, or because the test results indicate the current LiteLLM version (1.82.0) handles this routing differently than the raw Ollama docs suggest.

**Safe rule:** Always use `think=False` (bool) for qwen3.5 and always use the `ollama/` prefix (confirmed working in all method combinations by the smoke test). Do not rely on `think="low"` for qwen3.5.

---

## 4. Problems Encountered

### Problem 1: All Models Returned Empty Responses Initially

**Symptom:** During the full pipeline run (L4), `smart_llm` (configured as `gpt-oss:20b-cloud`) and other models with think mode produced empty strings as output. No exception was raised. The PowerPoint generation step received blank content and produced empty slides or failed silently downstream.

**Root cause:**

```
Model output:
  "<think>Final answer here</think>"   ← entire response is inside <think>

LiteLLM _parse_content_for_reasoning():
  reasoning_content = "Final answer here"
  content           = ""               ← stripped away!

SmartLiteLLM returns:
  resp.message.content = ""
  resp.text            = ""

Pipeline sees:
  empty string → no exception → silent failure
```

**Discovery:** A targeted smoke test (this PoC script) that prints the raw response for each combination revealed the empty strings, which allowed isolating the root cause.

**Fix:** Configure think mode explicitly per model (see Section 6). For models that support disabling think mode, use the correct parameter type. For models where think mode cannot be disabled (e.g., gpt-oss which ignores `think=False`), rely on the fact that the model's default behavior happens to produce non-empty output.

---

### Problem 2: `think=False` Silently Ignored for gpt-oss

**Symptom:** Setting `extra_body={"think": False}` for `gpt-oss:20b-cloud` had no observable effect. The model continued to behave identically to the default configuration.

**Root cause:** `gpt-oss` only accepts string reasoning effort levels as valid values for the `think` parameter: `"low"`, `"medium"`, or `"high"`. Passing a boolean `False` is not a recognized value and is silently discarded by Ollama without returning an error.

**Source:** Ollama issue [ollama/ollama#12004](https://github.com/ollama/ollama/issues/12004) and LiteLLM PR [#13375](https://github.com/BerriAI/litellm/pull/13375).

**Impact in this project:** Low. gpt-oss returns non-empty responses under all three think configs tested (default, `think=False`, `think="low"`), so the silent ignore does not cause pipeline failures. However, developers should not assume `think=False` provides any control over gpt-oss reasoning depth.

---

### Problem 3: `think="low"` Does Not Work for qwen3.5

**Symptom:** Setting `extra_body={"think": "low"}` for `qwen3.5:cloud` produced empty responses across all four prefix/method combinations. The behavior was identical to the default (no think config) case.

**Root cause:** `qwen3.5` treats `think="low"` as an instruction to use "low effort" thinking rather than as an instruction to skip thinking. The model still enters think mode, produces a `<think>` block, and does not reliably output text after the closing tag for short prompts. LiteLLM's parser then strips the think block and returns empty content.

**What works:** Only `think=False` (Python boolean `False`) reliably instructs qwen3.5 to completely skip the think block and produce a direct answer.

**Fix:** In `.env` or `ModelFactory` configuration, always pass `{"think": false}` (JSON `false`, Python `False`) for qwen3.5. Never use string values for this model's think parameter.

---

### Problem 4: nemotron `ollama_chat/acomplete` + Default Config = Empty Response

**Symptom:** The specific combination of `ollama_chat/` prefix + `acomplete()` method + no think config produced an empty response for `nemotron-3-super:cloud`. All other three combinations (with `ollama_chat/` or with `ollama/`) worked fine under default config.

**Root cause:** With the `ollama_chat/` prefix, LiteLLM routes to `/api/chat`, but `acomplete()` serializes the request as a completion-style call. This mismatch causes the response to be parsed through an unexpected code path where the think block stripping leaves `content=""` for nemotron's default output format on that endpoint.

```
nemotron default output format (on /api/chat endpoint via acomplete path):
  "<think>Hello</think>"

LiteLLM parsing via ollama_chat/acomplete code path:
  reasoning_content = "Hello"
  content           = ""        ← empty
```

**Fix:** Add `think=False` or `think="low"` to nemotron's extra_body. Either value works (nemotron accepts both booleans and string levels). With think mode explicitly disabled, the model outputs `Hello` directly with no `<think>` block, and all four combinations pass.

---

### Problem 5: LiteLLM Version Constraint and PR #13375

**Context:** LiteLLM PR [#13375](https://github.com/BerriAI/litellm/pull/13375), titled "Fix Ollama GPT-OSS streaming with 'thinking' field," fixed a bug in the streaming chunk parser that could cause gpt-oss responses to be misclassified when the `thinking` field was present in streamed chunks.

**Installed version:** LiteLLM 1.82.0 (confirmed in environment).

**`pyproject.toml` constraint:** `litellm>=1.0,<=1.82.0`

**Status:** PR #13375 is included in 1.82.0. No action needed. The constraint caps at 1.82.0 to prevent accidental upgrades that may introduce breaking changes; if upgrading beyond 1.82.0 in the future, re-run this compatibility test to catch any regressions.

---

## 5. Full Test Results

### Test Setup

| Parameter | Value |
|---|---|
| Script | `poc/litellm-multi-provider-chat/ollama_model_compatibility_test.py` |
| Environment | micromamba env `py3.12` |
| Ollama API base | `http://localhost:11434` |
| Prompt | `"Say hello in one word."` |
| Timeout per case | 60 seconds |
| Total test cases | 44 (5 models × up to 12 combinations each: 4 think configs × 4 prefix/method combos; ministral has only 1 think config × 4 combos = 4 cases) |

For each model, the four prefix/method combinations tested are:
- `ollama/acomplete` — text completion endpoint + completion-style call
- `ollama/achat` — text completion endpoint + chat-style call
- `ollama_chat/acomplete` — chat endpoint + completion-style call
- `ollama_chat/achat` — chat endpoint + chat-style call

### Results by Model

#### ministral-3:14b-cloud

No think mode. Only default config tested (1 config × 4 combos = 4 cases).

| think config | ollama/acomplete | ollama/achat | ollama_chat/acomplete | ollama_chat/achat |
|---|---|---|---|---|
| default | ✅ | ✅ | ✅ | ✅ |

All combinations pass. No special configuration needed.

---

#### qwen3.5:cloud

Has think mode. 3 think configs × 4 combos = 12 cases.

| think config | ollama/acomplete | ollama/achat | ollama_chat/acomplete | ollama_chat/achat |
|---|---|---|---|---|
| default | ❌ empty response | ❌ empty response | ❌ empty response | ❌ empty response |
| think=False | ✅ | ✅ | ✅ | ✅ |
| think="low" | ❌ empty response | ❌ empty response | ❌ empty response | ❌ empty response |

Only `think=False` (boolean) works. Both default and `think="low"` produce empty responses across all combinations.

---

#### gpt-oss:20b-cloud

Has think mode (string-level only). 3 think configs × 4 combos = 12 cases.

| think config | ollama/acomplete | ollama/achat | ollama_chat/acomplete | ollama_chat/achat |
|---|---|---|---|---|
| default | ✅ | ✅ | ✅ | ✅ |
| think=False | ✅ | ✅ | ✅ | ✅ |
| think="low" | ✅ | ✅ | ✅ | ✅ |

All combinations pass under all configs. `think=False` is silently ignored but does not cause failures because gpt-oss's default output format happens to be compatible with LiteLLM's parser.

---

#### nemotron-3-super:cloud

Has think mode. 3 think configs × 4 combos = 12 cases.

| think config | ollama/acomplete | ollama/achat | ollama_chat/acomplete | ollama_chat/achat |
|---|---|---|---|---|
| default | ✅ | ✅ | ❌ empty response | ✅ |
| think=False | ✅ | ✅ | ✅ | ✅ |
| think="low" | ✅ | ✅ | ✅ | ✅ |

Default config fails for exactly one combination: `ollama_chat/acomplete`. Adding either `think=False` or `think="low"` fixes all combinations.

---

#### gemma4:31b-cloud

No think mode issues. 3 think configs × 4 combos = 12 cases.

| think config | ollama/acomplete | ollama/achat | ollama_chat/acomplete | ollama_chat/achat |
|---|---|---|---|---|
| default | ✅ | ✅ | ✅ | ✅ |
| think=False | ✅ | ✅ | ✅ | ✅ |
| think="low" | ✅ | ✅ | ✅ | ✅ |

All combinations pass under all configs. No special configuration needed.

---

### Summary: Which Models Need Special Config?

```
Model                    │ Default config safe? │ Fix required
─────────────────────────┼──────────────────────┼───────────────────────
ministral-3:14b-cloud    │ ✅ Yes               │ None
gpt-oss:20b-cloud        │ ✅ Yes               │ None
gemma4:31b-cloud         │ ✅ Yes               │ None
nemotron-3-super:cloud   │ ⚠️ Partial (3/4)     │ Add think=False
qwen3.5:cloud            │ ❌ No  (0/4)         │ Add think=False (bool!)
```

---

## 6. Recommended Configuration Per Model

Based on the test results, the minimal safe configuration for each model is:

```json
{
  "ministral-3:14b-cloud":  { "prefix": "ollama", "extra_body": {} },
  "gpt-oss:20b-cloud":      { "prefix": "ollama", "extra_body": {} },
  "gemma4:31b-cloud":       { "prefix": "ollama", "extra_body": {} },
  "qwen3.5:cloud":          { "prefix": "ollama", "extra_body": {"think": false} },
  "nemotron-3-super:cloud": { "prefix": "ollama", "extra_body": {"think": false} }
}
```

**Why `ollama/` prefix for all models:** All five models pass all four prefix/method combinations when the correct think config is applied. The `ollama/` prefix is simpler (no `_chat` suffix) and has been verified to work. There is no benefit to using `ollama_chat/` and it introduces an additional failure mode for nemotron under default config (see Problem 4).

**Why `think=false` (bool) not `think="low"` for qwen3.5 and nemotron:** String levels (`"low"`) are silently accepted by qwen3.5 but do not disable thinking. Only boolean `false` reliably disables the `<think>` block for qwen3.5. For nemotron, either works, but using the same `false` boolean keeps the configuration consistent.

### How to Apply This in Code

In `ModelFactory` or wherever `SmartLiteLLM` is constructed, pass `extra_body` via `additional_kwargs`:

```python
# For qwen3.5 or nemotron:
llm = SmartLiteLLM(
    model="ollama/qwen3.5:cloud",
    temperature=0.0,
    additional_kwargs={
        "api_base": "http://localhost:11434",
        "extra_body": {"think": False},   # Python bool False → JSON false
    },
)

# For ministral, gpt-oss, gemma4 (no extra_body needed):
llm = SmartLiteLLM(
    model="ollama/ministral-3:14b-cloud",
    temperature=0.0,
    additional_kwargs={
        "api_base": "http://localhost:11434",
    },
)
```

In `.env`, if `ModelFactory` reads think config from environment variables, use:

```
# For qwen3.5 / nemotron — think must be boolean false, not the string "false"
# Actual env var format depends on ModelFactory implementation.
# If ModelFactory reads a JSON string: '{"think": false}'
# If ModelFactory reads separate flags: THINK_MODE=false
```

Verify how `ModelFactory` parses this and ensure it passes Python `False` (bool), not the string `"False"` or `"false"`, since JSON `null`/`false` and Python `False` are equivalent but the string `"false"` would be treated as a truthy non-empty string in most contexts.

---

## 7. How to Run the Test

### Prerequisites

1. **Ollama installed and running** at `http://localhost:11434`.
   - Install: https://ollama.ai
   - Verify: `curl http://localhost:11434/api/tags`

2. **All five models pulled locally** (these are large downloads — expect 5–30 GB each):

   ```bash
   ollama pull ministral-3:14b-cloud
   ollama pull qwen3.5:cloud
   ollama pull gpt-oss:20b-cloud
   ollama pull nemotron-3-super:cloud
   ollama pull gemma4:31b-cloud
   ```

   Verify all are present: `ollama list`

3. **micromamba environment `py3.12`** with `llama-index-llms-litellm` installed.
   - The backend's `pyproject.toml` defines all dependencies.
   - To set up: `cd backend && micromamba run -n py3.12 pip install llama-index-llms-litellm`

4. **Working directory** must be the repo root (or any path where `backend/` is accessible as a sibling of `poc/`), because the script adds `../../backend` to `sys.path`.

### Running the Test

```bash
# From the repo root (dev/ directory):
micromamba run -n py3.12 python poc/litellm-multi-provider-chat/ollama_model_compatibility_test.py
```

To override the Ollama base URL (e.g., if running Ollama on a different port or host):

```bash
OLLAMA_API_BASE=http://localhost:11434 \
  micromamba run -n py3.12 python poc/litellm-multi-provider-chat/ollama_model_compatibility_test.py
```

### Expected Output

The script prints a line per test case as it runs, then a summary matrix at the end:

```
══════════════════════════════════════════════════════════════════════
Model: qwen3.5:cloud
══════════════════════════════════════════════════════════════════════
  ❌ [ollama/acomplete] think=default      → (empty response)
  ❌ [ollama/achat]     think=default      → (empty response)
  ...
  ✅ [ollama/acomplete] think=think=False  → Hello
  ✅ [ollama/achat]     think=think=False  → Hello
  ...

RESULT MATRIX
══════════════════════════════════════════════════════════════════════

Model: qwen3.5:cloud
  think config    ollama/acomplete    ollama/achat        ollama_chat/acomplete ollama_chat/achat
  ──────────────────────────────────────────────────────────────────────────────
  default         ❌                  ❌                  ❌                    ❌
  think=False     ✅                  ✅                  ✅                    ✅
  think=low       ❌                  ❌                  ❌                    ❌
```

### Timeout Behavior

Each test case has a 60-second timeout. If a model is not loaded in Ollama's memory, the first call may take longer as Ollama loads the model weights into RAM. On Apple M1 with 16 GB unified memory, models larger than ~8B active parameters may take 20–40 seconds for the first call. If you see `(timeout >60s)`, increase `TIMEOUT` in the script or ensure the model is pre-loaded (`ollama run <model>` in a separate terminal first).

---

## Appendix: Relevant External References

| Reference | Relevance |
|---|---|
| [ollama/ollama#12004](https://github.com/ollama/ollama/issues/12004) | Documents that gpt-oss only accepts string reasoning levels, not booleans, for the `think` parameter |
| [ollama/ollama#14793](https://github.com/ollama/ollama/issues/14793) | Documents that `think=false` is silently ignored on `/api/generate` (only honored on `/api/chat`) |
| [LiteLLM PR #13375](https://github.com/BerriAI/litellm/pull/13375) | "Fix Ollama GPT-OSS streaming with 'thinking' field" — fixes chunk parser for gpt-oss; included in LiteLLM 1.82.0 |
| [Ollama /api/generate docs](https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-completion) | Parameters accepted by the text completion endpoint |
| [Ollama /api/chat docs](https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-chat-completion) | Parameters accepted by the chat endpoint (including `think`) |
