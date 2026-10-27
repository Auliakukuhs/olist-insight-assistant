"""Bangun docs/KAMUS-DATA.md dari view SQLite (#5).

Tipe, jumlah baris, persen kosong, dan contoh nilai dibaca dari data/olist.db,
jadi kamus tidak tertinggal dari ETL. Keterangan dan satuan ditulis di KOLOM.

    uv run python scripts/kamus_data.py
"""

import sqlite3
import sys
from pathlib import Path

DB = Path("data/olist.db")
OUT = Path("docs/KAMUS-DATA.md")

VIEW = {
    "v_item_penjualan": "item pesanan, semua status",
    "v_item_terjual": "item pesanan tanpa status `canceled` dan `unavailable`",
    "v_order": "pesanan",
    "v_pembayaran_per_order": "pesanan yang punya data pembayaran",
    "v_review_per_order": "pesanan yang punya review",
    "v_pasar": "item terjual tanpa `seller_id`, untuk customer dan seller",
    "v_ringkasan_kategori": "kategori",
    "v_ringkasan_seller": "seller",
}

# kolom: (satuan, keterangan)
KOLOM = {
    "order_id": ("", "ID pesanan, 32 karakter heksadesimal"),
    "order_item_id": ("", "Urutan item di dalam satu pesanan, mulai 1"),
    "product_id": ("", "ID produk. Data tidak memuat nama atau foto produk"),
    "seller_id": ("", "ID seller. Data internal, hanya admin yang melihat seller lain"),
    "kategori": (
        "",
        "Kategori produk dalam bahasa Inggris. Produk tanpa kategori diberi `unknown`",
    ),
    "kategori_utama": ("", "Kategori dengan penjualan terbesar milik seller"),
    "harga_brl": ("BRL", "Harga item, tanpa ongkir"),
    "ongkir_brl": ("BRL", "Ongkos kirim item"),
    "tanggal_beli": ("waktu lokal Brasil", "Waktu pesanan dibuat, `YYYY-MM-DD HH:MM:SS`"),
    "status_order": ("", "Status pesanan, misalnya `delivered`, `shipped`, `canceled`"),
    "kota_seller": ("", "Kota seller, huruf kecil tanpa aksen"),
    "negara_bagian_seller": ("", "Kode negara bagian seller, dua huruf"),
    "kota_pembeli": ("", "Kota pembeli, huruf kecil tanpa aksen"),
    "negara_bagian_pembeli": ("", "Kode negara bagian pembeli, dua huruf"),
    "terlambat": ("0 atau 1", "1 bila tiba sesudah tanggal estimasi. Kosong bila belum tiba"),
    "hari_kirim": ("hari", "Lama dari pesan sampai tiba di pembeli. Kosong bila belum tiba"),
    "skor": ("1 sampai 5", "Rata-rata skor review pesanan. Kosong bila tanpa review"),
    "skor_ulasan": ("1 sampai 5", "Rata-rata skor review pesanan. Kosong bila tanpa review"),
    "jumlah_review": ("review", "Jumlah review untuk pesanan ini"),
    "jumlah_pembayaran": ("transaksi", "Jumlah transaksi pembayaran untuk pesanan"),
    "total_bayar_brl": ("BRL", "Total dibayar pembeli, termasuk ongkir"),
    "cicilan_maks": ("kali", "Jumlah cicilan terbesar di pesanan"),
    "metode": ("", "Metode pembayaran utama, misalnya `credit_card`, `boleto`"),
    "jumlah_order": ("pesanan", "Jumlah pesanan unik"),
    "total_penjualan_brl": ("BRL", "Jumlah harga item terjual, tanpa ongkir"),
    "rata_harga_brl": ("BRL", "Rata-rata harga item"),
    "rata_ongkir_brl": ("BRL", "Rata-rata ongkir item"),
    "rata_skor": ("1 sampai 5", "Rata-rata skor review pesanan"),
    "rata_hari_kirim": ("hari", "Rata-rata lama kirim pesanan yang sudah tiba"),
    "persen_terlambat": ("persen", "Persen pesanan tiba sesudah estimasi, dari yang sudah tiba"),
    "kota": ("", "Kota seller"),
    "negara_bagian": ("", "Kode negara bagian seller"),
}

