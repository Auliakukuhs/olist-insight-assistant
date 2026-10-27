import gzip
import json
import shutil

import pytest
from fastapi.testclient import TestClient

from olist_assistant.agents.rag import Hit
from olist_assistant.api import auth, rekomendasi
from olist_assistant.api.main import app
from olist_assistant.api.ratelimit import RateLimiter

client = TestClient(app)
USERS = {"pembeli": {"password": "rahasia-pembeli", "peran": "customer"}}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "olist.db"
    with gzip.open("data/olist.db.gz") as source, path.open("wb") as target:
        shutil.copyfileobj(source, target)
    return path


class FakeSearch:
    def __init__(self):
        self.calls = []

    def reviews(self, query, product_id=None, k=6, **kwargs):
        self.calls.append(product_id)
        return [
            Hit(
                f"h-{product_id}",
                "Ulasan pembeli dengan skor 5 dari 5. Isi ulasan chegou rápido",
                {"review_id": "r" * 32, "review_score": 5},
                0.5,
            )
        ]


class FakeModel:
    def __init__(self, gagal=False):
        self.gagal = gagal

    def with_structured_output(self, schema):
        self.schema = schema
        return self

    def invoke(self, prompt):
        if self.gagal:
            raise RuntimeError("LLM mati")
        ids = [
            line.split(":")[0].strip("- ") for line in prompt.splitlines() if line.startswith("- ")
        ]
        return self.schema(
            daftar=[
                {"product_id": i, "alasan": f"Bagus ![x](https://evil.invalid/a.png) {i[:4]}"}
                for i in ids
            ]
        )


@pytest.fixture
def siap(db, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(db))
    monkeypatch.setenv("AUTH_SECRET", "kunci-uji")
    monkeypatch.setenv("DEMO_USERS", json.dumps(USERS))
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    monkeypatch.setattr(auth, "per_client_login", RateLimiter(1000))
    monkeypatch.setattr(rekomendasi, "per_akun", RateLimiter(1000))
    search = FakeSearch()
    monkeypatch.setattr(rekomendasi, "_pencarian", lambda: search)
    monkeypatch.setattr(rekomendasi, "_model", lambda: FakeModel())
    body = client.post(
        "/auth/login", json={"username": "pembeli", "password": "rahasia-pembeli"}
    ).json()
    return {"Authorization": f"Bearer {body['token']}"}, search


def test_peringkat_terbobot_tidak_dikuasai_produk_dengan_sedikit_ulasan():
    rows = [
        {"product_id": "a", "rata_skor": 5.0, "jumlah_ulasan": 5, "jumlah_order": 5},
        {"product_id": "b", "rata_skor": 4.7, "jumlah_ulasan": 60, "jumlah_order": 60},
        {"product_id": "c", "rata_skor": 3.0, "jumlah_ulasan": 40, "jumlah_order": 40},
    ]
    assert [r["product_id"] for r in rekomendasi.peringkat(rows, 3)] == ["b", "a", "c"]


def test_rekomendasi_memakai_filter_dan_tidak_membuka_seller_id(siap):
    headers, search = siap
    r = client.get("/rekomendasi?kategori=toys&harga_max=100&jumlah=3", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["produk"]) == 3 and "seller_id" not in r.text
    for p in body["produk"]:
        assert p["rata_harga_brl"] <= 100 and p["jumlah_ulasan"] >= rekomendasi.MIN_ULASAN
        assert "evil.invalid" not in p["alasan"]
        assert p["ulasan"][0]["cuplikan"] == "chegou rápido"
    skor = [p["skor_berbobot"] for p in body["produk"]]
    assert skor == sorted(skor, reverse=True)
    assert search.calls == [p["product_id"] for p in body["produk"]]


def test_negara_bagian_seller_disaring(siap):
    headers, _ = siap
    r = client.get("/rekomendasi?kategori=baby&negara_bagian_seller=rj", headers=headers)
    assert r.status_code == 200
    assert {p["negara_bagian_seller"] for p in r.json()["produk"]} <= {"RJ"}


def test_alasan_dari_angka_bila_llm_gagal(siap, monkeypatch):
    headers, _ = siap
    monkeypatch.setattr(rekomendasi, "_model", lambda: FakeModel(gagal=True))
    produk = client.get("/rekomendasi?kategori=toys&jumlah=1", headers=headers).json()["produk"]
    assert produk[0]["alasan"].startswith("Rata-rata skor")


@pytest.mark.parametrize(
    ("url", "kode"),
    [
        ("/rekomendasi?kategori=senjata", 422),
        ("/rekomendasi?kategori=toys&negara_bagian_seller=S1", 422),
        ("/rekomendasi?kategori=toys&harga_min=500&harga_max=100", 422),
    ],
)
def test_parameter_tidak_valid_ditolak(siap, url, kode):
    headers, _ = siap
    assert client.get(url, headers=headers).status_code == kode


def test_tanpa_login_ditolak(siap):
    assert client.get("/rekomendasi?kategori=toys").status_code == 401
