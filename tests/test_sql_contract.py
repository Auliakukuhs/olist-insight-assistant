from olist_assistant.agents.sql_contract import Message, SqlResult, jawab_sql


def test_jawab_sql_meneruskan_peran_dan_seller_id(monkeypatch):
    calls = []

    def fake_jawab(pertanyaan, riwayat, peran, seller_id):
        calls.append((peran, seller_id))
        return {"answer": "-", "sql": "", "rows": []}

    monkeypatch.setattr("olist_assistant.agents.sql_agent.jawab", fake_jawab)
    jawab_sql("Penjualan toko saya?", [], peran="seller", seller_id="a" * 32)
    assert calls == [("seller", "a" * 32)]


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