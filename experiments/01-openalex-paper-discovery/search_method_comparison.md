# Paper Discovery Search Method Comparison: Tavily-Assisted vs. OpenAlex Standalone

## Background & Motivation

A research-agent system automatically discovers academic papers on a given topic, filters them for relevance, downloads PDFs, and generates summaries and presentation slides. The original pipeline relied on Tavily — a paid third-party web search API — to find ArXiv-related results, which were then matched to OpenAlex records and expanded via citation chains. This design raised three concerns: Tavily is an external paid dependency outside the project's control, web search results vary across runs making the pipeline non-reproducible, and Tavily returns web pages (blog posts, documentation sites) that must be title-matched into OpenAlex, introducing a lossy translation step. This study evaluates whether Tavily can be replaced entirely with direct OpenAlex API queries augmented with quality filters.

## Experiment Setup

**Hardware:** Apple MacBook M1, 16GB unified memory. All models served locally via Ollama using Apple Metal.

**Relevance filter used throughout:** A two-stage classifier (described in detail in the companion ablation study) with Stage 1 using nomic-embed-text embeddings (cosine similarity threshold = 0.500, input: title + abstract) and Stage 2 using qwen3.5:2b with a strict prompt (input: title + abstract + keywords + topics + primary_topic + concepts), invoked only for papers in the score band [0.500, 0.610). This filter achieves F1 = 0.974, Precision = 1.000, Recall = 0.950 on a balanced 120-paper ground truth dataset.

**Evaluation metric:** Relevant paper count per topic after relevance filtering, with a target of at least 10 relevant papers per topic.

**Five test topics across four domains:**

| Topic | Domain |
|---|---|
| Attention mechanism in transformer models | NLP / Deep Learning |
| Federated learning privacy preservation | Distributed Systems |
| Reinforcement learning policy gradient optimization | Reinforcement Learning |
| Convolutional neural network image recognition | Computer Vision |
| CRISPR gene editing therapeutic applications | Biomedical (non-ML) |

**Two pipeline paths compared:**

- **Path A (Tavily-assisted):** Tavily web search → OpenAlex title-match → citation expansion → relevance filter
- **Path B (OpenAlex standalone):** OpenAlex BM25 search with quality filters (open access, cited_by_count > 50, publication_year > 2023, no retractions, sorted by citation count descending, per_page=100) → relevance filter

## Results

### OpenAlex Search Method Characterisation (3 methods, topic: attention mechanism in transformer models, per_page=25)

| Method | API Call | Candidates | Relevant | Relevance % | ArXiv | ArXiv % |
|---|---|---|---|---|---|---|
| Keyword Search | `search_filter` | 25 | 15 | 60% | 3 | 12% |
| BM25 Full-Text | `search` | 25 | 13 | 52% | 6 | 24% |
| Semantic Search | `similar` | 25 | 17 | 68% | 9 | 36% |

### Cross-Method Overlap (all three methods combined, no filtering)

| Comparison | Overlap |
|---|---|
| Keyword ∩ BM25 | 18 papers |
| Keyword ∩ Semantic | 0 papers |
| BM25 ∩ Semantic | 0 papers |
| Semantic unique | 25 papers |
| Keyword/BM25 union unique | 32 papers |

### Tavily Query Format Effects (topic: attention mechanism in transformer models)

| Query format | Academic Hits | Non-Academic Hits | Academic Hit Rate |
|---|---|---|---|
| Bare query | 0 | 5 | 0% |
| ArXiv-prefix query | 3 | 2 | 60% |

### Tavily Seed Quality vs. Direct OpenAlex (5 papers each)

| Metric | Tavily + OpenAlex title-match | OpenAlex direct search |
|---|---|---|
| Papers found | 5 | 5 |
| Citation counts | [308, 686, 104, 572, 461] | [235, 6,507, 5,499, 12, 68] |
| Median citations | 461 | 235 |
| Max citations | 686 | 6,507 |
| Overlap | 0 papers | 0 papers |
| API calls | 6 (1 Tavily + 5 OpenAlex) | 1 |

### Tavily Title-to-OpenAlex Match Quality (arxiv-prefix query, 5 titles)

| Tavily Title | OpenAlex Match | Match Quality |
|---|---|---|
| An analysis of attention mechanisms and its variance in transformer | Exact match (cited: 2) | Correct |
| Nexus: Higher-Order Attention Mechanisms in Transformers | No match | Lost |
| Attention Is All You Need - arXiv | "Deep Learning for Natural Language Processing" (cited: 58) | Wrong paper |
| Coffee Time Papers: Attention Is All You Need | "Embracing Chinese Global Security Ambitions" (cited: 26) | Wrong paper |
| Selective Attention Improves Transformer - arXiv | No match | Lost |

### Candidate Pool Sizing: per_page sweep (Path B, attention mechanism in transformer models)

