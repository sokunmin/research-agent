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
- The descriptive title explains *what was studied* — not the finding. The finding belongs in Summary → Result. Keep the title short enough to scan.
- Example: `# Experiment 9 — ReAct Agent: Prompt Example Key and Tool Dispatch in 4B Models`

---

### Task Context

**Purpose:** Give the reader a pipeline picture before they encounter any technical terms. An interviewer who doesn't know the system should understand where this step fits and why it matters before reading anything else.

**What to include:**
- A reference sentence identifying which numbered step in README → System Architecture this experiment targets
- A detail diagram showing the internal flow of that step (see below)
- Define any non-obvious variable names referenced later in the report (e.g. prompt names, schema names)

**Step detail diagram:**

One sentence introducing the experiment target within the step. Draw the internal flow of that step only — from its input down to its output. Use an EXPERIMENT TARGET box to highlight the specific sub-step under investigation. Do not include steps outside of this step.

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

**Multi-part experiments (Part A → Part B):**

When an experiment has sequential sub-experiments where Part A's output becomes Part B's fixed input, show multiple EXPERIMENT TARGET boxes connected by an arrow. Label each box with the part name. Annotate the connecting arrow with what Part A fixes for Part B.

```
 ┌─── EXPERIMENT TARGET: Part A ──────────────────────────────────┐
 │ <Part A name>                                                   │
 │   Input:  ...                                                   │
 │   Output: <value fixed for Part B>                             │
 └─────────────────────────────────────────────────────────────────┘
       │  <fixed value> fixed
       ▼
 ┌─── EXPERIMENT TARGET: Part B ──────────────────────────────────┐
 │ <Part B name>                                                   │
 │   Input:  ...                                                   │
 │   Output: ...                                                   │
 └─────────────────────────────────────────────────────────────────┘
```

---

### Summary (3-Point Style)

**Purpose:** Let the interviewer decide in 20 seconds whether to read further. Placed after Task Context so all terms in the Summary are already familiar.

**Format:**

Each bullet is a single short sentence — the claim stated directly. Sub-bullets are used only when necessary:

```markdown
- **Problem:** [1-sentence claim — what was missing or unevaluated]
- **Solution:** [1-sentence claim — method and what it isolates]
  - [sub-bullet only when Solution covers multiple parallel sub-experiments, e.g. Part A / Part B]
- **Result:** [1-sentence claim — winner and headline metric, stated as absolute improvement]
```

Do not add sub-bullets to Problem or Result — the details are already in Full Experimental Results. Sub-bullets on Solution are only needed when the experiment has multiple parallel sub-experiments that cannot be described in one sentence.

The main bullet must be short enough to read in one breath.

**Summary exists to hook the reader into continuing, not to front-load every detail.** Over-explaining buries the key point — the more detail crammed into a bullet, the harder it is for the reader to extract what actually matters. Every bullet must be understandable by a reader with zero context on this project, without reading any section below Summary, using the smallest set of facts that still lets Problem → Solution → Result connect into one coherent story. Do not use specific configuration names, prompt names, or field-set labels that are only defined in Experiment Setup — describe them conceptually instead (e.g. "a fast embedding pre-screen" not "Basic fields with nomic-embed-text").

**Rules:**
- Do not use internal experiment codes (E14, Path B, METHOD_A) in the Summary — use descriptive names
- Do not start with the experiment goal — start with the pipeline problem
- The **Problem** bullet must describe a pipeline-level failure — output missing, step stalling, reliability breaking — observable without knowledge of external APIs or data structures. An interviewer who has never used the API must understand what broke and why it matters from this bullet alone. API behaviors and data structure observations belong in Observations, not in the Problem statement.
- **Problem must describe what was unvalidated before the experiment, not a result the experiment produced.** This applies to numbers and to qualitative claims alike: do not cite any number from this report's own Full Experimental Results in Problem (numbers are only known after the ablation runs), and do not use outcome-asserting language ("has no guaranteed support," "is unreliable," "will fail") that states a conclusion without a number attached — both reverse cause and effect. This applies even to a threshold framed as a "pass condition," since a threshold is only meaningful once you know what result it's being compared against. Test: if the sentence would need rewriting after seeing the experiment's results, it is a Result, not a Problem.

  | Avoid (asserts an outcome) | Use instead (states the gap neutrally) |
  |---|---|
  | "...and function-calling passthrough has no guaranteed support across that many backends." | "...so nothing in the design indicates whether the same approach still works if the provider or model changes." |
  | "...which will silently drop valid results under load." | "...and load-time behavior for this path was never exercised." |
  | "...making the existing method unreliable for production use." | "...and no data exists on how the existing method performs outside its original single-provider setup." |

