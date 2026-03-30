## Ablation Study: Search Path Comparison — Tavily-Assisted vs. OpenAlex Standalone

### Abstract

This study evaluates whether the Tavily web-search dependency in the paper-discovery pipeline of a research-agent system can be replaced by direct OpenAlex API queries augmented with quality filters. Ten experiments across five research domains compare three OpenAlex search modalities (keyword, BM25, semantic), characterise Tavily's failure modes, determine an appropriate candidate pool size, and conduct a head-to-head pipeline comparison between the production path (Tavily-seeded citation expansion, Path A) and a proposed replacement (OpenAlex standalone with quality filters, Path B). Path A achieves the target of 10 or more relevant papers in only 2 of 5 domains and produces zero candidates for the flagship topic; Path B meets the target in 2 of 5 domains but retrieves candidates in all 5 domains and is fully deterministic. The results demonstrate that OpenAlex standalone is a viable and more reliable replacement for Tavily-assisted search, though both paths face challenges in narrow or ambiguous topic domains where strict relevance filtering reduces yield.

---

### 1. Introduction

The research-agent pipeline automatically discovers academic papers on a given topic, filters them for relevance, downloads PDFs, generates summaries, and produces presentation slides. In the original production system, paper discovery relies on Tavily web search to find ArXiv-related results, which are then matched to OpenAlex records and expanded via citation chains. This design introduces three concerns:

1. **External dependency**: Tavily is a paid third-party API whose availability, pricing, and behaviour are outside the project's control.
2. **Non-determinism**: Web search results vary across runs, making the pipeline non-reproducible.
3. **Indirect seeding**: Tavily returns web pages (blog posts, documentation sites) that must be title-matched into OpenAlex, introducing a lossy translation step.

This study asks three research questions:

- **RQ1**: What are the coverage and precision characteristics of OpenAlex's three search modalities (keyword, BM25, semantic) for academic paper discovery?
- **RQ2**: What are Tavily's specific failure modes when used as a seeding mechanism for OpenAlex?
- **RQ3**: Can a direct OpenAlex search path with quality filters (open access, citation count, recency) replace the Tavily-assisted path while meeting a target of at least 10 relevant papers per topic?

---

### 2. Experimental Setup

#### 2.1 Hardware Environment

All experiments are executed locally on an Apple MacBook with an M1 chip. All models (LLM and embedding) are served via Ollama, which leverages the M1's integrated GPU through Apple Metal. The M1 uses a unified memory architecture (UMA) in which CPU and GPU share the same memory pool. Reported wall-clock times should be interpreted as local Apple Silicon execution times.

#### 2.2 Relevance Filter (E14)

All experiments that require relevance filtering use the E14 two-stage configuration validated in the companion ablation study (see `ablation-study-relevant.md`). E14 comprises:

- **Stage 1**: nomic-embed-text embedding with cosine similarity threshold = 0.500, using title + abstract as input fields.
- **Stage 2**: qwen3.5:2b with Prompt-Strict, using title + abstract + keywords + topics + primary_topic + concepts as input fields. Stage 2 is invoked only for papers in the routing band [0.500, 0.610).

E14 achieves F1 = 0.974, Precision = 1.000, and Recall = 0.950 on a balanced 120-paper ground truth dataset. In this study, E14 is applied equally to both search paths as a common downstream filter; its classification performance is not under evaluation.

#### 2.3 Download Validation

A separate validation script (`extract-id.py`) confirms that papers passing the open-access status filter (`oa_status` in {diamond, gold, green}) are downloadable, achieving 5/5 successful downloads using a four-strategy fallback chain. Download reliability is not evaluated in this study.

#### 2.4 Evaluation Metric

The primary metric is the **relevant paper count** per topic after E14 filtering, with a target of **relevant >= 10**. Secondary metrics include candidate pool size, relevance rate (relevant / candidates), ArXiv presence rate, and citation counts.

#### 2.5 Topics

Five research topics spanning four domains are used to test generalisation:

| Label | Topic | Domain |
|---|---|---|
| RESEARCH_TOPIC | attention mechanism in transformer models | NLP / Deep Learning |
| TOPIC_Q | federated learning privacy preservation | Distributed Systems |
| TOPIC_R | reinforcement learning policy gradient optimization | Reinforcement Learning |
| TOPIC_S | convolutional neural network image recognition | Computer Vision |
| TOPIC_NEW | CRISPR gene editing therapeutic applications | Biomedical (non-ML) |

