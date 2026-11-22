"""Unit tests for single-collection Qdrant PaperStore."""

from __future__ import annotations

import hashlib
import os
from typing import Any

# Ensure config.Settings() can be instantiated in isolated unit-test environments
# without requiring a backend/.env file.
os.environ.setdefault("MLFLOW_TRACKING_URI", "http://localhost:8080")
os.environ.setdefault("WORKFLOW_ARTIFACTS_ROOT", "/tmp/workflow_artifacts")
os.environ.setdefault("SLIDE_TEMPLATE_PATH", "/tmp/template.pptx")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")

import pytest
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.schema import MetadataMode
from qdrant_client import AsyncQdrantClient, QdrantClient

from services.docling_pipeline import PaperChunk
from services.paper_store import PaperStore


class DeterministicEmbedding(BaseEmbedding):
    """Lightweight deterministic embedding model for offline unit tests."""

    embed_dim: int = 16

    def _embed(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        raw = [digest[i % len(digest)] / 255.0 for i in range(self.embed_dim)]
        norm = sum(x * x for x in raw) ** 0.5 or 1.0
        return [x / norm for x in raw]

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)


class FakeDoclingPipeline:
    """Fake DoclingPipeline returning preconfigured PaperChunk lists per doc key."""

    def __init__(self, chunks_by_doc: dict[Any, list[PaperChunk]]):
        self._chunks_by_doc = chunks_by_doc

    def chunk(self, doc: Any) -> list[PaperChunk]:
        return self._chunks_by_doc.get(doc, [])


@pytest.fixture
def paper_chunks() -> dict[str, list[PaperChunk]]:
    return {
        "doc_alpha": [
            PaperChunk(
                enriched_text="Alpha paper introduces a transformer sparse attention mechanism for long documents.",
                headings=["1. Introduction"],
                page_no=1,
            ),
            PaperChunk(
                enriched_text="Alpha experiments show 3x speedup on 128k context benchmarks.",
                headings=["4. Experiments", "4.1 Benchmarks"],
                page_no=5,
            ),
        ],
        "doc_beta": [
            PaperChunk(
                enriched_text="Beta paper proposes a diffusion model for protein folding trajectories.",
                headings=["1. Overview"],
                page_no=1,
            ),
            PaperChunk(
                enriched_text="Beta achieves state-of-the-art RMSD on CASP15 targets.",
                headings=["3. Results"],
                page_no=4,
            ),
        ],
    }


@pytest.fixture
def store_and_client(paper_chunks: dict[str, list[PaperChunk]]) -> tuple[PaperStore, QdrantClient]:
    client = QdrantClient(":memory:")
    aclient = AsyncQdrantClient(":memory:")
    docling = FakeDoclingPipeline(paper_chunks)
    embed_model = DeterministicEmbedding()
    store = PaperStore(
        docling=docling,
        embed_model=embed_model,
        client=client,
        aclient=aclient,
    )
    return store, client


def test_empty_db_guard(store_and_client: tuple[PaperStore, QdrantClient]) -> None:
    """Before any paper is indexed, queries and checks return empty/False without 404."""
    store, _ = store_and_client

    assert store.is_indexed("paper_alpha") is False
    assert store.retrieve_context("paper_alpha", ["transformer"], top_k=3) == []
    assert store.search("transformer", paper_id="paper_alpha", limit=3) == []
    assert store.search("transformer", limit=3) == []


@pytest.mark.asyncio
async def test_single_collection_for_multiple_papers(
    store_and_client: tuple[PaperStore, QdrantClient],
) -> None:
    """Indexing two distinct papers creates only a single Qdrant collection."""
    store, client = store_and_client

    count_a = await store.index_paper("doc_alpha", "paper_alpha", "Alpha Title")
    count_b = await store.index_paper("doc_beta", "paper_beta", "Beta Title")

    assert count_a == 2
    assert count_b == 2
    assert store.is_indexed("paper_alpha") is True
    assert store.is_indexed("paper_beta") is True

    collections = client.get_collections().collections
    assert len(collections) == 1
    assert collections[0].name == store._collection


