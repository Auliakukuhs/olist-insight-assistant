"""Jalankan set serangan ke API lewat HTTP, seperti pengguna sungguhan.

Dipakai untuk staging, baik manual maupun dari CI. Setiap peran login dengan
akun demonya, setiap kasus memakai sesi baru kecuali yang berbagi `session`.
Hasil dinilai `check_case` yang sama dengan evaluasi di proses, lalu gerbang
rilis menolak satu pun kegagalan berat.

Variabel lingkungan:
    STAGING_API_URL          alamat API, misalnya https://...on.aws
    STAGING_API_KEY          API_ACCESS_KEY staging
    STAGING_DEMO_PASSWORDS   JSON {"admin": "...", "seller": "...", "customer": "..."}

Contoh:
    uv run python scripts/serang_api.py data/eval/redteam_otoritas.jsonl data/eval/redteam.jsonl
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

try:  # jaringan yang memeriksa SSL memakai sertifikat sistem, di CI tidak perlu
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from olist_assistant.evaluation import check_case, resolve_dates  # noqa: E402
from olist_assistant.gerbang import nilai_gerbang  # noqa: E402


def main() -> None:
    url = os.environ["STAGING_API_URL"].rstrip("/")
    headers = {"X-API-Key": os.environ["STAGING_API_KEY"]}
    passwords = json.loads(os.environ["STAGING_DEMO_PASSWORDS"])
    batas = float(os.getenv("GERBANG_BATAS_RINGAN", "0.1"))
    client = httpx.Client(timeout=120)
    token = {}
    for peran, password in passwords.items():
        r = client.post(
            f"{url}/auth/login", json={"username": peran, "password": password}, headers=headers
        )
        r.raise_for_status()
        token[peran] = r.json()["token"]
    run = uuid.uuid4().hex[:6]
    hasil = []
    for berkas in sys.argv[1:]:
        for line in Path(berkas).read_text().splitlines():
            case = resolve_dates(json.loads(line))
            peran = case.get("peran", "customer")
            sesi = f"redteam-{run}-{case.get('session', case['id'])}"
            mulai = time.monotonic()
            r = client.post(
                f"{url}/chat",
                json={"message": case["question"], "session_id": sesi},
                headers={**headers, "Authorization": f"Bearer {token[peran]}"},
            )
            if r.status_code != 200:
                route, answer, sources, error = "error", "", [], f"HTTP {r.status_code}"
            else:
                body = r.json()
                route, answer, sources, error = body["route"], body["answer"], body["sources"], None
            verdict = check_case(case, route, answer, sources)
            hasil.append(case | verdict | {"rute": route, "jawaban": answer, "error": error})
            tanda = "LULUS" if verdict["lulus"] and not error else "GAGAL"
            detik = time.monotonic() - mulai
            print(f"{tanda} {case['id']:10s} {peran:8s} rute={route:12s} {detik:5.1f}s")
            time.sleep(1)  # di bawah rate limit per akun
    gerbang = nilai_gerbang(hasil, batas)
    Path("reports").mkdir(exist_ok=True)
    Path("reports/gerbang_staging.json").write_text(
        json.dumps({"gerbang": gerbang, "semua": hasil}, ensure_ascii=False, indent=2)
    )
    print(
        json.dumps(
            {k: v for k, v in gerbang.items() if k != "gagal_ringan"}, ensure_ascii=False, indent=1
        )
    )
    sys.exit(0 if gerbang["lulus"] else 1)


if __name__ == "__main__":
    main()
