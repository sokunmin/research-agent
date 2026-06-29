import logging
import uuid

from docling_core.types.doc import DoclingDocument
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import AsyncQdrantClient, QdrantClient, models
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from config import settings
from services.docling_pipeline import DoclingPipeline, PaperChunk

logger = logging.getLogger(__name__)

VECTOR_DIM = 768  # nomic-embed-text output dimension


def build_qdrant_clients() -> tuple[QdrantClient, AsyncQdrantClient]:
    """Return (sync_client, async_client) connected to Qdrant server."""
    return (
        QdrantClient(url=settings.QDRANT_URL),
        AsyncQdrantClient(url=settings.QDRANT_URL),
    )


class PaperStore:
    """Unified Qdrant interface for paper indexing, search, and RAG retrieval.

    Manages two Qdrant namespaces:
    - "papers" collection: cross-paper semantic search (raw Qdrant PointStruct format)
    - Per-paper collections: BM25 hybrid RAG summarization (LlamaIndex TextNode format)

    The two formats are incompatible and must live in separate collections.
    Create once in workflow __init__ and inject where needed.
    """

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
        self._search_collection = settings.QDRANT_COLLECTION_NAME
        self._ensure_search_collection()

    def _ensure_search_collection(self) -> None:
        if not self._client.collection_exists(self._search_collection):
            self._client.create_collection(
                collection_name=self._search_collection,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            self._client.create_payload_index(
                collection_name=self._search_collection,
                field_name="paper_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            logger.info(f"Created Qdrant collection '{self._search_collection}'")

    def is_indexed(self, paper_id: str) -> bool:
        """Return True if any chunk for paper_id exists in the search collection."""
        result = self._client.count(
            self._search_collection,
            count_filter=Filter(
                must=[FieldCondition(key="paper_id", match=MatchValue(value=paper_id))]
            ),
            exact=True,
        )
        return result.count > 0

    def _is_rag_indexed(self, paper_id: str) -> bool:
        try:
            return (self._client.get_collection(paper_id).points_count or 0) > 0
        except Exception:
            return False

    async def index_paper(
        self, doc: DoclingDocument, paper_id: str, title: str
    ) -> int:
        """Chunk once, index into both search and RAG collections. Idempotent."""
        search_done = self.is_indexed(paper_id)
        rag_done = self._is_rag_indexed(paper_id)
        if search_done and rag_done:
            return 0
        chunks = self._docling.chunk(doc)
        if not search_done:
            await self._index_for_search(chunks, paper_id, title)
        if not rag_done:
            self._index_for_rag(chunks, paper_id)
        return len(chunks)

    async def _index_for_search(
        self, chunks: list[PaperChunk], paper_id: str, title: str
    ) -> None:
        points = []
        for i, pc in enumerate(chunks):
            embedding = self._embed_model.get_text_embedding(pc.enriched_text)
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{paper_id}_chunk_{i}"))
            points.append(PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "paper_id": paper_id,
                    "title": title,
                    "text": pc.enriched_text,
                    "headings": pc.headings,
                    "page_no": pc.page_no,
                },
            ))
        await self._aclient.upsert(collection_name=self._search_collection, points=points)
        logger.info(f"Search-indexed {len(points)} chunks for paper_id='{paper_id}'")

    def _index_for_rag(self, chunks: list[PaperChunk], paper_id: str) -> None:
        nodes = [
            TextNode(
                text=pc.enriched_text,
                id_=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{paper_id}_chunk_{i}")),
                metadata={"headings": pc.headings, "page_no": pc.page_no},
            )
            for i, pc in enumerate(chunks)
        ]
        vector_store = self._rag_vector_store(paper_id)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        VectorStoreIndex(
            nodes, embed_model=self._embed_model,
            storage_context=storage_context, show_progress=False,
        )
        logger.info(f"RAG-indexed {len(nodes)} chunks for paper_id='{paper_id}'")

    def _rag_vector_store(self, paper_id: str) -> QdrantVectorStore:
        return QdrantVectorStore(
            client=self._client,
            aclient=self._aclient,
            collection_name=paper_id,
            enable_hybrid=True,
            fastembed_sparse_model="Qdrant/bm25",
        )

    def retrieve_context(
        self, paper_id: str, queries: list[str], top_k: int
    ) -> list[str]:
        """BM25 hybrid multi-query retrieval with deduplication."""
        index = VectorStoreIndex.from_vector_store(
            self._rag_vector_store(paper_id), embed_model=self._embed_model
        )
        retriever = index.as_retriever(
            vector_store_query_mode="hybrid",
            similarity_top_k=top_k,
        )
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
        embedding = self._embed_model.get_text_embedding(query)
        query_filter = None
        if paper_id:
            query_filter = Filter(must=[
                FieldCondition(key="paper_id", match=MatchValue(value=paper_id))
            ])
        result = self._client.query_points(
            collection_name=self._search_collection,
            query=embedding,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return [{"score": r.score, **r.payload} for r in result.points]

    def search_multi_paper(
        self, query: str, paper_ids: list[str], per_paper_limit: int = 3
    ) -> dict[str, list[dict]]:
        return {
            doc_id: self.search(query, paper_id=doc_id, limit=per_paper_limit)
            for doc_id in paper_ids
        }
