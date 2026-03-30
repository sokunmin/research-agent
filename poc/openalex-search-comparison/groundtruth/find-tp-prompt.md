# Task: Collect 40–60 Candidate Papers on Attention Mechanism in Transformer Models

## Context

You are Stage 1 of a two-stage pipeline for building a research benchmark dataset.

**Your job is collection, not judgment.**

A separate, more thorough AI agent (Stage 2) will read the full PDF of each
paper you collect and make the final relevance decision. Your goal is to
cast a wide enough net so that Stage 2 has good material to work with.

Research query: **"attention mechanism in transformer models"**

---

## Your Task

Search the web and collect **40–60 candidate papers** (target: 60, minimum: 40)
that pass the pre-screening filter described below.

- **Target**: 60 papers
- **Minimum acceptable**: 40 papers
- If all search strategies are exhausted and the count is ≥ 40, stop and report
  the final count at the end of the output file as a top-level `"collection_note"` field.
- If fewer than 40 papers are found after exhausting all strategies, also report
  this clearly in `"collection_note"`.

Stop searching once you have 60 candidates. Do not over-think relevance —
when in doubt, include the paper. It is better to include a borderline paper
than to miss a genuinely relevant one.

---

## Checkpoint / Resume Instructions

**Before searching**, read the output file if it already exists:
`/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/poc/openalex-search-comparison/candidates-web.json`

- If the file exists: load it, count existing entries, collect only the
  remaining papers needed to reach 60. Use existing titles to avoid duplicates.
- If the file does not exist: start fresh.

**While searching**, follow this strictly sequential loop — do not attempt
to run multiple searches in parallel:

```
for each search query:
    1. Run one WebSearch
    2. For each result that passes pre-screening:
         a. Read candidates-web.json (get current array)
         b. Check title is not already in the array
         c. Append new entry
         d. Write full array back to file
    3. If total collected >= 60: stop
```

Writing after each confirmed candidate (read → append → write) ensures
the file is always consistent and a new session can safely resume from it.

---

## Filters

Filters are divided into two categories: **hard filters** and **soft filters**.

### Hard Filters (Always Exclude)

Exclude a paper immediately — without further consideration — if **either** of
the following is true:

1. **Year < 2023.** The existing dataset already covers pre-2023 work. This is
   an absolute cutoff, not a proxy for relevance. A highly relevant 2022 paper
   would still be excluded here.
2. **No ArXiv ID and no direct PDF URL.** The downstream pipeline
   (`download_arxiv.py`) requires either an `arxiv_id` to download the PDF, or
   a direct PDF download URL in the `pdf_url` field. If a paper has neither,
   it cannot be processed and must be skipped.

> **Note on the year cutoff:** Do not treat borderline 2023 papers as lower
> priority simply because they are near the cutoff boundary. A paper from early
> 2023 is just as valid as one from 2025 if it passes all other filters.

### Soft Filter (When in Doubt, Include)

**Topic relevance pre-screening** — include a paper if its abstract/title
suggests the paper is about transformers or attention in a substantive way —
i.e., transformers/attention are not just used as a black-box tool, but appear
to be part of what the paper is actually discussing.

Soft-exclude only if clearly obvious:
- The paper is purely about medical diagnosis, healthcare policy, or clinical
  decision-making with no architectural contribution
- The paper is purely about object detection (YOLO variants, etc.) and
  attention is not mentioned in the abstract at all
- The paper is clearly about agriculture, finance, social science, or other
  domains where transformers appear only as an applied tool

If you are unsure about topic relevance → **include it**.

---

## ArXiv ID Requirement

Papers **must** have either an `arxiv_id` or a direct PDF URL to be included.
Apply the following priority rules:

1. **Prioritise papers that have an ArXiv version** — prefer these whenever
   available.
2. A paper **without** an `arxiv_id` may still be included **only if** a
   direct PDF download URL is available. In this case, set `arxiv_id` to
   `null` and record the direct PDF URL in the optional `pdf_url` field.
