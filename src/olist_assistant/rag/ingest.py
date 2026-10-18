"""Upsert dokumen RAG ke Qdrant secara idempoten.

Payload memakai bentuk `page_content` dan `metadata` supaya koleksi bisa dibaca
langsung oleh `QdrantVectorStore` dari langchain-qdrant di agent RAG.
"""

from collections.abc import Callable, Iterator, Sequence

from qdrant_client import QdrantClient, models

from olist_assistant.rag.documents import RagDocument

EMBEDDING_MODEL = "text-embedding-3-small"
VECTOR_SIZE = 1536

Embedder = Callable[[list[str]], list[list[float]]]

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
    batch_size: int = 128,
) -> int:
    """Upsert per batch. ID deterministik membuat ingestion ulang menimpa, bukan menambah."""
    written = 0
    for batch in _batches(documents, batch_size):
        vectors = embed([doc.text for doc in batch])
        client.upsert(
            collection_name=name,
            points=[
                models.PointStruct(
                    id=doc.id,
                    vector=vector,
                    payload={"page_content": doc.text, "metadata": doc.metadata},
                )
                for doc, vector in zip(batch, vectors, strict=True)
            ],
        )
        written += len(batch)
    return written
