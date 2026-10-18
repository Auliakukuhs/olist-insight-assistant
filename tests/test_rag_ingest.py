import hashlib

from qdrant_client import QdrantClient

from olist_assistant.rag.documents import RagDocument, doc_id
from olist_assistant.rag.ingest import ensure_collection, upsert_documents

SIZE = 8


def fake_embed(texts: list[str]) -> list[list[float]]:
    """Vektor deterministik dari hash teks, pengganti OpenAI di tes."""
    return [[b / 255 for b in hashlib.sha256(t.encode()).digest()[:SIZE]] for t in texts]


DOCS = [
    RagDocument(id=doc_id("review", f"r{i}", f"o{i}"), text=f"ulasan {i}", metadata={"i": i})
    for i in range(5)
]


def test_ingestion_ulang_tidak_menggandakan_titik():
    client = QdrantClient(":memory:")
    ensure_collection(client, "uji", vector_size=SIZE)
    upsert_documents(client, "uji", DOCS, fake_embed, batch_size=2)
    upsert_documents(client, "uji", DOCS, fake_embed, batch_size=2)
    assert client.count("uji", exact=True).count == len(DOCS)


def test_payload_terbaca_langchain_qdrant():
    client = QdrantClient(":memory:")
    ensure_collection(client, "uji", vector_size=SIZE)
    upsert_documents(client, "uji", DOCS[:1], fake_embed)
    point = client.retrieve("uji", ids=[DOCS[0].id], with_payload=True)[0]
    assert point.payload == {"page_content": "ulasan 0", "metadata": {"i": 0}}


def test_ensure_collection_tidak_menghapus_koleksi_yang_ada():
    client = QdrantClient(":memory:")
    ensure_collection(client, "uji", vector_size=SIZE)
    upsert_documents(client, "uji", DOCS, fake_embed)
    ensure_collection(client, "uji", vector_size=SIZE)
    assert client.count("uji", exact=True).count == len(DOCS)
