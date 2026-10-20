import sqlite3

import pytest
from fastapi.testclient import TestClient

from olist_assistant.api.analytics import VIEW_CONTRACT, db_path
from olist_assistant.api.main import app

client = TestClient(app)


@pytest.fixture
def sqlite_kecil(tmp_path, monkeypatch):
    """Database kecil berisi tabel dengan nama dan kolom sesuai kontrak view."""
    path = tmp_path / "olist.db"
    conn = sqlite3.connect(path)
    for view, cols in VIEW_CONTRACT.items():
        conn.execute(f"CREATE TABLE {view} ({', '.join(cols)})")
    conn.executemany(
        "INSERT INTO v_ringkasan_kategori VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("toys", 100, 9000.0, 90.0, 15.0, 4.1, 8.0),
            ("baby", 50, 12000.0, 240.0, 20.0, 3.9, 12.5),
        ],
    )
    conn.execute(
        "INSERT INTO v_ringkasan_seller VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("s1", "sao paulo", "SP", "toys", 30, 2700.0, 4.3, 7.5, 5.0),
    )
    conn.executemany(
        "INSERT INTO v_item_penjualan VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("o1", "s1", "toys", 50.0, 10.0, "2017-01-05 10:00:00"),
            ("o1", "s1", "toys", 40.0, 10.0, "2017-01-05 10:00:00"),
            ("o2", "s1", "baby", 200.0, 20.0, "2017-02-01 09:00:00"),
        ],
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("SQLITE_PATH", str(path))
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    return path


def test_kategori_urut_dan_limit(sqlite_kecil):
    body = client.get(
        "/analytics/kategori", params={"urut": "total_penjualan_brl", "limit": 1}
    ).json()
    assert [r["kategori"] for r in body["data"]] == ["baby"]
    assert body["mata_uang"] == "BRL"


def test_kolom_urut_di_luar_daftar_ditolak(sqlite_kecil):
    response = client.get("/analytics/kategori", params={"urut": "1; DROP TABLE x"})
    assert response.status_code == 422


def test_seller_ditemukan_dan_tidak(sqlite_kecil):
    assert client.get("/analytics/seller/s1").json()["negara_bagian"] == "SP"
    assert client.get("/analytics/seller/tidak-ada").status_code == 404


def test_tren_per_bulan_tanpa_penggandaan_order(sqlite_kecil):
    data = client.get("/analytics/tren", params={"seller_id": "s1"}).json()["data"]
    assert data == [
        {"bulan": "2017-01", "jumlah_order": 1, "total_penjualan_brl": 90.0},
        {"bulan": "2017-02", "jumlah_order": 1, "total_penjualan_brl": 200.0},
    ]
    toys = client.get("/analytics/tren", params={"kategori": "toys"}).json()["data"]
    assert [r["bulan"] for r in toys] == ["2017-01"]


def test_parameter_berbahaya_diperlakukan_sebagai_data(sqlite_kecil):
    response = client.get("/analytics/seller/x' OR '1'='1")
    assert response.status_code == 404


def test_database_belum_ada_503(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "tidak-ada.db"))
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    assert client.get("/analytics/kategori").status_code == 503


def test_butuh_api_key_bila_diatur(sqlite_kecil, monkeypatch):
    monkeypatch.setenv("API_ACCESS_KEY", "rahasia")
    assert client.get("/analytics/kategori").status_code == 401
    ok = client.get("/analytics/kategori", headers={"X-API-Key": "rahasia"})
    assert ok.status_code == 200


@pytest.mark.skipif(not db_path().exists(), reason="data/olist.db belum dibuat ETL (#4)")
def test_view_hasil_etl_sesuai_kontrak():
    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    try:
        for view, cols in VIEW_CONTRACT.items():
            actual = {row[1] for row in conn.execute(f"PRAGMA table_info({view})")}
            assert set(cols) <= actual, f"{view} kurang kolom {set(cols) - actual}"
    finally:
        conn.close()
