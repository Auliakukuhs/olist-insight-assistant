import sqlite3

import pandas as pd
import pytest

from olist_assistant.api.analytics import VIEW_CONTRACT
from olist_assistant.sql.etl import CSV_FILES, build_database

# Data mini. Pesanan o1 punya 2 item dan 2 pembayaran, sengaja untuk menguji
# bahwa total tidak berlipat setelah join.
MINI = {
    "orders": [
        {
            "order_id": "o1",
            "customer_id": "c1",
            "order_status": "delivered",
            "order_purchase_timestamp": "2017-01-05 10:00:00",
            "order_approved_at": "2017-01-05 11:00:00",
            "order_delivered_carrier_date": "2017-01-06 09:00:00",
            "order_delivered_customer_date": "2017-01-20 15:00:00",
            "order_estimated_delivery_date": "2017-01-15 00:00:00",
        },
        {
            "order_id": "o2",
            "customer_id": "c2",
            "order_status": "delivered",
            "order_purchase_timestamp": "2017-02-01 09:00:00",
            "order_approved_at": "2017-02-01 10:00:00",
            "order_delivered_carrier_date": "2017-02-02 09:00:00",
            "order_delivered_customer_date": "2017-02-05 12:00:00",
            "order_estimated_delivery_date": "2017-02-10 00:00:00",
        },
    ],
    "order_items": [
        {
            "order_id": "o1",
            "order_item_id": "1",
            "product_id": "p1",
            "seller_id": "s1",
            "shipping_limit_date": "",
            "price": "50.0",
            "freight_value": "10.0",
        },
        {
            "order_id": "o1",
            "order_item_id": "2",
            "product_id": "p1",
            "seller_id": "s1",
            "shipping_limit_date": "",
            "price": "40.0",
            "freight_value": "10.0",
        },
        {
            "order_id": "o2",
            "order_item_id": "1",
            "product_id": "p2",
            "seller_id": "s1",
            "shipping_limit_date": "",
            "price": "200.0",
            "freight_value": "20.0",
        },
    ],
    "order_payments": [
        {
            "order_id": "o1",
            "payment_sequential": "1",
            "payment_type": "voucher",
            "payment_installments": "1",
            "payment_value": "30.0",
        },
        {
            "order_id": "o1",
            "payment_sequential": "2",
            "payment_type": "credit_card",
            "payment_installments": "3",
            "payment_value": "80.0",
        },
        {
            "order_id": "o2",
            "payment_sequential": "1",
            "payment_type": "boleto",
            "payment_installments": "1",
            "payment_value": "220.0",
        },
    ],
    "order_reviews": [
        {
            "review_id": "r1",
            "order_id": "o1",
            "review_score": "2",
            "review_comment_title": "",
            "review_comment_message": "atrasou",
            "review_creation_date": "",
            "review_answer_timestamp": "",
        },
        {
            "review_id": "r2",
            "order_id": "o2",
            "review_score": "5",
            "review_comment_title": "",
            "review_comment_message": "",
            "review_creation_date": "",
            "review_answer_timestamp": "",
        },
    ],
    "products": [
        {
            "product_id": "p1",
            "product_category_name": "brinquedos",
            "product_name_lenght": "10",
            "product_description_lenght": "100",
            "product_photos_qty": "1",
            "product_weight_g": "300",
            "product_length_cm": "10",
            "product_height_cm": "10",
            "product_width_cm": "10",
        },
        {
            "product_id": "p2",
            "product_category_name": "",
            "product_name_lenght": "",
            "product_description_lenght": "",
            "product_photos_qty": "",
            "product_weight_g": "",
            "product_length_cm": "",
            "product_height_cm": "",
            "product_width_cm": "",
        },
    ],
    "sellers": [
        {
            "seller_id": "s1",
            "seller_zip_code_prefix": "01001",
            "seller_city": "sao paulo",
            "seller_state": "SP",
        },
    ],
    "customers": [
        {
            "customer_id": "c1",
            "customer_unique_id": "u1",
            "customer_zip_code_prefix": "01002",
            "customer_city": "sao paulo",
            "customer_state": "SP",
        },
        {
            "customer_id": "c2",
            "customer_unique_id": "u2",
            "customer_zip_code_prefix": "20000",
            "customer_city": "rio de janeiro",
            "customer_state": "RJ",
        },
    ],
    "category_translation": [
        {"product_category_name": "brinquedos", "product_category_name_english": "toys"},
    ],
    "geolocation": [
        {
            "geolocation_zip_code_prefix": "01001",
            "geolocation_lat": "-23.5",
            "geolocation_lng": "-46.6",
            "geolocation_city": "sao paulo",
            "geolocation_state": "SP",
        },
        {
            "geolocation_zip_code_prefix": "01001",
            "geolocation_lat": "-23.7",
            "geolocation_lng": "-46.8",
            "geolocation_city": "sao paulo",
            "geolocation_state": "SP",
        },
    ],
}


@pytest.fixture
def db(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for table, rows in MINI.items():
        pd.DataFrame(rows).to_csv(raw / CSV_FILES[table], index=False)
    path = tmp_path / "olist.db"
    build_database(raw, path)
    conn = sqlite3.connect(path)
    yield conn
    conn.close()


def one(conn, sql):
    return conn.execute(sql).fetchone()[0]


def test_total_pembayaran_tidak_berlipat(db):
    assert one(db, "SELECT SUM(total_bayar_brl) FROM v_pembayaran_per_order") == 330.0
    # Pembuktian kenapa view perlu: join langsung item x pembayaran melipatgandakan.
    salah = one(
        db, "SELECT SUM(p.payment_value) FROM order_items i JOIN order_payments p USING (order_id)"
    )
    assert salah == 440.0


def test_satu_baris_per_item(db):
    assert one(db, "SELECT COUNT(*) FROM v_item_penjualan") == 3


def test_kategori_diterjemahkan_dan_kosong_jadi_unknown(db):
    rows = dict(db.execute("SELECT product_id, kategori FROM v_item_penjualan").fetchall())
    assert rows == {"p1": "toys", "p2": "unknown"}


def test_keterlambatan_dan_ringkasan_kategori(db):
    toys = db.execute(
        "SELECT jumlah_order, total_penjualan_brl, rata_skor, persen_terlambat "
        "FROM v_ringkasan_kategori WHERE kategori = 'toys'"
    ).fetchone()
    assert toys == (1, 90.0, 2.0, 100.0)


def test_ringkasan_seller(db):
    row = db.execute(
        "SELECT kategori_utama, jumlah_order, total_penjualan_brl, persen_terlambat "
        "FROM v_ringkasan_seller WHERE seller_id = 's1'"
    ).fetchone()
    assert row == ("unknown", 2, 290.0, 50.0)


def test_id_berawalan_nol_tetap_utuh(db):
    assert one(db, "SELECT seller_zip_code_prefix FROM sellers") == "01001"


def test_geolocation_diringkas_per_kode_pos(db):
    assert one(db, "SELECT COUNT(*) FROM geolocation") == 1


def test_view_sesuai_kontrak_analytics(db):
    for view, columns in VIEW_CONTRACT.items():
        actual = {row[1] for row in db.execute(f"PRAGMA table_info({view})")}
        assert set(columns) <= actual, f"{view} kurang kolom {set(columns) - actual}"