@pytest.mark.asyncio
async def test_index_paper_idempotency(
    store_and_client: tuple[PaperStore, QdrantClient],
) -> None:
    """Re-indexing the same paper_id returns 0 and does not increase point count."""
    store, client = store_and_client

    first = await store.index_paper("doc_alpha", "paper_alpha", "Alpha Title")
    assert first == 2
    count_after_first = client.count(store._collection, exact=True).count

    second = await store.index_paper("doc_alpha", "paper_alpha", "Alpha Title")
    assert second == 0
    count_after_second = client.count(store._collection, exact=True).count
    assert count_after_second == count_after_first


@pytest.mark.asyncio
async def test_retrieve_context_isolation_and_dedup(
    store_and_client: tuple[PaperStore, QdrantClient],
) -> None:
    """retrieve_context returns only chunks from the requested paper_id and deduplicates across queries."""
    store, _ = store_and_client

    await store.index_paper("doc_alpha", "paper_alpha", "Alpha Title")
    await store.index_paper("doc_beta", "paper_beta", "Beta Title")

    # Repeated/overlapping queries should be deduplicated and strictly scoped to paper_alpha
    chunks = store.retrieve_context(
        "paper_alpha",
        queries=["transformer sparse attention", "transformer sparse attention", "128k context benchmarks"],
        top_k=5,
    )

    assert len(chunks) == 2
    assert len(set(chunks)) == len(chunks)
    assert all("Alpha" in c for c in chunks)
    assert not any("Beta" in c for c in chunks)


def test_excluded_metadata_keys_on_nodes(
    store_and_client: tuple[PaperStore, QdrantClient],
    paper_chunks: dict[str, list[PaperChunk]],
) -> None:
    """_to_nodes excludes metadata keys from both EMBED and LLM content modes."""
    store, _ = store_and_client
    chunks = paper_chunks["doc_alpha"]

    nodes = store._to_nodes(chunks, "paper_alpha", "Alpha Title")

    assert len(nodes) == len(chunks)
    for node, chunk in zip(nodes, chunks):
        assert node.get_content(metadata_mode=MetadataMode.EMBED) == chunk.enriched_text
        assert node.get_content(metadata_mode=MetadataMode.LLM) == chunk.enriched_text
        assert node.metadata["paper_id"] == "paper_alpha"
        assert node.metadata["title"] == "Alpha Title"
        assert node.metadata["headings"] == chunk.headings
        assert node.metadata["page_no"] == chunk.page_no


@pytest.mark.asyncio
async def test_search_and_search_multi_paper(
    store_and_client: tuple[PaperStore, QdrantClient],
) -> None:
    """search() and search_multi_paper() return dicts with expected metadata and score keys."""
    store, _ = store_and_client

    await store.index_paper("doc_alpha", "paper_alpha", "Alpha Title")
    await store.index_paper("doc_beta", "paper_beta", "Beta Title")

    expected_keys = {"score", "text", "paper_id", "title", "headings", "page_no"}

    # Unscoped search across all papers
    all_results = store.search("protein folding diffusion", limit=4)
    assert len(all_results) > 0
    for item in all_results:
        assert expected_keys.issubset(item.keys())

    # Paper-scoped search
    alpha_results = store.search("sparse attention", paper_id="paper_alpha", limit=3)
    assert len(alpha_results) > 0
    assert all(item["paper_id"] == "paper_alpha" for item in alpha_results)
    assert all(expected_keys.issubset(item.keys()) for item in alpha_results)

    # Multi-paper search
    multi = store.search_multi_paper(
        "experiments results",
        paper_ids=["paper_alpha", "paper_beta"],
        per_paper_limit=2,
    )
    assert set(multi.keys()) == {"paper_alpha", "paper_beta"}
    assert len(multi["paper_alpha"]) > 0
    assert len(multi["paper_beta"]) > 0
    assert all(item["paper_id"] == "paper_alpha" for item in multi["paper_alpha"])
    assert all(item["paper_id"] == "paper_beta" for item in multi["paper_beta"])
    for results in multi.values():
        for item in results:
            assert expected_keys.issubset(item.keys())
