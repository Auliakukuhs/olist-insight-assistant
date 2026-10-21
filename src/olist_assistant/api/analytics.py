"""Endpoint data agregat untuk halaman market analysis seller di Streamlit.

Query di sini ditulis tetap, tidak dibuat LLM, dan nilai dari pengguna selalu
lewat parameter terikat, sehingga aman dari SQL injection. Endpoint membaca
view SQLite hasil ETL (issue #4). Kolom yang wajib ada di setiap view tertulis
di VIEW_CONTRACT dan dijaga tes.
"""

import os
import sqlite3
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from olist_assistant.api.auth import current_user
from olist_assistant.api.schemas import Pengguna

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
    # Sama dengan v_item_penjualan tanpa pesanan canceled dan unavailable.
    "v_item_terjual": [
        "order_id",
        "seller_id",
        "kategori",
        "harga_brl",
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

User = Annotated[Pengguna | None, Depends(current_user)]


def check_seller_access(user: Pengguna | None, seller_id: str) -> None:
    """Performa per seller adalah data internal. Seller hanya boleh melihat miliknya."""
    if user is None or user.peran == "admin":
        return
    if user.peran == "seller" and user.seller_id == seller_id:
        return
    detail = (
        "Seller hanya bisa melihat datanya sendiri"
        if user.peran == "seller"
        else "Data performa seller hanya untuk seller yang bersangkutan dan admin"
    )
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail=detail)


def db_path() -> Path:
    return Path(os.getenv("SQLITE_PATH", "data/olist.db"))


def query(sql: str, params: tuple = ()) -> list[dict]:
    """Jalankan query baca saja. Database belum ada menjadi 503."""
    path = db_path()
    if not path.exists():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Data SQL belum tersedia di server"
        )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only = ON")
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


@router.get("/kategori")
def kategori(
    urut: Urutan = "total_penjualan_brl",
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    min_order: Annotated[int, Query(ge=1)] = 1,
    user: User = None,
) -> KategoriResponse:
    """Ringkasan per kategori, diurutkan menurun.

    min_order menyaring kategori kecil. Tanpa itu urutan rata_skor dan
    persen_terlambat dikuasai kategori dengan belasan order saja.
    """
    # Nama kolom tidak bisa jadi parameter terikat. Aman karena urut dibatasi Literal.
    rows = query(
        f"SELECT * FROM v_ringkasan_kategori WHERE jumlah_order >= ? ORDER BY {urut} DESC LIMIT ?",
        (min_order, limit),
    )
    return KategoriResponse(data=[KategoriRow(**r) for r in rows])


@router.get("/seller/{seller_id}")
def seller(seller_id: str, user: User = None) -> SellerRow:
    check_seller_access(user, seller_id)
    rows = query("SELECT * FROM v_ringkasan_seller WHERE seller_id = ?", (seller_id,))
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Seller tidak ditemukan")
    return SellerRow(**rows[0])


@router.get("/tren")
def tren(
    kategori: str | None = None, seller_id: str | None = None, user: User = None
) -> TrenResponse:
    """Penjualan per bulan tanpa pesanan batal, bisa difilter kategori atau seller."""
    if seller_id is not None:
        check_seller_access(user, seller_id)
    rows = query(
        """
        SELECT strftime('%Y-%m', tanggal_beli) AS bulan,
               COUNT(DISTINCT order_id) AS jumlah_order,
               ROUND(SUM(harga_brl), 2) AS total_penjualan_brl
        FROM v_item_terjual
        WHERE (? IS NULL OR kategori = ?) AND (? IS NULL OR seller_id = ?)
        GROUP BY bulan
        ORDER BY bulan
        """,
        (kategori, kategori, seller_id, seller_id),
    )
    return TrenResponse(data=[TrenRow(**r) for r in rows])
