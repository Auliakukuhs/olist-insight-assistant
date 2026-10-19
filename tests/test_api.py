import pytest
from fastapi.testclient import TestClient

from olist_assistant import __version__
from olist_assistant.agents.supervisor import Supervisor
from olist_assistant.api.main import app, get_supervisor

client = TestClient(app)


def fake_supervisor(route="rag", rag_error=None):
    def rag(question, history):
        if rag_error:
            raise rag_error
        return {
            "answer": "jawaban uji",
            "sources": [{"kind": "review", "id": "r1", "snippet": "x"}],
        }

    return Supervisor(
        classify=lambda q, h: route,
        rag=rag,
        sql=lambda q, h: {"answer": "angka", "sql": "SELECT 1", "rows": [{"n": 1}]},
        synthesize=lambda q, s, r: s + r,
    )


VALID = {"message": "Kategori apa yang paling laris?", "session_id": "sesi-1"}


@pytest.fixture(autouse=True)
def tanpa_api_key(monkeypatch):
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    app.dependency_overrides[get_supervisor] = fake_supervisor
    yield
    app.dependency_overrides.clear()


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_chat_mengikuti_kontrak():
    response = client.post("/chat", json=VALID)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"answer", "route", "sources", "table", "request_id"}
    assert body["route"] == "rag"
    assert body["sources"] == [{"kind": "review", "id": "r1", "snippet": "x"}]
    assert len(body["request_id"]) == 32


def test_chat_sql_mengembalikan_tabel():
    app.dependency_overrides[get_supervisor] = lambda: fake_supervisor("sql")
    body = client.post("/chat", json=VALID).json()
    assert body["route"] == "sql"
    assert body["table"] == [{"n": 1}]


def test_agent_gagal_menjadi_502_dengan_kode():
    app.dependency_overrides[get_supervisor] = lambda: fake_supervisor(rag_error=RuntimeError("x"))
    response = client.post("/chat", json=VALID)
    assert response.status_code == 502
    assert "kode" in response.json()["detail"]


def test_tanpa_kunci_layanan_503(monkeypatch):
    app.dependency_overrides.clear()
    get_supervisor.cache_clear()
    for key in ("OPENAI_API_KEY", "QDRANT_URL", "QDRANT_API_KEY"):
        monkeypatch.setenv(key, "")
    monkeypatch.setattr("olist_assistant.api.main.load_dotenv", lambda: None)
    assert client.post("/chat", json=VALID).status_code == 503


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
