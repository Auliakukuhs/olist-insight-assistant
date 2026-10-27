"""Grafik otomatis (#62) dan CSV (#69) dari tabel hasil SQL, tanpa Streamlit."""

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))

from pasar import bandingkan, pangsa_bulanan, seller_id_sah  # noqa: E402
from tabel import bentuk_grafik, data_grafik, ke_csv  # noqa: E402

KATEGORI = [{"kategori": "bed_bath_table", "jumlah": 9417}, {"kategori": "toys", "jumlah": 3886}]
BULAN = [{"bulan": "2017-02", "total": 2.0}, {"bulan": "2017-01", "total": 1.0}]


def test_kategori_dan_angka_jadi_bar_chart():
    assert bentuk_grafik(KATEGORI) == {"jenis": "bar", "label": "kategori", "angka": "jumlah"}


def test_bulan_jadi_line_chart_terurut():
    bentuk = bentuk_grafik(BULAN)
    assert bentuk == {"jenis": "line", "label": "bulan", "angka": "total"}
    assert data_grafik(BULAN, bentuk) == {"bulan": ["2017-01", "2017-02"], "total": [1.0, 2.0]}


def test_tahun_berupa_angka_tetap_jadi_line_chart():
    tahun = [{"tahun": 2017, "pesanan": 45101}, {"tahun": 2018, "pesanan": 54011}]
    assert bentuk_grafik(tahun) == {"jenis": "line", "label": "tahun", "angka": "pesanan"}


def test_tabel_yang_tidak_cocok_tetap_tabel():
    tiga_kolom = [{"kategori": "toys", "jumlah": 1, "rata": 2.0}] * 2
    dua_angka = [{"harga": 10.0, "ongkir": 2.0}] * 2
    dua_teks = [{"kota": "sao paulo", "negara_bagian": "SP"}] * 2
    satu_baris = KATEGORI[:1]
    terlalu_panjang = [{"kategori": f"k{i}", "jumlah": i} for i in range(51)]
    for tabel in (None, [], tiga_kolom, dua_angka, dua_teks, satu_baris, terlalu_panjang):
        assert bentuk_grafik(tabel) is None, tabel


def test_csv_utf8_dengan_bom_dan_kosong_untuk_none():
    data = ke_csv([{"kota": "são paulo", "rata": 1.5}, {"kota": None, "rata": 2}])
    assert data.startswith(b"\xef\xbb\xbf")
    baris = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert baris == [["kota", "rata"], ["são paulo", "1.5"], ["", "2"]]


def test_csv_menetralkan_rumus_spreadsheet():
    data = ke_csv(
        [{"teks": '=HYPERLINK("http://x")', "angka": -5}, {"teks": "@SUM(A1)", "angka": 1}]
    )
    baris = list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))
    assert baris[1] == ['\'=HYPERLINK("http://x")', "-5"]
    assert baris[2][0] == "'@SUM(A1)"


def test_toko_dibanding_pasar_menandai_unggul_dan_kalah():
    toko = {"rata_skor": 3.9, "persen_terlambat": 5.0}
    pasar = {"rata_skor": 4.1, "persen_terlambat": 8.0}
    skor, terlambat = bandingkan(toko, pasar)
    assert skor["label"] == "Skor ulasan" and not skor["lebih_baik"]
    assert round(skor["selisih"], 2) == -0.2
    assert terlambat["lebih_baik"] and terlambat["selisih"] == -3.0
    assert bandingkan(toko, None) == []
    assert bandingkan({"rata_skor": None, "persen_terlambat": 5.0}, pasar)[0]["label"] == (
        "Persen terlambat"
    )


def test_pangsa_bulanan_terurut_dan_tanpa_bagi_nol():
    toko = [{"bulan": "2017-02", "total_penjualan_brl": 300.0}]
    pasar = [
        {"bulan": "2017-02", "total_penjualan_brl": 1500.0},
        {"bulan": "2017-01", "total_penjualan_brl": 1000.0},
        {"bulan": "2017-03", "total_penjualan_brl": 0.0},
    ]
    assert pangsa_bulanan(toko, pasar) == [
        {"bulan": "2017-01", "pangsa_persen": 0.0},
        {"bulan": "2017-02", "pangsa_persen": 20.0},
    ]


def test_seller_id_sah():
    assert seller_id_sah("4869f7a5dfa277a7dca6462dcf3b52b2")
    assert seller_id_sah(" 4869F7A5DFA277A7DCA6462DCF3B52B2 ")
    for salah in ("", "abc", "../admin", "4869f7a5dfa277a7dca6462dcf3b52b2?x=1"):
        assert not seller_id_sah(salah)
