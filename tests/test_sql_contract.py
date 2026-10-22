import pytest

from olist_assistant.agents.sql_contract import Message, SqlResult, jawab_sql


def test_jawab_sql_belum_diimplementasikan():
    with pytest.raises(NotImplementedError):
        jawab_sql("Berapa rata-rata ongkir?", [])


def fake_jawab_sql(pertanyaan: str, riwayat: list[Message]) -> SqlResult:
    return {
        "answer": "Rata-rata ongkir 19,99 BRL.",
        "sql": "SELECT AVG(freight_value) AS rata_ongkir FROM v_item_penjualan LIMIT 1",
        "rows": [{"rata_ongkir": 19.99}],
    }


def test_bentuk_hasil_yang_dipakai_supervisor():
    hasil = fake_jawab_sql("Berapa rata-rata ongkir?", [{"role": "user", "content": "halo"}])
    assert set(hasil) == set(SqlResult.__annotations__)
    assert hasil["sql"].lstrip().upper().startswith("SELECT")
    assert isinstance(hasil["rows"], list)


def test_data_pasar_tidak_memuat_view_per_seller():
    from olist_assistant.agents.sql_contract import DATA_PASAR, VIEW_PER_PERAN

    assert {"v_ringkasan_seller", "v_item_terjual", "v_item_penjualan"}.isdisjoint(DATA_PASAR)
    assert VIEW_PER_PERAN["customer"] == DATA_PASAR
    assert DATA_PASAR < VIEW_PER_PERAN["seller"] < VIEW_PER_PERAN["seller"] | {"x"}
    assert VIEW_PER_PERAN["admin"] > DATA_PASAR