| per_page | Candidates | Relevant | Relevance % |
|---|---|---|---|
| 25 | 25 | 1 | 4% |
| 50 | 50 | 3 | 6% |
| 100 | 100 | 4 | 4% |
| 150 | 150 | 4 | 3% |

### Path A — Tavily-Assisted Pipeline: Non-Determinism Test (3 runs, attention mechanism topic)

| Run | Seeds Found | Candidates | Relevant | Meets Target (≥10) |
|---|---|---|---|---|
| Run 1 | 1 | 0 | 0 | No |
| Run 2 | 1 | 0 | 0 | No |
| Run 3 | 1 | 0 | 0 | No |

### Path A — Five-Domain Results (1 run per topic)

| Topic | Domain | Seeds | Candidates | Relevant | Meets Target |
|---|---|---|---|---|---|
| Attention mechanism in transformers | NLP / DL | 1 | 0 | 0 | No |
| Federated learning privacy | Distributed Systems | 2 | 6 | 4 | No |
| RL policy gradient | Reinforcement Learning | 2 | 4 | 1 | No |
| CNN image recognition | Computer Vision | 2 | 52 | 11 | Yes |
| CRISPR gene editing | Biomedical | 1 | 50 | 37 | Yes |

### Path B — OpenAlex Standalone: Five-Domain Results

| Topic | Domain | Candidates | Relevant | Meets Target |
|---|---|---|---|---|
| Attention mechanism in transformers | NLP / DL | 100 | 4 | No |
| Federated learning privacy | Distributed Systems | 92 | 12 | Yes |
| RL policy gradient | Reinforcement Learning | 100 | 2 | No |
| CNN image recognition | Computer Vision | 100 | 6 | No |
| CRISPR gene editing | Biomedical | 100 | 40 | Yes |

### Head-to-Head Pipeline Comparison

| Topic | Path A Candidates | Path A Relevant | Path B Candidates | Path B Relevant | Winner |
|---|---|---|---|---|---|
| Attention mechanism in transformers | 0 | 0 | 100 | 4 | Path B |
| Federated learning privacy | 6 | 4 | 92 | 12 | Path B |
| RL policy gradient | 4 | 1 | 100 | 2 | Path B |
| CNN image recognition | 52 | 11 | 100 | 6 | Path A |
| CRISPR gene editing | 50 | 37 | 100 | 40 | Path B |
| **Total** | **112** | **53** | **492** | **64** | **Path B** |
| **Topics ≥ 10** | | **2/5** | | **2/5** | **Tie** |

| Property | Path A (Tavily-assisted) | Path B (OpenAlex standalone) |
|---|---|---|
| Topics with ≥ 10 relevant | 2/5 | 2/5 |
| Total relevant papers | 53 | 64 |
| Topics with 0 candidates | 1/5 | 0/5 |
| Deterministic | No (Tavily-dependent) | Yes |
| External API dependency | Tavily (paid) | None |
| API calls per topic | 1 Tavily + N search_filter + N cites | 1 OpenAlex |

## Key Findings

- **Semantic search accesses a disjoint literature region.** The semantic (`similar`) method and the keyword/BM25 methods have zero paper overlap. Semantic search returns 68% relevance rate and 36% ArXiv presence vs. 52–60% relevance and 12–24% ArXiv for the text-based methods. Total unique papers across all three methods: 57.

- **Tavily's title-to-OpenAlex translation fails 80% of the time.** Of 5 Tavily-returned titles, only 1 (20%) matched the correct OpenAlex record. Two titles returned no match; two returned completely wrong papers. The failure mode is that web-scraped titles contain formatting artefacts (e.g., "- arXiv" suffixes, blog prefixes) that break OpenAlex's search logic.

- **Path A catastrophically fails on the primary use case topic.** All 3 runs returned zero candidates for the attention mechanism topic because the single Tavily-seeded paper had no citing works in OpenAlex. This is a structural fragility: the entire candidate pool depends on the seed paper's citation graph.

- **Path B eliminates zero-candidate failures entirely.** Path B retrieves 92–100 candidates across all 5 topics. Total relevant papers: 64 vs. 53 for Path A. Path B is fully deterministic and requires only 1 OpenAlex API call per topic vs. N+1 calls for Path A.

- **Low relevant counts for some topics reflect strict quality filtering, not search failure.** The 4% relevance rate for the attention mechanism topic results from `cited_by_count > 50` and `publication_year > 2023` together excluding both foundational papers (published before 2023) and newer but less-cited papers. Papers that do pass all filters are genuinely relevant and downloadable.

## Decision

Path B (OpenAlex standalone) adopted as the default paper discovery method, replacing the Tavily-assisted pipeline. Recommended configuration: `per_page=100`, `cited_by_count > 50`, `publication_year > (current_year - 3)`, `oa_status` in {diamond, gold, green}. For topics where relevant count falls below target, the recommended mitigation is relaxing quality filter parameters (citation threshold, year window) rather than reintroducing Tavily.
