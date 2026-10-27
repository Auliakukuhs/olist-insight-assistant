import json

import pytest
from fastapi.testclient import TestClient

from olist_assistant.agents.supervisor import Supervisor
from olist_assistant.api import auth, main, umpan_balik
from olist_assistant.api.main import app, get_supervisor
from olist_assistant.api.ratelimit import RateLimiter

client = TestClient(app)
USERS = {
    "toko": {
        "password": "rahasia-toko",
        "peran": "seller",
        "seller_id": "4869f7a5dfa277a7dca6462dcf3b52b2",
    },
    "pembeli": {"password": "rahasia-pembeli", "peran": "customer"},
}


class FakeLangfuse:
    def __init__(self):
        self.scores = []

    def create_score(self, **kwargs):
        self.scores.append(kwargs)


def supervisor():
    sup = Supervisor(
        classify=lambda q, h: "rag",
        rag=lambda q, h: {"answer": "Pembeli mengeluh telat.", "sources": []},
        sql=lambda q, h, u: {"answer": "", "sql": "", "rows": []},
        synthesize=lambda q, s, r: "",
    )
    sup.tracing = lambda trace_id: []
    return sup


@pytest.fixture
def langfuse(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "kunci-uji")
    monkeypatch.setenv("DEMO_USERS", json.dumps(USERS))
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    monkeypatch.setattr(auth, "per_client_login", RateLimiter(1000))
    monkeypatch.setattr(auth, "per_account_login", RateLimiter(1000))
    monkeypatch.setattr(main, "per_account", RateLimiter(1000))
    monkeypatch.setattr(main, "per_session", RateLimiter(1000))
    monkeypatch.setattr(main, "per_client", RateLimiter(1000))
    monkeypatch.setattr(umpan_balik, "per_client_feedback", RateLimiter(1000))
    monkeypatch.setattr(umpan_balik, "pemilik_trace", umpan_balik.PemilikTrace())
    fake = FakeLangfuse()
    monkeypatch.setattr(umpan_balik, "langfuse_client", lambda: fake)
    sup = supervisor()
    app.dependency_overrides[get_supervisor] = lambda: sup
    yield fake
    app.dependency_overrides.clear()


def masuk(username):
    body = client.post(
        "/auth/login", json={"username": username, "password": USERS[username]["password"]}
    ).json()
    return {"Authorization": f"Bearer {body['token']}"}


def tanya(headers):
    body = client.post(
        "/chat", json={"message": "Keluhan bayi?", "session_id": "s1"}, headers=headers
    )
    assert body.status_code == 200
    return body.json()["trace_id"]


def test_chat_mengembalikan_trace_id_dan_umpan_balik_tercatat(langfuse):
    headers = masuk("toko")
    trace_id = tanya(headers)
    assert len(trace_id) == 32
    response = client.post(
        "/feedback",
        json={"trace_id": trace_id, "suka": False, "komentar": "angkanya kurang"},
        headers=headers,
    )
    assert response.status_code == 200 and response.json() == {"tercatat": True}
    score = langfuse.scores[0]
    assert score["trace_id"] == trace_id and score["value"] == 0
    assert score["data_type"] == "BOOLEAN" and score["comment"] == "angkanya kurang"
    assert score["metadata"] == {"peran": "seller"}


def test_mengganti_pilihan_memperbarui_score_yang_sama(langfuse):
    headers = masuk("toko")
    trace_id = tanya(headers)
    for suka in (True, False):
        client.post("/feedback", json={"trace_id": trace_id, "suka": suka}, headers=headers)
    assert langfuse.scores[0]["score_id"] == langfuse.scores[1]["score_id"]


def test_tidak_bisa_menilai_jawaban_akun_lain(langfuse):
    trace_id = tanya(masuk("toko"))
    response = client.post(
        "/feedback", json={"trace_id": trace_id, "suka": True}, headers=masuk("pembeli")
    )
    assert response.status_code == 404
    assert langfuse.scores == []


def test_trace_tidak_dikenal_dan_tanpa_login_ditolak(langfuse):
    headers = masuk("toko")
    response = client.post("/feedback", json={"trace_id": "a" * 32, "suka": True}, headers=headers)
    assert response.status_code == 404
    response = client.post("/feedback", json={"trace_id": "a" * 32, "suka": True})
    assert response.status_code == 401
    response = client.post(
        "/feedback", json={"trace_id": "bukan-hex", "suka": True}, headers=headers
    )
    assert response.status_code == 422


def test_langfuse_mati_menjawab_503(langfuse, monkeypatch):
    monkeypatch.setattr(umpan_balik, "langfuse_client", lambda: None)
    headers = masuk("toko")
    trace_id = tanya(headers)
    response = client.post("/feedback", json={"trace_id": trace_id, "suka": True}, headers=headers)
    assert response.status_code == 503


def test_pemilik_trace_dibatasi_jumlahnya():
    pemilik = umpan_balik.PemilikTrace(batas=2)
    for i in range(3):
        pemilik.catat(f"{i:032x}", "toko")
    assert pemilik.pemilik(f"{0:032x}") is None
    assert pemilik.pemilik(f"{2:032x}") == "toko"
