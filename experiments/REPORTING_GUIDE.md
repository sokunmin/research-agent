# Research Agent: Experiment Reporting Guide (Interview-Ready)

## Core Objective
This directory documents the qualitative and quantitative analyses of the system's core components. The golden rule is: **Enable an interviewer (GenAI & RAG Expert) to grasp your engineering depth within 2 minutes via a Summary, while providing full experimental data for deep-dive verification.**

---

## Standard Report Structure

### 1. Semantic Title
Reflect the **AI Task Type** and the **Optimization Goal**. Avoid internal project codes.
*   **Good:** `Optimizing_Retrieval_Precision_via_Two_Stage_Reranking.md`

### 2. Summary (The 3-Line Style)
Place this at the top. **CRITICAL: Do not use internal experiment codes (e.g., E14, Path B) here.** Use functional descriptions.
*   **Problem:** The specific AI failure mode or bottleneck observed.
*   **Solution:** The high-level engineering intervention.
*   **Result:** Quantifiable improvements (e.g., F1 Score, Success Rate).

### 3. Transparency & Traceability
Explicitly list the source materials to prove the experiment is real:
*   **Test Script:** Path to the `.py` file.
*   **Raw Data:** Path to the `.json` or `.log` file.
*   **Hardware:** Execution environment (e.g., MacBook M1 / Ollama / Local).

### 4. Task Context
A brief description of where this experiment fits within the Research Agent workflow.

### 5. Strategy & Parameter Definitions
Before showing tables, define the terms used (e.g., what "Strict" vs. "Loose" prompting means in this specific context). This enables the reader to understand the tables without scrolling back.

### 6. Full Experimental Results (DO NOT DELETE)
**MANDATORY: Retain all original data tables and experiment logs.**
*   The Summary is for quick reading, but the full tables are required for evidence.
*   Ensure table headers are self-explanatory (e.g., use `Stage-1 (Embedding)` instead of `S1`).
*   The report should allow an interviewer to see exactly which experiments were performed and their specific outcomes.

### 7. Observations
Document your personal insights and non-intuitive findings derived from the data.
*   *Note: Use "Observations" as the heading, avoiding casual terms like "Aha! Moments".*

---

## Workflow for Updating Reports (For AI Agents/Developers)

When refactoring or updating an existing report, you MUST follow these steps:
1.  **Detailed Reading:** Thoroughly read the original report. Identify all key data points, tables, and specific configuration details.
2.  **Preservation Principle:** Ensure NO important information is deleted. The goal is to rearrange or rephrase for clarity, not to reduce the evidence.
3.  **Propose Direction:** Before modifying the file, communicate the intended direction of the update to the user.
4.  **Provide Diff:** Provide a "Before vs. After" analysis (or git diff) for the user to review.
5.  **Execute:** Only apply changes after the user has approved the proposal and diff.

---

## Technical Keyword Mapping (Terminology Alignment)
Align your descriptions with industry-standard terms:
*   Search Evaluation -> **Data Source Benchmarking / Retrieval Quality**
*   Filtering -> **Reranking / Multi-stage Filtering**
*   JSON Control -> **Constrained Decoding / Grammar Enforcement**
*   ReAct Optimization -> **Agent Steering / Instruction Following**

---

## Tone and Voice (Personal Project Style)
This is a **personal side project**. To ensure a natural and professional tone:
1. **Avoid "We":** Do not use "We" when describing actions or findings (e.g., avoid "We compared four architectures").
2. **Objective Description:** Prefer passive voice or objective phrasing to focus on the data (e.g., "Four architecture types were compared").
3. **Use of "I":** Only use "I" when necessary to express personal decisions or specific manual observations.

---

## Pipeline Integration Status
The final section of the report must explicitly state whether the experimental findings have been integrated into the project's main pipeline.
*   **Avoid "Production":** Since this is a personal project, use "Pipeline" or "System" instead of "Production".
*   **Integration Status:** Clearly mark as **[INTEGRATED]** or **[PROPOSED]** and describe which part of the source code now utilizes these findings.

---

## Fact-Check & Integrity Standards
1.  **Data Consistency:** Metrics must match raw JSON logs.
2.  **Honest Reporting:** If a model variant failed, document the failure. It demonstrates your ability to diagnose and design architectural workarounds.
3.  **Self-Contained:** Each report must be understandable on its own without requiring the reader to open other files.
