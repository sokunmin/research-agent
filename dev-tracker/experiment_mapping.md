# Experiment Mapping: experiments/ ↔ poc/

This file maps each clean experiment in `experiments/` to its original
source files in `poc/`, and classifies all poc/ files by their role.

---

## 01-openalex-paper-discovery

| experiments/ | poc/openalex-search-comparison/ | Role |
|---|---|---|
| search_method_comparison.md | search_method_comparison.md | Report |
| search_method_comparison.py | search_method_comparison.py | Experiment script |
| relevance_filter_ablation.md | relevance_filter_ablation.md | Report |
| relevance_filter_ablation.py | relevance_filter_ablation.py | Experiment script |
| stage1_threshold_analysis.md | stage1_threshold_analysis.md | Report |
| stage1_threshold_analysis.py | stage1_threshold_analysis.py | Analysis script |
| pdf_download_fallback.md | pdf_download_fallback.md | Report |
| pdf_download_fallback.py | pdf_download_fallback.py | Experiment script |
| imgs/roc_curve.png | imgs/roc_curve.png | Generated plot |
| imgs/score_distribution.png | imgs/score_distribution.png | Generated plot |
| imgs/coverage_vs_load.png | imgs/coverage_vs_load.png | Generated plot |

### poc-only files (dataset construction tools — no experiments/ equivalent)

| File | Role |
|---|---|
| build_balanced.py | Build 120-paper balanced ground truth dataset |
| download_arxiv.py | Batch download ArXiv PDFs for ground truth |
| enrich_metadata.py | Enrich paper metadata via OpenAlex lookup |
| fill_abstracts.py | Fill missing abstracts in ground truth JSON |
| merge_candidates.py | Merge candidate papers into ground truth JSON |
| merge_results.py | Merge LLM relevance results into ground truth JSON |
| list_remaining.py | List papers not yet processed |
| parse_log.py | Parse experiment output logs into structured JSON |
| imgs/threshold_sweep.png | Exploratory plot (not referenced in any report) |
| groundtruth/groundtruth-balanced.json | 120-paper benchmark dataset |
| groundtruth/relevant-system-prompt.md | LLM system prompt used in Stage-2 (ground truth collection) |
| groundtruth/find-tp-prompt.md | Prompt used to collect true positive candidates |
| groundtruth/ablation-study-prompt.md | Meta-prompt used to generate ablation study report draft |

---

## 02-agent-behavior

| experiments/ | poc/agent-behavior-test/ | Role |
|---|---|---|
| react_agent_behavior.md | react_agent_behavior.md | Report |
| react_agent_slide_gen.py | react_agent_slide_gen.py | Experiment script |
| react_agent_slide_modify.py | react_agent_slide_modify.py | Experiment script |
| layout_selection_baseline.md | layout_selection_baseline.md | Report |
| layout_selection_baseline.py | layout_selection_baseline.py | Experiment script (v2) |
| layout_selection_prompt_eng.md | layout_selection_prompt_eng.md | Report |
| layout_selection_prompt_eng.py | layout_selection_prompt_eng.py | Experiment script |
| structured_output_methods.md | structured_output_methods.md | Report |
| structured_output_methods.py | structured_output_methods.py | Experiment script (v2) |
| cloud_model_smoke_test.md | cloud_model_smoke_test.md | Report |
| cloud_model_smoke_test.py | cloud_model_smoke_test.py | Experiment script |

### poc-only files (iteration history — superseded by v2)

| File | Role |
|---|---|
| layout_name_test.py | v1 of layout_selection_baseline.py (single model only) |
| augment_test.py | v1 of structured_output_methods.py (fewer methods tested) |
