"""Periksa kunci layanan sebelum red team, tanpa menampilkan nilainya.

Kasus yang galat karena kunci salah tidak menguji apa pun. Skrip ini gagal
lebih dulu dengan pesan yang jelas: kunci mana, dan kode galatnya.

Contoh:
    uv run python scripts/periksa_kunci.py            # OpenAI dan Qdrant
    uv run python scripts/periksa_kunci.py staging    # API staging
"""

import json
import os
import sys

import httpx


def periksa_openai() -> str:
    from openai import OpenAI

    OpenAI(timeout=20).embeddings.create(model="text-embedding-3-small", input="uji kunci")
    return "embedding text-embedding-3-small berhasil"


def periksa_qdrant() -> str:
    from qdrant_client import QdrantClient

    from olist_assistant.agents.rag import COLLECTION

    url = os.environ["QDRANT_URL"].strip()
    if not url.startswith("https://"):
        raise ValueError("QDRANT_URL harus diawali https://")
    client = QdrantClient(url=url, api_key=os.environ["QDRANT_API_KEY"].strip(), timeout=20)
    nama = os.getenv("QDRANT_COLLECTION", COLLECTION)
    points, _ = client.scroll(nama, limit=1, with_payload=False)
    return f"scroll koleksi {nama} berhasil ({len(points)} titik contoh)"


def periksa_staging() -> str:
    url = os.environ["STAGING_API_URL"].rstrip("/")
    headers = {"X-API-Key": os.environ["STAGING_API_KEY"]}
    passwords = json.loads(os.environ["STAGING_DEMO_PASSWORDS"])
    hasil = []
    for peran in ("admin", "seller", "customer"):
        r = httpx.post(
            f"{url}/auth/login",
            json={"username": peran, "password": passwords[peran]},
            headers=headers,
            timeout=30,
        )
        hasil.append(f"{peran} {r.status_code}")
        r.raise_for_status()
    return "login staging berhasil: " + ", ".join(hasil)


def main() -> None:
    target = sys.argv[1:] or ["openai", "qdrant"]
    cek = {"openai": periksa_openai, "qdrant": periksa_qdrant, "staging": periksa_staging}
    gagal = False
    for nama in target:
        try:
            print(f"OK    {nama}: {cek[nama]()}")
        except Exception as error:  # pesan galat tanpa nilai kunci
            gagal = True
            status = getattr(error, "status_code", None) or getattr(
                getattr(error, "response", None), "status_code", None
            )
            print(f"GAGAL {nama}: {type(error).__name__} {status or ''} {str(error)[:300]}")
    sys.exit(1 if gagal else 0)


if __name__ == "__main__":
    main()