3. If a paper has **neither** an `arxiv_id` **nor** a direct PDF download URL,
   **skip the paper entirely** (this is a hard filter — see above).

---

## Abstract Completeness Requirement

Web search snippets are often truncated. After a paper passes pre-screening:

1. Check whether the abstract looks complete (not cut off mid-sentence).
2. If the abstract appears truncated, use `WebFetch` on the paper's ArXiv
   abstract page (`https://arxiv.org/abs/{arxiv_id}`) to retrieve the full
   abstract before writing the entry.
3. Only write the entry once a reasonably complete abstract is confirmed.

---

## Search Strategy

Run searches across these 5 dimensions to ensure diversity. Use ArXiv,
Semantic Scholar, Papers With Code as primary sources.

| Dimension | Example queries |
|-----------|----------------|
| Core mechanism | "self-attention mechanism transformer", "multi-head attention" |
| Efficiency variants | "efficient attention", "flash attention", "sparse attention", "linear attention" |
| Theory & analysis | "attention interpretability transformer", "attention head analysis" |
| Motivated alternatives | "Mamba state space model", "RWKV", "attention-free transformer" |
| Surveys & foundations | "survey attention transformer", "transformer architecture" |

To find recent papers, explicitly append the year to your queries, e.g.:
- `"attention transformer 2025 arxiv"`
- `"efficient attention 2024 site:arxiv.org"`
- Search ArXiv sorted by submission date (newest first)
- On Semantic Scholar, apply the "Publication Date" filter to 2023–2026

Do not rely solely on training memory — actively search for papers
published in 2024 and 2025 that may not yet be widely cited.

### Minimum Papers Per Dimension (Hard Requirement)

Each dimension **must** contribute at least 8 papers. Track per-dimension
counts as you go. Do not stop searching a dimension until it has contributed
≥ 8 papers (unless all reasonable search queries for that dimension are
exhausted).

| Dimension | Minimum papers |
|-----------|---------------|
| Core mechanism | 8 |
| Efficiency variants | 8 |
| Theory & analysis | 8 |
| Motivated alternatives | 8 |
| Surveys & foundations | 8 |

Total minimum guaranteed by dimension floors = 40. The remaining papers (up
to 60) can come from any dimension. If a dimension cannot reach 8 despite
exhausting all its queries, note which dimension fell short in
`"collection_note"` and compensate by collecting additional papers from
another dimension.

---

## Papers Already in Dataset (Skip These)

Skip any paper whose title closely matches any title in the list below.

**Matching rule:** Match by **normalised title** — convert to lowercase,
collapse all whitespace to a single space, and ignore punctuation differences
(e.g., hyphens, colons, apostrophes, quotation marks). Matching is
case-insensitive. If the agent finds a paper that is clearly the same work as
an excluded title (even with minor title differences between the arXiv
preprint version and the published conference version), skip it.

**When unsure:** If you are not certain whether a candidate matches an
excluded title, **prefer to include it**. A false negative (wrongly excluding
a valid paper) is more costly at this stage than a false positive (including
a paper that is later rejected by Stage 2).

