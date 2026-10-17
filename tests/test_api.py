import pytest
from fastapi.testclient import TestClient

from olist_assistant import __version__
from olist_assistant.api.main import app

client = TestClient(app)

VALID = {"message": "Kategori apa yang paling laris?", "session_id": "sesi-1"}


@pytest.fixture(autouse=True)
def tanpa_api_key(monkeypatch):
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_chat_stub_mengikuti_kontrak():
    response = client.post("/chat", json=VALID)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"answer", "route", "sources", "table", "request_id"}
    assert body["route"] == "stub"
    assert body["sources"] == []
    assert len(body["request_id"]) == 32


def test_chat_role_bawaan_customer_dan_seller_diterima():
    response = client.post("/chat", json={**VALID, "role": "seller"})
    assert response.status_code == 200


@pytest.mark.parametrize(
    "perubahan",
    [
        {"message": ""},
        {"message": "x" * 2001},
        {"session_id": ""},
        {"session_id": "ada spasi"},
        {"session_id": "../etc/passwd"},
        {"role": "admin"},
    ],
)
def test_chat_menolak_input_tidak_valid(perubahan):
    response = client.post("/chat", json={**VALID, **perubahan})
    assert response.status_code == 422


def test_chat_tidak_menerima_riwayat_dari_klien():
    # Field asing diabaikan. Riwayat hanya diambil dari server per session_id.
    response = client.post("/chat", json={**VALID, "history": [{"role": "user", "content": "x"}]})
    assert response.status_code == 200


def test_api_key_diwajibkan_bila_diatur(monkeypatch):
    monkeypatch.setenv("API_ACCESS_KEY", "rahasia-uji")
    assert client.post("/chat", json=VALID).status_code == 401
    assert client.post("/chat", json=VALID, headers={"X-API-Key": "salah"}).status_code == 401
    ok = client.post("/chat", json=VALID, headers={"X-API-Key": "rahasia-uji"})
    assert ok.status_code == 200


def test_health_tidak_butuh_api_key(monkeypatch):
    monkeypatch.setenv("API_ACCESS_KEY", "rahasia-uji")
    assert client.get("/health").status_code == 200