---

### 3. Search Method Characterisation (Exp 01--04)

Experiments 01 through 03 evaluate the three OpenAlex search modalities on the RESEARCH_TOPIC ("attention mechanism in transformer models") with `per_page=25` and E14 filtering. Experiment 04 examines cross-method overlap without filtering.

#### 3.1 Individual Method Results

**Keyword Search (Exp 01)** uses `Works().search_filter(title_and_abstract=...)`, which matches title and abstract fields with AND logic across query terms.

**BM25 Full-Text Search (Exp 02)** uses `Works().search(...)`, which applies BM25 relevance ranking across title, abstract, and full text.

**Semantic Search (Exp 03)** uses `Works().similar(...)`, which performs embedding-based similarity search without requiring keyword matches.

| Method | API Call | Candidates | Relevant | Relevance % | ArXiv | ArXiv % |
|---|---|---|---|---|---|---|
| Keyword Search (Exp 01) | `search_filter` | 25 | 15 | 60% | 3 | 12% |
| BM25 Full-Text (Exp 02) | `search` | 25 | 13 | 52% | 6 | 24% |
| Semantic Search (Exp 03) | `similar` | 25 | 17 | 68% | 9 | 36% |

Semantic search achieves the highest relevance rate (68%) and the highest ArXiv presence (36%). It also returns qualitatively different papers: titles such as "Attention Mechanism, Transformers, BERT, and GPT: Tutorial and Survey" and "A Multiscale Visualization of Attention in the Transformer Model" are topically precise, whereas keyword and BM25 methods return application-domain papers that happen to mention "attention mechanism" and "transformer" (e.g., damage detection models, time-series forecasters, medical image segmentation).

BM25 retrieves higher-cited papers on average (median citations in the hundreds) compared to semantic search (median in single digits), reflecting the BM25 tendency to surface well-established, heavily-cited works. Semantic search surfaces newer, more topically focused papers that may have fewer citations.

#### 3.2 Cross-Method Overlap (Exp 04)

Experiment 04 re-fetches all three methods and computes pairwise set overlaps:

| Comparison | Overlap |
|---|---|
| Keyword intersection BM25 (M1 intersection M2) | 18 papers |
| Keyword intersection Semantic (M1 intersection M3) | 0 papers |
| BM25 intersection Semantic (M2 intersection M3) | 0 papers |
| Semantic unique (M3 only) | 25 papers |
| Keyword/BM25 union (M1 union M2 only) | 32 papers |

The keyword and BM25 methods share 18 of 25 papers (72% overlap), indicating that BM25 largely subsumes keyword search for this query. The semantic method returns a completely disjoint set of 25 papers with zero overlap to either keyword or BM25 results. This confirms that semantic search accesses a fundamentally different region of the literature — papers that discuss attention mechanisms and transformers conceptually but may not contain the exact query terms in their title, abstract, or full text. The total unique paper count across all three methods is 57 (25 semantic + 32 keyword/BM25), demonstrating strong complementary coverage.

---

### 4. Tavily Dependency Analysis (Exp 05--07)

#### 4.1 Tavily Query Format Effects (Exp 05)

Experiment 05 compares two Tavily query formats for the RESEARCH_TOPIC:

- **Query A (bare)**: `"attention mechanism in transformer models"`
- **Query B (arxiv-prefix)**: `"arxiv papers about the state of the art of attention mechanism in transformer models"`

| Format | Academic Hits | Non-Academic Hits | Academic Hit Rate |
|---|---|---|---|
| Query A (bare) | 0 | 5 | 0% |
| Query B (arxiv-prefix) | 3 | 2 | 60% |

The bare query returns zero academic sources; all five results are blog posts and documentation pages (Medium, IBM, NVIDIA Developer, d2l.ai, Machine Learning Mastery). The arxiv-prefix format raises the academic hit rate to 60%, but two of the five results remain non-academic (a ResearchGate page and a Medium blog post). This demonstrates that Tavily's usefulness as an academic paper discovery tool is entirely dependent on prompt engineering, and even the best-case format fails to achieve full academic coverage.

#### 4.2 Seed Quality Comparison (Exp 06)

Experiment 06 compares the quality of papers obtained via two seeding strategies:

