"""Uji beban ke API lewat HTTP: beberapa pengguna serentak, campuran pertanyaan.

Setiap gelombang menjalankan N pengguna bersamaan. Setiap pengguna login dengan
salah satu akun demo, lalu mengirim beberapa pertanyaan berurutan. Dicatat:
latensi p50 dan p95, galat 429 (rate limit), 5xx, dan timeout.

Pertanyaan pertama sesi yang berulang dijawab dari cache (#67), jadi jumlah jawaban
cache dicatat terpisah, dan p95_agent_detik hanya menghitung jawaban yang benar-benar
diproses agent. Angka itu yang dipakai untuk menilai kapasitas.

Variabel lingkungan sama dengan scripts/serang_api.py (STAGING_*).

Contoh:
    uv run python scripts/uji_beban.py 5 10 20
"""

import asyncio
import json
import os
import statistics
import sys
import time
import uuid
from collections import Counter
from pathlib import Path

import httpx

try:  # jaringan yang memeriksa SSL memakai sertifikat sistem
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

PERTANYAAN = [
    ("customer", "Berapa rata-rata ongkir ke RJ?"),
    ("customer", "Apa keluhan utama pembeli furniture?"),
    ("seller", "Berapa jumlah pesanan toko saya?"),
    ("seller", "Apa yang perlu ditingkatkan untuk produk bayi, dan berapa rata-rata penjualannya?"),
    ("admin", "Kategori apa yang paling sering terlambat?"),
    ("admin", "Halo apa kabar?"),
]
PER_PENGGUNA = 2


async def login(client: httpx.AsyncClient, url: str, headers: dict, passwords: dict) -> dict:
    token = {}
    for peran, password in passwords.items():
        r = await client.post(
            f"{url}/auth/login", json={"username": peran, "password": password}, headers=headers
        )
        r.raise_for_status()
        token[peran] = r.json()["token"]
    return token


async def pengguna(client, url, headers, token, nomor: int, hasil: list) -> None:
    sesi = f"beban-{uuid.uuid4().hex[:8]}"
    for i in range(PER_PENGGUNA):
        peran, q = PERTANYAAN[(nomor + i) % len(PERTANYAAN)]
        mulai, cache = time.monotonic(), False
        try:
            r = await client.post(
                f"{url}/chat",
                json={"message": q, "session_id": sesi},
                headers={**headers, "Authorization": f"Bearer {token[peran]}"},
            )
            kode = r.status_code
            cache = kode == 200 and bool((r.json().get("proses") or {}).get("cache"))
        except httpx.TimeoutException:
            kode = "timeout"
        except httpx.HTTPError as error:
            kode = type(error).__name__
        detik = round(time.monotonic() - mulai, 2)
        hasil.append({"kode": kode, "detik": detik, "peran": peran, "cache": cache})


async def gelombang(n: int, url: str, headers: dict, passwords: dict) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        token = await login(client, url, headers, passwords)
        hasil: list[dict] = []
        mulai = time.monotonic()
        await asyncio.gather(*(pengguna(client, url, headers, token, i, hasil) for i in range(n)))
        durasi = time.monotonic() - mulai
    sukses = sorted(h["detik"] for h in hasil if h["kode"] == 200)
    agent = sorted(h["detik"] for h in hasil if h["kode"] == 200 and not h["cache"])

    def persen(p: float, data: list[float] = sukses) -> float | None:
        return data[min(len(data) - 1, int(len(data) * p))] if data else None

    return {
        "pengguna_serentak": n,
        "permintaan": len(hasil),
        "kode": dict(Counter(str(h["kode"]) for h in hasil)),
        "p50_detik": round(statistics.median(sukses), 1) if sukses else None,
        "p95_detik": persen(0.95),
        "dari_cache": len(sukses) - len(agent),
        "p95_agent_detik": persen(0.95, agent),
        "maks_detik": sukses[-1] if sukses else None,
        "durasi_gelombang_detik": round(durasi, 1),
    }


async def main() -> None:
    url = os.environ["STAGING_API_URL"].rstrip("/")
    headers = {"X-API-Key": os.environ["STAGING_API_KEY"]}
    passwords = json.loads(os.environ["STAGING_DEMO_PASSWORDS"])
    laporan = []
    for n in [int(a) for a in sys.argv[1:]] or [5, 10, 20]:
        hasil = await gelombang(n, url, headers, passwords)
        laporan.append(hasil)
        print(json.dumps(hasil, ensure_ascii=False))
        await asyncio.sleep(65)  # kuota rate limit per menit kembali penuh
    Path("reports").mkdir(exist_ok=True)
    Path("reports/uji_beban.json").write_text(json.dumps(laporan, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
