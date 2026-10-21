"""Endpoint data agregat untuk halaman market analysis seller di Streamlit.

Query di sini ditulis tetap, tidak dibuat LLM, dan nilai dari pengguna selalu
lewat parameter terikat, sehingga aman dari SQL injection. Endpoint membaca
view SQLite hasil ETL (issue #4). Kolom yang wajib ada di setiap view tertulis
di VIEW_CONTRACT dan dijaga tes.
"""

import os
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

# Kontrak dengan ETL. Nama dan kolom ini yang dibaca endpoint.
VIEW_CONTRACT: dict[str, list[str]] = {
    "v_ringkasan_kategori": [
        "kategori",
        "jumlah_order",
        "total_penjualan_brl",
        "rata_harga_brl",
        "rata_ongkir_brl",
        "rata_skor",
        "persen_terlambat",
    ],
    "v_ringkasan_seller": [
        "seller_id",
        "kota",
        "negara_bagian",
        "kategori_utama",
        "jumlah_order",
        "total_penjualan_brl",
        "rata_skor",
        "rata_hari_kirim",
        "persen_terlambat",
    ],
    "v_item_penjualan": [
        "order_id",
        "seller_id",
        "kategori",
        "harga_brl",
        "ongkir_brl",
        "tanggal_beli",
    ],
}

Urutan = Literal["total_penjualan_brl", "jumlah_order", "rata_skor", "persen_terlambat"]


class KategoriRow(BaseModel):
    kategori: str
    jumlah_order: int
    total_penjualan_brl: float
    rata_harga_brl: float
    rata_ongkir_brl: float
    rata_skor: float | None
    persen_terlambat: float | None


class SellerRow(BaseModel):
    seller_id: str
    kota: str
    negara_bagian: str
    kategori_utama: str | None
    jumlah_order: int
    total_penjualan_brl: float
    rata_skor: float | None
    rata_hari_kirim: float | None
    persen_terlambat: float | None


class TrenRow(BaseModel):
    bulan: str
    jumlah_order: int
    total_penjualan_brl: float


class KategoriResponse(BaseModel):
    data: list[KategoriRow]
    mata_uang: Literal["BRL"] = "BRL"
    catatan: str = "Data historis OLIST 2016 sampai 2018, bukan harga atau stok saat ini."


class TrenResponse(BaseModel):
    data: list[TrenRow]
    mata_uang: Literal["BRL"] = "BRL"


router = APIRouter(prefix="/analytics", tags=["analytics"])


def db_path() -> Path:
    return Path(os.getenv("SQLITE_PATH", "data/olist.db"))


def existing_db_path() -> Path:
    """Lokasi database. Database belum ada menjadi 503."""
    path = db_path()
    if not path.exists():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Data SQL belum tersedia di server"
        )
    return path


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Jalankan query baca saja."""
    path = existing_db_path()
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


@lru_cache(maxsize=8)
def _view_utuh(view: str, path: str, mtime: float) -> tuple[dict, ...]:
    # mtime ikut jadi kunci cache, jadi database yang diganti terbaca ulang.
    return tuple(query(f"SELECT * FROM {view}"))


def ringkasan(view: Literal["v_ringkasan_kategori", "v_ringkasan_seller"]) -> tuple[dict, ...]:
    """Seluruh isi view ringkasan, dihitung sekali lalu disimpan di memori.

    View ringkasan mengagregasi semua item setiap kali dibaca, sekitar satu detik
    di laptop dan lebih lama di container 0,25 vCPU. Isinya tidak berubah
    selama container hidup, karena database ikut di dalam image.
    """
    path = existing_db_path()
    return _view_utuh(view, str(path), path.stat().st_mtime)


def warm_up() -> bool:
    """Hitung kedua ringkasan sebelum request pertama. False bila database belum ada."""
    if not db_path().exists():
        return False
    ringkasan("v_ringkasan_kategori")
    ringkasan("v_ringkasan_seller")
    return True


@router.get("/kategori")
def kategori(
    urut: Urutan = "total_penjualan_brl",
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> KategoriResponse:
    """Ringkasan per kategori, diurutkan menurun."""
    # Nilai kosong ditaruh paling bawah, sama seperti ORDER BY ... DESC di SQLite.
    rows = sorted(
        ringkasan("v_ringkasan_kategori"),
        key=lambda r: (r[urut] is not None, r[urut] or 0),
        reverse=True,
    )
    return KategoriResponse(data=[KategoriRow(**r) for r in rows[:limit]])


@router.get("/seller/{seller_id}")
def seller(seller_id: str) -> SellerRow:
    for row in ringkasan("v_ringkasan_seller"):
        if row["seller_id"] == seller_id:
            return SellerRow(**row)
    raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Seller tidak ditemukan")


@router.get("/tren")
def tren(kategori: str | None = None, seller_id: str | None = None) -> TrenResponse:
    """Penjualan per bulan, bisa difilter kategori atau seller."""
    rows = query(
        """
        SELECT strftime('%Y-%m', tanggal_beli) AS bulan,
               COUNT(DISTINCT order_id) AS jumlah_order,
               ROUND(SUM(harga_brl), 2) AS total_penjualan_brl
        FROM v_item_penjualan
        WHERE (? IS NULL OR kategori = ?) AND (? IS NULL OR seller_id = ?)
        GROUP BY bulan
        ORDER BY bulan
        """,
        (kategori, kategori, seller_id, seller_id),
    )
    return TrenResponse(data=[TrenRow(**r) for r in rows])
