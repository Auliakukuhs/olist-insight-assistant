"""Upsert dokumen RAG ke Qdrant secara idempoten.

Payload memakai bentuk `page_content` dan `metadata` supaya koleksi bisa dibaca
langsung oleh `QdrantVectorStore` dari langchain-qdrant di agent RAG.
"""

import time
from collections.abc import Callable, Iterator, Sequence

from qdrant_client import QdrantClient, models

from olist_assistant.rag.documents import RagDocument

EMBEDDING_MODEL = "text-embedding-3-small"
VECTOR_SIZE = 1536

Embedder = Callable[[list[str]], list[list[float]]]
Progress = Callable[[int, int], None]

KEYWORD_FIELDS = ("metadata.doc_type", "metadata.categories", "metadata.seller_states")


def ensure_collection(client: QdrantClient, name: str, vector_size: int = VECTOR_SIZE) -> None:
    """Buat koleksi bila belum ada. Koleksi yang sudah ada tidak dihapus."""
    if client.collection_exists(name):
        return
    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
    )
    for field in KEYWORD_FIELDS:
        client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
    client.create_payload_index(name, "metadata.review_score", models.PayloadSchemaType.INTEGER)


def _batches(items: Sequence[RagDocument], size: int) -> Iterator[Sequence[RagDocument]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def upsert_documents(
    client: QdrantClient,
    name: str,
    documents: Sequence[RagDocument],
    embed: Embedder,
    batch_size: int = 64,
    attempts: int = 3,
    progress: Progress | None = None,
) -> int:
    """Upsert per batch. ID deterministik membuat ingestion ulang menimpa, bukan menambah."""
    written = 0
    for batch in _batches(documents, batch_size):
        vectors = embed([doc.text for doc in batch])
        points = [
            models.PointStruct(
                id=doc.id,
                vector=vector,
                payload={"page_content": doc.text, "metadata": doc.metadata},
            )
            for doc, vector in zip(batch, vectors, strict=True)
        ]
        _upsert_with_retry(client, name, points, attempts)
        written += len(batch)
        if progress:
            progress(written, len(documents))
    return written


def _upsert_with_retry(
    client: QdrantClient, name: str, points: list[models.PointStruct], attempts: int
) -> None:
    """Ulangi batch yang gagal karena jaringan. Aman karena upsert dengan ID sama idempoten."""
    for attempt in range(1, attempts + 1):
        try:
            client.upsert(collection_name=name, points=points)
            return
        except Exception:
            if attempt == attempts:
                raise
            time.sleep(2**attempt)
