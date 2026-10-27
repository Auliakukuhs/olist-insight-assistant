"""Grafik otomatis (#62) dan CSV (#69) dari tabel hasil SQL, tanpa Streamlit."""

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))

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
