# Experiment 6 — Constrained Decoding vs. Text Completion: Structured Output Method Selection Across LiteLLM Providers

## Task Context

This experiment targets **Step 5 — Slide Outline + Human-in-the-Loop** from the system architecture (README → System Architecture).

Before the pipeline diagram, two terms need defining: a PPTX **layout** and its **placeholders**. A slide is built from a layout (a pre-designed template slot) containing one or more placeholders (text boxes with a fixed position and style). One `.pptx` template file defines multiple layouts (e.g. "Title Slide", "Section Header", "Blank"), each with a different placeholder arrangement.

```
┌──────────────────────────────────────┐
│  Layout: "Title and Content"         │  ← layout_name
│  ┌─────────────────────────────┐     │
│  │ Placeholder idx=0 (Title)   │     │  ← idx_title_placeholder
│  └─────────────────────────────┘     │
│  ┌─────────────────────────────┐     │
│  │ Placeholder idx=1 (Content) │     │  ← idx_content_placeholder
│  │                             │     │
│  └─────────────────────────────┘     │
└──────────────────────────────────────┘
```

Given one slide's text content, the LLM's job in this step is to pick which layout fits it and which placeholder index each piece of text belongs in. lz-chen's original does not ship a template file — `SLIDE_TEMPLATE_PATH` points to a personal, gitignored PPTX from her employer's branding. This fork supplies its own template asset instead.

```
Input: paper summaries (*.md, one per paper)        ← Step 4: Summarization
      │
      ▼
┌── 5. SLIDE OUTLINE + HUMAN-IN-THE-LOOP ───────────────────────────────┐
├─── Original (lz-chen) ───────────┬─── My Implementation ──────────────┤
│ GPT-4o: 1 outline per paper      │ Local LLM: 1 title slide           │
│ FunctionCallingProgram           │           + 4 content slides       │
│ HITL: approve / reject           │ LLMTextCompletionProgram           │
│                                  │ HITL: approve / give feedback      │
│                                  │ → Layout selection by LLM          │
└──────────────────────────────────┴────────────────────────────────────┘
      │
      ▼
Output: slide_outlines.json                          → Step 6: PPTX Rendering
```

Within Step 5, the layout selection sub-step (`outlines_with_layout`) is the experiment target:

```
Step 5 — Slide Outline + Human-in-the-Loop (detail)
──────────────────────────────────────────────────────────────────
 paper summaries (*.md, one per paper)
       │
       ▼
 [summary2outline]        LLM → PaperSlideOutline
       │                  { paper_title, paper_authors, paper_year,
       │                    content_slides[4]: List[SlideOutline] }
       ▼                    ↑ loops back on rejection
 [gather_feedback_outline]    Human-in-the-Loop: approve / revise
       │
       ▼
 ┌─── EXPERIMENT TARGET ────────────────────────────────────────┐
 │ [outlines_with_layout]                                       │
 │   For each content slide:                                    │
 │     LLM picks layout from the PPTX template                  │
 │   Input:  SlideOutline { title, content }                    │
 │   Prompt: AUGMENT_LAYOUT_PMT                                 │
 │   Output: SlideOutlineWithLayout { title, content,           │
 │                                    layout_name,              │
 │                                    idx_title_placeholder,    │
 │                                    idx_content_placeholder } │
 └──────────────────────────────────────────────────────────────┘
       │
       ▼
 slide_outlines.json      → Step 6: PPTX Rendering
```

`AUGMENT_LAYOUT_PMT` is the prompt for the `outlines_with_layout` step. It asks the LLM to look at each slide's content and select the appropriate layout from the available PPTX template layouts — returning the layout name and placeholder indices as structured JSON. If the LLM returns malformed output here, `slide_gen` has nothing valid to render and the whole pipeline stops.

---

## Summary

