"""Reproduksi temuan audit 25 Oktober 2026 (S02, S03, S05, S06, S09) dan perbaikannya."""

import json

import pytest
from fastapi.testclient import TestClient

from olist_assistant.api import auth, main
from olist_assistant.api.main import app, get_supervisor, periksa_konfigurasi
from olist_assistant.api.ratelimit import RateLimiter
from olist_assistant.config import get_settings

client = TestClient(app, raise_server_exceptions=False)
USERS = {
    "alice": {"password": "rahasia-alice", "peran": "customer"},
    "bob": {"password": "rahasia-bob", "peran": "customer"},
}


class Stub:
    def __init__(self):
        self.roles = []

    def ask(self, message, thread, role, seller_id):
        self.roles.append(role)
        return {"answer": "ok", "route": "sql", "sources": []}


@pytest.fixture
def stub(monkeypatch):
    for name in ("AUTH_SECRET", "DEMO_USERS", "API_ACCESS_KEY", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(main, "per_client", RateLimiter(1000))
    monkeypatch.setattr(main, "per_session", RateLimiter(1000))
    monkeypatch.setattr(main, "per_account", RateLimiter(1000))
    monkeypatch.setattr(auth, "per_client_login", RateLimiter(1000))
    monkeypatch.setattr(auth, "per_account_login", RateLimiter(1000))
    s = Stub()
    app.dependency_overrides[get_supervisor] = lambda: s
    yield s
    app.dependency_overrides.clear()


@pytest.fixture
def login(stub, monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "kunci-uji")
    monkeypatch.setenv("DEMO_USERS", json.dumps(USERS))
    return stub


def masuk(username):
    body = client.post(
        "/auth/login", json={"username": username, "password": USERS[username]["password"]}
    )
    assert body.status_code == 200
    return {"Authorization": f"Bearer {body.json()['token']}"}


def chat(session="s1", headers=None, **extra):
    payload = {"message": "Berapa total pesanan?", "session_id": session, **extra}
    return client.post("/chat", json=payload, headers=headers or {})


def test_s02_produksi_tanpa_rahasia_gagal_tertutup(stub, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    response = chat(role="admin")
    assert response.status_code == 503
    assert stub.roles == []
    with pytest.raises(RuntimeError, match="AUTH_SECRET"):
        periksa_konfigurasi(get_settings())


def test_s02_lokal_tanpa_login_tetap_boleh(stub):
    assert chat(role="admin").status_code == 200


def test_s03_header_palsu_tidak_mereset_batas_login(login, monkeypatch):
    monkeypatch.setattr(auth, "per_client_login", RateLimiter(2))
    salah = {"username": "tidak-ada", "password": "x"}
    codes = [
        client.post(
            "/auth/login",
            json={**salah, "username": f"u{i}"},
            headers={"X-Forwarded-For": f"198.51.100.{i}, 192.0.2.20"},
        ).status_code
        for i in range(4)
    ]
    assert codes == [401, 401, 429, 429]


def test_s03_batas_login_per_akun_dari_banyak_alamat(login, monkeypatch):
    monkeypatch.setattr(auth, "per_account_login", RateLimiter(2))
    codes = [
        client.post(
            "/auth/login",
            json={"username": "alice", "password": "salah"},
            headers={"X-Forwarded-For": f"192.0.2.{i}"},
        ).status_code
        for i in range(3)
    ]
    assert codes == [401, 401, 429]


def test_s03_s06_kuota_akun_tidak_bisa_direset_dengan_header_dan_sesi_baru(login, monkeypatch):
    headers = masuk("alice")
    monkeypatch.setattr(main, "per_account", RateLimiter(2))
    codes = [
        chat(f"sesi-{i}", {**headers, "X-Forwarded-For": f"198.51.100.{i}, 192.0.2.20"}).status_code
        for i in range(3)
    ]
    assert codes == [200, 200, 429]


def test_s06_session_id_sama_tidak_menghabiskan_kuota_akun_lain(login, monkeypatch):
    alice, bob = masuk("alice"), masuk("bob")
    monkeypatch.setattr(main, "per_session", RateLimiter(1))
    assert [chat("bersama", alice).status_code, chat("bersama", bob).status_code] == [200, 200]


def test_s05_token_akun_yang_dihapus_atau_diubah_perannya_tidak_berlaku(login, monkeypatch):
    headers = masuk("alice")
    assert client.get("/auth/me", headers=headers).status_code == 200
    monkeypatch.setenv("DEMO_USERS", json.dumps({"bob": USERS["bob"]}))
    assert client.get("/auth/me", headers=headers).status_code == 401
    berubah = {**USERS, "alice": {**USERS["alice"], "peran": "admin"}}
    monkeypatch.setenv("DEMO_USERS", json.dumps(berubah))
    assert client.get("/auth/me", headers=headers).status_code == 401


def test_s09_password_tidak_dipantulkan_dan_token_aneh_menjadi_401(login):
    rahasia = "RAHASIA-" * 40
    response = client.post("/auth/login", json={"username": "alice", "password": rahasia})
    assert response.status_code == 422
    assert "RAHASIA" not in response.text
    response = client.get("/auth/me", headers={b"authorization": b"Bearer abc.\xc3\xa9"})
    assert response.status_code == 401
    assert (
        client.get("/auth/me", headers={"Authorization": "Bearer " + "a." * 3000}).status_code
        == 401
    )


def test_limiter_membuang_kunci_kedaluwarsa(monkeypatch):
    from olist_assistant.api import ratelimit

    monkeypatch.setattr(ratelimit, "MAX_KEYS", 10)
    clock = [0.0]
    limiter = RateLimiter(2, clock=lambda: clock[0])
    for i in range(50):
        limiter.check(f"k{i}")
    clock[0] = 3600.0
    limiter.check("baru")
    assert len(limiter._hits) == 1
