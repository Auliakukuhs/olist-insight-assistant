"""Bangun dokumen RAG dari CSV OLIST lalu upsert ke Qdrant Cloud.

Contoh:
    uv run --group ingest python scripts/ingest_qdrant.py --dry-run
    uv run --group ingest python scripts/ingest_qdrant.py --collection olist_rag_v1

Mode biasa membutuhkan OPENAI_API_KEY, QDRANT_URL, dan QDRANT_API_KEY di
environment atau di berkas .env. Kunci tidak pernah dicetak.
"""

import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

from olist_assistant.rag.documents import build_all_documents, load_tables
from olist_assistant.rag.ingest import EMBEDDING_MODEL, ensure_collection, upsert_documents

REQUIRED_ENV = ("OPENAI_API_KEY", "QDRANT_URL", "QDRANT_API_KEY")


def load_dotenv(path: Path) -> None:
    """Muat .env sederhana tanpa menimpa environment yang sudah ada."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value:
                os.environ.setdefault(key.strip(), value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--collection", default="olist_rag_v1")
    parser.add_argument("--dry-run", action="store_true", help="Bangun dokumen tanpa embedding")
    parser.add_argument("--limit", type=int, default=None, help="Ambil N dokumen pertama saja")
    args = parser.parse_args()

    documents = build_all_documents(load_tables(args.raw_dir))
    if args.limit:
        documents = documents[: args.limit]
    per_type = collections.Counter(doc.metadata["doc_type"] for doc in documents)
    print(f"{len(documents)} dokumen: {dict(per_type)}")

    if args.dry_run:
        print(json.dumps(documents[0].__dict__, ensure_ascii=False, indent=2))
        return 0

    load_dotenv(Path(".env"))
    missing = [key for key in REQUIRED_ENV if not os.getenv(key)]
    if missing:
        print(f"Environment belum lengkap: {', '.join(missing)}", file=sys.stderr)
        return 1

    from langchain_openai import OpenAIEmbeddings
    from qdrant_client import QdrantClient

    embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    client = QdrantClient(
        url=os.environ["QDRANT_URL"], api_key=os.environ["QDRANT_API_KEY"], timeout=60
    )
    ensure_collection(client, args.collection)
    started = time.monotonic()

    def report(done: int, total: int) -> None:
        if done == total or done % 3200 < 64:
            minutes = (time.monotonic() - started) / 60
            print(f"  {done}/{total} ({done / total:.0%}), {minutes:.1f} menit", flush=True)

    written = upsert_documents(
        client, args.collection, documents, embeddings.embed_documents, progress=report
    )
    total = client.count(args.collection, exact=True).count
    print(f"{written} dokumen di-upsert. Isi koleksi {args.collection} sekarang {total} titik.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