- **Method X**: Tavily (bare query) returns 5 titles, each title-matched to OpenAlex via `search_filter`.
- **Method Y**: Direct `Works().search(topic, per_page=5)`.

| Metric | Method X (Tavily + OpenAlex) | Method Y (OpenAlex Direct) |
|---|---|---|
| Papers found | 5 | 5 |
| Citation counts | [308, 686, 104, 572, 461] | [235, 6,507, 5,499, 12, 68] |
| Median citations | 461 | 235 |
| Max citations | 686 | 6,507 |
| Overlap | 0 papers | 0 papers |
| API calls | 6 (1 Tavily + 5 OpenAlex) | 1 |

The two methods return completely disjoint paper sets. Method X retrieves application-domain papers (3D medical image segmentation, brain mechanisms, saliency prediction, fault diagnosis) that are tangential to the query topic. Method Y retrieves the foundational "Attention Is All You Need" (6,507 citations) and other highly-cited transformer papers. Despite Method X having a higher median citation count, its papers are topically irrelevant — the title-matching step maps non-academic Tavily titles to the closest lexical match in OpenAlex, which is often a thematically unrelated paper. Method Y achieves comparable or superior quality with a single API call instead of six.

#### 4.3 Title Match Gap (Exp 07)

Experiment 07 uses the arxiv-prefix Tavily query and attempts to match each returned title to an OpenAlex record via `search_filter(title_and_abstract=title)`:

| Tavily Title | OpenAlex Match | Match Quality |
|---|---|---|
| An analysis of attention mechanisms and its variance in transformer | Exact match (cited: 2) | Correct |
| Nexus: Higher-Order Attention Mechanisms in Transformers | No match | Lost |
| Attention Is All You Need - arXiv | "Deep Learning for Natural Language Processing" (cited: 58) | Wrong paper |
| Coffee Time Papers: Attention Is All You Need | "Embracing Chinese Global Security Ambitions" (cited: 26) | Wrong paper |
| Selective Attention Improves Transformer - arXiv | No match | Lost |

Of five Tavily titles, only one (20%) produces a correct OpenAlex match. Two titles return no match at all, and two titles match to completely wrong papers. The title "Attention Is All You Need - arXiv" — one of the most cited papers in machine learning — fails to match because the suffix "- arXiv" disrupts the `search_filter` AND logic, and the query instead matches an unrelated paper. This reveals a critical brittleness in the Tavily-to-OpenAlex translation: web-scraped titles contain suffixes, prefixes, and formatting artefacts that cause `search_filter` to return incorrect or empty results.

#### 4.4 Synthesis: Tavily Failure Modes

The three experiments identify four distinct failure modes:

1. **Non-academic results**: Even with an optimised query prefix, 40% of Tavily results are non-academic (Exp 05).
2. **Title mismatch**: Web-scraped titles contain artefacts (e.g., "- arXiv", blog post prefixes) that cause OpenAlex `search_filter` to return wrong papers or no match (Exp 07: 80% failure rate).
3. **Topical drift**: When Tavily returns non-academic titles, `search_filter` maps them to the closest lexical match in OpenAlex, yielding papers unrelated to the query (Exp 06, Exp 07).
4. **Redundant cost**: Tavily requires a paid API call plus N additional OpenAlex calls, while direct OpenAlex search achieves equal or better results with a single call (Exp 06).

---

### 5. Candidate Pool Sizing (Exp 08)

Experiment 08 sweeps the `per_page` parameter for Path B on the RESEARCH_TOPIC, using the full Path B filter stack (open access, `oa_status` in {diamond, gold, green}, `cited_by_count > 50`, `publication_year > 2023`, no retractions, sorted by citation count descending) with E14 relevance filtering.

| per_page | Candidates | Relevant | Relevance % |
|---|---|---|---|
| 25 | 25 | 1 | 4% |
| 50 | 50 | 3 | 6% |
| 100 | 100 | 4 | 4% |
| 150 | 150 | 4 | 3% |

Relevant paper count plateaus at 4 between `per_page=100` and `per_page=150`, indicating that the pool of high-cited, open-access, recent papers relevant to this specific topic is exhausted by 100 candidates. The low absolute relevance rates (3--6%) reflect the stringent quality filters: `cited_by_count > 50` and `publication_year > 2023` together constrain the pool to high-impact recent papers, many of which use transformers as a tool in application domains (medical imaging, time-series forecasting) rather than studying attention mechanisms per se. E14 correctly rejects these application papers.

