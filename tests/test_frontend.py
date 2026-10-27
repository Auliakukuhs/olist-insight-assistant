"""Tes antarmuka Streamlit dengan API palsu, tanpa LLM dan tanpa jaringan."""

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

import requests  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

# Path absolut, karena AppTest 1.66 membaca path relatif dari letak berkas tes.
APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
SELLER = "4869f7a5dfa277a7dca6462dcf3b52b2"
PROSES = {
    "agent": ["supervisor", "sql", "rag"],
    "tools": ["jalankan_sql", "cari_ulasan"],
    "alasan": "Router LLM memilih hybrid.",
    "langkah": [{"nama": "Agent SQL", "durasi_ms": 4000, "token_input": 900, "token_output": 50}],
    "token_input": 900,
    "token_output": 50,
    "biaya_usd": 0.000165,
    "durasi_ms": 4100,
    "model": "gpt-4o-mini",
}


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.ok = status < 400
        self.content = b"x"
        self.text = str(body)

    def json(self):
        return self._body


class FakeApi:
    def __init__(self):
        self.calls = []
        self.cache = False

    def __call__(self, method, url, headers=None, json=None, params=None, timeout=None):
        path = url.removeprefix("http://api.uji")
        self.calls.append((method, path, headers or {}, json, params or {}))
        if path == "/auth/login":
            if json["password"] != "benar":
                return FakeResponse(401, {"detail": "Username atau password salah"})
            peran = json["username"]
            seller_id = SELLER if peran == "seller" else None
            user = {"username": peran, "peran": peran, "seller_id": seller_id}
            return FakeResponse(200, {"token": f"token-{peran}", "pengguna": user})
        if path == "/chat":
            return FakeResponse(
                200,
                {
                    "answer": "Rata-rata 82,04 BRL dan pembeli mengeluh telat.",
                    "route": "hybrid",
                    "sources": [
                        {"kind": "sql", "id": "query", "snippet": "SELECT 1"},
                        {"kind": "review", "id": "r1", "snippet": "chegou atrasado"},
                    ],
                    "table": [{"rata": 82.04}],
                    "proses": {**PROSES, "cache": self.cache},
                    "request_id": "x" * 32,
                    "trace_id": "a" * 32,
                },
            )
        if path == "/feedback":
            return FakeResponse(200, {"tercatat": True})
        if path.startswith("/analytics/kategori"):
            baris = {
                "kategori": "toys",
                "jumlah_order": 3800,
                "total_penjualan_brl": 1.0,
                "rata_harga_brl": 1.0,
                "rata_ongkir_brl": 1.0,
                "rata_skor": 4.2,
                "persen_terlambat": 6.0,
            }
            return FakeResponse(200, {"data": [baris], "mata_uang": "BRL", "catatan": "historis"})
        if path.startswith("/rekomendasi"):
            produk = {
                "product_id": "dd6a505f83" + "0" * 22,
                "jumlah_order": 36,
                "jumlah_ulasan": 36,
                "rata_harga_brl": 49.79,
                "rata_skor": 4.69,
                "skor_berbobot": 4.58,
                "persen_terlambat": 0.0,
                "negara_bagian_seller": "SP",
                "alasan": "Pembeli memuji kualitasnya.",
                "ulasan": [{"id": "r1", "skor": 5, "cuplikan": "chegou rápido"}],
            }
            return FakeResponse(
                200, {"kategori": "toys", "produk": [produk], "catatan": "skor terbobot"}
            )
        if path.startswith("/analytics/seller/"):
            return FakeResponse(
                200,
                {
                    "seller_id": SELLER,
                    "kota": "guariba",
                    "negara_bagian": "SP",
                    "kategori_utama": "watches_gifts",
                    "jumlah_order": 1131,
                    "total_penjualan_brl": 229237.63,
                    "rata_skor": 4.13,
                    "rata_hari_kirim": 15.1,
                    "persen_terlambat": 10.5,
                },
            )
        if path.startswith("/analytics/tren"):
            return FakeResponse(200, {"data": [], "mata_uang": "BRL"})
        return FakeResponse(404, {"detail": "tidak ada"})


