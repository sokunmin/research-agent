"""A4: Verify Qdrant local file mode upsert and query_points API."""
import sys
import uuid
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

sys.path.insert(0, str(Path(__file__).parent.parent))
from poc_base import DoclingPoc, PocReporter

COLLECTION = "papers_test"
QDRANT_TEST_PATH = "./poc/docling-qdrant/qdrant_storage_test"


def run() -> bool:
    r = PocReporter("A4")
    doc = DoclingPoc.load_doc()
    chunker = DoclingPoc.build_chunker()
    chunks = DoclingPoc.get_chunks(doc, chunker)

    test_chunks = chunks
    raw_chunks = list(chunker.chunk(dl_doc=doc))

    client = QdrantClient(path=QDRANT_TEST_PATH)
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=768, distance=Distance.COSINE),
    )
    r.check("collection created", client.collection_exists(COLLECTION))

    from llama_index.embeddings.litellm import LiteLLMEmbedding
    embed_model = LiteLLMEmbedding(model_name="ollama/nomic-embed-text")

    points = []
    for i, (raw, doc_chunk) in enumerate(zip(raw_chunks, test_chunks)):
        enriched = chunker.contextualize(chunk=raw)
        embedding = embed_model.get_text_embedding("search_document: " + enriched)
        points.append(PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_DNS, f"test_chunk_{i}")),
            vector=embedding,
            payload={
                "document_id": "1706.03762",
                "headings": doc_chunk.meta.headings or [],
                "text": enriched,
            },
        ))

    client.upsert(collection_name=COLLECTION, points=points)
    r.check(f"{len(points)} points upserted", True)

    queries = [
        "What is the Transformer model and why was it proposed to replace recurrent networks?",
        "How does scaled dot-product attention work and why is the scaling factor used?",
        "What BLEU scores did the Transformer achieve on WMT 2014 English-German and English-French translation tasks?",
    ]

    q_scores = []
    for qi, query_text in enumerate(queries, start=1):
        query_emb = DoclingPoc.embed(query_text)
        result = client.query_points(
            collection_name=COLLECTION,
            query=query_emb,
            limit=3,
            with_payload=True,
        )
        r.check(f"Q{qi} query_points returns .points", hasattr(result, "points"))
        top_score = result.points[0].score if result.points else 0.0
        q_scores.append(top_score)
        print(f"[A4] Q{qi}: {query_text[:60]}...")
        for pt in result.points:
            print(f"  score={pt.score:.3f} headings={pt.payload.get('headings')} text={pt.payload.get('text','')[:80]}")

    q1_top_score, q2_top_score, q3_top_score = q_scores
    r.check("Q1 top score > 0.65", q1_top_score > 0.65, f"{q1_top_score:.3f}")
    r.check("Q2 top score > 0.65", q2_top_score > 0.65, f"{q2_top_score:.3f}")
    r.check("Q3 top score > 0.65", q3_top_score > 0.65, f"{q3_top_score:.3f}")

    # Cleanup test storage
    import shutil
    shutil.rmtree(QDRANT_TEST_PATH, ignore_errors=True)
    print(f"[A4] Cleaned up test Qdrant storage: {QDRANT_TEST_PATH}")

    return r.summary()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