- **Problem must not cite findings from experiments dated later than this one.** Check the experiment's date against other experiments referenced in README — an experiment cannot be motivated by a finding that did not exist yet.
- **Problem must rest on objective, architectural facts about the original (lz-chen) implementation for this specific step only** — derived from the factual reference table in this guide's Project Context section, not from any measured performance number, and not from what the fork does, adds, or changes. Sentences like "this fork adds X" or "this fork routes Y through Z" describe an engineering decision — they belong in Solution or Decision, not Problem.
- **Problem must be high-level and self-contained** — a reader with zero context on this project must understand it from this sentence alone, without needing any term defined later in the report.
- **Suggested method:** list the original implementation's objective shortcomings for this step (aim for ~5 candidates), discard any that duplicate each other, depend on another experiment's findings, or imply a measured result, then keep the most important 3 (fewer if fewer qualify) and compress them into one sentence.
- **Problem must cover every consequence Task Context raises for this step, while staying high-level and concise enough for a zero-context reader to understand in one read.** If Task Context's introductory paragraph states multiple failure modes (e.g., false positives wasting downstream compute AND false negatives silently dropping valid results), Problem must address all of them — but not as an itemized checklist. Find the single architectural cause that explains all the consequences at once, and let the consequences appear as a brief aside, not a list.

---

### Experiment Setup

**Purpose:** Define all variables so the reader can interpret the results tables without scrolling back.

**Principle: group same-type information into one table.**

Organize by what the experiment actually varies. Read the Python script to identify which parameters are fixed (same across all conditions) and which form the comparison axis (what changes between conditions). Create sub-section names that match the content — do not apply a fixed template.

- Parameters shared across all conditions belong in one block. Name the sub-section based on what those parameters describe — e.g. "Shared Model Config", "Common Pipeline Parameters", "Evaluation Setup" — not a generic label like "Fixed Conditions". Only list parameters that are active and have a value — omit absent or unused parameters.
- **The comparison axis** (what was varied) belongs in a separate block, one table per axis.
- **The only required sub-section is Metrics** — define every metric used in Results tables, state which is primary, and explain what each measures.

Each sub-section covers one type of information only. Do not include rows already covered by another nearby table.

Do not add an Objective sub-section — this repeats what Summary already states.

**Format consistency:** All sections within Experiment Setup that present structured data must use the same format. If the experiment's Setup uses tables as the primary format, all data sections (Metrics, Strategies, Parameters) must also use tables — do not mix prose paragraphs with tables in the same Setup section. Each table column carries one type of information only.

**What to omit:**
- Do not include a Hardware sub-section — the README documents the M1 hardware environment for all experiments. Repeating it in each report adds noise without value.
- **Only list what is active and has a value.** Omit any row or item where the value is absent, unused, or None — absence is not worth documenting. This applies to all Setup tables and any configuration table.

**✅ Convention:**
Add `✅ = currently used in the pipeline` at the top of this section. ✅ marks one thing only: whether a config, strategy, or model is currently applied in the pipeline. Do not use it for any other purpose. If the pipeline configuration was superseded by a follow-up experiment, do not mark `✅`; instead add a note explaining that further experiments were done.

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

**Purpose:** Explain what the numbers mean — specifically, what is non-obvious or surprising.

**Structure:** Each `###` sub-heading is a question. The lead-in answers it in one sentence — stating both the finding and its reason, connected with an em dash if needed. Bullets follow with data only.

```markdown
### Why Does X Happen?

One sentence: what happened and why — connected with an em dash if needed.

- Metric or data point that proves the lead-in (numbers required).
- Second bullet only when it adds a number not captured in the lead-in.
```

