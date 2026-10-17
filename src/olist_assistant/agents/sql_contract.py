"""Kontrak agent SQL.

Supervisor hanya bergantung pada tanda tangan `jawab_sql` dan bentuk
`SqlResult`. Implementasinya dikerjakan di F3 (owner Starletto) dan wajib
memenuhi guardrail berikut.

- Koneksi SQLite read-only.
- Hanya satu pernyataan SELECT, hanya ke view yang ada di allowlist.
- Selalu ada LIMIT dan batas waktu eksekusi.
- Fungsi tanggal memakai strftime, karena SQLite tidak punya YEAR() atau MONTH().
"""

from typing import Literal, TypedDict


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class SqlResult(TypedDict):
    answer: str
    """Jawaban bahasa natural untuk pengguna."""
    sql: str
    """Query SELECT yang benar-benar dijalankan, untuk trace dan demo."""
    rows: list[dict[str, str | int | float | None]]
    """Hasil query, paling banyak sebanyak LIMIT."""


def jawab_sql(pertanyaan: str, riwayat: list[Message]) -> SqlResult:
    raise NotImplementedError("Agent SQL dikerjakan di F3 oleh Starletto")
