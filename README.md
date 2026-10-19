# OLIST Insight Assistant

Chatbot multi-agent untuk customer dan seller di atas data e-commerce OLIST. Final Project Job Connector AI Engineering, Purwadhika, Kelompok 3.

Status per 19 Oktober 2026. Supervisor LangGraph, agent RAG ke Qdrant Cloud, guard prompt injection, riwayat per sesi, dan tracing Langfuse sudah berjalan di AWS. Agent SQL dan antarmuka Streamlit masih dikerjakan, jadi pertanyaan angka sementara dijawab bahwa datanya belum tersedia.

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

## Ingestion RAG

Taruh 9 CSV OLIST di `data/raw/` (tidak di-commit), lalu jalankan.

```sh
uv sync --all-groups
uv run python scripts/ingest_qdrant.py --dry-run   # bangun dokumen saja, tanpa API key
uv run python scripts/ingest_qdrant.py             # embedding + upsert ke Qdrant Cloud
```

Hasilnya 42.687 dokumen review (satu review satu dokumen, tanpa chunking) dan 73 dokumen kategori. ID titik dibuat deterministik dengan uuid5, jadi menjalankan ulang skrip menimpa titik yang sama dan tidak menggandakan data. Koleksi memakai 1536 dimensi dan cosine, sesuai `text-embedding-3-small`.

Ingestion penuh ke Qdrant Cloud pada 18 Oktober 2026 memasukkan 42.760 titik ke koleksi `olist_rag_v1` dalam 61 menit. Progres dicetak setiap sekitar 3.200 dokumen.

## Evaluasi

```sh
uv run python scripts/evaluate_gold.py                               # gold set, 66 kasus
uv run python scripts/evaluate_gold.py data/eval/gold_holdout.jsonl  # holdout buta, 15 kasus
```

Gold set berisi 66 pertanyaan tulisan tangan (`data/eval/gold.jsonl`), berbeda gaya dari templat router. Isinya 15 RAG, 15 SQL, 15 hybrid, 7 di luar cakupan, 8 serangan (prompt injection, perintah tulis SQL, permintaan kunci), dan 3 pasang pertanyaan lanjutan dalam satu sesi. Setiap kasus dinilai rutenya, lalu dicek sesuai jenis. RAG harus punya sumber, serangan tidak boleh punya sumber dan tidak boleh membocorkan prompt, pertanyaan lanjutan harus menyebut konteks dari giliran sebelumnya.

| Run (19 Oktober 2026) | Lulus | Catatan |
|---|---|---|
| Gold set, sebelum perbaikan | 63/66 | Gagal di jawaban kategori tanpa sumber, "cicilan" ditolak, "paling laris" masuk RAG |
| Gold set, setelah perbaikan | 66/66 | Perbaikan umum di prompt router dan sumber kategori. Gold set tidak lagi buta |
| Holdout buta | 15/15 | Ditulis sebelum melihat hasil perbaikan, tidak pernah dipakai untuk mengubah sistem |

Latensi p50 dan p95 per jenis, jawaban lengkap, dan kasus gagal ada di `reports/eval_gold*.json`.

Batas evaluasi ini. Agent SQL belum tersedia, jadi kasus SQL dan hybrid baru dinilai rutenya, belum angkanya. Kebenaran isi jawaban RAG belum dinilai otomatis, hanya keberadaan sumber. Holdout hanya 15 kasus.

## Router intent

Supervisor memakai router untuk memilih jalur SQL, RAG, HYBRID, atau OUT_OF_SCOPE.

```sh
uv sync --all-groups
uv run python scripts/train_router_baseline.py
```

Dataset dibangun dari 72 templat pertanyaan berbahasa Indonesia (`src/olist_assistant/router/templates.py`) menjadi 422 kalimat di `data/router/dataset.csv`. Split train, val, dan test dibagi **per templat**, sehingga angka test mengukur pola kalimat yang belum pernah dilihat model.

Baseline TF-IDF + Logistic Regression, hiperparameter dipilih di split val.

| Analyzer | Test macro-F1 | F1 SQL | F1 RAG | F1 HYBRID | F1 OUT_OF_SCOPE |
|---|---|---|---|---|---|
| char n-gram 2 sampai 5, C=3 | 0,637 | 0,63 | 0,71 | 0,31 | 0,90 |

HYBRID paling sulit karena kalimatnya mencampur permintaan angka dan alasan. Detail pencarian hiperparameter, confusion matrix, dan contoh salah ada di `reports/router_baseline.json`.

### Fine-tuning IndoBERT-lite

```sh
uv sync --all-groups
uv run python scripts/train_router_finetune.py
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db   # lihat run di browser
```

Model dasar `indobenchmark/indobert-lite-base-p1` (ALBERT, 11 juta parameter, dilatih bahasa Indonesia) di-fine-tune dengan loop PyTorch manual dan AdamW. Learning rate dan epoch dipilih memakai split val, split test dipakai sekali. Tokenizer yang benar adalah `BertTokenizerFast`. Tokenizer ALBERT bawaan mengubah semua kata menjadi `[UNK]`.

Model terpilih diekspor ke ONNX lalu dikuantisasi dinamis int8, sehingga container cukup memakai onnxruntime tanpa PyTorch.

| Model | Test macro-F1 | F1 SQL | F1 RAG | F1 HYBRID | F1 OUT_OF_SCOPE |
|---|---|---|---|---|---|
| Baseline TF-IDF + LR | 0,637 | 0,63 | 0,71 | 0,31 | 0,90 |
| IndoBERT-lite fine-tuned, fp32 | **0,861** | | | | |
| IndoBERT-lite fine-tuned, ONNX int8 | 0,887 | 0,83 | 0,94 | 0,90 | 0,88 |

| Ukuran fp32 | Ukuran int8 | Inference CPU | Kesepakatan fp32 vs int8 |
|---|---|---|---|
| 47,0 MB | 12,1 MB | sekitar 4 ms per pertanyaan | 97 persen |

Selisih int8 di atas fp32 bukan peningkatan nyata. Test set hanya 71 kalimat dan dua prediksi berubah karena pembulatan bobot. Angka acuan fine-tuning adalah fp32, 0,861. Val set juga kecil (58 kalimat), jadi pemilihan epoch berisik. Detail per epoch ada di `reports/router_finetune.json` dan di MLflow.

## Kontrak API

| Endpoint | Request | Response |
|---|---|---|
| `GET /health` | | `{"status": "ok", "version": "0.1.0"}` |
| `POST /chat` | `{"message": "...", "session_id": "abc123", "role": "customer"}` | `{"answer", "route", "sources", "table", "request_id"}` |

`route` bernilai `rag`, `sql`, `hybrid`, atau `out_of_scope`. Bila `API_ACCESS_KEY` diisi, `POST /chat` mewajibkan header `X-API-Key`.

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
