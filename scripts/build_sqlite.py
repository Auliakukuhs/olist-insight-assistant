"""Bangun data/olist.db dari 9 CSV OLIST, lalu kompres menjadi data/olist.db.gz.

Contoh:
    uv run python scripts/build_sqlite.py
"""

import gzip
import shutil
import sqlite3
import time
from pathlib import Path

from olist_assistant.sql.etl import build_database

RAW_DIR = Path("data/raw")
DB_PATH = Path("data/olist.db")
GZ_PATH = Path("data/olist.db.gz")


def main() -> None:
    started = time.monotonic()
    counts = build_database(RAW_DIR, DB_PATH)
    for table, rows in counts.items():
        print(f"{table:22s} {rows:>9,} baris")

    with DB_PATH.open("rb") as source, gzip.open(GZ_PATH, "wb", compresslevel=9) as target:
        shutil.copyfileobj(source, target)

    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT ROUND(SUM(total_bayar_brl), 2) FROM v_pembayaran_per_order")
    print(f"\nTotal pembayaran {total.fetchone()[0]:,.2f} BRL (harus 16,008,872.12)")
    conn.close()
    db_mb = DB_PATH.stat().st_size / 1e6
    gz_mb = GZ_PATH.stat().st_size / 1e6
    print(f"{DB_PATH} {db_mb:.1f} MB, {GZ_PATH} {gz_mb:.1f} MB")
    print(f"Selesai dalam {time.monotonic() - started:.1f} detik")


if __name__ == "__main__":
    main()