The selection of `PATH_B_PER_PAGE = 100` is justified on two grounds: (a) it captures the full relevant pool (no additional relevant papers appear at 150), and (b) it provides a 25x candidate-to-relevant ratio that accommodates topics with higher base relevance rates, as confirmed by the five-domain results in Section 6.

---

### 6. Pipeline Comparison (Exp 09 vs. Exp 10)

#### 6.1 Path A: Production Baseline (Exp 09)

Path A implements the current production pipeline:

```
Tavily("arxiv papers about the state of the art of {topic}", max_results=2)
  -> OpenAlex search_filter(title_and_abstract=title) per Tavily result  [1 seed per result]
  -> OpenAlex filter(cites=seed_id, per_page=50)  [citing papers as candidates]
  -> E14 relevance filter
```

**Part 1 — Non-determinism test (3 runs, RESEARCH_TOPIC)**

| Run | Seeds Found | Candidates | Relevant | Meets Target (>=10) |
|---|---|---|---|---|
| Run 1 | 1 | 0 | 0 | No |
| Run 2 | 1 | 0 | 0 | No |
| Run 3 | 1 | 0 | 0 | No |

All three runs returned the same seed paper ("Local Attention Mechanism: Boosting the Transformer Architecture") and zero citing candidates. The delta across runs is 0, indicating that Tavily returned identical results across the three runs — likely due to server-side caching. The structural failure is that the single seed paper has zero citing works in OpenAlex that pass the filter, producing an empty candidate pool regardless of Tavily's behaviour.

**Part 2 — Five-domain results (1 run per topic)**

| Topic | Domain | Seeds | Candidates | Relevant | Meets Target |
|---|---|---|---|---|---|
| RESEARCH_TOPIC | NLP / DL | 1 | 0 | 0 | No |
| TOPIC_Q | Distributed Systems | 2 | 6 | 4 | No |
| TOPIC_R | Reinforcement Learning | 2 | 4 | 1 | No |
| TOPIC_S | Computer Vision | 2 | 52 | 11 | Yes |
| TOPIC_NEW | Biomedical | 1 | 50 | 37 | Yes |

Path A meets the target (relevant >= 10) in **2 of 5 topics**. The RESEARCH_TOPIC — the project's primary use case — yields zero candidates due to the seed paper having no citing works. TOPIC_Q and TOPIC_R fail because Tavily finds only 1--2 seeds whose citation networks are small (4--6 citing papers). An additional failure is observed for TOPIC_NEW, where one of the two Tavily seeds causes an OpenAlex API error because the Tavily-scraped title contains web-page formatting artefacts (truncation and a "- arXiv" suffix: "Gene and RNA Editing: Methods, Enabling ... - arXiv"), which generates an invalid query parameter. This is the same title-artefact failure mode documented in Exp 07, reducing the effective seed count to 1.

#### 6.2 Path B: Replacement Path (Exp 10)

Path B implements the proposed replacement:

```
OpenAlex search(topic) + is_oa + oa_status in {diamond,gold,green}
  + cited_by_count > 50 + publication_year > 2023 + type != retraction
  + sort(cited_by_count desc) + per_page=100
  -> E14 relevance filter
```

| Topic | Domain | Candidates | Relevant | Meets Target |
|---|---|---|---|---|
| RESEARCH_TOPIC | NLP / DL | 100 | 4 | No |
| TOPIC_Q | Distributed Systems | 92 | 12 | Yes |
| TOPIC_R | Reinforcement Learning | 100 | 2 | No |
| TOPIC_S | Computer Vision | 100 | 6 | No |
| TOPIC_NEW | Biomedical | 100 | 40 | Yes |

Path B meets the target in **2 of 5 topics**. Critically, it retrieves candidates for all five topics (92--100 per topic), eliminating the zero-candidate failure observed in Path A. TOPIC_Q improves from 4 relevant (Path A) to 12 relevant (Path B), crossing the target threshold. TOPIC_NEW performs strongly in both paths (37 vs. 40 relevant), confirming that the biomedical domain has abundant high-cited, open-access, recent literature on CRISPR.

#### 6.3 Head-to-Head Comparison

