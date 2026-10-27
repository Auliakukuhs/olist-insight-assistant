import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from olist_assistant.agents.supervisor import Supervisor
from olist_assistant.api import auth, main
from olist_assistant.api.analytics import VIEW_CONTRACT
from olist_assistant.api.auth import make_token, read_token
from olist_assistant.api.main import app, get_supervisor
from olist_assistant.api.ratelimit import RateLimiter
from olist_assistant.api.schemas import Pengguna

client = TestClient(app)
SELLER = "4869f7a5dfa277a7dca6462dcf3b52b2"
LAIN = "0" * 32
USERS = {
    "admin": {"password": "rahasia-admin", "peran": "admin"},
    "toko": {"password": "rahasia-toko", "peran": "seller", "seller_id": SELLER},
    "pembeli": {"password": "rahasia-pembeli", "peran": "customer"},
}


class Calls:
    """Supervisor palsu yang mencatat peran yang sampai ke agent SQL."""

    def __init__(self):
        self.sql_users = []
        self.threads = []

    def supervisor(self):
        def sql(question, history, user):
            self.sql_users.append(user)
            return {"answer": "angka", "sql": "SELECT 1", "rows": []}

        supervisor = Supervisor(
            classify=lambda q, h: "sql",
            rag=lambda q, h: {"answer": "-", "sources": []},
            sql=sql,
            synthesize=lambda q, s, r: s,
        )
        ask = supervisor.ask

        def recording_ask(question, thread, *args):
            self.threads.append(thread)
            return ask(question, thread, *args)

        supervisor.ask = recording_ask
        return supervisor


@pytest.fixture
def login_aktif(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "kunci-uji")
    monkeypatch.setenv("DEMO_USERS", json.dumps(USERS))
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    monkeypatch.setattr(auth, "per_client_login", RateLimiter(1000))
    monkeypatch.setattr(main, "per_session", RateLimiter(1000))
    monkeypatch.setattr(main, "per_client", RateLimiter(1000))
    calls = Calls()
    app.dependency_overrides[get_supervisor] = calls.supervisor
    yield calls
    app.dependency_overrides.clear()


def token_for(username):
    body = client.post(
        "/auth/login", json={"username": username, "password": USERS[username]["password"]}
    )
    assert body.status_code == 200
    return {"Authorization": f"Bearer {body.json()['token']}"}


def test_login_mengembalikan_token_dan_peran(login_aktif):
    body = client.post("/auth/login", json={"username": "toko", "password": "rahasia-toko"}).json()
    assert body["pengguna"] == {"username": "toko", "peran": "seller", "seller_id": SELLER}
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.json()["peran"] == "seller"


@pytest.mark.parametrize(
    "kredensial",
    [{"username": "toko", "password": "salah"}, {"username": "tidak-ada", "password": "x"}],
)
def test_login_salah_ditolak_dengan_pesan_sama(login_aktif, kredensial):
    response = client.post("/auth/login", json=kredensial)
    assert response.status_code == 401
    assert response.json()["detail"] == "Username atau password salah"


def test_token_palsu_atau_kedaluwarsa_ditolak():
    user = Pengguna(username="toko", peran="seller", seller_id=SELLER)
    token = make_token(user, "kunci")
    assert read_token(token, "kunci") == user
    assert read_token(token, "kunci-lain") is None
    payload, signature = token.split(".")
    admin = make_token(Pengguna(username="toko", peran="admin"), "kunci").split(".")[0]
    assert read_token(f"{admin}.{signature}", "kunci") is None
    assert read_token(token, "kunci", now=10**12) is None
    assert read_token("bukan-token", "kunci") is None


def test_chat_wajib_token_bila_login_aktif(login_aktif):
    response = client.post("/chat", json={"message": "Berapa ongkir?", "session_id": "s1"})
    assert response.status_code == 401


def test_peran_dari_token_bukan_dari_body(login_aktif):
    body = {"message": "Berapa rata-rata ongkir ke RJ?", "session_id": "s1", "role": "admin"}
    client.post("/chat", json=body, headers=token_for("toko"))
    assert login_aktif.sql_users == [{"peran": "seller", "seller_id": SELLER}]


def test_riwayat_dipisah_per_akun(login_aktif):
    body = {"message": "Berapa ongkir?", "session_id": "sama"}
    client.post("/chat", json=body, headers=token_for("toko"))
    client.post("/chat", json=body, headers=token_for("pembeli"))
    assert login_aktif.threads == ["toko:sama", "pembeli:sama"]


def test_login_dibatasi_per_klien(login_aktif, monkeypatch):
    monkeypatch.setattr(auth, "per_client_login", RateLimiter(2))
    salah = {"username": "toko", "password": "salah"}
    codes = [client.post("/auth/login", json=salah).status_code for _ in range(3)]
    assert codes == [401, 401, 429]


def test_login_mati_tanpa_auth_secret(monkeypatch):
    monkeypatch.delenv("AUTH_SECRET", raising=False)
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    response = client.post("/auth/login", json={"username": "a", "password": "b"})
    assert response.status_code == 503


def test_akun_seller_tanpa_seller_id_ditolak_saat_dibaca(monkeypatch):
    rusak = {"toko": {"password": "x", "peran": "seller"}}
    monkeypatch.setenv("DEMO_USERS", json.dumps(rusak))
    with pytest.raises(ValueError, match="seller_id"):
        auth.demo_users(main.get_settings())


@pytest.fixture
def analytics_db(tmp_path, monkeypatch):
    path = tmp_path / "olist.db"
    conn = sqlite3.connect(path)
    for view, cols in VIEW_CONTRACT.items():
        conn.execute(f"CREATE TABLE {view} ({', '.join(cols)})")
    for seller in (SELLER, LAIN):
        conn.execute(
            "INSERT INTO v_ringkasan_seller VALUES (?, 'sp', 'SP', 'toys', 1, 10.0, 4.0, 5.0, 0.0)",
            (seller,),
        )
    conn.commit()
    conn.close()
    monkeypatch.setenv("SQLITE_PATH", str(path))


@pytest.mark.parametrize(
    ("username", "seller_id", "code"),
    [
        ("toko", SELLER, 200),
        ("toko", LAIN, 403),
        ("pembeli", SELLER, 403),
        ("admin", LAIN, 200),
    ],
)
def test_performa_seller_menurut_peran(login_aktif, analytics_db, username, seller_id, code):
    headers = token_for(username)
    assert client.get(f"/analytics/seller/{seller_id}", headers=headers).status_code == code
    tren = client.get("/analytics/tren", params={"seller_id": seller_id}, headers=headers)
    assert tren.status_code == code


def test_ringkasan_kategori_boleh_semua_peran(login_aktif, analytics_db):
    for username in USERS:
        assert client.get("/analytics/kategori", headers=token_for(username)).status_code == 200


def test_swagger_punya_tombol_authorize_untuk_api_key_dan_token():
    schemes = client.get("/openapi.json").json()["components"]["securitySchemes"]
    assert schemes["APIKeyHeader"] == {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "API_ACCESS_KEY",
    }
    assert schemes["HTTPBearer"]["scheme"] == "bearer"
    chat = client.get("/openapi.json").json()["paths"]["/chat"]["post"]
    assert {"HTTPBearer": []} in chat["security"]