# (jebakan, angka, akibat dan penanganan)
JEBAKAN = [
    (
        "Review tanpa teks",
        "58,7 persen dari 99.224 review (judul kosong 88,3 persen)",
        "Qdrant hanya memuat review yang punya judul atau teks (`rag/documents.py`). "
        "Skor semua review tetap dipakai SQL",
    ),
    (
        "Produk tanpa kategori",
        "610 produk, 1.603 item",
        "Diberi kategori `unknown` supaya tidak hilang dari total",
    ),
    (
        "Data historis",
        "Pesanan 4 September 2016 sampai 17 Oktober 2018",
        'Bukan harga, stok, atau seller saat ini. Ditolak bila ditanya "sekarang"',
    ),
    (
        "Pesanan belum tiba",
        "2.965 pesanan tanpa tanggal tiba",
        "`terlambat` dan `hari_kirim` kosong, tidak dihitung sebagai tepat waktu",
    ),
    (
        "Pesanan batal",
        "549 item `canceled` dan `unavailable` (97.242,96 BRL)",
        "Tidak masuk penjualan. Pakai `v_item_terjual` untuk penjualan",
    ),
    (
        "Join pembayaran",
        "Join langsung item dengan pembayaran menaikkan total dari 16,0 juta menjadi 20,3 juta BRL",
        "Pembayaran dan review diringkas per pesanan dulu",
    ),
    (
        "Pesanan tanpa review",
        "768 pesanan",
        "`skor` kosong",
    ),
    (
        "Kategori dan seller kecil",
        "11 dari 74 kategori di bawah 30 pesanan, 3 di bawah 10",
        "Peringkat rasio (skor, persen terlambat) memakai minimal 30 pesanan, "
        "ditegakkan di kode agent SQL (`MIN_ORDER`)",
    ),
    (
        "Nama dan kontak",
        "Tidak ada di data",
        "Pertanyaan nama, alamat, atau kontak orang ditolak",
    ),
]


def ribuan(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def persen(nilai: float) -> str:
    """Satu desimal dengan koma, tanpa ",0" di ujung."""
    return f"{nilai:.1f}".replace(".", ",").removesuffix(",0") + "%"


def tipe(conn, view: str, kolom: str) -> str:
    rows = conn.execute(
        f'SELECT typeof("{kolom}"), COUNT(*) FROM {view} GROUP BY 1 ORDER BY 2 DESC'
    ).fetchall()
    nama = {"text": "teks", "integer": "bilangan bulat", "real": "desimal"}
    jenis = [nama.get(t, t) for t, _ in rows if t != "null"]
    return ", ".join(jenis) or "kosong"


def contoh(conn, view: str, kolom: str) -> str:
    rows = conn.execute(
        f'SELECT DISTINCT "{kolom}" FROM {view} WHERE "{kolom}" IS NOT NULL LIMIT 3'
    ).fetchall()
    nilai = []
    for (v,) in rows:
        teks = f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)
        nilai.append(f"`{teks[:12]}...`" if len(teks) > 20 else f"`{teks}`")
    return ", ".join(nilai)


def bangun(conn) -> str:
    bagian = [
        "# Kamus data OLIST",
        "",
        "Dibangun otomatis oleh `scripts/kamus_data.py` dari `data/olist.db`. Agent SQL dan "
        "endpoint analytics hanya membaca view di bawah, tidak membaca tabel mentah.",
        "",
        "## Jebakan data",
        "",
        "Hal yang perlu diingat saat membaca angka, menulis prompt agent, atau menjawab "
        "pertanyaan penguji.",
        "",
        "| Jebakan | Angka | Akibat dan penanganan |",
        "|---|---|---|",
        *(f"| {a} | {b} | {c} |" for a, b, c in JEBAKAN),
        "",
    ]
    for view, butir in VIEW.items():
        baris = conn.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
        bagian += [f"## `{view}`", "", f"Satu baris per {butir}. {ribuan(baris)} baris.", ""]
        bagian += [
            "| Kolom | Tipe | Satuan | Keterangan | Kosong | Contoh |",
            "|---|---|---|---|---|---|",
        ]
        for _, kolom, *_ in conn.execute(f"PRAGMA table_info({view})"):
            satuan, keterangan = KOLOM[kolom]
            kosong = conn.execute(
                f'SELECT 100.0 * SUM("{kolom}" IS NULL) / COUNT(*) FROM {view}'
            ).fetchone()[0]
            bagian.append(
                f"| `{kolom}` | {tipe(conn, view, kolom)} | {satuan or '-'} | {keterangan} "
                f"| {persen(kosong)} | {contoh(conn, view, kolom)} |"
            )
        bagian.append("")
    return "\n".join(bagian)


def kolom_tanpa_keterangan(conn) -> list[str]:
    return [
        f"{view}.{kolom}"
        for view in VIEW
        for _, kolom, *_ in conn.execute(f"PRAGMA table_info({view})")
        if kolom not in KOLOM
    ]


if __name__ == "__main__":
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    hilang = kolom_tanpa_keterangan(conn)
    if hilang:
        sys.exit(f"Kolom belum punya keterangan di KOLOM: {', '.join(hilang)}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(bangun(conn))
    print(f"{OUT} ditulis")
