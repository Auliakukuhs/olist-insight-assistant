"""Kontrak agent SQL.

Supervisor hanya bergantung pada tanda tangan `jawab_sql` dan bentuk
`SqlResult`. Implementasinya dikerjakan di F3 (owner Starletto) dan wajib
memenuhi guardrail berikut.

- Koneksi SQLite read-only.
- Hanya satu pernyataan SELECT, hanya ke view yang ada di `VIEW_PER_PERAN`
  untuk peran pengguna. Ditegakkan oleh kode, bukan hanya oleh prompt.
- Seller hanya melihat datanya sendiri lewat view `v_penjualan_saya` dan
  `v_ringkasan_saya` yang difilter `seller_id` dari token login. LLM tidak
  pernah menentukan `seller_id`.
- Selalu ada LIMIT dan batas waktu eksekusi.
- Fungsi tanggal memakai strftime, karena SQLite tidak punya YEAR() atau MONTH().
"""

from typing import Literal, TypedDict

Peran = Literal["customer", "seller", "admin"]


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class Pengguna(TypedDict):
    peran: Peran
    seller_id: str | None


class SqlResult(TypedDict):
    answer: str
    """Jawaban bahasa natural untuk pengguna."""
    sql: str
    """Query SELECT yang benar-benar dijalankan, untuk trace dan demo. Kosong bila ditolak."""
    rows: list[dict[str, str | int | float | None]]
    """Hasil query, paling banyak sebanyak LIMIT."""


# Data pasar (tanpa seller_id) boleh untuk semua peran. Performa per seller
# adalah data internal perusahaan, hanya admin yang boleh membaca semuanya.
DATA_PASAR = {"v_pasar", "v_ringkasan_kategori"}
VIEW_PER_PERAN: dict[Peran, set[str]] = {
    "customer": DATA_PASAR,
    "seller": DATA_PASAR | {"v_penjualan_saya", "v_ringkasan_saya"},
    "admin": DATA_PASAR
    | {
        "v_item_penjualan",
        "v_item_terjual",
        "v_pembayaran_per_order",
        "v_review_per_order",
        "v_order",
        "v_ringkasan_seller",
    },
}


def jawab_sql(
    pertanyaan: str,
    riwayat: list[Message],
    peran: Peran = "customer",
    seller_id: str | None = None,
) -> SqlResult:
    raise NotImplementedError("Agent SQL dikerjakan di F3 oleh Starletto")
