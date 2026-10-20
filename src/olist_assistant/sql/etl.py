"""ETL 9 CSV OLIST ke satu database SQLite.

Alurnya Extract (baca CSV), Transform (rapikan tipe kolom dan ringkas
geolocation), lalu Load (tulis tabel ke SQLite dan buat view).
"""

import sqlite3
from pathlib import Path

import pandas as pd

# Nama tabel di database dan nama berkas CSV aslinya.
CSV_FILES = {
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
    "geolocation": "olist_geolocation_dataset.csv",
}

# Kolom yang diubah dari teks ke angka. Kolom lain tetap teks.
NUMBER_COLUMNS = {
    "order_items": ["order_item_id", "price", "freight_value"],
    "order_payments": ["payment_sequential", "payment_installments", "payment_value"],
    "order_reviews": ["review_score"],
    "products": [
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm",
    ],
}

# Kolom yang tidak dipakai dan dibuang supaya database kecil. Teks ulasan
# sudah tersimpan di Qdrant untuk RAG, SQL cukup memakai skornya.
DROP_COLUMNS = {
    "products": ["product_name_lenght", "product_description_lenght"],
    "order_reviews": ["review_comment_title", "review_comment_message", "review_answer_timestamp"],
    "orders": ["order_approved_at", "order_delivered_carrier_date"],
}

# Index hanya untuk kolom penghubung yang dipakai join di dalam view.
INDEXES = [
    "CREATE INDEX idx_items_order ON order_items(order_id)",
    "CREATE INDEX idx_orders_order ON orders(order_id)",
    "CREATE INDEX idx_payments_order ON order_payments(order_id)",
    "CREATE INDEX idx_reviews_order ON order_reviews(order_id)",
]

VIEWS_SQL = Path(__file__).with_name("views.sql")


def read_csv(raw_dir: Path, table: str) -> pd.DataFrame:
    """Baca satu CSV. dtype=str menjaga ID dan kode pos yang berawalan nol."""
    df = pd.read_csv(raw_dir / CSV_FILES[table], dtype=str, encoding="utf-8-sig")
    for column in NUMBER_COLUMNS.get(table, []):
        df[column] = pd.to_numeric(df[column])
    return df.drop(columns=DROP_COLUMNS.get(table, []))


def summarize_geolocation(geo: pd.DataFrame) -> pd.DataFrame:
    """Satu baris per prefix kode pos. Data asli punya 1 juta baris dan banyak duplikat."""
    geo = geo.assign(
        lat=pd.to_numeric(geo["geolocation_lat"]), lng=pd.to_numeric(geo["geolocation_lng"])
    )
    return geo.groupby("geolocation_zip_code_prefix", as_index=False).agg(
        lat=("lat", "mean"),
        lng=("lng", "mean"),
        kota=("geolocation_city", "first"),
        negara_bagian=("geolocation_state", "first"),
    )


def build_database(raw_dir: Path, db_path: Path) -> dict[str, int]:
    """Bangun ulang database dari nol. Kembalikan jumlah baris per tabel."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    counts = {}
    conn = sqlite3.connect(db_path)
    try:
        for table in CSV_FILES:
            df = read_csv(raw_dir, table)
            if table == "geolocation":
                df = summarize_geolocation(df)
            df.to_sql(table, conn, index=False)
            counts[table] = len(df)
        for statement in INDEXES:
            conn.execute(statement)
        conn.executescript(VIEWS_SQL.read_text())
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    return counts