**Bullets = numbers only.** Every bullet must contain at least one concrete number or measurement. Bullets with no number are deleted. Bullets that contain both a number and a mechanism explanation — delete the mechanism clause, keep the number. No concluding clauses ("confirming...", "not better", "the lowest of all strategies" without a number). Aim for 1–2 bullets; delete any bullet that doesn't directly prove the lead-in.

**Mechanism explanations must stay conceptual, not implementation-level.** The lead-in explains *why* using a general mechanism (e.g., "the prompt splits selection into a semantic-classification step and a mechanical lookup step, and the model skips the second step") — not by enumerating the actual implementation logic (every branch of a decision tree, every rule in a prompt, quoted code). A GenAI/RAG-background interviewer will never read the underlying script; the lead-in must be understandable without it. This rule applies to Decision lead-ins as well.

No ASCII diagrams. No `**Conclusion:**` labels. When rewriting an existing report that contains ASCII diagrams in this section, remove the diagram and promote the `**Conclusion:**` text that followed it into the lead-in sentence.

Use `###` sub-headings when the section covers multiple independent findings. Each sub-heading must be phrased as a question, not a statement.

**What belongs here vs. in Decision:**
- Observations = what the data reveals
- Decision = what was chosen and why

---

### Decision

**Purpose:** Show engineering judgment — what was chosen and why.

**Structure:** Same as Observations. The lead-in states the winner and the reason in one sentence. Bullets add decision-critical data not captured in the lead-in — key trade-offs or constraints. Alternatives' metrics are in Results tables; do not repeat them here.

```markdown
### Which X?

`winner` is selected — one sentence stating why.

- Winner metric: value.
```

Use `###` sub-headings when the section answers multiple independent questions. Each sub-heading must be phrased as a question.

**Bullets = numbers only.** The same rule applies here as in Observations: every bullet must contain at least one concrete number or measurement. Delete bullets with no number. Delete mechanism clauses from bullets that already have a number.

**Rules:**
- No ASCII diagrams or decision trees
- Do not repeat pipeline background here — that belongs in Task Context
- Do not repeat findings from Observations — reference them, don't restate

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
| **✅ INTEGRATED** | 1 sentence: what was swapped out and what replaced it + file reference · `### Impact` (optional — only add if key metrics are not already stated in Observations and Decision) |
| **🚫 SUPERSEDED** | `### What replaced it` · `### Why the decision was made` · `### Transferable findings` |
| **⏳ NOT INTEGRATED** | `### Current state` · `### What is blocking` |
| **🔬 PROPOSED** | `### Supporting data` · `### Validation needed` |

Content rules by status:

- **✅ INTEGRATED:** Do not include a "What triggered" section — the trigger is already covered by Observations and Decision. "What changed" is 1 conceptual sentence (no API syntax, no filter parameter values); include file name and function name as a brief reference. Sub-headings use `###` not `####`.
- **🚫 SUPERSEDED:** Do not include "What triggered" — same reason. State what replaced it and why, then list transferable findings explicitly.

Example for ✅ INTEGRATED (with Impact — use only when key metrics are not already in Observations/Decision):

```markdown
## Pipeline Integration Status ✅ INTEGRATED

Tavily citation-expansion replaced by direct OpenAlex BM25 search with quality filters in `paper_scraping.py` → `fetch_candidate_papers()`.

### Impact

- Zero-candidate failure eliminated across all five tested domains.
- Total relevant papers: 53 → 64 (+21 papers).
- Pipeline is now fully deterministic; no paid external API required.
```

Example for ✅ INTEGRATED (without Impact — when Observations and Decision already state the key metrics):

