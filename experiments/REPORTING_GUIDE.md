# Research Agent: Experiment Reporting Guide (Interview-Ready)

## Project Context (Read First)

This is a **side project** — a fork of [lz-chen/research-agent](https://github.com/lz-chen/research-agent), used for job hunting in the GenAI & RAG domain. It is not a production system.

Key terms used consistently across all reports:

| Term | Meaning |
|---|---|
| **Original (lz-chen)** | The baseline implementation from the original author |
| **My Implementation** | The forked version with modifications under experiment |
| **P0 / baseline variant** | The original author's prompt or configuration, used as the control condition |
| **pipeline** | The end-to-end system in this fork — never "production" |

**AI agents writing or editing reports must follow these rules:**
- Never use the word "production" — use "pipeline" or "lz-chen's original" instead
- P0 (or any "baseline" variant) represents the original author's implementation, not a pre-existing deployment
- "My Implementation" in diagrams always refers to this fork's approach

**Original Pipeline (lz-chen/research-agent) — factual reference for diagram "Original (lz-chen)" columns**

Do not invent or assume details about lz-chen's original implementation. Use only the facts in this table when writing "Original (lz-chen)" columns in Task Context diagrams or any comparison.

| Step | lz-chen original |
|---|---|
| Paper Discovery | Tavily web search → Semantic Scholar API (title match + citation expansion) — not OpenAlex |
| PDF Download | `arxiv` library only (`download_paper_arxiv()`); ArXiv ID required; no fallback; non-ArXiv papers silently dropped |
| PDF Parsing | `marker-pdf` (`convert_single_pdf()`) — PDF → markdown; not LlamaParse, not Docling |
| Summarization | PDF converted to images (PNG per page) → Azure GPT-4o multimodal; not from parsed text |
| Relevance Filter | GPT-4o-mini scores every candidate via `FunctionCallingProgram`; no embedding pre-screening |
| Slide Output | 1 slide per paper; `content` is a single text string (not multi-bullet, not multi-slide) |
| LLM Provider | Azure OpenAI exclusively (GPT-4o / GPT-4o-mini); no LiteLLM abstraction |
| Slide Validation | Binary valid/invalid only via Azure VLM; no failure type classification |

Note: The fork uses OpenAlex instead of Semantic Scholar because the Semantic Scholar API was unavailable during development. OpenAlex was used to simulate the same structural pattern (search + citation expansion) before being replaced with a direct BM25 search approach validated in Exp 1.

---

## Core Objective

This directory documents qualitative and quantitative analyses of the system's core components. The goal is to let an interviewer (GenAI & RAG background) grasp the engineering depth within 2 minutes via the Summary, while retaining full experimental data for deep-dive verification.

Each report must be self-contained — readable without opening any other file.

---

## Report Structure

Use this fixed section order. Do not reorder.

```
Task Context
Summary
Experiment Setup
Full Experimental Results
Observations
Decision
Pipeline Integration Status
```

### Report Title (H1)

The first line of every experiment MD file must follow this exact format:

```
# Experiment N — <Descriptive Title>
```

- `N` is the experiment number matching the README entry (`#### Experiment N — ...`)
- The descriptive title explains *what was studied and what the key finding was* — not just the component name. The MD title carries more weight than the README entry title, which summarises the outcome in the *Result:* line.
- Example: `# Experiment 9 — ReAct Agent: How a Prompt Example Key Breaks Tool Dispatch in 4B Models`

---

### Task Context

**Purpose:** Give the reader a pipeline picture before they encounter any technical terms. An interviewer who doesn't know the system should understand where this step fits and why it matters before reading anything else.

**What to include:**
- A reference sentence identifying which numbered step in README → System Architecture this experiment targets
- Two-level ASCII diagrams (see below)
- A brief explanation of what breaks if this step fails
- Define any non-obvious variable names referenced later in the report (e.g. prompt names, schema names)

**Two-level diagram structure:**

**Level 1 — System Architecture placement (from README):**

One sentence naming the step, then reproduce the step's box from the README System Architecture diagram. Show only the input arriving at that step and the output leaving it — do not draw the neighboring steps.

```
This experiment targets Step N — <Step Name> (README → System Architecture).

Input: <what arrives>        ← Step N-1: <name>
      │
      ▼
┌── N. STEP NAME ─────────────────────────────────────────────────────┐
├─── Original (lz-chen) ───────────┬─── My Implementation ────────────┤
│ ...                              │ ...                              │
└──────────────────────────────────┴──────────────────────────────────┘
      │
      ▼
Output: <what leaves>                → Step N+1: <name>
```

The separator row must use `Original (lz-chen)` and `My Implementation` as column headers — not a plain horizontal line. This tells the interviewer at a glance which side is the forked baseline and which side is the contribution being reported.

**Level 2 — Step-internal detail:**

One sentence introducing the experiment target within the step. Draw the internal flow of Step N only — from the step's input down to its output. Use an EXPERIMENT TARGET box to highlight the specific sub-step under investigation. Do not include steps outside of Step N.

```
Step N — <Step Name> (detail)
──────────────────────────────────────────────────────────────────
 <step input>
       │
       ▼
 [sub-step A]     <what it produces>
       │
       ▼
 ┌─── EXPERIMENT TARGET ──────────────────────────────────────┐
 │ [sub-step B]                                               │
 │   Input:  ...                                              │
 │   Prompt: ...                                              │
 │   Output: ...                                              │
 └────────────────────────────────────────────────────────────┘
       │
       ▼
 <step output>    → Step N+1: <name>
```

---

### Summary (3-Point Style)

**Purpose:** Let the interviewer decide in 20 seconds whether to read further. Placed after Task Context so all terms in the Summary are already familiar.

**Format:**

Each of the three bullets follows the same two-level structure — a short 1-sentence claim on the main bullet, then 2–3 indented sub-bullets (`  - `) with the concrete details:

```markdown
- **Problem:** [1-sentence claim — what broke and where]
  - [concrete symptom: metric value, error type, observed behaviour]
  - [root cause: what produced the symptom]
- **Solution:** [1-sentence claim — method and what it isolates]
  - [scale: number of variants / models / runs]
  - [key methodological detail: what was held constant, what was varied]
- **Result:** [1-sentence claim — what was chosen and the headline metric]
  - [non-obvious secondary finding that the headline number alone does not convey]
```

The main bullet must be short enough to read in one breath. Push all specifics (numbers, model names, file names) into sub-bullets.

**Rules:**
- Do not use internal experiment codes (E14, Path B, METHOD_A) in the Summary — use descriptive names
- Do not start with the experiment goal — start with the pipeline problem
- The **Problem** bullet must describe a pipeline-level failure — output missing, step stalling, reliability breaking — observable without knowledge of external APIs or data structures. An interviewer who has never used the API must understand what broke and why it matters from this bullet alone. API behaviors and data structure observations belong in Observations, not in the Problem statement.

---

### Experiment Setup

**Purpose:** Define all variables so the reader can interpret the results tables without scrolling back.

**What to include:**
- **Objective** — three bullet points, each on its own line:
  - **Problem:** the specific failure or gap that motivated the experiment, with a concrete symptom (e.g. metric value, error type)
  - **Goal:** the question the experiment answers — what is being compared and under what conditions
  - **Pass condition:** the criterion a result must meet to be considered acceptable — not a judgment of success, just the defined threshold
- A methods comparison table
- A prompt/config variants table
- **Metrics** — define every metric used in the Results tables. State which metric is the primary indicator and what its values mean (e.g. 0 = failure, 1 = efficient, >1 = self-debugging). Do not just list metric names.
- **Components or tools under test** — if the experiment measures agent tools, API calls, or system components, include a brief table explaining what each one does. An interviewer without pipeline context must understand why these are being measured.
- Other parameters (models, runs, execution mode, total calls)

**What to omit:**
- Do not include a Hardware sub-section — the README documents the M1 hardware environment for all experiments. Repeating it in each report adds noise without value.

**✅ Convention:**
Add `✅ = currently used in the pipeline` at the top of this section. Mark `✅` on every row and column header that represents the current pipeline configuration — in both the Setup tables and all Results tables. If the pipeline configuration was superseded by a follow-up experiment, do not mark `✅`; instead add a note explaining that further experiments were done.

---

### Full Experimental Results

**Purpose:** Evidence. Readers can skip this and read Observations; the data is here for verification.

**What to include:**
- Success rate tables per model (with `✅` on pipeline row/column)
- Latency tables per model (with `✅` on pipeline row/column)
- Cross-method summary table

**What to omit:**
- Per-breakdown tables where results are binary (all 0% or all 100% per cell) — these repeat what the success rate table already shows. Instead, note the finding in one sentence in Observations.

**Sub-experiment context — when and what format:**

When Full Experimental Results contains multiple rounds or sub-experiments, each with a distinct purpose, add a brief context block directly under the sub-experiment heading and before the table, then a `**Conclusion:**` line directly after the table:

```markdown
- **Purpose:** why this round was run
- **Expected:** what a passing result looks like for this round

[table]

**Conclusion:** [1 sentence — pipeline consequence + one non-obvious insight not visible from the table alone]
```

Rules for the `**Conclusion:**` line:
- Always present for every sub-experiment table — not optional
- Maximum 1 sentence
- No API syntax or SDK method names — use conceptual names ("BM25 search", "embedding similarity")
- Do not restate numbers already visible in the table
- Lead with pipeline consequence, then the non-obvious insight

Omit the Purpose/Expected block (but keep the `**Conclusion:**`) when the experiment has only one result table and the Objective in Setup already provides sufficient context.

**Post-table notes — when and what format:**

The `**Conclusion:**` line covers the standard case. Add additional post-table notes only when:

- **Use bullet points** when the table shows wrong or unexpected values but omits expected values — list expected output per failing case (e.g., `` `cover/title_slide` → `TITLE_SLIDE` ``).
- **Use 1 prose sentence** for single-instance silent failures or format mismatches where showing expected vs actual behavior requires a brief explanation beyond the Conclusion line.

---

### Observations

**Purpose:** Explain what the numbers mean — specifically, what is non-obvious or surprising. This is where engineering depth is demonstrated.

**Structure — causal narrative, not parallel bullets:**

Start from the root cause or bug, then follow the chain of findings. Each finding should lead into the next. Use an ASCII causal chain diagram as the primary structure, then use short text paragraphs to fill in details the diagram cannot hold.

**When to use `###` sub-headings within Observations:**

- Use `###` sub-headings when the Observations cover multiple independent root causes or distinct finding clusters — readers should be able to jump directly to the problem they care about.
- Keep a single causal chain (no sub-headings) when all findings are truly sequential: one root cause leads to the next finding, which leads to the next.
- Each sub-heading gets its own mini causal chain and text paragraphs.

```markdown
## Observations

### Finding cluster A
[mini causal chain + text paragraphs]

### Finding cluster B
[mini causal chain + text paragraphs]
```

**ASCII diagram type — causal chain:**
```
Root problem
      │
      ▼
Finding 1 (root cause)
      │  explanation
      │
      ▼
Finding 2 (new trap or constraint)
      │
      ├─ case A ──── result ✗
      │    · reason
      │
      └─ case B ──── result ✓
```

**Text after the diagram — bold conclusion + bullet points:**

After each ASCII diagram, write a bold 1-line conclusion (`**Conclusion:**`), then support it with either short blog-style prose paragraphs (2–3 sentences each) or bullet points — whichever communicates the finding more clearly. Avoid long academic paragraphs. Each sentence must follow tech blog sentence style (see Writing Style → General rules).

```markdown
**Bold one-line conclusion:**
- specific data point or metric that supports the conclusion
- mechanism or reason (what caused this result)
- implication or constraint for the pipeline (what this means downstream)
```

Use multiple bold-conclusion + bullet-list blocks when a single `###` section contains more than one distinct finding (e.g., CoT effect AND extended metadata effect are two separate findings within the same sub-heading).

Rules for bullet content:
- Lead each bullet with the fact, not the interpretation
- Include the exact numbers (e.g. "FN rises 19 → 31" not "recall dropped significantly")
- Explain the origin of non-obvious items (e.g. why a variable has an unexpected value, where a string came from)
- Do not repeat what the diagram already shows

**When to add a comparison tree in Observations:**

If the experiment compared multiple variants (prompts, configs) of a single chosen method, add a comparison tree after the text paragraphs. Start from the variable being compared, show each variant's per-model outcome, and note any trade-offs. Use this to explain which variant was kept and why — without opening a separate section.

**Symbol legend for comparison trees:**

| Symbol | Meaning |
|---|---|
| ✓ | Meets the target (tied best or clearly correct) |
| △ | Partial — works but worse than the chosen variant (trade-off or accuracy drop) |
| ✗ | Failed — unacceptable result or invalid output |

Always define the reference point in the tree header so the symbols are unambiguous, e.g. `sorted by accuracy high → low  [✓ = tied P1 ✅  △ = worse than P1  ✗ = failed]`.

**ASCII diagram type — comparison tree:**
```
Variable being compared (sorted by accuracy high → low)
[✓ = tied best  △ = worse than chosen  ✗ = failed]
      │
      ├─ Variant A ── 100% ✓
      │    Trade-off: requires prompt change
      │
      ├─ Variant B ── 100% ✓  ← chosen
      │    No trade-offs
      │
      ├─ Variant C ── 92%  △
      │    −8pp vs Variant B, no accuracy gain
      │
      └─ Variant D ── 0%   ✗
           Produces invalid output names
```

Follow with 1–2 sentences: which variant was kept and the fallback if the primary model changes.

**When a finding requires external API or data structure knowledge:**

If a finding depends on knowledge of a specific API, data format, or external system, provide a minimal concrete example before the causal chain diagram — enough for a context-free reader to understand what the system returns. Do not write a full API tutorial — just enough context for the diagram to be self-explanatory.

Format: one sentence introducing what the system returns, followed by a short code block (4–8 lines) showing a representative input or output, then the causal chain.

Example:
```markdown
OpenAlex returns paper metadata as a JSON dict. The `ids` field
contains DOI, MAG, PMID — but no ArXiv entry:

​```json
"ids": {"doi": "https://doi.org/10.48550/...", "mag": "2741809807"}
​```

The ArXiv URL appears only in a nested `locations` array...
```

**What belongs here vs. in Decision:**
- Observations = what the data reveals
- Decision = what was chosen and why

---

### Decision

**Purpose:** Show engineering judgment — what was chosen, why one option was rejected over another.

**Structure — trade-off diagram + minimal text:**

Start directly from the decision question. Use an ASCII trade-off diagram to show options and their key properties. Follow with 1–2 sentences covering fallback scenarios or caveats the diagram cannot express.

**ASCII diagram type — decision tree:**
```
Decision question
      │
      ├── Option A
      │     ✓ advantage
      │     ✗ constraint that ruled it out
      │     → REJECTED
      │
      └── Option B ✅
            ✓ advantage
            △ trade-off
            → CHOSEN: reason
```

**When to use `###` sub-headings within Decision:**

Use `###` sub-headings when the Decision section answers multiple independent questions. A question is independent if it can be answered without first resolving the other questions.

Two common patterns:
- **Sequential dependency** (one question unlocks the next): "Which architecture?" → then "Within the chosen architecture, which configuration?" — these are two independent questions even though the second is scoped by the first. Use two `###` sub-headings.
- **Parallel options** (same level, unrelated): "Which suffix for the normal path?" vs "Which suffix for the error path?" — clearly independent. Use two `###` sub-headings.

**One `###` sub-heading = one code block.** Never combine two independent decision questions into the same code block. Each `###` heading introduces exactly one decision tree in its own fenced code block.

**Multi-dimensional decision trees:**

When a decision question spans multiple independent dimensions (e.g. Stage-1 model AND Stage-2 prompt AND input fields), use one `###` sub-heading per dimension, each with its own code block. Never flatten multi-dimensional options into a single same-level tree — branches at the same level must be genuine alternatives to each other, not alternatives across different dimensions.

**Branch ordering:**

Order decision branches by pipeline execution flow when the decision spans multiple pipeline components: input → processing → output. Do not order by experiment axis number or alphabetically.

```markdown
### Which architecture?

```
Decision question A
      │
      ├── Option 1 → REJECTED
      └── Option 2 ✅ → CHOSEN
```

### Within the chosen architecture: which configuration?

```
Decision question B
      │
      ├── Sub-option X → REJECTED
      └── Sub-option Y ✅ → CHOSEN
```
```

**Rules:**
- Do not repeat pipeline background here — that belongs in Task Context
- Do not repeat findings from Observations — reference them, don't restate
- End with a brief fallback note if relevant

---

### Pipeline Integration Status

**Purpose:** Let the interviewer know whether the findings were acted on.

**Four possible statuses:**

| Status | When to use |
|---|---|
| **[INTEGRATED]** | The chosen option is live in the pipeline. State which file/step was changed and why that option was selected over the alternatives. |
| **[SUPERSEDED]** | The approach was abandoned mid-experiment or after evaluation — a different architecture was adopted instead. This covers two cases: (a) the experiment itself was the evidence trail for the abandonment decision; (b) a later architectural change made the finding irrelevant. State what replaced it and why. |
| **[NOT INTEGRATED]** | The experiment produced a valid finding that is ready to apply, but has not been integrated yet. State what is blocking or deferred. |
| **[PROPOSED]** | The finding points to a potential improvement but requires further validation before integration. State the data that supports consideration and what additional validation is needed. Do not recommend adoption — that is a project decision, not an experiment finding. |

**Heading format — status badge inline:**

The status badge appears inline with the section heading, not on a separate line below. Use an emoji prefix for at-a-glance scanning:

```markdown
## Pipeline Integration Status ✅ INTEGRATED
## Pipeline Integration Status 🚫 SUPERSEDED
## Pipeline Integration Status ⏳ NOT INTEGRATED
## Pipeline Integration Status 🔬 PROPOSED
```

**When to use `###` sub-headings within Pipeline Integration Status:**

Use `###` sub-headings whenever the section covers more than one independent aspect. Keep a single prose block only when the status is a one-liner with nothing else to add.

Recommended sub-heading sets by status:

| Status | Recommended `###` sub-headings |
|---|---|
| **✅ INTEGRATED** | 1 sentence: what was swapped out and what replaced it + file reference · `### Impact` (2–3 bullet numbers) |
| **🚫 SUPERSEDED** | `### What replaced it` · `### Why the decision was made` · `### Transferable findings` |
| **⏳ NOT INTEGRATED** | `### Current state` · `### What is blocking` |
| **🔬 PROPOSED** | `### Supporting data` · `### Validation needed` |

Content rules by status:

- **✅ INTEGRATED:** Do not include a "What triggered" section — the trigger is already covered by Observations and Decision. "What changed" is 1 conceptual sentence (no API syntax, no filter parameter values); include file name and function name as a brief reference. Sub-headings use `###` not `####`.
- **🚫 SUPERSEDED:** Do not include "What triggered" — same reason. State what replaced it and why, then list transferable findings explicitly.

Example for ✅ INTEGRATED:

```markdown
## Pipeline Integration Status ✅ INTEGRATED

Tavily citation-expansion replaced by direct OpenAlex BM25 search with quality filters in `paper_scraping.py` → `fetch_candidate_papers()`.

### Impact

- Zero-candidate failure eliminated across all five tested domains.
- Total relevant papers: 53 → 64 (+20.8%).
- Pipeline is now fully deterministic; no paid external API required.
```

Example for 🚫 SUPERSEDED:

```markdown
## Pipeline Integration Status 🚫 SUPERSEDED

### What replaced it
- <new architecture or method that was adopted instead>

### Why the decision was made
- <reason — measured failure mode or architectural constraint>

### Transferable findings
- <finding that remains applicable even though the approach was abandoned>
```

**Rules:**
- Use "pipeline" not "production"
- If integration is partial or deferred, say so explicitly
- **🚫 SUPERSEDED** is not a failure — state the transferable value of the finding explicitly (e.g. "the finding about small-model prompt sensitivity remains applicable to any future agent step")
- **All statuses must be factual** — state what happened and what the data shows. Do not make recommendations or predict future outcomes.

---

## Writing Style

### Which sections use which style

All text in the report uses blog-style. Tables and code blocks are data-only — no style applies to them.

| Section | Additional requirement beyond blog-style |
|---|---|
| Task Context | Must orient the reader to the pipeline before any technical terms appear |
| Summary | Problem first, then experiment, then result — in that order |
| Experiment Setup | Must be complete and precise enough to reproduce the experiment |
| Results tables | Data only — no prose |
| Sub-experiment context (Purpose / Expected) | Each line is one short statement — no multi-clause sentences |
| Post-table Conclusion | 1 sentence — pipeline consequence + non-obvious insight; no API syntax; no number restatement |
| Observations | Conclusion-first paragraphs; causal chain diagram as primary structure |
| Decision | Start directly from the decision question; no pipeline background |
| Pipeline Integration Status | State what happened and what the data shows — no recommendations |

### Blog-style rules (all text sections)
- First sentence of each paragraph = the conclusion or main point
- Short sentences. Split long ones.
- **Active voice, no first person** — use subject-verb-object without "we" or "I". "The model achieves F1=0.974" is active voice. "It was found that..." is passive — avoid it. Use "I" only for personal decisions or manual observations that cannot be attributed to the experiment itself.
- Contractions are fine (it's, don't, can't)
- Do not restate what a diagram already shows
- No internal experiment codes in narrative (Round 1, Method A, E14) — use descriptive names
- **American English spelling** — use American spelling throughout. Common British→American pairs: artifact (not artefact), behavior (not behaviour), favor (not favour), characterize (not characterise), stabilize (not stabilise), generalize (not generalise), realize (not realise), optimize (not optimise), normalize (not normalise), serialize (not serialise), summarize (not summarise), recognize (not recognise).
- **Tech blog sentence style — one idea per sentence:** applies to every sentence in all body text (bullets, prose, captions, post-table conclusions). Exempt: headings and sub-headings, which are descriptive labels, not sentences. Rule: if a sentence contains a subordinate clause (`which`, `where`, `even though`, `because`) that can be split into a separate sentence, split it. The goal is that each sentence is immediately understood on first read — no re-reading required.

  | ❌ Paper-style | ✅ Tech blog |
  |---|---|
  | "When the only code example in the prompt is the layout lookup block (which has no null guards), gemma3:4b treats the absence of null guards as a style signal and omits them — even when the text instruction says to guard against None." | "gemma3:4b copies the style of the code example — including what's missing. The layout example has no null guard. So the model omits null guards too, even when the text says otherwise." |

### Objectivity rules (strictly enforced)

Reports are factual records of what happened and what the data shows. Any claim that goes beyond the measured data is a violation.

**What counts as objective (write this):**
- Observations directly tied to a metric, output, or logged event: "python-pptx has no markdown parser — bullet text collapsed into a single paragraph"
- Decisions with a stated reason: "The approach was replaced on 2026-04-15 because of non-deterministic output and Docker dependency"
- Trade-offs with measured evidence: "P3 adds +1.9s latency on gemma3:4b with no accuracy gain"

**What counts as subjective (never write this):**
- Universal negative claims not backed by a controlled experiment: ❌ "No prompt engineering can fix this" ❌ "This approach will never work" ❌ "X is impossible"
- Prescriptive forward-looking claims: ❌ "recommended" ❌ "should adopt" ❌ "expected to generalize"
- Inferences that exceed what the data shows: ❌ "This proves the approach is fundamentally flawed" — instead: "Three independent failure modes remained unresolved after N prompt variants"
- Causal claims without a controlled test: ❌ "Larger prompts cause attention dilution" — unless that hypothesis was tested and measured

**The test before writing any claim:**
> *Can this sentence be verified by reading the experiment's data tables, logs, or commit messages?*
> - Yes → write it
> - No → remove it or reframe as a hypothesis explicitly labelled as such

### General rules
- Avoid "We" — use subject-verb-object phrasing without first person
- Use "I" only for personal decisions or manual observations
- Use "pipeline" or "system" — not "production"
- Do not use internal experiment codes in narrative text (METHOD_A, E14, Path B) — use descriptive names in tables, descriptive phrases in prose
- Avoid paper-style hedging language ("it was observed that", "results suggest")
- **No subjective recommendations** — do not write "recommended", "should adopt", "expected to generalize", or similar forward-looking claims unless directly supported by measured data. Reports document what happened and what the data shows; project decisions belong outside the report.
- **Pipeline consequence first:** every finding must lead with what breaks at the pipeline level (paper lost, step stalls, latency doubles), then explain the technical mechanism that caused it. "lz-chen's download step permanently loses non-ArXiv papers" is the headline; "because `download_paper_arxiv()` only accepts an `arxiv_id` parameter" is the mechanism. Never open a finding with the mechanism.
- **Heading hierarchy:** never skip heading levels. After `##` always use `###`; after `###` always use `####`. `##` → `####` without an intermediate `###` is not allowed.
- **API syntax in prose:** API syntax and SDK method names belong in table columns (as brief reference) or Task Context (defined once). Never include them in prose sections (Summary, Observations, post-table Conclusion, Decision). Use conceptual names in prose: "BM25 full-text search" not `` `Works().search(q)` ``, "embedding similarity" not `` `nomic-embed-text cosine sim` ``.
- **Define once, reference by name:** every method, term, or concept is defined exactly once — in Task Context or Experiment Setup. Subsequent sections (Results, Observations, Decision) reference by name only and do not re-explain. If Task Context defines a methods table, Results uses the method name directly without repeating what it does.

---

## ASCII Diagram Reference

| Location | Diagram type | Starting point | Purpose |
|---|---|---|---|
| Task Context | Pipeline flow | Pipeline requirements | Orient reader to where the step fits |
| Observations | Causal chain | Root problem / bug | Show how findings connect |
| Decision | Decision tree | Decision question | Show trade-off and chosen option |
| Observations (prompt/config) | Comparison tree | Variable being compared | Show per-case outcomes |

---

## What to Remove

- **Transparency & Traceability section** (file paths, raw data paths) — interviewers do not verify experiment data; this section adds noise without value
- **Per-breakdown tables** where results are binary — replace with one sentence in Observations
- **Redundant prose** that restates what a diagram already shows

---

## README Integration (For AI Agents)

README.md uses a **two-tier structure**:

- **README (index layer):** one compact entry per experiment — table + three-line context block. Gives the interviewer enough to decide whether to click through.
- **`experiments/*.md` (detail layer):** the full interview-ready report with all sections.

### When to add a README entry

Only add a README entry when the `experiments/*.md` report is fully interview-ready (all 7 sections complete, ✅ applied, diagrams in place). Do not create a placeholder entry for an unfinished report.

### README entry format

Each experiment entry must follow this fixed format:

```
#### Experiment N — <Title>

**System Architecture:** Step X — <Step Name> [(sub-step or note if applicable)]

| <most representative comparison table — lz-chen baseline vs selected approach, 1 table maximum> |

- *Problem:* [1 sentence — pipeline-level failure, lz-chen baseline as reference point]
- *Change:* [1 sentence — the architectural decision made]
- *Result:* [1 sentence — headline metric]

> ✅ INTEGRATED / 🚫 SUPERSEDED / ⏳ NOT INTEGRATED / 🔬 PROPOSED
> → Full report: [experiments/path/to/report.md](experiments/path/to/report.md)
```

**Rules:**
- No `**Goal:**` field — the title and **System Architecture** line already convey this.
- No `**Key Finding:**` field — the *Result:* line replaces it. Do not use any alternative label.
- No status badge sentence inline with the heading — the badge appears as a standalone `> ✅ / 🚫 / ⏳ / 🔬` line after the P/C/R block.
- No more than one table per README entry — pick the table that most directly compares the lz-chen baseline against the selected approach.
- *Problem:* must be pipeline-level — what failed or was missing, not an API detail. Use lz-chen's approach as the baseline reference where one exists.
- *Change:* states the architectural decision, not the exploration path. Sub-experiments and ablation details belong in the full report.
- *Result:* states the headline metric or outcome. Do not restate the goal.
- All three bullets (*Problem:*, *Change:*, *Result:*) are required. Do not omit any.
- Use `*Change:*` not `*Fix:*` — "Fix" implies a bug; "Change" covers design decisions, evaluations, and migrations.
- The full report link must point to the correct path in `experiments/` including the numeric prefix (e.g. `01-search_method_comparison.md`).
- Tech blog sentence style applies to all three P/C/R lines — one idea per sentence, no subordinate clauses that can be split.

**ASCII diagram rules:**

*Per-experiment entry:* Only include an ASCII diagram or image inside an experiment entry when it is not already present in the System Architecture section AND not already present in the full report. Diagrams that appear in either place must not be repeated in the experiment entry — the table + P/C/R block covers the same content more concisely.

*Section-level:* Add a section-level ASCII diagram between a subsection heading (e.g. `### Experiments — Paper Discovery Pipeline`) and its first experiment entry when two or more experiments in that group have a logical sequence or causal relationship that no single full report covers. This diagram shows the interviewer why the experiments are ordered this way and what each feeds into the next. Do not add a section-level diagram if the relationship is already obvious from the experiment titles alone.

### Where to place the entry in README

README has two experiment subsections:
- `### Experiments — Paper Discovery Pipeline` — for Steps 1–4
- `### Experiments — Slide Generation Pipeline` — for Steps 5–7

Place the new entry in the correct subsection, in Step order. If two experiments target the same step, place the currently-in-pipeline one first, then the superseded one.

### Updating an existing README entry

If a full report is revised (e.g. data corrected, new finding added), check whether the README entry's table or P/C/R block needs to change. Update only the affected lines — do not rewrite the entire entry.

---

## Workflow for Updating Reports (For AI Agents)

When writing or refactoring a report:

1. **Read the source material thoroughly** — identify all key data points, tables, specific configuration details, and non-obvious findings
2. **Follow the section order** — Task Context → Summary → Setup → Results → Observations → Decision → Integration Status
2b. **Cross-check narrative numbers** — verify every metric cited in Summary and Objective against the Full Experimental Results tables in the same report before finalising
3. **Apply ✅ consistently** — mark in every table, add the legend in Experiment Setup
4. **Build causal narratives** — Observations must read as a story with a logical chain, not a list of independent findings
5. **Preserve all data** — do not delete numbers, tables, or findings; only restructure for clarity
6. **Explain non-obvious items** — anything an interviewer might find strange (unexpected values, naming, design choices) needs a brief origin note
7. **Propose before executing** — for significant restructuring, state the intended direction and confirm before applying changes

---

## Technical Keyword Mapping (Terminology Alignment)

Align descriptions with industry-standard terms:

- Search Evaluation → **Data Source Benchmarking / Retrieval Quality**
- Filtering → **Reranking / Multi-stage Filtering**
- JSON Control → **Constrained Decoding / Grammar Enforcement**
- ReAct Optimization → **Agent Steering / Instruction Following**

---

## Fact-Check & Integrity Standards

- **Data consistency:** Metrics must match raw source data
- **Internal consistency:** Numbers cited in Summary and Objective must match the values in the Full Experimental Results tables of the same report — not from pre-experiment estimates or informal observations made outside the experiment
- **Honest reporting:** If a method failed, document the failure and the root cause — this demonstrates diagnostic ability
- **No fabrication:** Do not infer results not present in the source data
- **Stale ✅:** If a pipeline configuration has changed since the experiment, update or remove the ✅ marker and note what changed

---

## Review Checklist (For AI Agents)

Before finalizing any experiment report, go through every section explicitly in order. Do not skip sections because they were not discussed in context — each checkbox must be verified independently against the rules in this guide.

| Section | Check |
|---|---|
| **Task Context** | Heading hierarchy correct (`##` → `###`)? Tech blog sentence style applied to all body text? Headings and sub-headings are exempt. |
| **Summary** | Tech blog sentence style per sentence? No internal experiment codes (Path B, E14, Method A)? Problem bullet is pipeline-level (no API details)? |
| **Experiment Setup** | Hardware sub-section removed? `✅` marked on all current-pipeline rows and columns? All metrics defined? |
| **Full Experimental Results** | `Conclusion` removed from Purpose/Expected block? `**Conclusion:**` present after every sub-experiment table? Tech blog sentence style in Conclusion line? |
| **Observations** | `###` sub-headings (not `####`)? Tech blog sentence style in all body text? Bold conclusion uses `**Conclusion:**` (colon, not period)? |
| **Decision** | `###` sub-headings where needed? No pipeline background restated (belongs in Task Context)? No findings from Observations restated? |
| **Pipeline Integration Status** | Badge inline in heading (`## Pipeline Integration Status ✅ INTEGRATED`)? `###` sub-headings (not `####`)? No "What triggered" section? "What changed" is 1 conceptual sentence with no API syntax? |
| **Entire file** | No `**Conclusion.**` (period) — must be `**Conclusion:**` (colon)? No "production" — must be "pipeline"? American English spelling throughout? No heading level skipped (`##` → `####` not allowed)? |

**Rule:** Every row must be verified. Skipping a section because it was not part of the current discussion is not acceptable.
