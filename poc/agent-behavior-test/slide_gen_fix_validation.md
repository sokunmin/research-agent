# Slide Gen Fix Validation — Experiment Report

**Date:** 2026-04-05  
**Script:** `poc/agent-behavior-test/slide_gen_fix_validation.py`  
**Template used:** `assets/template-en.pptx` (12 layouts)  
**Result:** 17 / 17 PASS

---

## 1. System Context

This project generates PowerPoint slides from academic paper summaries via a multi-step workflow:

```
[markdown summaries]
  → summary2outline (LLM)          → SlideOutline {title, content}
  → outlines_with_layout (LLM)     → SlideOutlineWithLayout {title, content, layout_name, idx_*}
                                      serialised to slide_outlines.json
  → slide_gen (ReActAgent)          → agent writes + executes python-pptx code in Docker sandbox
  → validate_slides / modify_slides → final .pptx
```

**Relevant files:**
- `backend/agent_workflows/slide_gen.py` — workflow orchestration, Bugs #1 #3 #4 live here
- `backend/agent_workflows/schemas.py` — Pydantic schema `SlideOutlineWithLayout`, Bug #2a lives here
- `backend/prompts/prompts.py` — `SLIDE_GEN_PMT` (agent system prompt), Bugs #2b #4 live here
- `backend/services/sandbox.py` — Docker sandbox wrapper (`upload_file`, `list_files`, `run_code`)
- `backend/utils/tools.py` — `get_all_layouts_info()` reads layout metadata from template PPTX

**Key constraint:** The agent runs python-pptx code **inside a Docker sandbox container** (`/sandbox/`),
not in the backend container (`/app/`). Files must be explicitly uploaded before the agent can read them.

---

## 2. The Four Bugs

### Bug #1 — JSON double-encoding
**File:** `backend/agent_workflows/slide_gen.py`, `outlines_with_layout` step  
**Line:** `json.dump([o.json() for o in slides_w_layout], f, indent=4)`

`o.json()` is a Pydantic v1 compatibility method that returns a **JSON string**, not a dict.
`json.dump` then serialises that string again, producing a file containing `list[str]` instead of `list[dict]`.
When the agent reads the file, `item['layout_name']` raises `TypeError: string indices must be integers`.

**Fix:** `json.dump([o.model_dump() for o in slides_w_layout], f, indent=4)`

---

### Bug #2a — Placeholder index type: `Optional[str]` in schema
**File:** `backend/agent_workflows/schemas.py`

`AUGMENT_LAYOUT_PMT` instructs the LLM to output idx as "a string" (`"0"`, `"1"`).
`SlideOutlineWithLayout` schema stores them as `Optional[str]` with a `coerce_int_to_str` validator.
After JSON round-trip, `item['idx_title_placeholder']` is the string `"0"`.
`slide.placeholders["0"]` raises `TypeError: '%d format: a real number is required, not str'`.
python-pptx requires an **integer** key for `placeholders[]`.

**Two fix options:**

| Option | Change | Result |
|--------|--------|--------|
| **Fix A** | Keep `Optional[str]`, add `int()` cast in `SLIDE_GEN_PMT` prompt: `slide.placeholders[int(item['idx'])]` | Works, but requires prompt patch |
| **Fix B** (recommended) | Change schema to `Optional[int]`, remove `coerce_int_to_str` validator | Pydantic v2 lax mode auto-coerces `"0"` → `0`; `model_dump()` produces int directly; no prompt patch needed |

---

### Bug #2b — `add_slide()` API misuse
**File:** `backend/prompts/prompts.py`, `SLIDE_GEN_PMT`

The prompt says "match each slide to its layout by `layout_name`" but provides no API pattern.
The agent guesses `prs.slides.add_slide("TITLE_AND_BODY")` or `prs.slides.add_slide(0)`.
Both raise `AttributeError: 'str'/'int' object has no attribute 'part'`
(python-pptx requires a `SlideLayout` **object**, not a string or integer).

**Fix:** Add explicit lookup pattern to `SLIDE_GEN_PMT`:
```python
layout = next(l for l in prs.slide_layouts if l.name == item['layout_name'])
slide  = prs.slides.add_slide(layout)
```

**Additional risk (EXP-3D):** If `layout_name` from JSON does not match any layout in the template,
`next()` raises `StopIteration`. Production code must wrap in `try/except StopIteration` with a fallback.

---

### Bug #3 — JSON file not uploaded to sandbox
**File:** `backend/agent_workflows/slide_gen.py`, `slide_gen` step, lines ~384–394

The workflow uploads the PPTX template to the sandbox but **not** `slide_outlines.json`.
The prompt also passes backend container paths (e.g., `/app/workflow_artifacts/.../slide_outlines.json`)
instead of sandbox paths (`/sandbox/slide_outlines.json`).
The agent tries to open a file that does not exist in the sandbox → `FileNotFoundError`.

