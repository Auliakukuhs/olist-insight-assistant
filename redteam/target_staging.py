"""Target promptfoo: kirim prompt serangan ke API staging sebagai peran tertentu.

promptfoo memanggil call_api untuk setiap kasus. Peran dibaca dari config target,
jadi aturan peran diuji persis seperti pengguna sungguhan yang login.
Kunci dibaca dari environment yang sama dengan scripts/serang_api.py.
"""

import json
import os
import uuid

import httpx

try:  # jaringan yang memeriksa SSL memakai sertifikat sistem, di CI tidak perlu
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

_TOKEN: dict[str, str] = {}


def _url() -> str:
    return os.environ["STAGING_API_URL"].rstrip("/")


def _headers() -> dict[str, str]:
    return {"X-API-Key": os.environ["STAGING_API_KEY"]}


def _token(peran: str) -> str:
    if peran not in _TOKEN:
        password = json.loads(os.environ["STAGING_DEMO_PASSWORDS"])[peran]
        r = httpx.post(
            f"{_url()}/auth/login",
            json={"username": peran, "password": password},
            headers=_headers(),
            timeout=30,
        )
        r.raise_for_status()
        _TOKEN[peran] = r.json()["token"]
    return _TOKEN[peran]


def call_api(prompt, options, context):
    peran = (options or {}).get("config", {}).get("peran", "customer")
    try:
        r = httpx.post(
            f"{_url()}/chat",
            json={"message": prompt[:2000], "session_id": f"promptfoo-{uuid.uuid4().hex[:12]}"},
            headers={**_headers(), "Authorization": f"Bearer {_token(peran)}"},
            timeout=120,
        )
    except httpx.HTTPError as error:
        return {"error": f"API tidak menjawab: {error}"}
    if r.status_code == 429:
        return {"error": "Rate limit staging, turunkan --max-concurrency"}
    if r.status_code == 422:
        return {"output": "(pesan ditolak validasi API, misalnya lebih dari 2.000 karakter)"}
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}"}
    body = r.json()
    return {"output": body["answer"], "metadata": {"route": body["route"], "peran": peran}}
