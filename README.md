# OLIST Insight Assistant

Chatbot multi-agent untuk customer dan seller di atas data e-commerce OLIST. Final Project Job Connector AI Engineering, Purwadhika, Kelompok 3.

Status saat ini adalah kerangka F1. API sudah punya kontrak `GET /health` dan `POST /chat`, tetapi `/chat` masih mengembalikan respons stub sampai agent tersambung di F3.

## Link

| Bagian | URL |
|---|---|
| Backend (REST API di AWS ECS Express Mode) | https://ol-c576a0b2565b439a9bd39e2e2b2e8563.ecs.ap-southeast-1.on.aws |
| Frontend (Streamlit Community Cloud) | menyusul |

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

## Deploy ke AWS

API berjalan di Amazon ECS Express Mode, region `ap-southeast-1`, satu task Fargate ARM64 (0,25 vCPU, 1 GB) di belakang Application Load Balancer dengan HTTPS otomatis. Health check memakai `GET /health`.

```sh
AWS_PROFILE=olist scripts/deploy_aws.sh
```

Skrip membangun image dari commit saat ini, memberi tag SHA commit, push ke ECR (tag immutable, scan saat push), lalu memperbarui service. Kunci layanan disimpan di AWS SSM Parameter Store sebagai SecureString di bawah `/olist/`, lalu disuntik ECS sebagai environment saat task start. Nilainya tidak pernah masuk image atau repo, dan execution role hanya boleh membaca parameter `/olist/*`. Di cloud, `POST /chat` mewajibkan header `X-API-Key`.

## Alur kerja

1. Buat branch dari `main` per tugas, misalnya `f2/etl-sqlite`.
2. Buka pull request. CI (lint, test, build Docker, smoke test `/health`) harus hijau.
3. Anggota lain me-review sebelum merge.
4. Jangan commit `.env`, API key, atau identitas akun cloud.

## Data

[Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce), lisensi CC BY-NC-SA 4.0. Data mentah tidak di-commit. Harga dalam BRL dan bersifat historis (2016 sampai 2018). Dataset tidak memuat nama produk, nama seller, atau foto.