| Topic | Path A Candidates | Path A Relevant | Path B Candidates | Path B Relevant | Winner |
|---|---|---|---|---|---|
| RESEARCH_TOPIC | 0 | 0 | 100 | 4 | Path B |
| TOPIC_Q | 6 | 4 | 92 | 12 | Path B |
| TOPIC_R | 4 | 1 | 100 | 2 | Path B |
| TOPIC_S | 52 | 11 | 100 | 6 | Path A |
| TOPIC_NEW | 50 | 37 | 100 | 40 | Path B |
| **Total** | **112** | **53** | **492** | **64** | **Path B** |
| **Topics >= 10** | | **2/5** | | **2/5** | **Tie** |

| Property | Path A | Path B |
|---|---|---|
| Topics with >= 10 relevant | 2/5 | 2/5 |
| Total relevant papers | 53 | 64 |
| Topics with 0 candidates | 1/5 (RESEARCH_TOPIC) | 0/5 |
| Deterministic | No (Tavily-dependent) | Yes |
| External API dependency | Tavily (paid) | None |
| API calls per topic | 1 Tavily + N search_filter + N cites | 1 OpenAlex |

#### 6.4 Analysis

**Where Path A succeeds**: Path A outperforms Path B on TOPIC_S (convolutional neural network image recognition), where the citation expansion strategy discovers 52 candidates with 11 relevant papers. This topic benefits from citation chaining because CNNs for image recognition have a well-connected citation graph — influential survey papers cite many related works. When Tavily happens to find a well-connected seed, the citation fan-out produces a high-quality candidate pool.

**Where Path A fails**: Path A catastrophically fails on RESEARCH_TOPIC, producing zero candidates across all three runs. The root cause is structural: the single seed found by Tavily ("Local Attention Mechanism: Boosting the Transformer Architecture") has no citing works in OpenAlex, so `filter(cites=seed_id)` returns an empty set. This is not a Tavily non-determinism issue — it is a fundamental fragility of the citation-expansion design, where the entire candidate pool depends on the seed paper's citation graph. For TOPIC_Q and TOPIC_R, Path A finds seeds but their citation networks are too small (4--6 papers) to generate a sufficient candidate pool.

**Where Path B succeeds**: Path B retrieves 92--100 candidates for every topic, eliminating zero-candidate failures entirely. For TOPIC_Q (federated learning privacy preservation), Path B triples the relevant count from 4 to 12, crossing the target threshold. For TOPIC_NEW (CRISPR gene editing), Path B matches Path A's strong performance (40 vs. 37 relevant). The deterministic nature of Path B means these results are exactly reproducible.

**Where Path B underperforms**: Path B yields only 4 relevant papers for RESEARCH_TOPIC and 2 for TOPIC_R. These low counts arise from the interaction between BM25 search and the `cited_by_count > 50` filter. BM25 ranks papers by term frequency, which favours application-domain papers that use transformers or reinforcement learning as tools (e.g., medical image segmentation, time-series forecasting, robotics) over papers that study these methods in the abstract. The quality filters then retain only high-cited papers among these results. E14 correctly identifies that most of these high-cited application papers are not relevant to the core topic, producing a low relevant count. This is the intended behaviour of the pipeline — it surfaces only genuinely relevant, downloadable papers — but it means that for topics where the core literature has fewer high-cited open-access papers published after 2023, the yield will be below the target.

---

### 7. Discussion

#### Low Relevant Counts for RESEARCH_TOPIC and TOPIC_R

RESEARCH_TOPIC ("attention mechanism in transformer models") yields only 4 relevant papers under Path B from a pool of 100 candidates (4% relevance rate). TOPIC_R ("reinforcement learning policy gradient optimization") yields 2 from 100 (2%). These low rates do not indicate a failure of the search method; rather, they reflect the combined effect of two design choices:

1. **Quality filters select for high-impact recent papers**: The `cited_by_count > 50` and `publication_year > 2023` constraints exclude the long tail of recent but less-cited papers and the highly-cited but older foundational works. For RESEARCH_TOPIC, the most relevant papers (e.g., "Attention Is All You Need" with 6,507 citations, published 2017) predate the year filter, while newer attention mechanism papers may not yet have accumulated 50 citations.

