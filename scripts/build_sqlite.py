"""Bangun data/olist.db dari 9 CSV OLIST, lalu kompres menjadi data/olist.db.gz.

Butuh grup ingest (pandas).

Contoh:
    uv sync --group ingest
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

# Total payment_value di CSV asli. Angka lain berarti ada join yang berlipat.
EXPECTED_PAYMENT_BRL = 16_008_872.12


def main() -> None:
    started = time.monotonic()
    counts = build_database(RAW_DIR, DB_PATH)
    for table, rows in counts.items():
        print(f"{table:22s} {rows:>9,} baris")

    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT ROUND(SUM(total_bayar_brl), 2) FROM v_pembayaran_per_order")
    total = total.fetchone()[0]
    conn.close()
    print(f"\nTotal pembayaran {total:,.2f} BRL")
    if total != EXPECTED_PAYMENT_BRL:
        raise SystemExit(f"Total seharusnya {EXPECTED_PAYMENT_BRL:,.2f}. Ada join yang berlipat.")

    # mtime=0 dan tanpa nama berkas supaya database yang sama menghasilkan gzip
    # yang sama persis, sehingga git tidak melihat perubahan palsu.
    with DB_PATH.open("rb") as source, GZ_PATH.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as target:
            shutil.copyfileobj(source, target)
    db_mb = DB_PATH.stat().st_size / 1e6
    gz_mb = GZ_PATH.stat().st_size / 1e6
    print(f"{DB_PATH} {db_mb:.1f} MB, {GZ_PATH} {gz_mb:.1f} MB")
    print(f"Selesai dalam {time.monotonic() - started:.1f} detik")


if __name__ == "__main__":
    main()