```python
# Current (buggy)
SLIDE_GEN_PMT.format(
    json_file_path=ev.outlines_fpath.as_posix(),   # /app/... — backend path, NOT sandbox
    template_fpath=self.slide_template_path,         # /app/... — same problem
)
upload_result = self.sandbox.upload_file(self.slide_template_path)  # JSON not uploaded
```

**Fix (two changes):**
```python
# 1. Upload JSON before agent starts
self.sandbox.upload_file(str(ev.outlines_fpath))        # new line
self.sandbox.upload_file(self.slide_template_path)       # already exists

# 2. Pass sandbox paths to prompt
SLIDE_GEN_PMT.format(
    json_file_path=f"{SANDBOX_DIR}/{Path(ev.outlines_fpath).name}",   # /sandbox/slide_outlines.json
    template_fpath=f"{SANDBOX_DIR}/{Path(self.slide_template_path).name}",
)
```

`upload_file()` in `services/sandbox.py` calls `session.copy_to_runtime(local_path, "/sandbox/<filename>")`.
This cannot be tested without Docker running; existing e2e coverage: `backend/tests/e2e/test_sandbox.py:45–62`.

---

### Bug #4 — Agent saves PPTX to wrong path
**File:** `backend/prompts/prompts.py`, `SLIDE_GEN_PMT`

The prompt says: `"Save the final file as {generated_slide_fname} using prs.save()"`.
`generated_slide_fname = "paper_summaries.pptx"` — filename only, no directory.
`prs.save("paper_summaries.pptx")` saves to the container's CWD, which is **not** `/sandbox/`.
`download_all_files_from_session()` scans `/sandbox/` → file not found → `RuntimeError`.

**Two fix options:**

| Option | Prompt change | Notes |
|--------|--------------|-------|
| **Fix A** (recommended) | `"Save as /sandbox/{generated_slide_fname}"` | Explicit, CWD-independent |
| **Fix B** | Keep relative path, verify Docker CWD = `/sandbox/` | Fragile; depends on container entrypoint config |

EXP-6A confirmed: `prs.save("relative.pptx")` saves to `os.getcwd()`. In a Docker sandbox where
CWD is not `/sandbox/`, Fix B would silently fail. Fix A is unambiguous.

---

## 3. Experiment Results (17/17 PASS)

All experiments passed. "PASS" means the expected behaviour was observed — including bugs (confirming they exist) and fixes (confirming they work).

### Bug #1 — JSON serialisation

| Exp | What was tested | Result | Key data |
|-----|----------------|--------|----------|
| EXP-1A | `o.json()` → double-encode → confirms bug | PASS | `item_type='str'`, `can_access_layout_name=False` |
| EXP-1B | `o.model_dump()` → correct structure | PASS | `item_type='dict'`, `layout_name='TITLE_AND_BODY'` |

**⚠ EXP-1B caveat:** Even after applying Fix #1, `idx_title_placeholder='0'` (string) because
the current schema is `Optional[str]`. Bug #2a fix is also required.

```
EXP-1B details:
  idx_title_type:  'str'
  idx_title_value: '0'
  would_need_int_cast: True   ← Fix #1 alone is NOT sufficient
```

---

### Bug #2a — Placeholder index type

| Exp | Schema | Input `0` (int) | Input `"0"` (str) | `model_dump()` type | Needs `int()` cast? |
|-----|--------|-----------------|-------------------|---------------------|---------------------|
| EXP-2A | `Optional[str]` + coerce | stored as `"0"` | stored as `"0"` | `str` | **Yes** |
| EXP-2B | `Optional[int]` (Fix B) | stored as `0` | stored as `0` | `int` | **No** |

Pydantic v2 lax mode automatically coerces `"0"` → `0` for `Optional[int]` without any validator.

**EXP-2C — End-to-end validation with real template:**
```
str dump value: "0"  →  slide.placeholders["0"]  →  TypeError  (str_fails=True)
int dump value:  0   →  slide.placeholders[0]    →  "Title 1"  (int_succeeds=True)
```
Fix B (`Optional[int]`) eliminates the placeholder access bug without any prompt changes.

---

### Bug #2b — `add_slide()` API

| Exp | Call | Actual error | Expected error type |
|-----|------|-------------|---------------------|
| EXP-3A | `add_slide("TITLE_AND_BODY")` | `AttributeError: 'str' object has no attribute 'part'` | (expected any exception) |
| EXP-3B | `add_slide(0)` | `AttributeError: 'int' object has no attribute 'part'` | (expected any exception) |
| EXP-3C | Correct lookup via `next(l for l in prs.slide_layouts if l.name == ...)` | Success, slide added | — |
| EXP-3D | Lookup with `"NONEXISTENT_LAYOUT_XYZ"` | `StopIteration` | — |

