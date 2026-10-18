# OLIST Insight Assistant

Chatbot multi-agent untuk customer dan seller di atas data e-commerce OLIST. Final Project Job Connector AI Engineering, Purwadhika, Kelompok 3.

Status saat ini adalah kerangka F1. API sudah punya kontrak `GET /health` dan `POST /chat`, tetapi `/chat` masih mengembalikan respons stub sampai agent tersambung di F3.

## Arsitektur

```
Streamlit  --HTTPS-->  FastAPI di AWS (satu container)
                          |
                          v
                Supervisor LangGraph + chat history per session
                   |                         |
                   v                         v
              Agent RAG                  Agent SQL
           (Qdrant Cloud)          (SQLite read-only, view terkurasi)
```

- **Agent RAG** menjawab dari teks review dan profil kategori.
- **Agent SQL** menjawab angka, harga, dan lokasi dari SQLite.
- **Supervisor** memilih RAG, SQL, atau keduanya, dan menyimpan riwayat percakapan di server per `session_id`.

## Menjalankan lokal

Butuh [uv](https://docs.astral.sh/uv/) dan Python 3.12.

```sh
uv sync
uv run uvicorn olist_assistant.api.main:app --reload
```

Atau dengan Docker.

```sh
cp .env.example .env
docker compose up --build
```

API terbuka di `http://localhost:8000`, dokumentasi interaktif di `http://localhost:8000/docs`.

## Ingestion RAG

Taruh 9 CSV OLIST di `data/raw/` (tidak di-commit), lalu jalankan.

```sh
uv sync --all-groups
uv run python scripts/ingest_qdrant.py --dry-run   # bangun dokumen saja, tanpa API key
uv run python scripts/ingest_qdrant.py             # embedding + upsert ke Qdrant Cloud
```

Hasilnya 42.687 dokumen review (satu review satu dokumen, tanpa chunking) dan 73 dokumen kategori. ID titik dibuat deterministik dengan uuid5, jadi menjalankan ulang skrip menimpa titik yang sama dan tidak menggandakan data. Koleksi memakai 1536 dimensi dan cosine, sesuai `text-embedding-3-small`.

Ingestion penuh ke Qdrant Cloud pada 18 Oktober 2026 memasukkan 42.760 titik ke koleksi `olist_rag_v1` dalam 61 menit. Progres dicetak setiap sekitar 3.200 dokumen.

## Kontrak API

| Endpoint | Request | Response |
|---|---|---|
| `GET /health` | | `{"status": "ok", "version": "0.1.0"}` |
| `POST /chat` | `{"message": "...", "session_id": "abc123", "role": "customer"}` | `{"answer", "route", "sources", "table", "request_id"}` |

`route` bernilai `rag`, `sql`, `hybrid`, `out_of_scope`, atau `stub`. Bila `API_ACCESS_KEY` diisi, `POST /chat` mewajibkan header `X-API-Key`.

## Tim dan pembagian

| Anggota | Jalur |
|---|---|
| Kukuh ([@Auliakukuhs](https://github.com/Auliakukuhs)) | Kerangka, kontrak API, Docker, CI, deploy AWS, agent RAG, supervisor, router intent |
| Starletto ([@Starletto](https://github.com/Starletto)) | ETL ke SQLite, agent SQL dan guardrail, Streamlit |

## Alur kerja

1. Buat branch dari `main` per tugas, misalnya `f2/etl-sqlite`.
2. Buka pull request. CI (lint, test, build Docker, smoke test `/health`) harus hijau.
3. Anggota lain me-review sebelum merge.
4. Jangan commit `.env`, API key, atau identitas akun cloud.

## Data

[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), lisensi CC BY-NC-SA 4.0. Data mentah tidak di-commit. Harga dalam BRL dan bersifat historis (2016 sampai 2018). Dataset tidak memuat nama produk, nama seller, atau foto.
