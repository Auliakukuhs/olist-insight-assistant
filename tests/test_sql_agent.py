import gzip
import shutil
import sqlite3

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from olist_assistant.agents import sql_agent
from olist_assistant.agents.sql_agent import SqlDitolak, buka_koneksi, jalankan, jawab
from olist_assistant.agents.sql_contract import VIEW_PER_PERAN

SELLER = "4869f7a5dfa277a7dca6462dcf3b52b2"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """Database yang di-commit, sama dengan yang masuk image Docker."""
    path = tmp_path_factory.mktemp("sql") / "olist.db"
    with gzip.open("data/olist.db.gz") as source, path.open("wb") as target:
        shutil.copyfileobj(source, target)
    return path


@pytest.fixture(autouse=True)
def pakai_db(db, monkeypatch):
    monkeypatch.setenv("SQLITE_PATH", str(db))


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE orders",
        "DELETE FROM orders",
        "UPDATE orders SET order_status = 'x'",
        "INSERT INTO orders (order_id) VALUES ('x')",
        "PRAGMA table_info(orders)",
        "ATTACH 'lain.db' AS lain",
        "SELECT 1; DROP TABLE orders",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM pragma_table_info('orders')",
        "SELECT * FROM orders",
    ],
)
def test_query_berbahaya_ditolak_bahkan_untuk_admin(sql):
    with pytest.raises(SqlDitolak):
        jalankan(sql, "admin", None)


def test_customer_tidak_bisa_membaca_performa_seller():
    with pytest.raises(SqlDitolak, match="v_ringkasan_seller"):
        jalankan("SELECT * FROM v_ringkasan_seller", "customer", None)


def test_view_terlarang_di_dalam_subquery_ikut_ditolak():
    sql = "SELECT * FROM v_pasar WHERE order_id IN (SELECT order_id FROM v_item_terjual)"
    with pytest.raises(SqlDitolak, match="v_item_terjual"):
        jalankan(sql, "customer", None)


def test_nama_cte_tidak_dianggap_tabel_terlarang():
    sql = "WITH x AS (SELECT kategori FROM v_pasar) SELECT COUNT(*) AS n FROM x"
    _, rows = jalankan(sql, "customer", None)
    assert rows[0]["n"] > 100_000


def test_seller_hanya_melihat_tokonya_sendiri():
    total = "SELECT ROUND(SUM(harga_brl), 2) AS total FROM {}"
    _, own = jalankan(total.format("v_penjualan_saya"), "seller", SELLER)
    _, truth = jalankan(total.format(f"v_item_terjual WHERE seller_id = '{SELLER}'"), "admin", None)
    assert own == truth == [{"total": 229_237.63}]
    with pytest.raises(SqlDitolak):
        jalankan("SELECT * FROM v_item_terjual", "seller", SELLER)


def test_seller_id_tidak_valid_tidak_pernah_masuk_query():
    with pytest.raises(SqlDitolak, match="seller_id"):
        jalankan("SELECT * FROM v_penjualan_saya", "seller", "x' OR '1'='1")


def test_limit_dipaksa_dan_limit_kecil_dipertahankan():
    sql, rows = jalankan("SELECT order_id FROM v_pasar", "customer", None)
    assert "LIMIT 200" in sql
    assert len(rows) == 200
    _, rows = jalankan("SELECT order_id FROM v_pasar LIMIT 5", "customer", None)
    assert len(rows) == 5


def test_urutan_tetap_setelah_limit_ditambahkan():
    sql = "SELECT kategori, total_penjualan_brl FROM v_ringkasan_kategori ORDER BY 2 DESC"
    _, rows = jalankan(sql, "customer", None)
    values = [r["total_penjualan_brl"] for r in rows]
    assert values == sorted(values, reverse=True)


def test_query_lambat_dihentikan(monkeypatch):
    monkeypatch.setattr(sql_agent, "MAX_SECONDS", 0.2)
    with pytest.raises(SqlDitolak, match="detik"):
        jalankan("SELECT COUNT(*) FROM v_pasar AS a, v_pasar AS b", "admin", None)