**Note:** The error is `AttributeError`, not `TypeError` as might be assumed from the name. Any code
that catches only `TypeError` will miss this failure.

**EXP-3D implication:** Production prompt fix must also add a `StopIteration` guard:
```python
try:
    layout = next(l for l in prs.slide_layouts if l.name == item['layout_name'])
except StopIteration:
    layout = prs.slide_layouts[0]   # fallback to first available layout
slide = prs.slides.add_slide(layout)
```

---

### Placeholder indexing (validates Fix #2a end-to-end)

| Exp | Access | Error type | Error message |
|-----|--------|-----------|---------------|
| EXP-4A | `slide.placeholders["0"]` | `TypeError` | `'%d format: a real number is required, not str'` |
| EXP-4B | `slide.placeholders[0]` | — (success) | placeholder name: `'Title 1'` |

---

### auto_size and MSO_AUTO_SIZE (validates prompt requirement for auto-sizing)

| Exp | Finding |
|-----|---------|
| EXP-5A | Template has **12 layouts**, **14 placeholders** with `auto_size=TEXT_TO_FIT_SHAPE` across 7 layouts: TITLE_SLIDE, TITLE_AND_BODY, PHOTO_LANDSCAPE, SECTION_HEADER_CENTER, PHOTO_PORTRAIT, SECTION_HEADER_TOP, CONTENT_WITH_PHOTO, BULLET_LIST |
| EXP-5B | `from pptx.enum.text import MSO_AUTO_SIZE` imports correctly; `ph.text_frame.auto_size = MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE` sets and reads back as `'TEXT_TO_FIT_SHAPE (2)'` |

Agent code must check the `auto_size` field from `get_all_layouts_info()` and apply
`MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE` (and skip setting font size) for affected placeholders.

---

### Bug #4 — Save path

| Exp | Call | Where file lands | Suitable for sandbox? |
|-----|------|-----------------|----------------------|
| EXP-6A | `prs.save("relative.pptx")` | `os.getcwd()` (wherever the process was started) | Only if CWD happens to be `/sandbox/` — **not guaranteed** |
| EXP-6B | `prs.save("/absolute/path/file.pptx")` | Exactly the specified path | Yes, if path is `/sandbox/<fname>` |

Fix A (`/sandbox/{generated_slide_fname}`) is unambiguous regardless of CWD.

---

### Multiline content in placeholders

| Exp | Input | Result |
|-----|-------|--------|
| EXP-7A | `placeholder.text = "* Key Approach\n* Conclusion"` | `paragraph_count=2`, split at `\n` |
| EXP-7B | Readback of same placeholder | `ph.text = '* Key Approach\n* Conclusion'` — exact round-trip |

`\n` in content strings correctly creates separate paragraphs. No special paragraph-insertion
code is needed; direct `placeholder.text = multiline_string` works.

---

## 4. Recommended Fix Implementation Order

Fix in this order — earlier bugs mask later ones, so fixing #1 and #3 first lets the agent
reach the python-pptx generation step where #2 and #4 would surface.

```
Priority  Bug   File                              Change
────────────────────────────────────────────────────────────────────────────────
1         #1    slide_gen.py (outlines_with_layout)
                  o.json()  →  o.model_dump()

2         #3    slide_gen.py (slide_gen step)
                  Add: self.sandbox.upload_file(str(ev.outlines_fpath))
                  Fix: json_file_path = f"/sandbox/{Path(ev.outlines_fpath).name}"
                  Fix: template_fpath = f"/sandbox/{Path(self.slide_template_path).name}"

3         #2a   schemas.py
                  idx_title_placeholder: Optional[str]  →  Optional[int]
                  idx_content_placeholder: Optional[str] →  Optional[int]
                  Remove coerce_int_to_str validator
                  Also update AUGMENT_LAYOUT_PMT: remove "as a string" from idx description

4         #2b   prompts.py (SLIDE_GEN_PMT)
                  Add layout lookup code pattern (with StopIteration guard)
                  Add null guard code pattern
                  (See slide_gen_prompt_eng.md for validated prompt variants P1–P3)

5         #4    prompts.py (SLIDE_GEN_PMT)
                  "Save as {generated_slide_fname}"
                →  "Save as /sandbox/{generated_slide_fname}"
```

---

## 5. What Was NOT Tested (Requires Docker)

Bug #3 (JSON not uploaded) cannot be validated without Docker running.
The fix mechanism is confirmed via code reading:
- `services/sandbox.py:97–103`: `upload_file(path)` → `copy_to_runtime(path, "/sandbox/<filename>")`
- `list_files()` scans `/sandbox/` via `os.listdir` inside the container
- Existing Docker e2e tests: `backend/tests/e2e/test_sandbox.py:45–62`