- **Problem:** lz-chen's original produces every slide through one fixed path — Azure OpenAI's GPT-4o calling its native function-calling API to generate a single text block per paper. Structured output and LLM provider are coupled into that one mechanism, so nothing in the design indicates whether the same approach still works if the provider or model changes.
- **Solution:** Compared 6 ways to get structured JSON out of an LLM — native function calling, four text-completion variants, and provider-native schema enforcement — across 5 models (2 local, 3 cloud) and 4 prompt variants.
- **Result:** Text completion was adopted as the pipeline solution — the only strategy, alongside one close variant, to reach 100% success on every model tested, while function calling failed on both local models and one of three cloud providers.

---

## Experiment Setup

✅ = currently used in the pipeline

### Shared Test Configuration

| Parameter | Value |
|---|---|
| Slide test case | 1 academic content slide ("Attention Is All You Need") |
| Runs per combination | 1 |
| Total LLM calls | 120 (108 real + 12 auto-skipped) |
| Execution mode | Ollama models sequential; cloud API models concurrent via `asyncio.gather` |

### Models Compared

| Model | Type |
|---|---|
| `ollama/gemma3:4b` | Local (Ollama) |
| `ollama/ministral-3:14b-cloud` | Local (Ollama, 14B) |
| `groq/openai/gpt-oss-20b` | Cloud API |
| `openrouter/google/gemini-3.1-flash-lite-preview` | Cloud API |
| `gemini/gemini-3.1-flash-lite-preview` | Cloud API |

### Methods Compared

**Three underlying approaches:**
- **Function Calling** — structure enforced by the model's native tool-call API (model-side)
- **Text Completion** — model outputs JSON as text; client-side Pydantic parser validates it
- **Constrained Decoding** — the serving layer masks the model's token probabilities at generation time so only schema-valid tokens can be produced (server-side)

| Method | API Owner | Mechanism |
|---|---|---|
| Function Calling | LlamaIndex (`FunctionCallingProgram`) | Relies on the model's native tool/function-calling capability via LiteLLM. Fails if the model does not support it. |
| Text Completion ✅ | LlamaIndex (`LLMTextCompletionProgram`) | Appends JSON schema instructions to the prompt; parses the text output into the Pydantic model. No native tool call required. |
| Ollama Format Parameter | LlamaIndex (`LLMTextCompletionProgram`) + Ollama server | Same as Text Completion, but passes the Pydantic schema as `format` in `additional_kwargs`. Ollama enforces grammar-constrained decoding server-side. Ollama-only — auto-skipped for cloud models. |
| Structured LLM Wrapper | LlamaIndex (`as_structured_llm()`) | Wraps the LLM with `as_structured_llm(OutputCls)`; the parsed Pydantic object is read from `response.raw`. |
| Structured Predict | LlamaIndex (`astructured_predict()`) | Routes through LlamaIndex's LLM-mode structured prediction; uses text completion internally. |
| Provider-Native Schema | litellm (bypasses LlamaIndex) | Calls `litellm.acompletion()` directly with `response_format=<Pydantic class>`, bypassing LlamaIndex entirely — the provider's own structured-output API enforces the shape. |

<details>
<summary>Function Calling — internal call chain</summary>

~~~text
FunctionCallingProgram(Function Calling)

from_defaults() construction step — can fail here, before any call
        │
        ▼