```
Attention Is All You Need
YOLOv10: Real-Time End-to-End Object Detection
Lost in the Middle: How Language Models Use Long Contexts
Ethical and regulatory challenges of AI technologies in healthcare: A narrative review
The Role of AI in Hospitals and Clinics: Transforming Healthcare in the 21st Century
A Review on Large Language Models: Architectures, Applications, Taxonomies, Open Issues and Challenges
GPT (Generative Pre-Trained Transformer)— A Comprehensive Review on Enabling Technologies, Potential Applications, Emerging Challenges, and Future Directions
YOLOv11: An Overview of the Key Architectural Enhancements
A Survey on In-context Learning
A review of graph neural networks: concepts, architectures, techniques, challenges, datasets, applications, and future directions
Vision Mamba: Efficient Visual Representation Learning with Bidirectional State Space Model
Recurrent Neural Networks: A Comprehensive Review of Architectures, Variants, and Applications
Generative AI in healthcare: an implementation science informed translational path on application, integration and governance
VMamba: Visual State Space Model
A pathology foundation model for cancer diagnosis and prognosis prediction
Graph of Thoughts: Solving Elaborate Problems with Large Language Models
YOLOv9: Learning What You Want to Learn Using Programmable Gradient Information
Federated learning for medical image analysis: A survey
Boltz-1 Democratizing Biomolecular Interaction Modeling
Bias in medical AI: Implications for clinical decision-making
Artificial intelligence for geoscience: Progress, challenges, and perspectives
Artificial Intelligence for Predictive Maintenance Applications: Key Components, Trustworthiness, and Future Trends
Large Language Models in Healthcare and Medical Domain: A Review
The application of large language models in medicine: A scoping review
Dissociating language and thought in large language models
Design of target specific peptide inhibitors using generative deep learning and molecular dynamics simulations
A critical review of RNN and LSTM variants in hydrological time series predictions
The ethics of ChatGPT in medicine and healthcare: a systematic review on Large Language Models (LLMs)
ChangeMamba: Remote Sensing Change Detection With Spatiotemporal State Space Model
Large language models could change the future of behavioral healthcare: a proposal for responsible development and evaluation
The YOLO Framework: A Comprehensive Review of Evolution, Applications, and Benchmarks in Object Detection
Review of battery state estimation methods for electric vehicles - Part I: SOC estimation
Deep learning for water quality
Gemma: Open Models Based on Gemini Research and Technology
Trends in Photovoltaic Applications 2024
A Comprehensive Systematic Review of YOLO for Medical Object Detection (2018 to 2023)
Visual attention methods in deep learning: An in-depth survey
Respecting causality for training physics-informed neural networks
A Review of Machine Learning and Deep Learning for Object Detection, Semantic Segmentation, and Human Action Recognition in Machine and Robotic Vision
DA-TransUNet: integrating spatial and channel dual attention with transformer U-net for medical image segmentation
A critical assessment of using ChatGPT for extracting structured data from clinical notes
MedSegDiff-V2: Diffusion-Based Medical Image Segmentation with Transformer
Large Language Models: A Survey
DeepSeek-V3 Technical Report
VM-UNet: Vision Mamba UNet for Medical Image Segmentation
Use of Artificial Intelligence in Improving Outcomes in Heart Disease: A Scientific Statement From the American Heart Association
Ethical Challenges and Solutions of Generative AI: An Interdisciplinary Perspective
A Systematic Review and Meta-Analysis of Artificial Intelligence Tools in Medicine and Healthcare: Applications, Considerations, Limitations, Motivation and Challenges
Remote Sensing Object Detection in the Deep Learning Era—A Review
Revolutionizing Cyber Threat Detection With Large Language Models: A Privacy-Preserving BERT-Based Lightweight Model for IoT/IIoT Devices
Generative AI for Transformative Healthcare: A Comprehensive Study of Emerging Models, Applications, Case Studies, and Limitations
Omni-Kernel Network for Image Restoration
Advances in Medical Image Segmentation: A Comprehensive Review of Traditional, Deep Learning and Hybrid Approaches
A generalist vision–language foundation model for diverse biomedical tasks
A Systematic Survey of Prompt Engineering in Large Language Models: Techniques and Applications
Privacy and Security Concerns in Generative AI: A Comprehensive Survey
BioMistral: A Collection of Open-Source Pretrained Large Language Models for Medical Domains
MM-LLMs: Recent Advances in MultiModal Large Language Models
Opportunities and Challenges for Machine Learning-Assisted Enzyme Engineering
A Review of Current Trends, Techniques, and Challenges in Large Language Models (LLMs)
CIFAKE: Image Classification and Explainable Identification of AI-Generated Synthetic Images
Artificial intelligence in digital pathology: a systematic review and meta-analysis of diagnostic test accuracy
Machine learning for antimicrobial peptide identification and design
A Survey on Intelligent Internet of Things: Applications, Security, Privacy, and Future Directions
Artificial Intelligence Alone Will Not Democratise Education: On Educational Inequality, Techno-Solutionism and Inclusive Tools
A Comprehensive Review and Analysis of the Allocation of Electric Vehicle Charging Stations in Distribution Networks
Employing deep learning and transfer learning for accurate brain tumor detection
Autonomous Vehicles: Evolution of Artificial Intelligence and the Current Industry Landscape
A Comprehensive Review on Synergy of Multi-Modal Data and AI Technologies in Medical Diagnosis
Change Detection Methods for Remote Sensing in the Last Decade: A Comprehensive Review
Drones in Precision Agriculture: A Comprehensive Review of Applications, Technologies, and Challenges
Inferring super-resolution tissue architecture by integrating spatial transcriptomics with histology
Synthetic data generation methods in healthcare: A review on open-source tools and methods
Machine learning-based energy management and power forecasting in grid-connected microgrids with multiple distributed energy sources
Large language models empowered agent-based modeling and simulation: a survey and perspectives
Quantum Computing for High-Energy Physics: State of the Art and Challenges
Scalable Parallel Algorithm for Graph Neural Network Interatomic Potentials in Molecular Dynamics Simulations
Fine-tuning protein language models boosts predictions across diverse tasks
Bad Actor, Good Advisor: Exploring the Role of Large Language Models in Fake News Detection
Empowering ChatGPT with guidance mechanism in blended learning: effect of self-regulated learning, higher-order thinking skills, and knowledge construction
The current state of artificial intelligence generative language models is more creative than humans on divergent thinking tasks
FusionMamba: dynamic feature enhancement for multimodal image fusion with Mamba
Automatic speech recognition using advanced deep learning approaches: A survey
Lightweight transformer image feature extraction network
A Comprehensive Survey of Deep Transfer Learning for Anomaly Detection in Industrial Time Series: Methods, Applications, and Directions
DeepSeekMoE: Towards Ultimate Expert Specialization in Mixture-of-Experts Language Models
An Improved YOLOv8 to Detect Moving Objects
AI and 6G Into the Metaverse: Fundamentals, Challenges and Future Research Trends
The Challenges of Machine Learning: A Critical Review
Foundation Models for Time Series Analysis: A Tutorial and Survey
AI deception: A survey of examples, risks, and potential solutions
A Survey on Visual Mamba
Deep learning-based approaches for multi-omics data integration and analysis
From CNN to Transformer: A Review of Medical Image Segmentation Models
β-Variational autoencoders and transformers for reduced-order modelling of fluid flows
A review of large language models and autonomous agents in chemistry
Computational redesign of a hydrolase for nearly complete PET depolymerization at industrially relevant high-solids loading
```

