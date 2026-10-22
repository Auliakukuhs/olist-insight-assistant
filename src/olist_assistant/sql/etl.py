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

# Dua kategori di products tidak punya terjemahan di CSV resmi, sehingga
# muncul dengan nama Portugis di samping 71 kategori berbahasa Inggris.
EXTRA_TRANSLATIONS = {
    "pc_gamer": "pc_gamer",
    "portateis_cozinha_e_preparadores_de_alimentos": "portable_kitchen_food_processors",
}

# Index untuk kolom penghubung yang dipakai join di dalam view, ditambah
# seller_id yang dipakai filter per seller. Tanpa index products dan customers,
# SQLite membangun index sementara di setiap query (tren per seller 99 ms jadi 7 ms).
INDEXES = [
    "CREATE INDEX idx_items_order ON order_items(order_id)",
    "CREATE INDEX idx_items_seller ON order_items(seller_id)",
    "CREATE INDEX idx_products_product ON products(product_id)",
    "CREATE INDEX idx_customers_customer ON customers(customer_id)",
    "CREATE INDEX idx_orders_order ON orders(order_id)",
    "CREATE INDEX idx_payments_order ON order_payments(order_id)",
    "CREATE INDEX idx_reviews_order ON order_reviews(order_id)",
]

# View ringkasan mengagregasi semua item setiap kali dibaca, sekitar 1,5 detik
# untuk satu seller. Hasilnya disimpan sekali sebagai tabel saat ETL, lalu view
# dengan nama yang sama membaca tabel itu, sehingga agent SQL tidak berubah.
# v_pasar ikut disimpan karena query agent SQL di atasnya turun dari 0,4 sampai
# 0,8 detik menjadi 6 sampai 75 ms, dengan tambahan sekitar 22 MB.
MATERIALIZED_VIEWS = {
    "v_ringkasan_kategori": "kategori",
    "v_ringkasan_seller": "seller_id",
    "v_pasar": "kategori",
}

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


def add_missing_translations(translation: pd.DataFrame) -> pd.DataFrame:
    known = set(translation["product_category_name"])
    extra = [
        {"product_category_name": pt, "product_category_name_english": en}
        for pt, en in EXTRA_TRANSLATIONS.items()
        if pt not in known
    ]
    return pd.concat([translation, pd.DataFrame(extra)], ignore_index=True)


def materialize(conn: sqlite3.Connection, view: str, key: str) -> None:
    """Ganti view dengan tabel berisi hasilnya, dan view baru yang membaca tabel itu."""
    table = view.removeprefix("v_")
    conn.execute(f"CREATE TABLE {table} AS SELECT * FROM {view}")
    conn.execute(f"CREATE INDEX idx_{table} ON {table}({key})")
    conn.execute(f"DROP VIEW {view}")
    conn.execute(f"CREATE VIEW {view} AS SELECT * FROM {table}")


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
            if table == "category_translation":
                df = add_missing_translations(df)
            df.to_sql(table, conn, index=False)
            counts[table] = len(df)
        for statement in INDEXES:
            conn.execute(statement)
        conn.executescript(VIEWS_SQL.read_text())
        for view, key in MATERIALIZED_VIEWS.items():
            materialize(conn, view, key)
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    return counts