if not llm.metadata.is_function_calling_model:
    raise ValueError(...)
        │  → pure local lookup (litellm's bundled model_cost table)
        │  → no API call at all; the 0.3-0.8s failure is table-lookup overhead
        ▼
lookup result = supported → proceed
        │
        ▼
wrap the Pydantic schema as a tool
        │
        ▼
llm.apredict_and_call([tool], ...)
        │  → llm.achat(tools=[tool], ...)
        ▼
extract tool_calls from the response, construct directly:
   output_cls(**tool_kwargs)
        │  ★ no regex, no text parsing —
        │    the Pydantic object is built straight from the API's
        │    native tool-call arguments
        ▼
return Model instance (or ValueError/TypeError)

★ A completely different mechanism family from the text-completion
  methods — relies on whether the model was trained for tool calling
  and whether the API natively supports it.
~~~

</details>

<details>
<summary>Text Completion — internal call chain</summary>

~~~text
LLMTextCompletionProgram (Text Completion — the method chosen for the pipeline)

llm.chat() returns raw text
        │
        ▼
PydanticOutputParser.parse(raw_text)
        │  → extract_json_str()  regex \{.*\} (DOTALL) grabs everything
        │    between the first { and the last }
        │  → model_validate_json()
        ▼
return Model instance

★ A fixed, non-branching path — the same logic runs regardless of
  which model is behind it.
~~~

</details>

<details>
<summary>Ollama Format Parameter — internal call chain</summary>

~~~text
LLMTextCompletionProgram + Ollama format kwarg (Ollama Format Parameter)

Same LLMTextCompletionProgram as Text Completion — the only difference
is an extra additional_kwargs={"format": schema}
        │
        ▼
LiteLLM wrapper._model_kwargs merges format in
        │
        ▼
litellm package: format isn't a standard parameter, falls into
non_default_params
        │
        ▼
Ollama-specific transform_request():
   format = optional_params.pop("format")
   data["format"] = format      ← placed into the outgoing HTTP body
        │
        ▼
POST /api/chat, body carries the format field
        │
        ▼
★ Python's involvement ends here — the actual grammar-constrained
  decoding runs server-side in Ollama (llama.cpp), not in this codebase
        │
        ▼
Response text is parsed by the same extract_json_str() (\{.*\} regex)
as Text Completion
        │  ★ Parsing is unchanged — same tolerance as Text Completion
        ▼
return Model instance
~~~

</details>

<details>
<summary>Structured LLM Wrapper — internal call chain</summary>

~~~text
as_structured_llm() (Structured LLM Wrapper)

new StructuredLLM(llm=self, output_cls=...)
        │  (does not mutate the original llm object — wraps it in a new shell)
        ▼
StructuredLLM.chat() internally calls:
   self.llm.structured_predict(...)
        │
        ▼
★ Reuses the entire branching logic from Structured Predict below!
   The PoC code never explicitly sets pydantic_program_mode here,
   so it stays at DEFAULT → the is_function_calling_model check
   branches dynamically, per model
        │
        ▼
Result lands in response.raw (not returned directly — wrapped in a
ChatResponse)
~~~

</details>

<details>
<summary>Structured Predict — internal call chain</summary>

~~~text
astructured_predict() (Structured Predict)

get_program_for_llm(pydantic_program_mode=...)
        │
        ▼
checks the llm.pydantic_program_mode field
        │
    ┌───┴─────────────────────────┐
    ▼                             ▼
= DEFAULT                       = LLM (the PoC code explicitly forces this)
    │                             │
    ▼                             ▼
checks is_function_calling_model  goes straight to LLMTextCompletionProgram
on the model                      (identical to the Text Completion method)
    │
  ┌─┴──────┐
  ▼        ▼
 True     False
  │        │
  ▼        ▼
native    LLMTextCompletionProgram
Function  (same as Text Completion)
Calling

★ Because the PoC code forces pydantic_program_mode = LLM before every
  call, this method is guaranteed to always take the safe text-completion
  path — it never depends on which model is behind it.
~~~

</details>

<details>
<summary>Provider-Native Schema — internal call chain</summary>

~~~text
litellm.acompletion(response_format=...) (Provider-Native Schema)

Bypasses LlamaIndex entirely, calls the litellm package directly
        │
        ▼
Step 1 — normalize the schema into one canonical shape regardless of
provider:
   type_to_response_format_param()
   → {"type": "json_schema", "json_schema": {"schema": {...}, "strict": True}}
        │
        ▼
Step 2 — branches per provider
    ┌─────────────┬───────────────────────┬──────────────────┐
    ▼             ▼                       ▼
  OpenAI        Ollama (ministral-3:14b-  Gemini
  passed as-is  cloud goes this way)      written into
                unwraps the envelope,     generationConfig.
                puts the raw schema       responseSchema
                back into Ollama's own
                format field
                ★ ends up almost
                  identical to what
                  Ollama Format Parameter
                  sends!
        │
        ▼
Response parsing: _strip_json_fence() — a hand-written regex
   Only recognizes a ```json ... ``` code-fenced block; if the
   response isn't fenced that way, it falls back to text.strip()
   as-is
        │  ★ Much stricter than the \{.*\} regex used by Text
        │    Completion / Ollama Format Parameter
        ▼
model_validate_json(content)
→ returns a Model instance, or fails validation outright
~~~

</details>

### Structured Output Fields

`SlideOutlineWithLayout` — the Pydantic schema every method must produce:

| Field | Meaning |
|---|---|
| `title` | Slide title text, copied verbatim from the input |
| `content` | Slide body text, copied verbatim from the input |
| `layout_name` | Name of the chosen layout from the PPTX template (e.g. "Title and Content") |
| `idx_title_placeholder` | Index of the placeholder that holds the title, within the chosen layout |
| `idx_content_placeholder` | Index of the placeholder that holds the body text, within the chosen layout |

### Prompt Variants

```
Prompt 1 (original, verbatim lz-chen prompt)
   │
   │  remove Norwegian phrase + add explicit output field list
   ▼
Prompt 2 ──────────────┬──────────────
   │                   │
   │  add a worked     │  replace the field list with a
   │  example          │  forceful "no schema wrapping" directive
   ▼                   ▼
Prompt 3            Prompt 4
(Prompt 2 + example)  (Prompt 2's setup + new closing instruction)
```

Prompt 3 and Prompt 4 are independent branches off Prompt 2, each isolating one change — not a linear Prompt 1→2→3→4 progression.

<details>
<summary>Prompt 1 (original) — full text</summary>

~~~text
You are an AI that selects slide layout from a template for the slide text given.
You will receive a page content with title and main text.
Your task is to select the appropriate layout and information such as index of the placeholder for the page
 based on what type of the content it is (e.g. is it topic overview/agenda,
 or actual content, or thank you message).
For content slides, make sure to
 - choose a layout that has content placeholder (also referred to as 'Plassholder for innhold')
 after the title placeholder
 - choose the content placeholder that is large enough for the text content

The following layout are available: {available_layout_names} with their detailed information:
{available_layouts}

Here is the slide content:
{slide_content}
~~~

</details>

<details>
<summary>Prompt 2 (field descriptions added) — full text</summary>

~~~text
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and main text body.

Select the layout and placeholder indices based on the content type
(e.g. agenda/overview, regular content, title slide, or closing/thank-you slide).

For content slides:
 - choose a layout that has a content placeholder after the title placeholder
 - choose the content placeholder that is large enough for the text

The following layouts are available: {available_layout_names} with their detailed information:
{available_layouts}

Here is the slide content:
{slide_content}

Output the following fields:
- title: the slide title text (copy verbatim from input)
- content: the slide body text (copy verbatim from input)
- layout_name: the exact name string of the chosen layout (must match one of the available layout names)
- idx_title_placeholder: the numeric index (as a string) of the title placeholder in the chosen layout
- idx_content_placeholder: the numeric index (as a string) of the content placeholder in the chosen layout
~~~

</details>

<details>
<summary>Prompt 3 (few-shot) — full text</summary>

~~~text
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and main text body.

Select the layout and placeholder indices based on the content type
(e.g. agenda/overview, regular content, title slide, or closing/thank-you slide).

For content slides:
 - choose a layout that has a content placeholder after the title placeholder
 - choose the content placeholder that is large enough for the text

The following layouts are available: {available_layout_names} with their detailed information:
{available_layouts}

--- Example ---
Slide content:
  title: "Deep Learning for NLP"
  content: "* Recurrent Networks\n* Transformers\n* BERT pre-training"

Expected output:
  title:                    "Deep Learning for NLP"
  content:                  "* Recurrent Networks\n* Transformers\n* BERT pre-training"
  layout_name:              "Title and Content"
  idx_title_placeholder:    "0"
  idx_content_placeholder:  "1"
--- End Example ---

Here is the slide content:
{slide_content}

Output the following fields:
- title: the slide title text (copy verbatim from input)
- content: the slide body text (copy verbatim from input)
- layout_name: the exact name string of the chosen layout (must match one of the available layout names)
- idx_title_placeholder: the numeric index (as a string) of the title placeholder in the chosen layout
- idx_content_placeholder: the numeric index (as a string) of the content placeholder in the chosen layout
~~~

</details>

<details>
<summary>Prompt 4 (no-wrap directive) — full text</summary>

~~~text
You are an AI that selects the most appropriate slide layout for given slide content.
You will receive a slide with a title and main text body.

Select the layout and placeholder indices based on the content type
(e.g. agenda/overview, regular content, title slide, or closing/thank-you slide).

For content slides:
 - choose a layout that has a content placeholder after the title placeholder
 - choose the content placeholder that is large enough for the text

The following layouts are available: {available_layout_names} with their detailed information:
{available_layouts}

Here is the slide content:
{slide_content}

CRITICAL: Provide the ACTUAL VALUES for each field — not a schema, not a description.
Do NOT wrap your answer inside a "properties" key or any JSON Schema structure.
Do NOT output field definitions or type annotations. Output concrete values only.

Required fields (fill each with the real value, not a placeholder):
- title:                   copy the title string from the slide content above
- content:                 copy the content string from the slide content above
- layout_name:             the exact layout name string chosen from the available list
- idx_title_placeholder:   the string form of the integer index for the title placeholder
- idx_content_placeholder: the string form of the integer index for the content placeholder
~~~

</details>

| Prompt | Description |
|---|---|
| Prompt 1 (original) | Verbatim `AUGMENT_LAYOUT_PMT` as used in the pipeline — no explicit output field descriptions, contains a Norwegian placeholder name (`Plassholder for innhold`) |
| Prompt 2 (field descriptions added) | Adds explicit output field descriptions; removes the Norwegian placeholder name |
| Prompt 3 (few-shot) | Prompt 2 plus an embedded example |
| Prompt 4 (no-wrap directive) | Adds an explicit instruction not to wrap output in a JSON schema definition |

> The prompt used in the pipeline was further redesigned in a follow-up experiment and is not directly equivalent to any of the 4 variants above. See the prompt experiment report for details.

### Metrics

| Metric | Definition | Role |
|---|---|---|
| Success Rate | Percentage of LLM calls returning valid JSON that matches the Pydantic schema without error. `0%` = crashes, returns schema definition, or malformed JSON. `100%` = all outputs valid. | Primary |
| Avg Elapsed (s) | Mean wall-clock time per call, including any retries. | Secondary (latency) |

---

## Full Experimental Results

### Success Rate — Prompts Passed per (Method × Model)

`x/4` = number of the 4 prompt variants that reached 100% success on this model.

| Method | `gemma3:4b` | `ministral-3:14b-cloud` | `groq/gpt-oss-20b` | `openrouter/gemini` | `gemini` (direct) |
|---|---|---|---|---|---|
| Function Calling | 0/4 | 0/4 | 3/4 | 0/4 | 4/4 |
| Text Completion ✅ | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 |
| Ollama Format Parameter | 4/4 | 4/4 | – | – | – |
| Structured LLM Wrapper | 4/4 | 4/4 | 3/4 | 4/4 | 4/4 |
| Structured Predict | 4/4 | 4/4 | 4/4 | 4/4 | 4/4 |
| Provider-Native Schema | 4/4 | 0/4 | 1/4* | 4/4 | 4/4 |

\* Groq's 1/4 is Prompt 4 only — the other 3 prompts fail due to rate-limit exhaustion at that point in the run, not a genuine method result.

**Conclusion:** Text Completion and Structured Predict are the only two methods with zero failures across every model and prompt; both 3/4 cells (Structured LLM Wrapper on Groq) fail on the same prompt — the no-wrap directive that Prompt 4 adds.

### Latency — Range Across Successful Calls (seconds)

Range spans the fastest to slowest successful call across the 4 prompts; failing calls are excluded from the range (a fast failure isn't a fast result).

| Method | `gemma3:4b` | `ministral-3:14b-cloud` | `groq/gpt-oss-20b` | `openrouter/gemini` | `gemini` (direct) |
|---|---|---|---|---|---|
| Function Calling | fails | fails | 0.5–4.6s | fails | 1.9–2.4s |
| Text Completion ✅ | 7.3–13.0s | 1.8–2.2s | 0.6–4.7s | 1.1–2.0s | 1.4–4.7s |
| Ollama Format Parameter | 6.9–7.6s | 1.8–47.6s† | – | – | – |
| Structured LLM Wrapper | 7.6–7.9s | 2.1–2.5s | 4.5–4.7s | 2.3–3.0s | 2.1–2.6s |
| Structured Predict | 7.4–8.2s | 1.8–2.2s | 4.6–13.0s | 1.4–1.8s | 2.2–3.5s |
| Provider-Native Schema | 4.8–6.5s | fails | 0.8s | 1.8–7.9s | 1.9–3.0s |

† A single anomalous 47.6s call on `ministral-3:14b-cloud` — a transient Ollama constrained-decoding stall, not typical latency for this method.

**Conclusion:** Provider-Native Schema is fastest among the methods that succeed on `gemma3:4b`; latency on the cloud models is dominated by per-call rate-limit variance rather than by which JSON-generation method is used.

---

## Observations

### Which methods have zero failures across the entire test matrix?

Text Completion and Structured Predict are the only two methods that reach 100% success on every one of the 5 models across all 4 prompts — zero failures in 20 of 20 combinations each.

- Every other method fails on at least 1 of 5 models: Function Calling on 3, Ollama Format Parameter is inapplicable to 3 (cloud-only skip), Structured LLM Wrapper on 1 (Groq, Prompt 4), Provider-Native Schema on 1 (ministral, all prompts).
- Both zero-failure methods are LlamaIndex text-completion paths — neither depends on native tool-calling or provider-side schema enforcement.

### Does Function Calling fail on OpenRouter because of the model or the routing layer?

Function Calling fails 100% of the time on the OpenRouter-routed Gemini model but succeeds 100% of the time on the same underlying model called directly through the Gemini API, showing the failure is a routing-layer capability check rather than a model limitation.

- OpenRouter calls fail in 0.0s across all 4 prompts — no network request is made before the failure.
- The direct Gemini API call succeeds on the identical model in 1.9–2.4s per call.

### Why doesn't Structured LLM Wrapper's near-perfect score make it a safe alternative to Text Completion?

Structured LLM Wrapper fails on Groq specifically because it silently defers to the same native tool-calling mechanism Function Calling uses whenever the underlying model supports it — inheriting that method's one weak spot instead of behaving as an independent implementation.

- Structured LLM Wrapper and Function Calling fail on the exact same cell: Groq, Prompt 4 — the only prompt either method fails on that model.
- Every other model and prompt combination for Structured LLM Wrapper matches Text Completion's 4/4 score exactly, making this one shared failure the only signal that separates the two methods' reliability.

---

## Decision

### Which structured-output method for the pipeline?

Text Completion is chosen over Structured Predict — the only other zero-failure method — because it needs no forced configuration step to reach that reliability.

- Structured Predict only matches Text Completion's reliability because the code forces a global setting on the shared LLM instance before every call — an extra step whose absence is easy to miss when debugging.

---

## Pipeline Integration Status ✅ INTEGRATED

Text completion method replaced function calling in `slide_gen.py` → `_text_program()` → `outlines_with_layout`.