---

## Output

Write results to:
`/Users/chunming/MyWorkSpace/agent_workspace/research-agent/dev/poc/openalex-search-comparison/candidates-web.json`

Write incrementally as described in the Checkpoint/Resume section above.

Use this JSON schema:

```json
[
  {
    "title": "Full paper title",
    "authors": ["Author A", "Author B"],
    "year": 2024,
    "venue": "NeurIPS / ICML / ICLR / ACL / arXiv / etc.",
    "arxiv_id": "2405.14135",
    "doi": "10.48550/arXiv.2405.14135",
    "url": "https://arxiv.org/abs/2405.14135",
    "pdf_url": null,
    "abstract": "Full abstract text.",
    "search_dimension": "Efficiency variants",
    "relevant": false,
    "reason": ""
  }
]
```

Field notes:
- `arxiv_id`: fill if available, otherwise `null` (papers with `null` here must have a direct PDF URL in `pdf_url`, or must be skipped — see ArXiv ID Requirement above)
- `pdf_url`: fill with a direct PDF download URL only for papers that have no `arxiv_id`; otherwise `null`
- `search_dimension`: one of "Core mechanism", "Efficiency variants", "Theory & analysis", "Motivated alternatives", "Surveys & foundations"
- `doi`: fill if available, otherwise `null`
- `relevant`: always `false` — Stage 2 will fill this
- `reason`: always `""` — Stage 2 will fill this