@pytest.fixture
def api(monkeypatch):
    fake = FakeApi()
    monkeypatch.setattr(requests, "request", fake)
    return fake


def start():
    at = AppTest.from_file(str(APP), default_timeout=30)
    at.secrets["API_URL"] = "http://api.uji"
    at.secrets["API_ACCESS_KEY"] = "kunci"
    return at.run()


def login(at, username, password="benar"):
    at.text_input[0].input(username)
    at.text_input[1].input(password)
    at.button[0].click()
    return at.run()


def test_password_salah_menampilkan_pesan(api):
    at = login(start(), "seller", "salah")
    assert "Username atau password salah" in at.error[0].value


def test_chat_mengirim_token_dan_menampilkan_panel_proses(api):
    at = login(start(), "seller")
    at.chat_input[0].set_value("Berapa rata-rata harga furniture?").run()
    method, path, headers, body, _ = [c for c in api.calls if c[1] == "/chat"][-1]
    assert method == "POST"
    assert headers == {"X-API-Key": "kunci", "Authorization": "Bearer token-seller"}
    assert set(body) == {"message", "session_id"}
    assert any("Agent SQL, Agent RAG" in c.value for c in at.caption)
    assert not any("dari cache" in c.value for c in at.caption)
    labels = [e.label for e in at.expander]
    assert "Detail proses" in labels and "Query SQL yang dijalankan" in labels
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Token input"] == "900"
    assert metrics["Total token"] == "950"


def test_jawaban_dari_cache_diberi_tanda(api):
    api.cache = True
    at = login(start(), "customer")
    at.chat_input[0].set_value("Berapa rata-rata ongkir?").run()
    assert any("dari cache" in c.value for c in at.caption)


def test_logout_kembali_ke_halaman_login(api):
    at = login(start(), "admin")
    at.sidebar.button[1].click().run()
    assert at.title[0].value == "OLIST Insight Assistant"
    assert len(at.text_input) == 2


def test_401_di_tengah_sesi_membersihkan_semua_dan_kembali_ke_login(api, monkeypatch):
    # Audit 25 Okt (S08): dulu hanya token yang dihapus, pengguna dan riwayat tertinggal.
    at = login(start(), "customer")
    at.chat_input[0].set_value("Berapa rata-rata harga furniture?").run()
    assert len(at.session_state.messages) == 2

    def kedaluwarsa(method, url, **kwargs):
        return FakeResponse(401, {"detail": "Silakan login ulang"})

    monkeypatch.setattr(requests, "request", kedaluwarsa)
    at.chat_input[0].set_value("Pertanyaan lanjutan").run()
    assert at.session_state.token is None and at.session_state.pengguna is None
    assert at.session_state.messages == []
    assert [t.label for t in at.text_input] == ["Username", "Password"]
    assert "Sesi login berakhir" in at.error[0].value


def test_cari_produk_mengirim_filter_dan_menampilkan_alasan(api):
    at = login(start(), "customer")
    assert [t.label for t in at.tabs] == ["Chat", "Cari produk"]
    at.number_input[1].set_value(100.0)
    at.selectbox[1].set_value("SP")
    at.button(key="FormSubmitter:cari_produk-Cari").click().run()
    kirim = [c for c in api.calls if c[1].startswith("/rekomendasi")]
    assert kirim, "API rekomendasi tidak dipanggil"
    assert kirim[-1][4] == {
        "kategori": "toys",
        "harga_min": 0.0,
        "harga_max": 100.0,
        "negara_bagian_seller": "SP",
    }
    assert any("Pembeli memuji kualitasnya." in m.value for m in at.markdown)
    assert any(m.label == "Skor ulasan" for m in at.metric)


def test_jempol_mengirim_umpan_balik_untuk_trace_jawaban(api):
    at = login(start(), "customer")
    at.chat_input[0].set_value("Berapa rata-rata harga furniture?").run()
    assert len(at.feedback) == 1
    at.feedback[0].set_value(0).run()
    kiriman = [c for c in api.calls if c[1] == "/feedback"]
    assert kiriman and kiriman[-1][3] == {"trace_id": "a" * 32, "suka": False}
