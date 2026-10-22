-- View terkurasi yang dibaca agent SQL dan endpoint analytics.
-- Aturan utama: tabel yang bisa punya banyak baris per pesanan (item,
-- pembayaran, ulasan) diringkas per order_id DULU sebelum digabung, supaya
-- angka tidak berlipat.

-- Satu baris per item pesanan, lengkap dengan kategori dan lokasi.
CREATE VIEW v_item_penjualan AS
SELECT
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS kategori,
    i.price AS harga_brl,
    i.freight_value AS ongkir_brl,
    o.order_purchase_timestamp AS tanggal_beli,
    o.order_status AS status_order,
    s.seller_city AS kota_seller,
    s.seller_state AS negara_bagian_seller,
    c.customer_city AS kota_pembeli,
    c.customer_state AS negara_bagian_pembeli
FROM order_items AS i
JOIN orders AS o ON o.order_id = i.order_id
LEFT JOIN products AS p ON p.product_id = i.product_id
LEFT JOIN category_translation AS t ON t.product_category_name = p.product_category_name
LEFT JOIN sellers AS s ON s.seller_id = i.seller_id
LEFT JOIN customers AS c ON c.customer_id = o.customer_id;

-- Item yang dihitung sebagai penjualan. Pesanan canceled dan unavailable tidak
-- pernah jadi transaksi, jadi tidak masuk angka penjualan maupun ringkasan.
CREATE VIEW v_item_terjual AS
SELECT *
FROM v_item_penjualan
WHERE status_order NOT IN ('canceled', 'unavailable');

-- Satu baris per pesanan. Pesanan bisa dibayar beberapa kali (voucher + kartu).
CREATE VIEW v_pembayaran_per_order AS
SELECT
    order_id,
    COUNT(*) AS jumlah_pembayaran,
    ROUND(SUM(payment_value), 2) AS total_bayar_brl,
    MAX(payment_installments) AS cicilan_maks,
    GROUP_CONCAT(DISTINCT payment_type) AS metode
FROM order_payments
GROUP BY order_id;

-- Satu baris per pesanan. Sebagian kecil pesanan punya lebih dari satu ulasan.
CREATE VIEW v_review_per_order AS
SELECT
    order_id,
    AVG(review_score) AS skor,
    COUNT(*) AS jumlah_review
FROM order_reviews
GROUP BY order_id;

-- Satu baris per pesanan: status, keterlambatan, lama kirim, dan skor.
CREATE VIEW v_order AS
SELECT
    o.order_id,
    o.order_status AS status_order,
    o.order_purchase_timestamp AS tanggal_beli,
    CASE
        WHEN o.order_delivered_customer_date IS NULL THEN NULL
        WHEN date(o.order_delivered_customer_date) > date(o.order_estimated_delivery_date) THEN 1
        ELSE 0
    END AS terlambat,
    julianday(o.order_delivered_customer_date) - julianday(o.order_purchase_timestamp) AS hari_kirim,
    r.skor
FROM orders AS o
LEFT JOIN v_review_per_order AS r ON r.order_id = o.order_id;

-- Satu baris per kategori.
CREATE VIEW v_ringkasan_kategori AS
WITH angka_item AS (
    SELECT
        kategori,
        COUNT(DISTINCT order_id) AS jumlah_order,
        ROUND(SUM(harga_brl), 2) AS total_penjualan_brl,
        ROUND(AVG(harga_brl), 2) AS rata_harga_brl,
        ROUND(AVG(ongkir_brl), 2) AS rata_ongkir_brl
    FROM v_item_terjual
    GROUP BY kategori
),
angka_order AS (
    SELECT
        k.kategori,
        ROUND(AVG(o.skor), 2) AS rata_skor,
        ROUND(100.0 * AVG(o.terlambat), 1) AS persen_terlambat
    FROM (SELECT DISTINCT order_id, kategori FROM v_item_terjual) AS k
    JOIN v_order AS o ON o.order_id = k.order_id
    GROUP BY k.kategori
)
SELECT a.*, b.rata_skor, b.persen_terlambat
FROM angka_item AS a
LEFT JOIN angka_order AS b ON b.kategori = a.kategori;

-- Satu baris per seller.
CREATE VIEW v_ringkasan_seller AS
WITH angka_item AS (
    SELECT
        seller_id,
        COUNT(DISTINCT order_id) AS jumlah_order,
        ROUND(SUM(harga_brl), 2) AS total_penjualan_brl
    FROM v_item_terjual
    GROUP BY seller_id
),
kategori_utama AS (
    SELECT seller_id, kategori
    FROM (
        SELECT
            seller_id,
            kategori,
            -- Nama kategori memecah seri supaya hasilnya sama di setiap build.
            ROW_NUMBER() OVER (
                PARTITION BY seller_id ORDER BY SUM(harga_brl) DESC, kategori
            ) AS urutan
        FROM v_item_terjual
        GROUP BY seller_id, kategori
    )
    WHERE urutan = 1
),
angka_order AS (
    SELECT
        so.seller_id,
        ROUND(AVG(o.skor), 2) AS rata_skor,
        ROUND(AVG(o.hari_kirim), 1) AS rata_hari_kirim,
        ROUND(100.0 * AVG(o.terlambat), 1) AS persen_terlambat
    FROM (SELECT DISTINCT seller_id, order_id FROM v_item_terjual) AS so
    JOIN v_order AS o ON o.order_id = so.order_id
    GROUP BY so.seller_id
)
SELECT
    s.seller_id,
    s.seller_city AS kota,
    s.seller_state AS negara_bagian,
    k.kategori AS kategori_utama,
    COALESCE(a.jumlah_order, 0) AS jumlah_order,
    COALESCE(a.total_penjualan_brl, 0) AS total_penjualan_brl,
    b.rata_skor,
    b.rata_hari_kirim,
    b.persen_terlambat
FROM sellers AS s
LEFT JOIN angka_item AS a ON a.seller_id = s.seller_id
LEFT JOIN kategori_utama AS k ON k.seller_id = s.seller_id
LEFT JOIN angka_order AS b ON b.seller_id = s.seller_id;


-- Data pasar untuk semua peran. Satu baris per item terjual, tanpa seller_id,
-- supaya performa per seller (data internal perusahaan) tidak bisa dihitung
-- dari sini. Disimpan sebagai tabel oleh ETL karena dibaca agent SQL.
CREATE VIEW v_pasar AS
SELECT
    i.order_id,
    i.product_id,
    i.kategori,
    i.harga_brl,
    i.ongkir_brl,
    i.tanggal_beli,
    i.kota_seller,
    i.negara_bagian_seller,
    i.kota_pembeli,
    i.negara_bagian_pembeli,
    o.terlambat,
    ROUND(o.hari_kirim, 1) AS hari_kirim,
    o.skor AS skor_ulasan
FROM v_item_terjual AS i
LEFT JOIN v_order AS o ON o.order_id = i.order_id;