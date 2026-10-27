"""Perhitungan halaman Market analysis (#12), tanpa Streamlit supaya bisa diuji.

Yang dibandingkan dengan toko hanya agregat pasar per kategori, jadi tidak ada
data seller lain yang terbuka.
"""

import re

SELLER_ID = re.compile(r"^[0-9a-f]{32}$")


def seller_id_sah(teks: str) -> bool:
    return bool(SELLER_ID.fullmatch(teks.strip().lower()))


def format_skor(nilai: float | None) -> str:
    return "-" if nilai is None else f"{nilai:.2f}"


def format_persen(nilai: float | None) -> str:
    return "-" if nilai is None else f"{nilai:.1f}%"


def bandingkan(toko: dict, kategori: dict | None) -> list[dict]:
    """Skor dan keterlambatan toko dibanding rata-rata kategori utamanya.

    "lebih_baik" True bila toko unggul: skor lebih tinggi, terlambat lebih rendah.
    Baris dengan nilai kosong di salah satu sisi dilewati.
    """
    if not kategori:
        return []
    hasil = []
    for kolom, label, tinggi_lebih_baik in (
        ("rata_skor", "Skor ulasan", True),
        ("persen_terlambat", "Persen terlambat", False),
    ):
        nilai_toko, nilai_pasar = toko.get(kolom), kategori.get(kolom)
        if nilai_toko is None or nilai_pasar is None:
            continue
        selisih = nilai_toko - nilai_pasar
        hasil.append(
            {
                "label": label,
                "toko": nilai_toko,
                "pasar": nilai_pasar,
                "selisih": selisih,
                "lebih_baik": selisih > 0 if tinggi_lebih_baik else selisih < 0,
            }
        )
    return hasil


def pangsa_bulanan(tren_toko: list[dict], tren_kategori: list[dict]) -> list[dict]:
    """Porsi penjualan toko di kategori utamanya per bulan, dalam persen.

    tren_toko adalah tren toko yang difilter ke kategori yang sama. Bulan tanpa
    penjualan kategori dilewati supaya tidak membagi dengan nol.
    """
    toko = {r["bulan"]: r["total_penjualan_brl"] for r in tren_toko}
    return [
        {
            "bulan": r["bulan"],
            "pangsa_persen": round(100 * toko.get(r["bulan"], 0.0) / r["total_penjualan_brl"], 2),
        }
        for r in sorted(tren_kategori, key=lambda r: r["bulan"])
        if r["total_penjualan_brl"]
    ]
