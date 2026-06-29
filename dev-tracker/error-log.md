---
## [2026-06-28] Docling `do_picture_classification=True` crashes Docker backend after ~6 minutes — `DocumentFigureClassifier-v2.5` saturates CPU with no MPS access `[環境: Docker on macOS M1]`
原因：`DocumentFigureClassifier-v2.5` is a Transformers-based image classifier activated by `do_picture_classification=True` in `DoclingPipeline._build_converter()`. Inside Docker on macOS M1, Apple MPS (Metal GPU) is permanently inaccessible — Hypervisor.framework does not expose a Metal GPU surface to the Linux VM — so the model runs entirely on CPU, saturating all cores and crashing after ~6 minutes (likely OOM or timeout). The same crash pattern applies to any Docling feature that uses a non-ONNX Transformers model in Docker on M1.
修正：Set `do_table_structure=False`, `do_picture_classification=False`, `generate_picture_images=False` in `backend/services/docling_pipeline.py`. Only ONNX-based Docling models (layout analysis, TableFormer) are safe to enable in Docker on M1; all Transformers-based models will exhibit this crash pattern.
---
## [2026-06-28] Docling `do_formula_enrichment=True` or `do_code_enrichment=True` crashes Docker backend after ~19 minutes — `CodeFormulaV2` VLM saturates CPU with no MPS access `[環境: Docker on macOS M1]`
原因：`do_formula_enrichment=True` and `do_code_enrichment=True` in `DoclingPipeline._build_converter()` activate the `CodeFormulaV2` Transformers VLM model. Inside Docker on macOS M1, MPS is permanently inaccessible (Hypervisor.framework does not expose Metal to the Linux VM), so the model runs on CPU at 100–280 seconds per image. After processing 7 images the pipeline crashed (`ERROR: Pipeline StandardPdfPipeline failed`), likely OOM or timeout. This was discovered during the `paper2summary` step.
修正：Set `do_formula_enrichment=False` and `do_code_enrichment=False` in `backend/services/docling_pipeline.py`. Formula and code enrichment are not needed for paper summarization and add disproportionate cost on CPU-only Docker environments.
---
## [2026-06-28] `ImportError: libGL.so.1: cannot open shared object file` crashes backend on startup when Docling is imported in Docker `[環境: Docker python:3.12-slim base image]`
原因：`opencv-python` is pulled in transitively by `rapidocr` (a Docling dependency) and requires `libGL.so.1` (OpenGL) at import time, even in headless server environments. The `python:3.12-slim` Docker base image does not include OpenGL libraries, so any `import docling` or downstream import raises `ImportError: libGL.so.1: cannot open shared object file: No such file or directory`. Swapping to `opencv-python-headless` is not straightforward because `rapidocr` pins `opencv-python` as a transitive dependency.
修正：Add `libgl1 libglib2.0-0` to the `apt-get install` block in `backend/Dockerfile` (same fix used in the official Docling Dockerfile).
---
## [2026-06-28] `pyalex` hangs indefinitely when OpenAlex API key is expired — no timeout support in `pyalex.config` `[通用: pyalex]`
原因：`pyalex` uses `requests.get()` with no timeout and retries on HTTP 429 indefinitely (`retry_http_codes` includes 429). When the OpenAlex API key expires, the API returns 429 or drops the connection, causing `fetch_candidate_papers()` to stall forever (observed at the `supervisor_search` step). `pyalex.config.timeout` does not exist — there is no built-in timeout mechanism in pyalex.
修正：Register a new OpenAlex account and update `OPENALEX_API_KEY` and `OPENALEX_EMAIL` in `.env`. For long-running pipelines, consider wrapping `pyalex` calls with `asyncio.wait_for()` or a `threading.Timer` to enforce an external timeout.
---
## [2026-06-26] `docker compose up` fails with `container dev-qdrant-1 is unhealthy` — curl-based healthcheck exits 127 on `qdrant/qdrant:v1.18.0` `[版本: qdrant/qdrant:v1.18.0+]`
原因：`qdrant/qdrant:v1.18.0` is a minimal image; curl, wget, and python are intentionally excluded for security reasons (Qdrant GitHub issues #3491, #4250). A healthcheck using `["CMD", "curl", "-sf", "http://localhost:6333/healthz"]` returns exit 127 (command not found), causing Docker to mark the container unhealthy and blocking dependent services.
修正：Replace the curl-based healthcheck in `docker-compose.yml` with a bash TCP check that uses only shell built-ins: `test: ["CMD-SHELL", "bash -c ':> /dev/tcp/127.0.0.1/6333' || exit 1"]`. Verified — container reaches `healthy` status with all checks exiting 0. Applies to all recent Qdrant images that ship without curl.
---
## [2026-06-17] `litellm.completion()` with `nemotron-3-super:cloud` + `think=True` returns empty `message.content` — correct extraction uses `reasoning_content` fallback `[通用]`
原因：Ollama routes the reasoning trace to `message.reasoning_content` / `message.thinking` when `think=True`, leaving `message.content` empty by design; `litellm.completion()` reads `message.content` by default and returns `""`, making the response appear empty even though output is present in `message.reasoning_content`.
修正：Use a fallback extraction chain: `msg = resp.choices[0].message; answer = msg.content or getattr(msg, "reasoning_content", "") or ""`; keep `think=True` for better-calibrated judge scores — do NOT set `think=False` to work around the empty content, as that removes the model's reasoning capability. Note: the `:cloud` variant currently writes the final answer directly to `message.content` even with `think=True`, so the fallback is not exercised on cloud but should be retained for local variants and future endpoint changes. Applies to `JudgeLLM` class in `summarization_comparison.py`.
---
## [2026-06-16] LiteLLM non-zero default temperature causes non-reproducible RAG evaluation metrics across retrieval configurations `[通用: LiteLLM + RAGAS 0.4.x + Ollama]`
原因：LiteLLM's default temperature is 0.1 (not 0.0); any non-zero temperature propagates randomness through the entire RAG evaluation chain — query expansion changes the retrieved chunks (affecting Recall@5/nDCG@5), and answer generation changes RAGAS semantic scores (Context Recall, Faithfulness, Context Precision) — making it impossible to attribute metric differences between retrieval configurations to genuine retrieval quality rather than LLM variation. Additionally, `nemotron-3-super`'s `num_ctx` was hardcoded to 4096 (1.5% of its 262K native context), silently truncating evaluation inputs; seed has no effect on this GGUF build so outputs vary slightly at token level, but RAGAS semantic scores are stable within ±0.05 at temperature=0.
修正：Set `temperature=0.0` on every `LiteLLM(...)` instantiation used for query expansion and answer generation; in the `RAGASEvaluator._nemotron_acompletion` wrapper add `kwargs.setdefault("temperature", 0.0); kwargs.setdefault("seed", 42); kwargs.setdefault("num_ctx", 32768)` (32K fits all RAG eval inputs on M1; always look up the model's actual context window before setting num_ctx). Affected files: `poc/poc_base.py` and `poc/rag-eval/retrieval_strategy_comparison.py`.
---
---
## [2026-06-16] Missing `paper_id` in Qdrant payload causes cross-paper chunk contamination in shared collection — dense-only Recall@5 drops from 0.610 to 0.333 `[通用: LlamaIndex QdrantVectorStore + shared collection per-paper evaluation]`
原因：`QdrantPaperIndex._embed_and_upsert()` never set `node.metadata["paper_id"]` before upserting, so the field was absent from every Qdrant payload. `build_retriever()` therefore had no filter to apply and searched all ~1,680 chunks across 28 papers. ML papers share vocabulary ("accuracy", "model", "training"), so off-paper chunks routinely outscored correct-paper chunks and inflated false negatives across all 6 retrieval configs (dense_only, hybrid_bm25, query_expansion, reranker variants). Absolute metric values from any run prior to the fix are wrong; relative rankings remain valid.
修正：(1) In `poc/poc_base.py` `QdrantPaperIndex._embed_and_upsert()`, add `node.metadata["paper_id"] = paper_id` before calling `get_text_embedding()`. (2) In `poc/rag-eval/retrieval_strategy_comparison.py` `build_retriever()`, add `paper_id: str` parameter and `filters=MetadataFilters(filters=[MetadataFilter(key="paper_id", value=paper_id)])` to `index.as_retriever()`. (3) In `SentenceSplitterExperiment._chunk_paper()`, add `node.metadata["paper_id"] = paper_id` explicitly. **The existing Qdrant index at `poc/rag-eval/qdrant_ml_papers_retrieval_index/` must be rebuilt** with `--rebuild-index` flag before re-evaluating, because the index was created without `paper_id` in the payload.
---
## [2026-06-16] `QueryFusionRetriever(use_async=True)` crashes with `ValueError: Async client not initialized` when using Qdrant local file mode `[版本: llama-index-vector-stores-qdrant + qdrant-client local file mode]`
原因：`QueryFusionRetriever(use_async=True)` routes queries through `QdrantVectorStore.aquery()`, which calls `_ensure_async_client()`. That method raises `ValueError` if no `AsyncQdrantClient` was provided at construction time. The intuitive fix — constructing an `AsyncQdrantClient(path=same_dir)` alongside the sync `QdrantClient` — fails because Qdrant local file mode uses `portalocker`; the second client immediately raises `RuntimeError: Storage folder is already accessed by another instance of Qdrant client`. Two concurrent clients on the same local path are not supported.
修正：Set `use_async=False` in `QueryFusionRetriever` in `poc/rag-eval/retrieval_strategy_comparison.py`. This forces the sync retrieval path (`query()` instead of `aquery()`), adding ~2–4 s per paper for configs with multiple query variants but not affecting metric values. When integrating into the Docker pipeline, replace local file mode with a Qdrant server (`QdrantClient(url="http://qdrant:6333")`); server mode allows both sync and async clients concurrently without file locking.
---
## [2026-06-16] `ragas 0.4.x` changed metric and LLM wrapper import paths — `from ragas.metrics import ...` raises `ImportError` `[版本: ragas 0.4.x]`
原因：`ragas 0.4.x` reorganized internal modules. `Faithfulness`, `ContextRecall`, and `ContextPrecision` moved from `ragas.metrics` to `ragas.metrics.collections`; `LlamaIndexLLMWrapper` moved from `ragas.llms` to `ragas.llms.base`. Code written against ragas 0.1–0.3 import paths raises `ImportError` or `ImportError: cannot import name '...'` at startup. Note: the separate `ChatVertexAI` crash (ragas importing `langchain_community.chat_models.vertexai` at module level regardless of LLM backend) is documented in the 2026-06-14 entry and requires a `sys.modules` stub applied before any ragas import.
修正：Update all ragas imports in `poc/rag-eval/retrieval_strategy_comparison.py`: use `from ragas.metrics.collections import Faithfulness, ContextRecall, ContextPrecision` and `from ragas.llms.base import LlamaIndexLLMWrapper`.
---
## [2026-06-14] `QdrantPaperIndex.is_paper_indexed()` raises `ValueError: Collection not found` on first run before any paper is indexed `[通用: qdrant-client local mode]`
原因：`is_paper_indexed()` called `qdrant_client.scroll(collection_name=...)` directly without checking whether the collection exists first. Qdrant local mode raises `ValueError` when you query a collection that has not been created yet, and the collection is only created lazily during the first `_embed_and_upsert()` call.
修正：Added `if not self._client.collection_exists(self.COLLECTION_NAME): return False` as the first line of `is_paper_indexed()` in `poc/poc_base.py` (`QdrantPaperIndex`). If the collection does not exist, nothing is indexed yet — return False immediately.
---
## [2026-06-14] `QdrantPaperIndex._delete_paper_points()` raises `ValueError: Collection not found` on first run before any paper is indexed `[通用: qdrant-client local mode]`
原因：`_delete_paper_points()` called `qdrant_client.delete(collection_name=...)` directly without checking whether the collection exists. On first run, the collection has not been created yet, so Qdrant raises `ValueError`. The collection is only created lazily during the first `_embed_and_upsert()` call.
修正：Added `if not self._client.collection_exists(self.COLLECTION_NAME): return` as the first line of `_delete_paper_points()` in `poc/poc_base.py` (`QdrantPaperIndex`). If the collection does not exist, there is nothing to delete — return early.
---
## [2026-06-14] `QdrantPaperIndex._write_sentinel()` raises Qdrant ID validation error — arbitrary strings are not valid point IDs `[通用: qdrant-client]`
原因：The sentinel point ID was set to a plain string like `"1608.06993__index_complete__"`. Qdrant only accepts two ID formats: unsigned 64-bit integers or UUID strings (`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`). An arbitrary string is not a valid Qdrant point ID and is rejected at insert time.
修正：Changed to `id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{paper_id}__sentinel__"))` in `poc/poc_base.py` (`QdrantPaperIndex._write_sentinel()`). `uuid5` generates a deterministic UUID from the input string, so the same `paper_id` always produces the same UUID — making the sentinel write idempotent (Qdrant overwrites on re-run rather than duplicating).
---
## [2026-06-14] `QdrantPaperIndex._write_sentinel()` raises `ValueError: Unnamed vectors are not allowed` in a named-vector collection `[通用: qdrant-client + LlamaIndex QdrantVectorStore with enable_hybrid=True]`
原因：The Qdrant collection was created with `enable_hybrid=True`, which uses named vectors: dense vectors stored under key `"text-dense"`, sparse vectors under `"text-sparse-new"`. The sentinel point was inserted with `vector=[0.0] * 768` (an unnamed plain list). Every point in a named-vector collection must use the named format `{"text-dense": [...]}`, and Qdrant rejects any unnamed vector.
修正：Changed sentinel vector to `vector={DEFAULT_DENSE_VECTOR_NAME: [0.0] * self.EMBEDDING_DIM}` in `poc/poc_base.py` (`QdrantPaperIndex._write_sentinel()`), where `DEFAULT_DENSE_VECTOR_NAME` is imported from `llama_index.vector_stores.qdrant.base` (value: `"text-dense"`). Using the LlamaIndex constant instead of a hardcoded string ensures consistency if LlamaIndex changes its default vector name in a future version.
---
## [2026-06-14] `QdrantPaperIndex._write_sentinel()` throws an opaque Qdrant internal exception when called after a failed `_embed_and_upsert()` — missing precondition check `[通用: qdrant-client]`
原因：`_write_sentinel()` is always called after `_embed_and_upsert()`. If `_embed_and_upsert()` fails mid-way, the Qdrant collection may not exist, and `_write_sentinel()` throws a raw Qdrant internal exception with no context about which paper failed or why.
修正：Added `if not self._client.collection_exists(self.COLLECTION_NAME): raise RuntimeError(...)` at the top of `_write_sentinel()` in `poc/poc_base.py` (`QdrantPaperIndex`). The error message explicitly names the missing collection and the paper ID, and points to `_embed_and_upsert` as the likely cause.
---
## [2026-06-14] `QdrantPaperIndex.__init__()` collection creation block is a no-op — `LlamaIndex QdrantVectorStore` uses lazy initialization, no collection is created until nodes are actually upserted `[版本: llama-index-vector-stores-qdrant]`
原因：`__init__` tried to create the Qdrant collection at startup using `QdrantVectorStore(...)` and `StorageContext.from_defaults(vector_store=...)`. Both calls are confirmed no-ops: `QdrantVectorStore.__init__` only calls `collection_exists()` (read-only); `StorageContext.from_defaults()` wraps the store in a Python dict with no I/O. The actual `create_collection()` only fires inside `VectorStoreIndex(nodes=nodes, ...)` when `nodes` is non-empty. Additionally, the return value of `StorageContext.from_defaults()` was not assigned to any variable, making the entire block inert.
修正：Removed the misleading no-op initialization block from `__init__()` in `poc/poc_base.py` (`QdrantPaperIndex`). Added a comment explaining that the collection is created lazily on the first `_embed_and_upsert()` call, and that all Qdrant read methods have explicit `collection_exists()` guards.
---
## [2026-06-14] `QdrantPaperIndex.rebuild_all()` collection re-creation after `delete_collection()` is also a no-op — same LlamaIndex lazy initialization issue `[版本: llama-index-vector-stores-qdrant]`
原因：`rebuild_all()` deletes the entire Qdrant collection then attempts to recreate an empty one using `QdrantVectorStore` and `StorageContext.from_defaults()`. Both calls are no-ops (see B-6 above); the collection is never recreated. The code appeared correct but silently did nothing — the collection was only recreated later on the first `_embed_and_upsert()` call. This caused confusion because no crash occurred (downstream methods had `collection_exists()` guards), making the bug invisible.
修正：Removed the no-op re-creation block from `rebuild_all()` in `poc/poc_base.py` (`QdrantPaperIndex`). Added a comment explaining that after `delete_collection()`, the collection will be recreated lazily on the first `_embed_and_upsert()` call.
---
## [2026-06-14] `import ragas` raises `ImportError: cannot import name 'ChatVertexAI' from 'langchain_community.chat_models.vertexai'` even when LangChain is not used `[版本: ragas 0.4.x + langchain-community 0.4.x]`
原因：`ragas/llms/base.py` imports `ChatVertexAI` from `langchain_community.chat_models.vertexai` at module level (not inside a function or try/except). In `langchain-community 0.4.x`, this module was moved to the separate `langchain-google-vertexai` package. The import fires unconditionally on any `import ragas` statement, even when only the LlamaIndex LLM backend is used and LangChain is never touched.
修正：Insert stub modules into `sys.modules` before any ragas import at the very top of the script in `poc/rag-eval/retrieval_strategy_comparison.py`. Create empty `ChatVertexAI` and `VertexAI` classes in stub modules named `langchain_community.chat_models.vertexai` and `langchain_community.llms.vertexai` respectively, so ragas's module-level import resolves without installing the Google Cloud package.
---
## [2026-06-14] `from llama_index.postprocessor.sentence_transformer_rerank import SentenceTransformerRerank` raises `ModuleNotFoundError` — wrong import path `[版本: llama-index-core]`
原因：`SentenceTransformerRerank` is part of `llama_index.core`, not a separate `llama_index.postprocessor` package. The path `llama_index.postprocessor.sentence_transformer_rerank` does not exist and was never a valid module.
修正：Changed import to `from llama_index.core.postprocessor import SentenceTransformerRerank` in `poc/rag-eval/retrieval_strategy_comparison.py`.
---
## [2026-06-11] `markdown_element_splitter` strategy scores recall5=0.000 across all 104 queries due to evaluation method incompatibility in `MetricsCalculator.find_relevant_ids()` `[版本: poc/rag-eval/chunking_strategy_comparison.py + LlamaIndex MarkdownElementNodeParser]`
原因：`LlamaIndex MarkdownElementNodeParser` uses an LLM to rewrite markdown tables into natural language summaries during chunking. `MetricsCalculator.find_relevant_ids()` uses verbatim substring match to find ground-truth passages in `node.text`. After LLM rewriting, the original table text no longer exists as a substring — `find_relevant_ids()` always returns empty — recall=0. This is an evaluation method incompatibility, not a retrieval failure.
修正：Excluded `markdown_element_splitter` from comparison tables. A fair evaluation requires semantic similarity matching between gt_passage and node.text instead of substring containment.
---
## [2026-06-11] `MetricsCalculator.find_relevant_ids()` always returns empty set when `VectorStoreIndex` is backed by `QdrantVectorStore`, causing all queries to be skipped with `reason=no_relevant_ids_found` `[版本: poc/rag-eval/chunking_strategy_comparison.py + LlamaIndex VectorStoreIndex + QdrantVectorStore]`
原因：When `QdrantVectorStore` is used as the backend for `VectorStoreIndex`, LlamaIndex does not populate its in-memory docstore (Python dict) during index construction. Iterating `index.docstore` returns nothing regardless of how many nodes were indexed.
修正：Pass the in-memory `nodes` list directly to `MetricsCalculator.find_relevant_ids()` instead of querying `index.docstore`. The list is always in scope within the same script execution.
---
## [2026-06-11] `AttributeError: 'ContextualDoclingNodeParser' object has no attribute 'get_nodes_from_documents'` crashes `docling_hybrid_chunker_512` and `docling_hierarchical_chunker` strategies `[版本: poc/rag-eval/poc_base.py ContextualDoclingNodeParser]`
原因：The custom `ContextualDoclingNodeParser` class in `poc_base.py` only implemented `parse_nodes()`. The evaluation script calls `get_nodes_from_documents()` uniformly for all strategies, which is the standard LlamaIndex `NodeParser` entry point. The custom class did not implement this method.
修正：Added `get_nodes_from_documents()` as an alias method in `ContextualDoclingNodeParser` that delegates to `parse_nodes()`.
---
## [2026-06-11] `LlamaIndex MarkdownElementNodeParser(llm=None)` raises `ValueError: No API key found for OpenAI` and default prompt discards all numeric values from table summaries `[版本: poc/rag-eval/chunking_strategy_comparison.py + LlamaIndex MarkdownElementNodeParser]`
原因：`MarkdownElementNodeParser(llm=None)` does NOT skip LLM calls — `llm=None` causes LlamaIndex to fall back to `Settings.llm`, which defaults to OpenAI. `extract_table_summaries()` always executes when the document contains markdown tables and cannot be bypassed. The default built-in prompt instructs the LLM to produce a "very concise summary", which discards specific numbers and model names.
修正：Pass `llm=LiteLLM(model="ollama/ministral-3:14b-cloud")` explicitly. Use a custom `summary_query_str` (RETRIEVAL_TABLE_SUMMARY_PROMPT) that instructs the LLM to preserve every number, percentage, model name, and benchmark score. Model `gpt-oss:20b-cloud` was ruled out after smoke test — it returned empty string for table summarization.
---
## [2026-06-11] `litellm.APIConnectionError: OllamaException - Client error '400 Bad Request'` in `SemanticSplitterNodeParser` before any chunk is produced, caused by markdown tables exceeding nomic-embed-text's 2048 BERT token limit `[版本: poc/rag-eval/chunking_strategy_comparison.py + LlamaIndex SemanticSplitterNodeParser + Ollama nomic-embed-text]`
原因：`SemanticSplitterNodeParser` calls `embed_model.get_text_embedding_batch()` internally during chunking to compute cosine similarity between adjacent sentences for boundary detection. Docling's markdown export treats entire multi-row tables as a single "sentence" — these can exceed nomic-embed-text's 2048 BERT token limit. This internal embed call happens inside the splitter's call stack before the script's outer `truncate_to_bert_limit()` loop has any opportunity to intercept.
修正：Implemented `TruncatingEmbeddingWrapper(BaseEmbedding)` that wraps `LiteLLMEmbedding` and applies `truncate_to_bert_limit()` before every `_get_text_embeddings()` call. Passed `TruncatingEmbeddingWrapper(embed_model)` to `SemanticSplitterNodeParser` instead of `embed_model` directly. The other 4 strategies are unaffected — they do not call the embedding model during chunking.
---
## [2026-06-10] BERT tokenizer truncation still causes HTTP 400 due to HuggingFace vs Ollama GGUF Unicode tokenization mismatch `[版本: poc/rag-eval/chunking_strategy_comparison.py + nomic-embed-text GGUF + HuggingFace bert-base-uncased]`
原因：HuggingFace `bert-base-uncased` and Ollama's GGUF build of `nomic-embed-text` count tokens differently for non-ASCII Unicode. The Unicode HORIZONTAL ELLIPSIS `…` (U+2026) counts as 1 token in HuggingFace but 2 tokens in Ollama's GGUF. Paper `2109.07958` node[17] had 2 occurrences of `…`; after truncation to 2046 HF tokens, Ollama counted 2046 + 2 (ellipsis extra) + 2 (CLS/SEP) = 2050 > 2048 → HTTP 400. The llama.cpp fix for NFD accent normalization (issue #5496) did not cover U+2026 because it has no NFD decomposition.
修正：Two-step fix in `truncate_to_bert_limit()`: (1) apply `unicodedata.normalize("NFKC", text)` before tokenizing — converts `…` → `...` and other Unicode compatibility characters to ASCII equivalents that both tokenizers count identically; (2) lower `BERT_MAX_TOKENS` from 2046 to 1900 (7% safety buffer below the 2048 hard limit) to absorb residual GGUF drift for characters not covered by NFKC.
---
## [2026-06-10] tiktoken and BERT WordPiece tokenizers give very different token counts for markdown tables, causing HTTP 400 from Ollama embedding endpoint `[版本: poc/rag-eval/chunking_strategy_comparison.py + LlamaIndex SentenceSplitter (tiktoken) + Ollama nomic-embed-text (BERT WordPiece)]`
原因：`SentenceSplitter` uses tiktoken (OpenAI BPE) to enforce `chunk_size=1024`, but Ollama's `nomic-embed-text` uses BERT WordPiece internally. These tokenizers diverge sharply on markdown table separator lines like `|---|---|---|`: tiktoken (BPE, merges repeated chars) counts the line as ~8 tokens; BERT WordPiece (splits char-by-char for unknown patterns) counts each `|` and `-` as 1 token, yielding ~90 tokens (10× more). Node[17] of paper `2109.07958` (BIG-Bench) measured 990 tiktoken tokens (under the 1024 limit) but 2422 BERT tokens (over the 2048 Ollama limit) — 65.7% of BERT tokens were `|` and `-` formatting characters.
修正：Load `bert-base-uncased` tokenizer from HuggingFace `transformers` at startup (tokenizer files only, ~700KB, no model weights). Before embedding each node, call `truncate_to_bert_limit()` to pre-check and truncate to the Ollama 2048-token hard limit. Log truncated nodes with `event=truncated`. Note: the deeper architectural issue (BERT-based embedding receiving markdown tables) is intentionally left for Phase 1 to measure — the experiment tests whether structure-aware chunkers (MarkdownElementNodeParser, Docling HybridChunker) outperform naive splitters on table-heavy documents.
---
## [2026-06-10] SentenceSplitter produces empty/whitespace-only nodes that cause HTTP 400 from Ollama embedding endpoint `[版本: poc/rag-eval/chunking_strategy_comparison.py + LlamaIndex SentenceSplitter + Ollama /api/embed]`
原因：`SentenceSplitter` (and other plain-text parsers including `SemanticSplitterNodeParser` and `MarkdownElementNodeParser`) can produce nodes with empty or whitespace-only `text` fields when the input markdown contains section headers with no body text or whitespace-only paragraphs between sections. Ollama's `/api/embed` endpoint rejects empty strings with HTTP 400 — passing `node.text = ""` to `embed_model.get_text_embedding("")` crashes the script on the first affected paper.
修正：Add a one-line filter immediately after chunking, before the embedding loop: `nodes = [n for n in node_parser.get_nodes_from_documents([li_doc]) if n.text.strip()]`. This removes any node whose text is empty or contains only whitespace characters.
---
## [2026-06-09] `DoclingChunker._TokenizerAdapter.get_tokenizer()` returned raw tiktoken encoder — `semchunk` received `List[int]` instead of `int` `[版本: backend/services/docling_chunker.py + semchunk]`
原因：`get_tokenizer()` 回傳 `Settings.tokenizer`（tiktoken encoder）本身。tiktoken 的 encode function 回傳 `List[int]`（token IDs），但 `semchunk` 呼叫回傳的 function 作為 `token_counter(text)`，期望收到 `int`。同一 class 的 `count_tokens()` 方法已正確使用 `len()`，但 `get_tokenizer()` 缺少此包裝，導致 `semchunk.py` 內 `if token_counter(split) > local_chunk_size:` 拋出 `TypeError: '>' not supported between instances of 'list' and 'int'`。
修正：`get_tokenizer()` 改為回傳 `lambda text: len(tokenizer(text))` 而非原始 tokenizer。
觸發時機：撰寫 `sparse_model_comparison.py` RAG 評估實驗腳本時發現。
---
## [2026-06-09] `VectorStoreIndex.docstore.docs` with external Qdrant store is always empty — all GT samples skipped, Recall@5 = 0.00 `[版本: poc/rag-eval/sparse_model_comparison.py + LlamaIndex VectorStoreIndex + QdrantVectorStore]`
原因：`all_nodes = list(index.docstore.docs.values())` 永遠回傳空 list。當 `VectorStoreIndex` 以 `QdrantVectorStore`（包含 in-memory mode）建立時，LlamaIndex 不填入 in-memory docstore——nodes 直接送進 Qdrant。`index.docstore.docs` 永遠為 `{}`。結果：`find_relevant_ids(all_nodes, gt_passages)` 每次都收到空 list 並回傳 `[]`，112 個 GT sample 全數以 `reason=no_relevant_ids_found` 被略過，所有 4 個設定的 Recall@5 = 0.00。此問題無 exception，為靜默的錯誤行為。
修正：移除 `all_nodes = list(index.docstore.docs.values())`，將 `find_relevant_ids(all_nodes, ...)` 改為 `find_relevant_ids(nodes, ...)`（`nodes` 為傳入 `build_index()` 的原始 `TextNode` list，在 scope 內）。
規則：使用任何外部 vector store（Qdrant、Pinecone、Weaviate 等）搭配 `VectorStoreIndex` 時，絕不使用 `index.docstore.docs` 取回 node 文字——一律保留對原始 nodes list 的參照。
觸發時機：執行 `sparse_model_comparison.py` 時，所有設定的 Recall@5 均為 0.00。
---
## [2026-06-09] fastembed `SparseTextEmbedding` (SPLADE) with ONNX Runtime hangs indefinitely at Python shutdown `[版本: fastembed + ONNX Runtime / macOS]`
原因：ONNX Runtime 建立 per-session thread pool，Python GC 或 shutdown 時這些 thread pool 無法乾淨地 join（已確認 ONNX Runtime issues #4093、#20354）。fastembed 的 `SparseTextEmbedding` 沒有 `close()` 或 teardown API。影響所有在 macOS 使用 fastembed sparse model 的腳本。BM25 與 miniCOIL 也使用 ONNX 但較小——SPLADE（507MB）最嚴重。程式正常印出 `[END]`（所有邏輯完成、所有結果已寫入）後，process 無限掛起，需 Ctrl+C 終止。
修正：在 `main()` 回傳後加入顯式 flush 與 `os._exit(0)`：
```python
if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
```
`os._exit(0)` 完全跳過 Python GC，繞過掛起的 thread cleanup。只要所有檔案寫入與 print 在 `os._exit(0)` 之前完成（由 `flush()` 保證），此做法是安全的。
規則：任何使用 fastembed sparse model（尤其是 SPLADE）的腳本，結尾皆應加上 `flush() + os._exit(0)` 以避免 shutdown 掛起。
觸發時機：執行 `sparse_model_comparison.py` with SPLADE sparse model（`prithivida/Splade_PP_en_v1`, 507MB ONNX）。
---
## [2026-05-27] poc/rag-filtering: paper_frequency 超過 1.0，heading 頻率統計失準 `[版本: poc/rag-filtering/run_analysis.py]`
原因：`compute_stats()` 以 chunk 計數除以論文篇數（`len(records) / n_papers`）。一篇論文的 References 章節被 HybridChunker 切成多個 chunk（每個 reference 一組），每個 chunk 都帶相同的 heading，導致同一篇論文對同一個 heading 貢獻多次。結果：`references` 的 paper_frequency = 11.46（遠超 1.0）；只出現在 1 篇論文的 `input`/`target` heading 因 chunk 數多，誤判為 paper_frequency = 0.46（看似 46% 論文都有）。
修正：在每筆 record 加入 `paper_idx` 欄位（該論文的 index），`compute_stats()` 改為先 group by `(heading, paper_idx)` 做 per-paper dedup，再數有幾篇 paper 含此 heading，最後除以總篇數。`paper_frequency` 恢復為正確的 0.0~1.0 比例。
---
## [2026-05-27] poc/rag-filtering: always_filter exact match 命中率低，多數 heading 變體無法匹配 `[版本: poc/rag-filtering/filter_config.json]`
原因：`always_filter` 設計為 exact string match，但同一個語意的章節在不同論文有不同寫法（`"funding"` vs `"acknowledgments and disclosure of funding"`；`"reproducibility statement"` vs `"e.1 reproducibility statement"`）。28 篇論文統計後，原本 8 個 always_filter heading 只有 2 個以完全相同字串出現（`author contributions`、`checklist`），其餘 6 個因前綴數字、拼法變體、巢狀章節編號等原因未命中。
修正：`filter_config.json` 新增 `keyword_filter` 欄位，存放關鍵字片段（如 `"acknowledgment"`、`"broader impact"`、`"ethic"`），runtime 做 `any(k in normalized for k in keyword_filter)` contains matching。一個關鍵字可同時覆蓋多種變體，不需逐一列舉每個寫法。
---
## [2026-05-26] nomic-embed-text cosine scores low without asymmetric prefix `[版本: nomic-embed-text + Qdrant + LlamaIndex LiteLLMEmbedding + ollama]`
原因：nomic-embed-text 設計為 asymmetric retrieval；未加前綴時以 symmetric 模式運行，query/document alignment 偏弱；entity-heavy 查詢（BLEU scores、資料集名稱）純 dense 更差，需 BM25 或 hybrid。
修正：query 加 `"search_query: "` 前綴，document/chunk 加 `"search_document: "` 前綴；symmetric fallback 可將 threshold 從 0.70 降至 0.65；POC 後 Q1=0.726、Q2=0.779、Q3=0.684，全數通過。
---
## [2026-05-26] Docling `generate_picture_images=True` does not auto-write images to disk `[版本: Docling + Python]`
原因：`PdfPipelineOptions(generate_picture_images=True)` 只將圖片以 base64 URI 存入 `PictureItem.image`（`ImageRef` 物件），不會自動寫入磁碟。
修正：需顯式呼叫 `el.get_image(result.document)` 取得 PIL image，再呼叫 `.save(path, "PNG")` 寫檔；正確迴圈：`for el, _ in result.document.iterate_items(): if isinstance(el, PictureItem): pil_img = el.get_image(result.document); pil_img.save(path, "PNG")`。
---
## [2026-05-18] Session restore after refresh shows EmptyCanvas even when workflow alive; "interrupted" banner shown on normal cancel `[版本: feat/supervisor-hitl]`
原因：Session restore 只將 `workflowId` 存入 `sessionStorage`，refresh 後其他狀態（`workflowPhase`、`paperCandidates`、`hitlRequest`、SSE stream）全部遺失；`workflowPhase` 維持 `'idle'` 導致 `canvasPhase='empty'`，partial restore 顯示錯誤畫面；cancelled workflow 的 `workflowId` 仍殘留在 storage 造成誤判。
修正：移除 session restore 機制，refresh = full reset；刪除 `frontend/lib/session.ts`，移除 `checkWorkflowStatusApi`、兩個 session `useEffect`，及 `backend/main.py` 的 `/workflow_status` endpoint；backend 已在 SSE disconnect 時透過 `is_disconnected() → wf.cancel()` 清理 workflow。
---
## [2026-05-18] After HITL submit, right panel shows "Loading outline..." instead of ProcessingCanvas `[版本: feat/supervisor-hitl]`
原因：`submitHitlFeedback` 呼叫 `setHitlRequest(null)` 但未更新 `workflowPhase`，phase 維持 `'awaiting-hitl'` → `canvasPhase='hitl'` → `OutlineCanvas(outline=undefined)` 觸發 `if (!outline)` fallback 顯示 "Loading outline..."。
修正：在 `submitHitlFeedback` 的 `setHitlRequest(null)` 之後加入 `setWorkflowPhase('running')`，讓 canvas 立即切換回 ProcessingCanvas；影響檔案：`frontend/hooks/useWorkflow.ts`。
---
## [2026-05-18] Clicking "Generate slides" crashes page with "This page couldn't load" `[版本: feat/supervisor-hitl]`
原因：`submitPaperSelection('select')` 呼叫 `setPaperCandidates(null)` 但未更新 `workflowPhase`，phase 停在 `'awaiting-paper-selection'` → `canvasPhase='paper-selection'` → `PaperDetailCanvas` 收到 `candidates={null}` → `null.map()` TypeError crash；舊版 ternary chain 在清空 `paperCandidates` 後自動 fallthrough 到 `'processing'`，refactor 後此隱含行為消失。
修正：在 `submitPaperSelection` select 分支的 `setPaperCandidates(null)` 旁加入 `setWorkflowPhase('running')`，React 18 batch 同一 render，`canvasPhase` 直接跳至 `'processing'`；影響檔案：`frontend/hooks/useWorkflow.ts`。
---
## [2026-05-18] User message bubble disappears after supervisor responds to non-research query `[版本: feat/supervisor-hitl]`
原因：`canvasPhase` 隱式由 `workflowId` 衍生；`data-supervisor-response` handler 呼叫 `setWorkflowId(null)` 重啟輸入框，導致 `canvasPhase='empty'`，ChatThread 的 `canvasPhase !== 'empty'` 條件失敗，user bubble 被隱藏；`data-no-results` 同樣觸發此問題。
修正：引入顯式 `WorkflowPhase` 狀態機（`idle | running | awaiting-paper-selection | awaiting-hitl | complete`）；新增獨立 `hasConversation: boolean` 控制 bubble 顯示；ChatThread 條件改為 `hasConversation`；`canvasPhase` 與 `isInputDisabled` 改由 `workflowPhase` lookup map 衍生；影響檔案：`frontend/hooks/useWorkflow.ts`、`frontend/lib/types.ts`、`frontend/components/chat/ChatThread.tsx`、`frontend/components/ResearchAgentApp.tsx`。
---
## [2026-05-17] Paper Q&A user bubble 不顯示，但 LLM 回應正常顯示 `[frontend: useWorkflow / ChatThread]`
原因：`handleSubmit` 在 `paper-selection` phase 呼叫 `submitPaperQuestion` 而非 `sendMessage`，AI SDK `messages` array 從未更新，沒有 user bubble 的資料來源。
修正：新增 `paperQAHistory: {question, answer}[]` state，直接 render user bubble 與 answer；不依賴 AI SDK messages array。`ChatThread.tsx` 從該 array render user bubble。
---
## [2026-05-17] LLM 回答 paper question 含 markdown 語法（**bold**、*italic*） `[backend: prompts.py]`
原因：`PAPER_QUESTION_PMT` 沒有 plain text 指令，LLM 預設使用 markdown 格式回答。
修正：prompt 加入 `"Be concise (2-4 sentences). Plain text only — no markdown, no bold, no asterisks."`。
---
## [2026-05-17] User bubble 在 New Search 後殘留，canvasPhase 已回到 empty 但仍顯示 `[frontend: ChatThread]`
原因：`reset()` 清除自訂 state，但 AI SDK `messages` array 由 SDK 管理無法清除，舊 user bubble 資料仍存在。
修正：`ChatThread.tsx` 加 `canvasPhase !== 'empty'` guard，phase 為 empty 時隱藏 user bubble。
---
## [2026-05-17] User bubble 要等 LLM 回應後才一起顯示，無即時反饋 `[frontend: useWorkflow]`
原因：`submitPaperQuestion` 單次 setState 在 `await` 之後，question 和 answer 同時出現。
修正：分兩次 setState：先 `{question, answer: ''}` 顯示 user bubble + "Thinking..."，await 回應後再填入 answer。
---
## [2026-05-17] LLM 錯誤「修正」模型名稱拼寫（如 Memba → MemNN 而非 Mamba） `[backend: prompts.py]`
原因：`SEARCH_PARAMS_EXTRACTION_PMT` 無 proper noun 保留指令，LLM 試圖修正使用者拼錯的模型名稱，但猜錯方向（Memba → MemNN 而非 Mamba）。
修正：prompt 加入 `"Do not attempt to correct or expand proper nouns, model names, or acronyms (e.g. BERT, GPT, Mamba, LoRA, RoFormer) — preserve them exactly as given."`。
---
## [2026-05-17] Workflow timeout 800s 後 UI 卡死，paper selection 回傳 404 無法操作 `[backend: main.py / frontend: useWorkflow]`
原因：`SummaryGenerationWorkflow(timeout=800)` 包含 HITL 等待時間。Timeout 後 `workflows.pop()` 移除 wf，前端送選擇回傳 404，frontend 無清除機制，PaperSelectCard 卡住無法操作。
修正：(1) `timeout=800` → `timeout=3600`；(2) `main.py` 捕獲 `asyncio.TimeoutError` → yield `data-no-results` 通知 frontend 清除狀態；(3) `useWorkflow.ts` `submitPaperSelection` 加 try/catch，404 時呼叫 `reset()`。
---
## [2026-05-17] Browser refresh 導致 workflow 資源洩漏，user_input_future 永遠 pending `[backend: main.py / summarize_and_generate_slides.py]`
原因：Refresh 導致 SSE 斷線，backend 不知道，workflow 繼續佔用 memory 和 asyncio task；若在 HITL 等待階段，`user_input_future` 永遠不會被 resolve。
修正：(1) `summarize_and_generate_slides.py` 新增 `cancel()` method，resolve pending future；(2) `main.py` 加 `request: Request` 參數，迴圈內 `await request.is_disconnected()` 偵測斷線 → 呼叫 `wf.cancel()` 並 break；(3) `finally` block 永遠呼叫 `wf.cancel()` + `workflows.pop()`；(4) 新增 `/workflow_status/{id}` endpoint；(5) frontend 新增 `session.ts` 封裝 sessionStorage，mount useEffect 查詢 backend 確認 session 狀態。
---
## [2026-05-17] Next.js Docker build 失敗：`ReferenceError: sessionStorage is not defined` `[frontend: session.ts / useWorkflow.ts]`
原因：Next.js build 時 server 預渲染頁面，`useState` lazy initializer 在 Node.js 執行，`sessionStorage` 是瀏覽器專屬 API，Node.js 不存在。`useState(() => workflowSession.get())` 觸發 ReferenceError。
修正：(1) `session.ts` 加 `isBrowser = typeof window !== 'undefined'` SSR guard，server 環境所有操作為 no-op；(2) `useWorkflow.ts` 將 `useState(lazy init)` 改回 `useState(null)`；(3) mount `useEffect`（只在 browser 執行）加 `setWorkflowId(savedId)` 還原 alive session。
---
## [2026-05-17] Paper Q&A 使用 40-word re-summary 作為 LLM context，細節問題無法回答 `[backend: summary_gen.py]`
原因：`_paper_candidates_cache` 儲存的是 LLM 生成的 40-word `abstract_summary`（UI 顯示用），`handle_paper_question` 錯誤使用這份截斷資料回答問題，細節（dataset、metrics 等）已丟失。
修正：新增 `_paper_qa_context: [{title, abstract}]`，存 OpenAlex 原始完整 abstract；`handle_paper_question` 改用此 cache，職責與 `_paper_candidates_cache` 分離。
---
## [2026-05-17] `paper_titles` 截斷 title 至 50 字元導致 intent classifier 無法正確識別 paper `[backend: summary_gen.py]`
原因：`handle_paper_question` 傳給 intent classifier 的 `phase_context` 中，paper title 用 `c['title'][:50]` 截斷，LLM 可能無法辨識 user 在問哪篇 paper，導致 intent 分類錯誤。
修正：移除 `[:50]` 截斷，傳完整 title。token 增加幅度可忽略。
---
## [2026-05-17] `cited_by_count` 在 `_work_to_paper()` 未 map，citation 資料全程丟失 `[backend: paper_scraping.py]`
原因：OpenAlex 有回傳 `cited_by_count`（用於 filter/sort），但 `_work_to_paper()` 轉換時未 map 進 `Paper` model，後續 `PaperCandidate`、frontend 均無此欄位。
修正：`Paper` model 加 `cited_by_count: Optional[int]`；`_work_to_paper()` 加 `cited_by_count=result.get("cited_by_count")`；`PaperCandidate` 加欄位；`summary_gen.py` 建構 candidate 時帶入；`types.ts` + `PaperDetailCanvas.tsx` 顯示。
---
## [2026-05-17] Paper 顯示順序以 similarity 排序，非 citation（原意是經典論文優先） `[backend: summary_gen.py]`
原因：`fetch_candidate_papers` OpenAlex 以 `cited_by_count` 排序，但 `filter_papers` 並行執行後順序打亂，`present_paper_candidates` 以 `similarity_score` 重排，citation 排序丟失。
修正：`present_paper_candidates` 改用 `key=lambda e: (e.paper.cited_by_count or 0, e.relevance.similarity_score)`，citations 為主、similarity 為次。
---
## [2026-05-17] `frontend/components/chat/PaperSelectCard.tsx` 被 `.gitignore` 的 `chat` pattern 忽略，未被 git 追蹤 `[git: .gitignore]`
原因：`.gitignore` 有 `chat` pattern（原意是忽略 Aider chat log），同時也 match `frontend/components/chat/` 目錄，導致該目錄下所有未追蹤的新檔案被忽略。已 commit 的檔案（如 `ChatThread.tsx`）不受影響。
修正：`.gitignore` 將 `chat` 改為 `.aider.chat*`，只忽略 Aider chat log 檔。再用 `git add` 將 `PaperSelectCard.tsx` 加入追蹤。
---
## [2026-05-12] Next.js standalone server fails to start in Docker: `getaddrinfo EAI_AGAIN <container-id>` `[版本: Next.js 15 / Node.js 20-alpine / Docker standalone mode]`
原因：Next.js `output: 'standalone'` 的 `server.js` 呼叫 `http.server.listen(port, hostname)`，hostname 來自 `os.hostname()`，在 Docker 內部回傳 container ID（如 `ada83d192ec1`）；Node.js 呼叫 `getaddrinfo()` 解析此 hostname，但 Docker 內部 DNS 無法解析自身 container ID，拋出 `EAI_AGAIN`。
修正：在 Dockerfile runner stage 加入 `ENV HOSTNAME=0.0.0.0`，覆蓋 `os.hostname()` 回傳值，使 server 直接 bind 到 wildcard address，不觸發 DNS 查詢。影響檔案：`frontend/Dockerfile`。
---
## [2026-05-09] shadcn ToggleGroup (base-ui) `value` 型別是 `string[]` 非 `string` `[版本: shadcn@4.7+ / base-ui]`
原因：shadcn 4.7+ 預設使用 base-ui 的 ToggleGroup，`value` 是 `readonly string[]`，`onValueChange` 簽名是 `(groupValue: string[], ...) => void`；Radix UI 的 `type="single"` 模式不存在，直接套用會有 TypeScript 型別錯誤。
修正：state 改為 `useState<string[]>([])`，用 `selection[0] ?? ""` 取得單選值；`multiple={false}`（預設）維持單選行為。
---
## [2026-05-09] `ResizablePanelGroup` prop 是 `orientation` 不是 `direction` `[版本: react-resizable-panels 新版]`
原因：舊版 react-resizable-panels 使用 `direction`，新版改為 `orientation`，TypeScript 會報 property does not exist，但 shadcn 的 wrapper 透過 `...props` spread，錯誤訊息不直觀。
修正：將 `direction="horizontal"` 改為 `orientation="horizontal"`。
---
## [2026-05-09] `ScrollArea` 在 flex column 中需加 `min-h-0` 才能滾動 `[通用]`
原因：flex item 預設 `min-height: auto`，內容超出時 flex item 跟著撐高而非被壓縮，導致 ScrollArea 無固定高度可滾動，內容直接溢出容器。
修正：ScrollArea 加上 `min-h-0` class（`min-height: 0`），允許 flex item 被壓縮至 flex-1 分配的空間，ScrollArea 才有確定高度可滾動。
---
## [2026-05-09] 新增 `event_type` 值需同步更新 Pydantic `Literal` 約束 `[版本: 專案 WorkflowStreamingEvent]`
原因：`schemas.py` 的 `WorkflowStreamingEvent.event_type` 定義為 `Literal["server_message", "request_user_input"]`，新增 `"paper_total"` 後若未更新 Literal，Pydantic 解析時直接拋 ValidationError，錯誤訊息指向 `event_type` field 但原因不直觀。
修正：在 `schemas.py` 的 Literal 加入新值 `"paper_total"`，再於 `main.py` 的 event_generator 加對應 elif 分支。
---
---
## [2026-04-19] Ollama fallback 對 optional str 欄位回傳 `null`，Pydantic v2 拒絕（`default=""` 不處理 explicit null）`[通用: Pydantic v2 + Ollama fallback]`
原因：Pydantic v2 的 `field: str = Field(default="")` 只在 key 缺席時套用 default；Ollama 輸出 `"suggestion_to_fix": null`（key 存在但值為 null），Pydantic 嚴格拒絕 `null → str` 強制轉換，拋 `Input should be a valid string`。
修正：定義 `NullableStr = Annotated[str, BeforeValidator(lambda v: "" if v is None else v)]`，在 parse 邊界將 null 正規化為空字串；所有語意等價於空字串的 str 欄位改用此 type alias，`Optional[str]` 只用在 None 與 "" 有不同語意的欄位。
---
## [2026-04-19] Ollama fallback 回傳 JSON 被 markdown fences 包裹，`model_validate_json` 失敗 `[通用: Ollama fallback + structured output]`
原因：Cloud model（Gemini）支援 `response_format` JSON 約束，回傳純 JSON；Ollama fallback 不支援此約束，在 JSON 外包上 ` ```json...``` ` fences，`model_validate_json(response.text)` 第一個字為 `` ` `` 而非 `{`，解析失敗。
修正：在 `LiteLLMMultiModal._clean_response_text()` 統一處理：`response_format is not None` 時自動 strip fences（`removeprefix("```json").removeprefix("```").removesuffix("```")`），集中於 service 層，workflow step 不需各自防禦。
---
## [2026-04-15] `FunctionCallingProgram` + Ollama `qwen3.5:2b` + 巢狀 array schema（`List[ParagraphItem]`）輸出 `{"argument_name": ..., "argument_value": ...}` 包裝，Pydantic validation fail `[版本: litellm 1.82.0 / 模型: qwen3.5:2b]`
原因：`SlideOutline.content` 從 `str` 改為 `List[ParagraphItem]`（巢狀 array of objects）後，`qwen3.5:2b` 的 function calling 無法正確處理複雜 nested schema，改以 `{"argument_name": "content", "argument_value": "[...]"}` 包裝格式輸出，導致 `title` 與 `content` 兩個 required fields 皆 missing。注意：同一模型在 `content: str`（簡單 schema）時 function calling 正常；schema 變複雜才觸發此問題，與 [2026-03-28] 的 `{"properties": {...}}` 格式是同類問題的不同表現。
修正：`slide_gen.py` 的 `summary2outline` step 將 `_fc_program`（`FunctionCallingProgram`）換為 `_text_program`（`LLMTextCompletionProgram`）；`LLMTextCompletionProgram` 將 JSON schema 嵌入 prompt text，不走 tool calling API，對任何 LLM 均相容。`_text_program` 預設使用 `_smart_llm`，比原本的 `_fast_llm` 慢，可視需求明確傳入 `llm=self._fast_llm`（須先確認該 model 能正確解析巢狀 schema）。
結論：Ollama 本地模型的 function calling 對簡單 schema（純 `str`/`int` fields）尚可用；含 nested array of objects 的 schema 請一律改用 `LLMTextCompletionProgram`。
---
## [2026-04-13] PPTX placeholder 的 `name` 欄位無語意，不可用字串比對識別用途 `[通用]`
原因：`placeholder.name` 是 template 工具的 display label（如 `"Google Shape;10;p36"`），命名慣例因工具而異，不含 "Title"/"Body" 等語意，字串比對在非標準 template 上失效。
修正：改用 `placeholder.placeholder_format.type`（`PP_PLACEHOLDER` enum，`TITLE=1` / `BODY=2`）過濾，此為 OpenXML 規格定義，跨所有 PPTX template 通用。
---
## [2026-04-09] pptx2images — MuPDF "No common ancestor in structure tree" 警告 `[通用]`
根本原因（版本升級問題，原作者程式碼本身沒有錯）：
1. LibreOffice 25.2.3（Debian 13）的 bug：Impress PDF export 生成格式不合規的 Tagged PDF，`/StructTreeRoot /K` 直接包含 16 個跨不同 page 的 structure elements，缺少共同根節點，違反 PDF/UA spec。MuPDF 每個 page 驗證一次，5 張投影片產生 5 次 error 後 fallback 到 content stream rendering。LibreOffice 7.4（Debian 12）無此 bug。
2. Dockerfile 未鎖版本：`FROM python:3.12-slim` 無 digest pinning，底層 Debian 從 12 (Bookworm) 升至 13 (Trixie)，LibreOffice 從 7.4.7 跳至 25.2.3，引入此 bug。
影響：Non-blocking warning。Smoke test 確認 PNG 輸出 byte-identical，Tagged PDF 結構樹僅用於 accessibility，不影響 rasterization。
修正方法：修改 `utils/file_processing.py` 的 `pptx2pdf()`，在 LibreOffice 指令加 JSON filter string 停用 Tagged PDF，從根本消除問題：
  修改前：`"--convert-to", "pdf",`
  修改後：`"--convert-to", 'pdf:impress_pdf_Export:{"UseTaggedPDF":{"type":"boolean","value":"false"}}',`
  說明：JSON filter string 語法非官方文件記載，但為 Gotenberg/unoconv/JODConverter 廣泛採用的 de-facto 標準，LibreOffice 7.4 與 25.x 均相容。UNO Python API 雖更標準但在 Docker subprocess 架構下複雜度過高。
詳細分析：`dev-tracker/poc/problem2_mupdf_analysis.md`、`dev-tracker/poc/problem2_libreoffice_api_research.md`
---
## [2026-04-09] Frontend — workflow error 後 NoneType 警告 `[通用]`
原因：Backend workflow 在 validate_slides crash 後，最後一個 event 為 `None`；Frontend 的 workflow info 格式化函式未對 `None` 做防守性檢查，直接呼叫 `.get()` 導致 `'NoneType' object has no attribute 'get'`。
修正方法：兩層修正並行實施。(1) **Backend 根本原因**：`main.py` 的 event_generator() 在 workflow crash 時發送的 error event 格式為 `{"event": "error", "message": "..."}` — 缺少 `event_content` key，不符合標準 `WorkflowStreamingEvent` 結構；改為以 `WorkflowStreamingEvent(event_type="server_message", event_sender="system", event_content={"message": error_message})` 格式發送，確保所有 event 都有 `event_content`。(2) **Frontend 防禦**：`slide_generation_page.py` 的 `format_workflow_info()` 第 89 行 `event_content.get('message')` 在取得 `event_content` 之前加 `None` guard：`if event_content is None: return json.dumps(info_json)`，避免任何非標準 event 格式造成 AttributeError。
---
## [2026-04-09] Agent 產生無效 python-pptx API 呼叫 — add_slide() 不接受 position argument `[通用]`
原因：`SLIDE_GEN_PMT` 的 code pattern 示範了標準 slide 建立，但未明確說明 `add_slide()` 只接受 `SlideLayout` 一個參數。Agent 根據 prompt 要求「若缺少 front/thank-you slide 需補上」，自行推測出不存在的 `prs.slides.add_slide(layout, 0)` API（position argument），此次因條件未觸發未爆炸，但屬潛在 runtime error。
修正方法：兩層修正。(1) **立即修（prompt 層）**：`SLIDE_GEN_PMT` 的模糊指示 `"If there is no front page or 'thank you' slide, add them using the appropriate layout"` 替換為明確的 pre/post loop 模式並加 CRITICAL 禁止語句：在 loop 之前先 `add_slide()` 封面（使得它成為第一張），在 loop 之後再 `add_slide()` 感謝頁；並明確標注 `prs.slides.add_slide(layout, 0)  # WRONG — raises TypeError`，python-pptx 無任何 insert-at-position API（context7 查詢確認，`Slides` 只有 `add_slide`、無 `insert_slide`/`move_slide`；`_sldIdLst` 為 private XML，無公開 API）。(2) **長期根本解（workflow 層，Option D）**：在 `slide_gen.py` 的 `outlines_with_layout` 步驟，Python code 直接向 `slides_w_layout` list 的首尾注入封面與感謝頁的 `SlideOutlineWithLayout` 物件（layout 名稱與 placeholder index 從 `self.pptx_spec.all_layout` 動態查詢），使 JSON 已包含所有 slides；`SLIDE_GEN_PMT` 改為 `"The JSON already contains ALL slides in order. Loop through EVERY item — do NOT add extra slides."`，完全消除 LLM 的條件判斷與 hallucination 空間。
---
## [2026-03-31] `template-en.pptx` 含三個中文 layout 名稱（項目符號、照片-一頁三張、空白），英文模型於 layout selection 時視而不見 `[環境: template-en.pptx 初始版本]`
原因：template 命名暗示全英文，但三個 layout 仍為中文，英文 LLM 無法將這些名稱與 slide 語意對應，實驗中從未被選中，導致準確率被低估。
修正：以 python-pptx 修改 XML 將三個 layout 重命名：項目符號 → BULLET_LIST、照片-一頁三張 → THREE_PHOTO、空白 → BLANK；實驗 prompt 與 expected set 同步更新。
---
## [2026-03-31] `SlideOutlineWithLayout` schema 強制 `idx_title_placeholder` / `idx_content_placeholder` 為必填 `str`，導致 THREE_PHOTO、FULL_PHOTO、BLANK 永遠 Pydantic validation fail `[通用]`
原因：這三個 layout 在 template 裡沒有 title/content placeholder，LLM 即使正確選出 layout name，仍因無法填入有效 idx 而輸出 null，Pydantic 拒絕 null → FAIL，appropriate rate 被低估。
修正：將 schema 的兩個 idx 欄位改為 `Optional[str] = None`，並同步更新 `slide_gen` agent 處理 idx 為 None 的情況。
---
## [2026-03-28] `FunctionCallingProgram` + Ollama 模型（via LiteLLM）回傳 `{"properties": {...}}` 包裝，Pydantic 5 fields missing，success rate 0% `[版本: litellm 1.82.0 + llama-index-llms-litellm 0.6.3 / 模型: gemma3:4b, qwen3.5:4b]`
原因：Ollama 模型在 function calling 呼叫中將 JSON Schema 的 `"properties"` 結構原樣輸出（schema 定義層），而非填入實際值（arguments 層）；即使透過 `litellm.register_model()` 宣告 `supports_function_calling=True` 使呼叫能到達 API，模型行為本身仍輸出錯誤格式，導致 LlamaIndex Pydantic 解析時所有 required fields 皆 missing。
修正：`slide_gen.py` 的 `outlines_with_layout` step 將 `FunctionCallingProgram` 換為 `LLMTextCompletionProgram`（不走 tool/function calling API，改走 prompt 內嵌 JSON schema 路徑，對任何 LLM 均相容）；若僅使用 Ollama，可改在 `LiteLLM` 的 `additional_kwargs` 傳入 `{"format": SlideOutlineWithLayout.model_json_schema()}`（Ollama server-side constrained generation），兩者均可達 100% success rate；cloud provider（Groq、Gemini）的 `FunctionCallingProgram` 呼叫不受影響，可透過 `config.py` flag 區分路徑。
---
## [2026-03-27] `ArtifactSandboxSession` init noise 污染 LLM tool observations，ReActAgent 無限 loop `[通用: llm-sandbox + ReActAgent]`
原因：`ArtifactSandboxSession` 預設 `enable_plotting=True`，在每個 `session.run()` 的 stdout 前插入 "Python plot detection setup complete
"；同時每次 `run()` 都在 `/sandbox/` 建立 UUID 命名的 `.py` 執行檔但從不清除，導致 `list_files` 回傳大量 UUID 殘檔。兩者共同污染 LLM tool observations，ReActAgent 誤判環境狀態後無限呼叫 `list_files`。
修正：(1) `run_code()` 與 `list_files()` 中的 `ArtifactSandboxSession` 呼叫均加 `enable_plotting=False`；(2) 在 `list_files()` 加 `_SANDBOX_ARTIFACT_RE = re.compile(r'^[0-9a-f]{32}\.[a-z]+$')` 過濾器，從結果中移除所有 UUID 執行產物。驗證：`run_code` 回傳乾淨 stdout；空 sandbox 時 `list_files_str` 回傳 `'(no files in /sandbox)'`。
影響檔案：`backend/services/sandbox.py`
---
## [2026-03-27] SSE 格式不符 W3C spec 且 `"Reasoning: "` prefix 重複拼接，Streamlit 顯示亂碼 `[通用: FastAPI SSE + Streamlit]`
原因：`run_react_agent()` 對每個 streaming token delta 都拼接 `"Reasoning: "` prefix，前端收到後 concatenate 成 "Reasoning: ThoughtReasoning: :Reasoning:  I..." 亂碼；同時 SSE yield 格式為裸 JSON 字串，不符 W3C SSE `data: ...

` 規格，與 Vercel AI SDK 不相容。
修正：(1) `main.py` 所有 SSE yield 改為 `f"data: {msg_str}

"`；(2) `slide_gen.py` 移除 `"Reasoning: "` prefix，改用 `_emit_message()` helper 直接傳遞 `ev.delta`；(3) `slide_generation_page.py` SSE 解析改為先 strip `data:` prefix 再 JSON.loads。戰略理由：對齊 W3C SSE 規格為未來遷移至 Vercel AI SDK 鋪路（Vercel AI SDK 是唯一同時支援 HITL 與自訂 workflow progress event 的前端選項）。
影響檔案：`backend/main.py`、`backend/agent_workflows/slide_gen.py`、`frontend/pages/slide_generation_page.py`
---
## [2026-03-27] Ollama 本地 LLM token-by-token streaming 在 Streamlit st.status 造成逐字顯示 `[環境: Ollama local LLM + Streamlit ≥1.55]`
原因：Ollama 以單 token 為單位 streaming（`AgentStream.delta` 每次一個詞），Streamlit 升級後 `st.expander`（收合）換成 `st.status(expanded=True)`，每個 token 各佔一行並帶分隔線，數百行暴露給使用者；cloud LLM（Gemini/Groq）以詞組為單位送 chunk 故舊版無此問題。
修正：frontend `get_stream_data()` 將 `event_sender == "react_agent"` 的事件改送 `("reasoning", msg)` 至 queue；`process_messages()` 以 `+=` concatenate 到 `current_reasoning`（而非 append 至 `received_lines`）；`workflow_display()` 新增獨立 `st.code` 區塊顯示累積 reasoning，每 2s rerun 時呈現完整句子而非逐字。
---
## [2026-03-26] `run_subworkflow` 轉發 StopEvent 至 parent context，main.py 無 guard 導致 SSE 連線中斷 `[通用]`
原因：`handler.stream_events()` 設計上會 yield `StopEvent` 作為終止信號；`run_subworkflow` 無條件 `ctx.write_event_to_stream(event)` 將其注入 parent stream，`main.py` 又無條件存取 `ev.msg`（`StopEvent` 無此欄位），拋出 `AttributeError`，SSE generator 進入 except block → workflow 從 dict 移除，前端連線中斷
修正：`run_subworkflow` 加 `if isinstance(event, StopEvent): continue` 過濾非 user-facing event；`main.py` event loop 加 `hasattr(ev, 'msg')` guard，避免單一 event 異常炸掉整條 SSE 連線
---
## [2026-03-26] Ollama qwen3.5 觸發 `FunctionCallingProgram` "does not support function calling API" `[版本: litellm 1.82.0 + llama-index-llms-litellm 0.6.3]`
原因：LiteLLM 以 `/api/show` 回傳的 Modelfile template 是否含 `"tools"` 字串判斷 function calling 支援；qwen3.5 的 template 只有 `{{ .Prompt }}`，不含 `tools`，導致 `is_function_calling_model=False`，LlamaIndex 的 `FunctionCallingProgram.from_defaults()` 在發 API 前就 raise。
修正：`model_factory.py` 的 `_build()` 呼叫 `_register_ollama_function_calling()`，用 `OllamaModelInfo().get_models()` 動態列出所有本地 Ollama models，透過 `litellm.register_model()` 顯式宣告 `supports_function_calling=True`；過濾掉已有 `ollama/` prefix 的 fallback entries 避免 offline 時雙重 prefix。
---
## [2026-03-26] `OllamaModelInfo.get_models()` Ollama offline 時靜默回傳 `['ollama/llama2']` 而非空 list `[通用]`
原因：LiteLLM 刻意設計 graceful degradation，`/api/tags` 失敗時 fallback 到 `litellm.models_by_provider["ollama"]`（hardcoded `["llama2"]`）並加 `ollama/` prefix；不 raise exception，有 unit test 驗證此行為。
修正：呼叫後過濾掉已帶 `ollama/` prefix 的項目（`if not name.startswith("ollama/")`），offline 時 register 空 dict，避免注入錯誤的 `ollama/ollama/llama2`。
---
## [2026-03-26] `LiteLLMMultiModal` AttributeError: rate_limiter，llama-index-core 版本漂移所致 `[版本: llama-index-core>=0.14.19]`
原因：`llms/callbacks.py` wrapper 在 0.14.19 新增 `if _self.rate_limiter is not None:`，同時套用到 `BaseLLM`（有此 field）和 `MultiModalLLM`（無此 field）；Dockerfile 缺 `poetry.lock`，docker build 自由解析到 0.14.19，本地 lock 鎖在 0.14.15，環境不一致使問題只在 docker 觸發。
修正：`LiteLLMMultiModal` 加 `rate_limiter: Optional[Any] = Field(default=None, exclude=True)`；Dockerfile 改為 `COPY pyproject.toml poetry.lock /app/` 鎖定版本。
---
## [2026-03-26] litellm 在 mock 攔截前嘗試 fetch 外部 https:// image URL，導致 pytest hang `[通用: litellm + unittest.mock]`
原因：`patch("services.multimodal.litellm.completion")` 對純文字 call 有效，但訊息含 `image_url` 且為外部 URL 時，litellm 內部先 fetch 該 URL，此行為發生在 mock 接手之前；`example.com` 無回應導致 test 無限 hang。
修正：測試中一律改用 image bytes（`image=raw_bytes, image_mimetype="image/jpeg"`），完全不使用外部 URL；fixture 圖片放 `tests/fixtures/`，一次載入為 `_TEST_IMAGE_BYTES` 共用。
---
## [2026-03-26] config.py 必填欄位（MLFLOW_TRACKING_URI 等）無 default，本機測試缺值直接 ValidationError `[環境: 無 docker-compose]`
原因：`MLFLOW_TRACKING_URI`、`WORKFLOW_ARTIFACTS_ROOT`、`SLIDE_TEMPLATE_PATH` 由 docker-compose 環境變數注入，無 default；本機跑 pytest 時 `.env` 未包含這些欄位，`Settings()` 在 import 時直接拋 `ValidationError`，所有 import 該模組的 test 全部 collection error。
修正：在 `.env` 加入本機 stub 值（`MLFLOW_TRACKING_URI=http://localhost:8080` 等），或在 `conftest.py` 以 `os.environ.setdefault` 補設。
---
## [2026-03-26] pydantic BaseSettings v2 對 .env 裡已移除的欄位拋 `extra_forbidden` `[版本: pydantic-settings>=2.0]`
原因：config.py 移除舊欄位（如 `TAVILY_MAX_RESULTS`、`NUM_MAX_CITING_PAPERS`）後，`.env` 若仍保留這些 key，pydantic v2 預設行為為拒絕並報 `Extra inputs are not permitted`；錯誤訊息不直觀，容易誤判為欄位格式問題。
修正：每次移除 config 欄位後，同步清理 `.env` 中對應的舊 key；`.env.example` 可作為 canonical reference 確認哪些 key 仍有效。
---
## [2026-03-20] pyalex `work.get("abstract")` 永遠回傳 None，需從 `abstract_inverted_index` 手動重建 `[通用]`
原因：OpenAlex API 以倒排索引格式儲存 abstract（`{word: [pos, ...]}`），`abstract` 欄位本身為空；pyalex 文件所述的自動重建在 list/singleton 呼叫中均未生效。
修正：從 `work["abstract_inverted_index"]` 反轉為 `{pos: word}`，按 key 排序後 join 成純文字；約 20% paper 在 OpenAlex 本身無 abstract（資料源限制，非 API 問題）。
---
## [2026-03-19] pyalex 預設 max_retries=0，similar() endpoint 偶發 HTTP 500 直接 crash `[通用]`
原因：pyalex 預設 `max_retries=0`，similar() 語義搜尋 endpoint 偶發 HTTP 500，直接 raise 不重試
修正：config 區設定 `pyalex.config.max_retries = 5` 與 `pyalex.config.retry_backoff_factor = 0.5`
---
## [2026-03-19] OpenAlex `work["ids"]` 不含 ArXiv ID，必須從 `locations` 解析 `[通用: pyalex]`
原因：OpenAlex 設計上 ArXiv 不列入 `ids` 欄位，只出現在 `locations[*]["landing_page_url"]`（如 `http://arxiv.org/abs/1706.03762`）。
修正：掃描 `work["locations"]`，找含 `"arxiv.org"` 的 `landing_page_url`，切最後一段取 ID；`pdf_url` 缺席時用 `f"https://arxiv.org/pdf/{arxiv_id}"` 構造。
---
## [2026-03-19] OpenAlex title search 拿到無 ArXiv 的出版版，ArXiv preprint 是未合併的獨立 record `[通用: pyalex title search]`
原因：同一篇論文的 publisher 版（如 AAAI）與 ArXiv preprint 有時是兩個未 dedup 的 OpenAlex record；`search_filter(title=).get(per_page=1)` 優先回傳引用數高的出版版，其 `locations` 無 `arxiv.org`，preprint record 被忽略。
修正：改為 `get(per_page=3)`，逐一掃描每個 record 的 `locations`，優先回傳含 `arxiv.org` 的 record；全無時 fallback 回第一筆。
---
## [2026-03-19] 學術出版商（AAAI OJS 等）對 `python-requests` User-Agent 回 403 `[通用]`
原因：AAAI OJS 伺服器黑名單封鎖 `python-requests/x.x.x` UA；`requests.get()` 預設不帶 browser UA，伺服器直接拒絕，curl 同 URL 無此問題。
修正：統一定義 `_BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 ... Chrome/120.0.0.0 ..."}` 並套用至所有 `requests.get(url, headers=_BROWSER_HEADERS)`。
---
## [2026-03-16] Breaking API change 修改時未全面搜尋 codebase，導致同一問題多處重複出現 `[通用]`
原因：修改 `run_subworkflow` 的 `stream_events()` 時，只修了當前報錯的地方，未搜尋 `main.py` 等其他使用相同舊 API 的位置，導致下次測試又出現相同錯誤。
修正：任何 breaking API change，先用 Grep 全面搜尋 codebase 所有使用位置，再用 context7 查最新 API，列出完整影響清單後一次修改完畢。
---
## [2026-03-16] llama-index-core 0.14.x `@step(pass_context=True)` 移除 `[版本: llama-index-core>=0.13.0]`
原因：0.14.x 的 `ctx: Context` 透過 type annotation 自動注入，`pass_context=True` 參數不再需要且已移除，使用會造成 `unexpected keyword argument`。
修正：所有 `@step(pass_context=True)` 改為 `@step`；有 `num_workers` 的改為 `@step(num_workers=N)`。
---
## [2026-03-16] llama-index-core 0.14.x `self.send_event()` 改為 `ctx.send_event()` `[版本: llama-index-core>=0.13.0]`
原因：0.14.x 將事件發送從 Workflow 實例方法改為 Context 方法，`self.send_event(ev)` 不再存在（會靜默失敗或 AttributeError）。
修正：所有 step 內的 `self.send_event(ev)` 改為 `ctx.send_event(ev)`。
---
## [2026-03-16] llama-index-core 0.14.x `Context.data` dict 完全移除 `[版本: llama-index-core>=0.13.0]`
原因：0.14.x 將 `ctx.data` dict 改為 async store API，舊的 `ctx.data["key"]` 拋出 `AttributeError: 'Context' object has no attribute 'data'`。
修正：寫入改為 `async with ctx.store.edit_state() as state: state["key"] = value`；讀取改為 `await ctx.store.get("key")`；concurrent step 的累加用 `edit_state()` 保證 atomic。
---
## [2026-03-16] llama-index-core 0.14.x 移除 `Workflow.add_workflows()` `[版本: llama-index-core>=0.13.0]`
原因：0.13.x 起 sub-workflow 注入改為 `Annotated[T, Resource(factory)]` DI 模式，`add_workflows()` 方法完全移除，呼叫時拋出 `AttributeError: object has no attribute 'add_workflows'`。
修正：改用 constructor injection——在 orchestrator `__init__` 接收 sub-workflow 實例為參數，存成 `self.xxx_wf`；`@step` 簽名移除 sub-workflow 參數，改用 `self.xxx_wf`；`main.py` 改為在建構時傳入。
---
## [2026-03-16] llama-index-core 0.14.x `stream_events()` 從 Workflow 實例移至 Handler `[版本: llama-index-core>=0.13.0]`
原因：`Workflow.run()` 改為同步回傳 `Handler` 物件，`stream_events()` 移到 Handler 上，Workflow 實例本身不再有此方法，呼叫 `sub_wf.stream_events()` 拋出 `AttributeError`。
修正（Approach A）：在 `run_subworkflow` 中直接呼叫 `Workflow.run(sub_wf, **kwargs)` 取得 Handler，改用 `handler.stream_events()` 與 `await handler`；並手動補設 `sub_wf.loop = asyncio.get_running_loop()`，因為繞過了 `HumanInTheLoopWorkflow.run()`。完整 Approach B 重構方案見 `BACKUP_PLAN.md`。
---
## [2026-03-16] `HumanInTheLoopWorkflow.run()` 為 `async def`，內部 `await Handler` 導致外部無法取得 Handler `[版本: llama-index-core>=0.13.0]`
原因：`HumanInTheLoopWorkflow.run()` override 為 `async def`，內部執行 `result = await super().run()`，將 `Workflow.run()` 回傳的 Handler 立即消化並回傳最終結果；呼叫端拿到 coroutine 而非 Handler，`handler.stream_events()` 無從取得。`SlideGenerationWorkflow` 的 HITL 步驟另依賴 `self.loop`（`self.loop.create_future()`），繞過此方法需手動補設。
修正：Approach A 繞過 `HumanInTheLoopWorkflow.run()`，直接呼叫 `Workflow.run(sub_wf)`；Approach B 將 `run()` 改為 sync def 並加 `MLflowAwareHandler` wrapper，詳見 `BACKUP_PLAN.md`。
---
## [2026-03-16] MLflow v3 security middleware 拒絕 Docker 容器間 Host header，回傳 403 `[版本: mlflow>=3.x]`
原因：MLflow v3 新增 security middleware，預設只允許 `localhost` 作為 Host header；backend 容器以 `http://mlflow:8080` 為 tracking URI，Host header 為 `mlflow:8080`，被 middleware 拒絕，log 顯示 `Rejected request with invalid Host header: mlflow:8080`，MLflow API 回傳 403。
修正：在 `docker-compose.yml` 的 mlflow `command` 加入 `--allowed-hosts mlflow,localhost,127.0.0.1`，允許 Docker 內部網路容器名稱作為合法 Host。
---
## [2026-03-16] LiteLLM model 字串必須帶 `{provider}/{model}` 前綴，否則報 LLM Provider NOT provided `[通用]`
原因：LiteLLM 以 model 字串的第一段作為 provider 識別（如 `groq/`、`gemini/`、`openrouter/`），若只寫 `model_name`（如 `qwen/qwen3-32b`，其中 `qwen` 不是合法 provider）則拋出 `BadRequestError: LLM Provider NOT provided`；唯一例外是 OpenAI（預設 provider）。
修正：所有 model 字串改為 `{provider}/{model}` 格式（如 `groq/moonshotai/kimi-k2-instruct`）；可用 `litellm.provider_list` 確認合法 provider 名稱。
---
## [2026-03-15] `draw_all_possible_flows` 從 `llama_index.core.workflow` 移至 `llama_index.utils.workflow` `[版本: llama-index-workflows>=2.9.0]`
原因：llama-index-workflows 2.9.0 起，`drawing.py` 中的舊函數 raise error，且 `llama_index.core.workflow.__init__.py` 不再 export `draw_all_possible_flows`，造成頂層 import 時 `ImportError`。
修正：從 `[tool.poetry.dependencies]` 新增 `llama-index-utils-workflow = ">=0.9.5"`；將 `draw_all_possible_flows` 的 import 從模組頂層移入 `if __name__ == "__main__":` 區塊，改用 `from llama_index.utils.workflow import draw_all_possible_flows`。
影響檔案：`backend/agent_workflows/summarize_and_generate_slides.py`、`backend/agent_workflows/summary_gen.py`。

## [2026-03-15] `docker-compose build` 通過不代表 backend runtime import 正常 `[驗收流程盲點]`
原因：`docker-compose build` 只建立 image（執行 Dockerfile），不執行 Python import。Backend 的 `ImportError` 只會在 container 啟動執行 `uvicorn main:app` 時才觸發。若 `.env` 未設定導致 backend 也 crash，容易誤判為「env 問題」而忽略真正的 `ImportError`。
修正：驗收流程改為 `docker-compose up --build`（全服務啟動），確認 backend log 出現 `Uvicorn running` 且無 `ImportError`，再以 `curl http://localhost:8000/` 驗證健康狀態。不可只跑 `docker-compose build`。

---
## [2026-03-12] LlamaIndex `Workflow` base class 無法直接實例化 — `WorkflowConfigurationError: no @step accepts StartEvent` `[版本: llama-index-workflows>=2.x]`
原因：`Workflow.__init__` 驗證至少要有一個 `@step` 接受 `StartEvent`，直接實例化 base class（如 `HumanInTheLoopWorkflow`）沒有任何 step，立即拋出 `WorkflowConfigurationError`。
修正：測試中建立 concrete subclass，加入 dummy `@step async def handle_start(self, ev: StartEvent) -> StopEvent`，再實例化 subclass 執行測試。
---
## [2026-03-12] macOS Python pytest 執行時 `ssl.SSLCertVerificationError` — HTTPS 下載失敗 `[環境: macOS + python.org Python + poetry venv]`
原因：python.org 安裝的 Python 不連結 macOS Keychain 憑證，poetry venv 執行時 `SSL_CERT_FILE` 為空，`urllib` 無法驗證任何 HTTPS 憑證（包含 arxiv.org）。
修正：在 `tests/conftest.py` 最頂端加 `import certifi; os.environ.setdefault("SSL_CERT_FILE", certifi.where())`，讓所有測試繼承 certifi CA bundle。
---
## [2026-03-12] LlamaIndex `ChatMessage(content="text").content` 回傳 content blocks list 而非字串 `[版本: llama-index-core>=0.13（含 0.14.x）]`
原因：0.13+ 統一用 content blocks 格式儲存訊息，即使只傳 plain string，`ChatMessage.content` 也回傳 `[{"type": "text", "text": "..."}]`，而非原始字串，導致 `assert sent["content"] == "ping"` 失敗。
修正：測試中用 `isinstance(content, list)` 判斷後取出 text block 再比對，或改為 `assert "ping" in str(sent["content"])`。
---
## [2026-03-12] LlamaIndex `ImageDocument(image_url=...)` 建構子發 HTTP 請求驗證 URL 可存取性 `[版本: llama-index-core>=0.13（含 0.14.x）]`
原因：0.13+ 的 `ImageDocument.__init__` 對 `image_url` 欄位執行 validator，實際發 HTTP request 確認 URL 回傳圖片，假 URL（如 `https://example.com/img.jpg`）直接拋出 `ValueError: The specified URL is not an accessible image`，unit test 無法使用假 URL。
修正：unit test 改用 `types.SimpleNamespace(image_url=..., image=None, image_path=None, image_mimetype=None)` mock interface，完全繞過 LlamaIndex validator。
---
## [2026-03-11] `llama-index-core>=0.14` 附帶 `llama-index-workflows`，本地 `workflows/` 被 site-packages 覆蓋 `[版本: llama-index-core>=0.14]`
原因：`llama-index-workflows` v2.15.1 在 site-packages 安裝同名的 `workflows/` package（含 `__init__.py`），本地 `backend/workflows/`（無 `__init__.py`，namespace package）優先順序低，`from workflows.events import *` 實際取到 LlamaIndex 內部事件，自定義 `SummaryEvent` 等不存在，拋出 `NameError`。`__init__.py` 補救無效（會破壞 `llama_index.core` 自身對 `workflows.context` 的 import）。
修正：將本地 `workflows/` 改名為不衝突的名稱（本專案改為 `agent_workflows/`），並全局替換所有 `from workflows.` import。
---
## [2026-03-11] context7 MCP 不同查詢對同一 API 描述不一致，需多次查詢交叉驗證 `[通用]`
原因：不同 subagent 查詢 context7 MCP 得到矛盾結果（例如 `update_prompts()` 在第一次查詢被描述為已移除，第二次查詢才確認仍存在），原因可能是搜尋 token 不同導致命中不同文件段落。
修正：對關鍵 API 存在性有疑問時，至少發起兩次不同角度的 context7 查詢，或直接用 `hasattr()` 在實際環境中驗證，以實際執行結果為準。
---
## [2026-03-11] `ReActAgent.update_prompts({"react_header": PromptTemplate(...)})` template 不可含 `{context_str}` `[版本: llama-index-core>=0.14]`
原因：`react_header` 是固定 header prompt，agent 渲染時不傳入 `context_str` 這個 key，若 PromptTemplate 字串含 `{context_str}` 佔位符則拋出 `KeyError: 'context_str'`。
修正：`react_header` 的 PromptTemplate 只寫純文字 system prompt，不加任何 `{...}` 佔位符；若需動態變數，改在 `agent.run(prompt, ctx=ctx)` 的 prompt 字串中組合。
---
## [2026-03-11] `ReActAgent.from_tools()` / `agent.chat()` 在 llama-index-core 0.14.x 不存在 `[版本: llama-index-core>=0.14]`
原因：0.14.x 將 ReActAgent 重構為 Workflow-based，`from_tools()` classmethod 與同步 `chat()` 均移除；import 路徑、建構方式、執行方式全部改變，AttributeError 不直觀。
修正：`from llama_index.core.agent.workflow import ReActAgent`；建構改為 `ReActAgent(tools=tools, llm=llm, timeout=120)`（`max_iterations` → `timeout` 秒）；執行改為 `await agent.run("...")`，腳本層用 `asyncio.run(async_fn())` 包裝；多輪對話需傳入 `ctx=Context(agent)` 保留歷史。
---
## [2026-03-10] LiteLLM 1.80 gemini/text-embedding-004 路由錯誤，正確 model 為 gemini/gemini-embedding-001 `[版本: litellm==1.80]`
原因：LiteLLM 1.80 對 `gemini/` prefix 的 embedding model 統一使用 `batchEmbedContents` endpoint；但 `text-embedding-004` 已從 Google AI Studio API 移除，只剩 `gemini-embedding-001` 支援 `embedContent`。
修正：將 `LLM_EMBED_MODEL` 預設值改為 `gemini/gemini-embedding-001`（dim=3072）。
---
## [2026-03-10] poetry install 時 lock file 與 pyproject.toml 不同步需先執行 poetry lock `[通用]`
原因：直接修改 pyproject.toml 後執行 `poetry install`，lock file 版本不匹配導致 install 失敗並提示 "pyproject.toml changed significantly"。
修正：先執行 `poetry lock`（無需 `--no-update`），再執行 `poetry install --no-root`。
---
## [2026-03-09] macOS Python 3.12 spawn 模式導致 marker test script crash `[環境: macOS Python 3.12]`
原因：Python 3.12 on macOS 預設 `multiprocessing` 使用 `spawn`，子進程重新 import 主模組時執行 module-level 的 `paper2md()` 呼叫，觸發 `RuntimeError: bootstrapping phase`。
修正：將所有測試執行邏輯包進 `main()` 函數，並加上 `if __name__ == '__main__': main()`。
---
## [2026-03-09] `paper2md()` 每次呼叫重新載入模型，Test 1/2 各花 20-25 分鐘 `[版本: marker >= 1.0.0]`
原因：`paper2md()` 內部每次都呼叫 `create_model_dict()`，導致 5 個 surya 模型（共 3GB+）重複載入，MPS Metal shader 也需重新 warm up。
修正：在 `paper2md()` 加 `artifact_dict=None` 參數，外部統一建立後傳入重用；Test 2 可省下 ~5 分鐘模型重載時間。
---
## [2026-03-09] surya `Recognizing Text` 在 M1 MPS 上每次轉換耗時 12–18 分鐘 `[環境: Apple M1 / PyTorch MPS]`
原因：surya text recognition 使用 autoregressive encoder-decoder，PyTorch MPS 對此架構支援不完整（缺 FlashAttention、`torch.compile` 仍 early stage），MPS cold start 第一個 chunk 需 238s。
修正（緩解）：(1) 重用 `artifact_dict` 避免重複 warm up；(2) 設 `RECOGNITION_BATCH_SIZE=32~64`（預設 256 對 M1 16GB 可能造成 memory pressure）；(3) 繼承 `OcrBuilder` 並擴大 `skip_ocr_blocks`，跳過已有 pdftext 的 block types（`Text`、`SectionHeader` 等），保留 `TextInlineMath`；根本解需等 PyTorch MPS 成熟或改用 Apple MLX 框架。
---
## [2026-03-09] `RECOGNITION_BATCH_SIZE` 預設 256 可能造成 M1 memory pressure `[環境: Apple M1 16GB unified memory]`
原因：每個 batch item 佔 50MB，預設 256 = 12.8GB；M1 CPU/GPU 共用記憶體，surya 模型本身已佔 ~11GB，幾乎無剩餘空間，導致頻繁記憶體交換拖慢速度。
修正：設環境變數 `RECOGNITION_BATCH_SIZE=32` 或 `64` 執行；搭配 `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0` 可解除 PyTorch MPS 記憶體上限（注意：設 0.0 有系統崩潰風險）。
---
## [2026-03-06] LlamaParse v2 images_to_save 加在主流程使所有論文 parse 時間暴增 10x `[通用]`
原因：`output_options.images_to_save=["embedded"]` 讓 server 對每篇論文額外裁圖、編碼、上傳 S3，圖片多的論文（lora 6 張、flash 4 張）從 ~15s 暴增至 ~220s。
修正：`images_to_save` 只放在專門驗證圖片的 Test 7（只跑 1 篇 attention.pdf），主流程 parse 不加，保持快速。
---
## [2026-03-06] LlamaParse v2 expand=images_content_metadata 未搭配 images_to_save 導致 jobs 永遠 RUNNING `[通用]`
原因：`expand=["images_content_metadata"]` 讓 server 嘗試產出圖片 metadata，但未設定 `output_options.images_to_save`，server 無圖可回卻不 FAIL，job 永遠卡在 RUNNING；SDK 無 timeout，client 無限 poll。
修正：必須同時設定 `output_options={"images_to_save": ["embedded"]}` 才能搭配 `images_content_metadata` expand；或完全不加此 expand。
---
## [2026-03-06] LlamaParse v2 output_options.embedded_images 格式錯誤導致 422 `[版本: llama-cloud>=1.0]`
原因：官方部分範例寫 `output_options={"embedded_images": {"enable": True}}`，但實際 API schema 不接受此欄位，回傳 422 `extra_forbidden`。
修正：正確格式為 `output_options={"images_to_save": ["embedded"]}`，對應官方 cURL 文件。
---
## [2026-03-06] LlamaParse 開發誤用 v1 舊版 API 導致無聲卡死 `[版本: llama-cloud-services < 1.0]`
原因：誤將棄用的舊版套件 (`llama-cloud-services`) 當作 v2 API，其 async poll 機制遇到無額度 (如 agentic_plus) 會因為沒有 timeout 而無限卡死。
修正：全面改用新版官方 SDK `llama-cloud >= 1.0`，並使用 `AsyncLlamaCloud` client 的兩段式呼叫 (`files.create` -> `parsing.parse`)。
## [2026-03-05] litellm>=1.82 與 llama-index<0.12 版本衝突，無法裝進主 poetry 環境 `[版本: litellm>=1.82 + llama-index<0.12]`
原因：llama-index<0.12 鎖定 llama-index-llms-openai<0.3.0，而 litellm>=1.82 要求更新版本，poetry dependency resolver 直接 fail
修正：在 poc 目錄建立獨立 venv（`python3 -m venv .venv && .venv/bin/pip install litellm`），不動主專案；正式整合需評估升級 llama-index 至 >=0.12
---