import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from olist_assistant.api import auth, pemakaian
from olist_assistant.api.main import app
from olist_assistant.api.ratelimit import RateLimiter

client = TestClient(app)
USERS = {
    "admin": {"password": "rahasia-admin", "peran": "admin"},
    "toko": {
        "password": "rahasia-toko",
        "peran": "seller",
        "seller_id": "4869f7a5dfa277a7dca6462dcf3b52b2",
    },
    "pembeli": {"password": "rahasia-pembeli", "peran": "customer"},
}


class FakeMetrics:
    """Menjawab kueri metrics Langfuse sesuai filter dan dimensinya, dan mencatat kuerinya."""

    def __init__(self):
        self.queries = []

    def metrics(self, query):
        q = json.loads(query)
        self.queries.append(q)
        names = [f["value"] for f in q["filters"] if f["column"] == "name"]
        dims = [d["field"] for d in q["dimensions"]]
        if q["view"] == "scores-boolean":
            data = [
                {"booleanValue": True, "count_count": 3},
                {"booleanValue": False, "count_count": 1},
            ]
        elif "tags" in dims:
            data = [
                {"tags": ["customer"], "count_count": 5},
                {"tags": ["seller"], "count_count": 2},
            ]
        elif "name" in dims:
            data = [{"name": "agent_sql", "count_count": 4}, {"name": "langsung", "count_count": 1}]
        elif names == ["olist-supervisor"]:
            data = [
                {
                    "time_dimension": "2026-10-25",
                    "count_count": 6,
                    "p50_latency": 3396,
                    "p95_latency": 11032.6,
                },
                {
                    "time_dimension": "2026-10-24",
                    "count_count": 2,
                    "p50_latency": 3991,
                    "p95_latency": 14456.4,
                },
            ]
        else:
            data = [
                {
                    "time_dimension": "2026-10-25",
                    "sum_totalTokens": 9000,
                    "sum_totalCost": 0.0012345,
                }
            ]
        return SimpleNamespace(data=data)


@pytest.fixture
def langfuse(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "kunci-uji")
    monkeypatch.setenv("DEMO_USERS", json.dumps(USERS))
    monkeypatch.setenv("LANGFUSE_TRACING_ENVIRONMENT", "production")
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    monkeypatch.setattr(auth, "per_client_login", RateLimiter(1000))
    fake = FakeMetrics()
    monkeypatch.setattr(
        pemakaian, "langfuse_client", lambda: SimpleNamespace(api=SimpleNamespace(metrics=fake))
    )
    yield fake


def masuk(username):
    body = client.post(
        "/auth/login", json={"username": username, "password": USERS[username]["password"]}
    ).json()
    return {"Authorization": f"Bearer {body['token']}"}


def test_admin_mendapat_ringkasan_per_hari_peran_agent_dan_umpan_balik(langfuse):
    body = client.get("/admin/pemakaian?hari=7", headers=masuk("admin")).json()
    assert body["environment"] == "production"
    assert [h["tanggal"] for h in body["per_hari"]] == ["2026-10-24", "2026-10-25"]
    hari_ini = body["per_hari"][1]
    assert hari_ini == {
        "tanggal": "2026-10-25",
        "pertanyaan": 6,
        "token": 9000,
        "biaya_usd": 0.0012,
        "latensi_p50_ms": 3396.0,
        "latensi_p95_ms": 11032.6,
    }
    assert body["per_hari"][0]["token"] == 0
    assert body["per_peran"] == {"customer": 5, "seller": 2}
    assert body["per_agent"] == {"sql": 4, "supervisor": 1}
    assert body["umpan_balik"] == {"naik": 3, "turun": 1}


def test_hanya_environment_server_ini_yang_dihitung(langfuse):
    client.get("/admin/pemakaian", headers=masuk("admin"))
    for q in langfuse.queries:
        assert {
            "column": "environment",
            "operator": "=",
            "value": "production",
            "type": "string",
        } in q["filters"]


@pytest.mark.parametrize("username", ["toko", "pembeli"])
def test_selain_admin_ditolak(langfuse, username):
    response = client.get("/admin/pemakaian", headers=masuk(username))
    assert response.status_code == 403
    assert langfuse.queries == []


def test_tanpa_login_dan_rentang_tidak_valid(langfuse):
    assert client.get("/admin/pemakaian").status_code == 401
    assert client.get("/admin/pemakaian?hari=90", headers=masuk("admin")).status_code == 422


def test_langfuse_mati_503(langfuse, monkeypatch):
    monkeypatch.setattr(pemakaian, "langfuse_client", lambda: None)
    assert client.get("/admin/pemakaian", headers=masuk("admin")).status_code == 503