2. **E14 strictly rejects application papers**: BM25 search for "attention mechanism in transformer models" returns papers that use transformers with attention in applied domains (damage detection, medical imaging, crop yield prediction). These papers contain the query terms but are not about attention mechanisms per se. E14's high precision (1.000) means it rejects these papers with zero false positives, which is the desired behaviour for a pipeline that must produce topically relevant summaries and slides.

The relevant papers that do pass both filters are genuinely relevant and downloadable. For a pipeline that requires a minimum of 5 papers per slide deck, the 4 papers found for RESEARCH_TOPIC approach viability, and the count can be increased by relaxing the citation threshold or expanding the year window.

#### Path A's Structural Failures

Path A's zero-candidate result for RESEARCH_TOPIC is not a one-time anomaly but a structural vulnerability. The citation-expansion design chains three sequential dependencies: (1) Tavily must return academic titles, (2) those titles must match OpenAlex records via `search_filter`, and (3) the matched seeds must have citing works. A failure at any stage produces zero candidates. Experiment 07 demonstrates that step 2 fails for 80% of Tavily titles, and Experiment 09 shows that even when a seed is found, its citation network may be empty. These are not edge cases — they represent the normal operating mode for topics where Tavily's web search does not reliably surface well-connected academic papers.

#### Determinism and Reproducibility

Path B is fully deterministic: the same query parameters always return the same candidate set from OpenAlex, and E14's cosine similarity threshold produces deterministic Stage-1 classifications. Path A depends on Tavily, which is subject to web-search ranking changes, server-side caching, and API availability. While the three runs in Experiment 09 Part 1 showed identical results (likely due to caching), this stability is not guaranteed over time and cannot be verified without repeated experiments at different time intervals.

#### Downloadability

All papers returned by Path B satisfy the `oa_status` in {diamond, gold, green} filter, ensuring they are open-access and downloadable. The separate validation in `extract-id.py` confirms a 100% download success rate (5/5 papers) using a four-strategy fallback chain. Path A does not apply an OA status filter, so some of its relevant papers may not be downloadable.

---

### 8. Conclusion

This study evaluates whether the Tavily web-search dependency in the research-agent's paper-discovery pipeline can be replaced by direct OpenAlex queries with quality filters. The evidence supports the following conclusions:

1. **OpenAlex standalone is more robust than Tavily-assisted search.** Path B retrieves candidates for all 5 topics (92--100 per topic), while Path A produces zero candidates for the project's primary topic (RESEARCH_TOPIC) due to the fragile Tavily-to-OpenAlex seed-matching chain. Across all five domains, Path B retrieves 64 total relevant papers compared to Path A's 53.

2. **Tavily introduces unnecessary complexity and fragility.** Four distinct failure modes are identified: non-academic results (0--60% academic hit rate depending on query format), title mismatch artefacts (80% failure rate in OpenAlex matching), topical drift from lexical title matching, and redundant API cost (6 calls vs. 1).

3. **Both paths achieve the target in 2 of 5 domains.** Path B meets the >= 10 relevant paper threshold for TOPIC_Q (12) and TOPIC_NEW (40). Path A meets it for TOPIC_S (11) and TOPIC_NEW (37). Neither path achieves the target for RESEARCH_TOPIC, TOPIC_R, or (in the case of Path A) TOPIC_Q.

4. **Low relevant counts under Path B reflect strict filtering, not search failure.** The 4% relevance rate for RESEARCH_TOPIC results from the intentional combination of high-citation and recency filters with E14's strict relevance judgement. The papers that do pass are genuinely relevant and downloadable. Relaxing the citation threshold or year window would increase yield at the cost of including lower-impact or older papers.

5. **Path B should replace Path A as the default search method.** It eliminates the Tavily dependency, reduces API calls from N+1 to 1 per topic, guarantees reproducibility, and ensures all returned papers are open-access and downloadable. For topics where the relevant count falls below the target, the recommended mitigation is to adjust the quality filter parameters (citation threshold, year window) rather than to reintroduce Tavily.

The replacement is recommended with the configuration `PATH_B_PER_PAGE = 100`, `cited_by_count > 50`, `publication_year > (current_year - 3)`, and `oa_status` in {diamond, gold, green}, using E14 as the downstream relevance filter. Future work should explore adaptive filter relaxation strategies that automatically lower the citation threshold when the relevant count falls below the target, and investigate combining BM25 with semantic search to improve coverage for narrow topics.