```markdown
## Pipeline Integration Status ✅ INTEGRATED

Hybrid BM25 retrieval with query expansion replaced dense-only retrieval in `paper_tools.py`. The `QueryFusionRetriever` in `summary_generation.py` generates 4 query variants, merges results using Reciprocal Rank Fusion (RRF), and passes the final top-5 chunks to the summarization LLM.
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
| Observations | Question heading → one-sentence lead-in (finding + reason) → data-only bullets |
| Decision | Start directly from the decision question; no pipeline background |
| Pipeline Integration Status | State what happened and what the data shows — no recommendations |

### Blog-style rules (all text sections)
- First sentence of each paragraph = the conclusion or main point
- Short sentences. Split long ones.
- **Active voice, no first person** — use subject-verb-object without "we" or "I". "The model achieves F1=0.974" is active voice. "It was found that..." is passive — avoid it. Use "I" only for personal decisions or manual observations that cannot be attributed to the experiment itself.
- Contractions are fine (it's, don't, can't)
- Do not restate what a diagram already shows
- No internal experiment codes in narrative (Round 1, Method A, E14) — use descriptive names
- **Jargon rule — standard IR/NLP terms vs non-standard phrasing:**
  - Standard IR/NLP terminology is expected by the target audience (GenAI & RAG practitioners) and requires no definition: IDF, BM25, RRF, embedding, Recall@k, nDCG, cross-encoder reranker, sparse retrieval, dense retrieval, top-k, query expansion, hybrid search, RAGAS.
  - Non-standard academic phrasing must be replaced with direct language. Common violations and their replacements:

  | Avoid | Use instead |
  |---|---|
  | "discriminating signal" | "strong match signal" or "high weight" |
  | "semantic averaging" | "general semantic similarity score" |
  | "semantically adjacent" | "topically nearby but not exact" |
  | "stabilizes the retrieval pool" | "always retrieves chunks with the exact keywords first" |
  | "confabulated claims" | "invented facts" or "made-up information" |
  | "surface chunks" | "retrieve chunks" or "bring in new chunks" |
  | "the full stack" (as shorthand) | spell out the config name on first use |

  - Undefined abbreviations: any abbreviation that is not in the standard IR/NLP list above must be spelled out on first use with the abbreviation in parentheses, e.g. "Reciprocal Rank Fusion (RRF)".

- **American English spelling** — use American spelling throughout. Common British→American pairs: artifact (not artefact), behavior (not behaviour), favor (not favour), characterize (not characterise), stabilize (not stabilise), generalize (not generalise), realize (not realise), optimize (not optimise), normalize (not normalise), serialize (not serialise), summarize (not summarise), recognize (not recognise).
- **Tech blog sentence style — one idea per sentence:** applies to every sentence in all body text (bullets, prose, captions, post-table conclusions). Exempt: headings and sub-headings, which are descriptive labels, not sentences. Rule: if a sentence contains a subordinate clause (`which`, `where`, `even though`, `because`) that can be split into a separate sentence, split it. The goal is that each sentence is immediately understood on first read — no re-reading required.

  | ❌ Paper-style | ✅ Tech blog |
  |---|---|
  | "When the only code example in the prompt is the layout lookup block (which has no null guards), gemma3:4b treats the absence of null guards as a style signal and omits them — even when the text instruction says to guard against None." | "gemma3:4b copies the style of the code example — including what's missing. The layout example has no null guard. So the model omits null guards too, even when the text says otherwise." |

- **One topic per paragraph:** If a paragraph contains more than one distinct idea or topic, split it into bullet points. Each paragraph covers one topic only. Do not group different ideas into a single paragraph.

- **Number representation for improvements:**
  - Metric improvements (Recall@5, nDCG, F1, etc.): use **absolute values** — write "+0.195 Recall@5", not "+47%". Percentages make small absolute gains look large when the baseline is low.
  - Latency comparisons between methods: use **multipliers** — write "15× faster than miniCOIL". Raw numbers in parentheses are required alongside the multiplier (e.g. "15× faster (13.5s vs 204s)").
  - Latency overhead of adding a component: use **absolute time** — write "+1,057s over 100 samples (+10.6s per query)", not "+20%".
  - Never use percentages for metric improvements in experiment reports.

- **Table bolding — ML paper convention:** In every results table, bold the best value in each column. For metrics where higher is better (Recall, nDCG, Faithfulness, etc.), bold the maximum. For latency, bold the minimum (fastest). When two or more configs tie for the best value, bold all tied values.

- **Cross-experiment number references:** When two experiments use different evaluation setups (different collection strategies, different sample sizes, different code paths), do not cite a metric value from one experiment as the baseline in the other. Reference the config name or method name instead (e.g. "the `dense_only` baseline config from Experiment 11", not "Recall@5 = 0.61 from Experiment 11"). The same config can produce different numbers under different setups.

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
- **Hypothetical future scenarios:** ❌ "If the downstream task changes to X, then Y would apply" ❌ "Should the pipeline evolve to support Z, this approach should be reconsidered." Reports document what was measured. Scenarios not tested in this experiment do not belong in any section.

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

Each entry heading must include the experiment date:

```
#### Experiment N — <Title>   (YYYY-MM-DD)
```

- **Date source:** use the date the experiment was run or completed — from the PoC record header or the experiment file's metadata. Do not use the git commit date of a later restructure.
- **Format:** `YYYY-MM-DD` in parentheses, separated from the title by three spaces.
- **One date per entry:** if an experiment ran over multiple days, use the completion date.

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
- **Internal consistency:** Numbers cited in Solution, Result, Observations, and Decision must match the values in the Full Experimental Results tables of the same report — not from pre-experiment estimates or informal observations made outside the experiment. This rule does not apply to Problem, which must contain no numbers from this report at all (see the Problem rules under Summary).
- **Honest reporting:** If a method failed, document the failure and the root cause — this demonstrates diagnostic ability
- **No fabrication:** Do not infer results not present in the source data
- **Stale ✅:** If a pipeline configuration has changed since the experiment, update or remove the ✅ marker and note what changed

---

## Review Checklist (For AI Agents)

Before finalizing any experiment report, go through every section explicitly in order. Do not skip sections because they were not discussed in context — each checkbox must be verified independently against the rules in this guide.

| Section | Check |
|---|---|
| **Task Context** | Heading hierarchy correct (`##` → `###`)? Tech blog sentence style applied to all body text? Headings and sub-headings are exempt. |
| **Summary** | Tech blog sentence style per sentence? No internal experiment codes (Path B, E14, Method A)? Problem bullet is pipeline-level (no API details)? Problem bullet contains no "this fork"/"my implementation" clause and no outcome-asserting language ("has no guaranteed support," "is unreliable," "will fail") even without a number? |
| **Experiment Setup** | Hardware sub-section removed? `✅` marked on all current-pipeline rows and columns? All metrics defined? |
| **Full Experimental Results** | `Conclusion` removed from Purpose/Expected block? `**Conclusion:**` present after every sub-experiment table? Tech blog sentence style in Conclusion line? |
| **Observations** | `###` sub-headings (not `####`)? Each sub-heading is a question? Lead-in is one sentence only (em dash if two clauses needed)? Lead-in states the mechanism **at a conceptual level, not implementation logic**? Bullets carry data only, not re-explanation of lead-in? Second bullet only if it covers a genuinely different case? No ASCII diagrams present? No future speculation? Tech blog sentence style in all body text? Standard IR/NLP terms used freely; non-standard academic phrasing replaced? |
| **Decision** | `###` sub-headings where needed? Each sub-heading is a question? Lead-in sentence states the winner directly? Bullets add decision-critical data not already in the lead-in? No alternative metrics repeated from Results tables? No pipeline background restated (belongs in Task Context)? No findings from Observations restated? No future speculation? |
| **Numbers** | Metric improvements expressed as absolute values (+0.195), not percentages (+47%)? Latency comparisons use multipliers (15×) with raw numbers in parentheses? Best value in each table column is bolded? Cross-experiment number references use config name, not metric value? |
| **Pipeline Integration Status** | Badge inline in heading (`## Pipeline Integration Status ✅ INTEGRATED`)? `###` sub-headings (not `####`)? No "What triggered" section? "What changed" is 1 conceptual sentence with no API syntax? |
| **Experiment scope** | Does every metric, comparison, and conclusion mentioned anywhere in the report have corresponding data in Full Experimental Results? If log or script evidence is missing for any item, omit it from the report and list the omitted items in the completion summary for the user to verify. |
| **Paragraph content** | Does any paragraph contain more than one distinct idea or topic? If yes, split into bullet points. Each paragraph covers one topic only. |
| **Entire file** | No `**Conclusion.**` (period) — must be `**Conclusion:**` (colon)? No "production" — must be "pipeline"? American English spelling throughout? No heading level skipped (`##` → `####` not allowed)? |

**Rule:** Every row must be verified. Skipping a section because it was not part of the current discussion is not acceptable.
