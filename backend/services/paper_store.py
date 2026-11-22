import logging
import uuid

from docling_core.types.doc import DoclingDocument
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.core.vector_stores import (
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import AsyncQdrantClient, QdrantClient, models
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
)

from config import settings
from services.docling_pipeline import DoclingPipeline, PaperChunk

logger = logging.getLogger(__name__)


def build_qdrant_clients() -> tuple[QdrantClient, AsyncQdrantClient]:
    """Return (sync_client, async_client) connected to Qdrant server."""
    return (
        QdrantClient(url=settings.QDRANT_URL),
        AsyncQdrantClient(url=settings.QDRANT_URL),
    )


class PaperStore:
    """Unified single-collection Qdrant interface for paper indexing, search, and RAG retrieval.

    Stores all papers in a single LlamaIndex QdrantVectorStore collection with
    dense + BM25 sparse hybrid search and a keyword payload index on `paper_id`.
    Create once in workflow __init__ and inject where needed.
    """

    _METADATA_KEYS = ["paper_id", "title", "headings", "page_no"]

    def __init__(
        self,
        docling: DoclingPipeline,
        embed_model,
        client: QdrantClient,
        aclient: AsyncQdrantClient,
    ):
        self._docling = docling
        self._embed_model = embed_model
        self._client = client
        self._aclient = aclient
        self._collection = settings.QDRANT_COLLECTION_NAME
        self._vector_store = QdrantVectorStore(
            client=self._client,
            aclient=self._aclient,
            collection_name=self._collection,
            enable_hybrid=True,
            fastembed_sparse_model="Qdrant/bm25",
            payload_indexes=[
                {
                    "field_name": "paper_id",
                    "field_schema": models.PayloadSchemaType.KEYWORD,
                }
            ],
        )

    def is_indexed(self, paper_id: str) -> bool:
        """Return True if any chunk for paper_id exists in the collection."""
        if not self._client.collection_exists(self._collection):
            return False
        result = self._client.count(
            self._collection,
            count_filter=Filter(
                must=[FieldCondition(key="paper_id", match=MatchValue(value=paper_id))]
            ),
            exact=True,
        )
        return result.count > 0

    async def index_paper(
        self, doc: DoclingDocument, paper_id: str, title: str
    ) -> int:
        """Chunk once and index into the unified Qdrant collection. Idempotent."""
        if self.is_indexed(paper_id):
            return 0
        chunks = self._docling.chunk(doc)
        if not chunks:
            return 0
        nodes = self._to_nodes(chunks, paper_id, title)
        storage_context = StorageContext.from_defaults(vector_store=self._vector_store)
        VectorStoreIndex(
            nodes,
            embed_model=self._embed_model,
            storage_context=storage_context,
            show_progress=False,
        )
        logger.info(f"Indexed {len(nodes)} chunks for paper_id='{paper_id}'")
        return len(nodes)

    def _to_nodes(
        self, chunks: list[PaperChunk], paper_id: str, title: str
    ) -> list[TextNode]:
        return [
            TextNode(
                text=pc.enriched_text,
                id_=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{paper_id}_chunk_{i}")),
                metadata={
                    "paper_id": paper_id,
                    "title": title,
                    "headings": pc.headings,
                    "page_no": pc.page_no,
                },
                excluded_embed_metadata_keys=self._METADATA_KEYS,
                excluded_llm_metadata_keys=self._METADATA_KEYS,
            )
            for i, pc in enumerate(chunks)
        ]

    def _build_retriever(self, top_k: int, paper_id: str | None = None):
        filters = None
        if paper_id is not None:
            filters = MetadataFilters(
                filters=[
                    MetadataFilter(
                        key="paper_id",
                        value=paper_id,
                        operator=FilterOperator.EQ,
                    )
                ]
            )
        index = VectorStoreIndex.from_vector_store(
            self._vector_store, embed_model=self._embed_model
        )
        return index.as_retriever(
            vector_store_query_mode="hybrid",
            similarity_top_k=top_k,
            filters=filters,
        )

    def retrieve_context(
        self, paper_id: str, queries: list[str], top_k: int
    ) -> list[str]:
        """BM25 hybrid multi-query retrieval with deduplication."""
        if not self._client.collection_exists(self._collection):
            return []
        retriever = self._build_retriever(top_k=top_k, paper_id=paper_id)
        seen_ids: set[str] = set()
        context_chunks: list[str] = []
        for query in queries:
            for node in retriever.retrieve(query):
                if node.node_id not in seen_ids:
                    seen_ids.add(node.node_id)
                    context_chunks.append(node.text)
        return context_chunks

    def search(
        self, query: str, paper_id: str | None = None, limit: int = 5
    ) -> list[dict]:
        if not self._client.collection_exists(self._collection):
            return []
        retriever = self._build_retriever(top_k=limit, paper_id=paper_id)
        return [
            {
                "score": node.score,
                "text": node.node.get_content(),
                **node.node.metadata,
            }
            for node in retriever.retrieve(query)
        ]

    def search_multi_paper(
        self, query: str, paper_ids: list[str], per_paper_limit: int = 3
    ) -> dict[str, list[dict]]:
        return {
            doc_id: self.search(query, paper_id=doc_id, limit=per_paper_limit)
            for doc_id in paper_ids
        }
