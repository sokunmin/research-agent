import logging
import uuid

from docling_core.types.doc import DoclingDocument
from qdrant_client import QdrantClient, models
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from config import settings
from services.docling_chunker import DoclingChunker
from tools.filter_tools import ChunkFilter

logger = logging.getLogger(__name__)

VECTOR_DIM = 768  # nomic-embed-text output dimension


class PaperVectorStore:
    """Qdrant local-file wrapper for paper chunk indexing and retrieval.

    All three constructor arguments are singletons injected from
    SummaryGenerationWorkflow.__init__ — never instantiated internally.
    """

    def __init__(self, chunker: DoclingChunker, chunk_filter: ChunkFilter, embed_model):
        self._chunker = chunker
        self._filter = chunk_filter
        self._embed_model = embed_model
        self._client = QdrantClient(path=settings.QDRANT_PATH)
        self._collection = settings.QDRANT_COLLECTION_NAME
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if not self._client.collection_exists(self._collection):
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            self._client.create_payload_index(
                collection_name=self._collection,
                field_name="paper_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
            logger.info(f"Created Qdrant collection '{self._collection}'")

    def is_indexed(self, document_id: str) -> bool:
        """Return True if any chunk for document_id is already in Qdrant."""
        result = self._client.count(
            self._collection,
            count_filter=Filter(
                must=[FieldCondition(key="paper_id", match=MatchValue(value=document_id))]
            ),
            exact=True,
        )
        return result.count > 0

    async def index_document_async(
        self, doc: DoclingDocument, document_id: str, title: str
    ) -> int:
        """Chunk, filter, embed, and upsert a paper into Qdrant.

        Embedding runs outside the lock (concurrent across papers). Only upsert()
        is serialized to prevent Gridstore corruption under concurrent tasks.
        Deterministic UUIDs (uuid5) make upsert idempotent.
        """
        paper_chunks = self._chunker.extract_chunks(doc, self._filter)
        points = []
        for i, pc in enumerate(paper_chunks):
            embedding = self._embed_model.get_text_embedding(pc.enriched_text)
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{document_id}_chunk_{i}"))
            points.append(PointStruct(
                id=point_id,
                vector=embedding,
                payload={
                    "paper_id": document_id,
                    "title": title,
                    "text": pc.enriched_text,
                    "headings": pc.headings,
                    "page_no": pc.page_no,
                },
            ))
        self._client.upsert(collection_name=self._collection, points=points)
        logger.info(f"Indexed {len(points)} chunks for document_id='{document_id}'")
        return len(points)

    def search(
        self, query: str, document_id: str | None = None, limit: int = 5
    ) -> list[dict]:
        """Embed query and retrieve similar chunks from Qdrant."""
        embedding = self._embed_model.get_text_embedding(query)
        query_filter = None
        if document_id:
            query_filter = Filter(must=[
                FieldCondition(key="paper_id", match=MatchValue(value=document_id))
            ])
        result = self._client.query_points(
            collection_name=self._collection,
            query=embedding,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
        )
        return [{"score": r.score, **r.payload} for r in result.points]

    def search_multi_paper(
        self, query: str, document_ids: list[str], per_paper_limit: int = 3
    ) -> dict[str, list[dict]]:
        """Cross-paper search with fair per-paper sampling."""
        return {
            doc_id: self.search(query, document_id=doc_id, limit=per_paper_limit)
            for doc_id in document_ids
        }