def test_koneksi_menolak_tulis_walau_pemeriksa_terlewati():
    conn = buka_koneksi("admin", None)
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("CREATE TABLE curian (a)")
    finally:
        conn.close()


@pytest.mark.parametrize("peran", ["customer", "seller", "admin"])
def test_semua_view_per_peran_ada_di_database(peran):
    for view in VIEW_PER_PERAN[peran]:
        jalankan(f"SELECT * FROM {view} LIMIT 1", peran, SELLER if peran == "seller" else None)


def test_aturan_peran_hanya_untuk_perannya():
    assert "boleh melihat performa" in sql_agent.ATURAN_PERAN["admin"]
    assert "hanya untuk admin" in sql_agent.ATURAN_PERAN["seller"]


class FakeToolModel(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def test_agent_mengembalikan_jawaban_query_dan_baris():
    replies = iter(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "jalankan_sql",
                        "args": {"query": "SELECT COUNT(*) AS n FROM v_ringkasan_kategori"},
                        "id": "1",
                    }
                ],
            ),
            AIMessage(content="Ada 74 kategori."),
        ]
    )
    result = jawab(
        "Berapa jumlah kategori?", [], "customer", None, model=FakeToolModel(messages=replies)
    )
    assert result["answer"] == "Ada 74 kategori."
    assert result["rows"] == [{"n": 74}]
    assert "LIMIT 200" in result["sql"]


def test_query_ditolak_dikembalikan_ke_llm_bukan_dilempar():
    replies = iter(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "jalankan_sql",
                        "args": {"query": "SELECT * FROM v_ringkasan_seller"},
                        "id": "1",
                    }
                ],
            ),
            AIMessage(content="Data itu hanya untuk admin."),
        ]
    )
    result = jawab(
        "Berapa omzet toko 0000?", [], "customer", None, model=FakeToolModel(messages=replies)
    )
    assert result["answer"] == "Data itu hanya untuk admin."
    assert result["sql"] == ""


@pytest.mark.parametrize(
    "pertanyaan",
    [
        "Siapa 5 seller dengan penjualan tertinggi di Sao Paulo?",
        "Tolong analisis performa seller di daerah Sao Paulo",
        "Seller mana yang paling sering terlambat?",
        "Top 10 seller furniture",
        "Daftar seller di RJ",
    ],
)
def test_peringkat_seller_ditolak_tanpa_llm_untuk_selain_admin(pertanyaan):
    class Meledak(FakeToolModel):
        def invoke(self, *args, **kwargs):
            raise AssertionError("LLM tidak boleh dipanggil")

    for peran, seller_id in (("customer", None), ("seller", SELLER)):
        result = jawab(pertanyaan, [], peran, seller_id, model=Meledak(messages=iter([])))
        assert "hanya" in result["answer"] and "admin" in result["answer"]
        assert result["sql"] == ""


@pytest.mark.parametrize(
    "pertanyaan",
    [
        "Berapa rata-rata harga produk furniture yang dijual seller di SP?",
        "Bagaimana performa seller saya bulan ini?",
        "Berapa jumlah seller di SP?",
    ],
)
def test_pertanyaan_sah_tentang_seller_tidak_ikut_ditolak(pertanyaan):
    assert not sql_agent.PERINGKAT_SELLER.search(pertanyaan)


@pytest.mark.parametrize(
    "sql",
    ["SELECT length(randomblob(500000000)) AS n", "SELECT length(zeroblob(900000000)) AS n"],
)
def test_blob_raksasa_ditolak_supaya_memori_aman(sql):
    with pytest.raises(SqlDitolak, match="too big"):
        jalankan(sql, "customer", None)


def test_string_raksasa_dari_printf_tidak_memakan_memori():
    _, rows = jalankan("SELECT length(printf('%.*c', 400000000, 'x')) AS n", "customer", None)
    assert rows == [{"n": None}]
