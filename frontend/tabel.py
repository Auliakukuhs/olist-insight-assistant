"""Grafik otomatis (#62) dan unduhan CSV (#69) dari tabel hasil SQL.

Tanpa Streamlit, supaya bisa diuji langsung. app.py yang menggambarnya.
"""

import csv
import io
import re

BARIS_MAKS_GRAFIK = 50
KOLOM_WAKTU = {"bulan", "month", "tahun", "year", "periode"}
NILAI_WAKTU = re.compile(r"^\d{4}(-\d{2})?$")
# Sel yang diawali karakter ini dijalankan sebagai rumus oleh Excel dan Google
# Sheets (CSV injection). Teks dari data diberi awalan apostrof supaya tetap teks.
AWALAN_RUMUS = ("=", "+", "-", "@", "\t", "\r")


def _angka(nilai) -> bool:
    return isinstance(nilai, int | float) and not isinstance(nilai, bool)


def bentuk_grafik(table: list[dict] | None) -> dict | None:
    """{"jenis": "line" atau "bar", "label": kolom, "angka": kolom}, atau None.

    Grafik hanya untuk tabel dengan tepat satu kolom label dan satu kolom angka,
    2 sampai 50 baris. Label waktu (bulan 2017-01 atau tahun) memakai line chart,
    selain itu bar chart. Tabel lain tetap ditampilkan sebagai tabel saja.
    """
    if not table or not 2 <= len(table) <= BARIS_MAKS_GRAFIK:
        return None
    kolom = list(table[0])
    if len(kolom) != 2 or any(list(baris) != kolom for baris in table):
        return None
    numerik = [k for k in kolom if all(_angka(b[k]) for b in table)]
    teks = [k for k in kolom if all(isinstance(b[k], str) for b in table)]
    # Tahun sering kembali sebagai bilangan bulat, jadi kolom waktu boleh angka.
    waktu = [k for k in kolom if k.lower() in KOLOM_WAKTU]
    if len(numerik) == 2 and len(waktu) == 1:
        label = waktu[0]
    elif len(numerik) == 1 and len(teks) == 1:
        label = teks[0]
    else:
        return None
    angka = next(k for k in kolom if k != label)
    berbentuk_waktu = label.lower() in KOLOM_WAKTU or all(
        NILAI_WAKTU.match(str(b[label])) for b in table
    )
    return {"jenis": "line" if berbentuk_waktu else "bar", "label": label, "angka": angka}


def data_grafik(table: list[dict], bentuk: dict) -> dict[str, list]:
    """Kolom untuk st.bar_chart atau st.line_chart. Waktu diurutkan dari yang awal."""
    baris = table
    if bentuk["jenis"] == "line":
        baris = sorted(table, key=lambda b: str(b[bentuk["label"]]))
    return {
        bentuk["label"]: [str(b[bentuk["label"]]) for b in baris],
        bentuk["angka"]: [b[bentuk["angka"]] for b in baris],
    }


def _aman(nilai):
    if isinstance(nilai, str) and nilai.startswith(AWALAN_RUMUS):
        return "'" + nilai
    return "" if nilai is None else nilai


def ke_csv(table: list[dict]) -> bytes:
    """CSV UTF-8 dengan BOM, supaya Excel membaca huruf non-ASCII dengan benar."""
    kolom = list(dict.fromkeys(k for baris in table for k in baris))
    buffer = io.StringIO()
    penulis = csv.DictWriter(buffer, fieldnames=kolom, lineterminator="\n")
    penulis.writeheader()
    for baris in table:
        penulis.writerow({k: _aman(baris.get(k)) for k in kolom})
    return buffer.getvalue().encode("utf-8-sig")
