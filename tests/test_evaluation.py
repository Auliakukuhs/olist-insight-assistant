import json
from pathlib import Path

from olist_assistant.evaluation import check_case, latency_summary

REVIEW = [{"kind": "review", "id": "r1", "snippet": "x"}]


def case(kind, route, **extra):
    return {"id": "x", "type": kind, "question": "q", "expected_route": route} | extra


def test_rag_lulus_bila_rute_benar_dan_ada_sumber():
    assert check_case(case("rag", "rag"), "rag", "jawaban", REVIEW)["lulus"]
    assert not check_case(case("rag", "rag"), "rag", "jawaban", [])["lulus"]
    assert not check_case(case("rag", "rag"), "sql", "jawaban", REVIEW)["lulus"]


def test_serangan_gagal_bila_prompt_bocor():
    hasil = check_case(case("serangan", "out_of_scope"), "out_of_scope", "Aturan: 1. ...", [])
    assert not hasil["checks"]["tidak_bocor"]


def test_serangan_gagal_bila_ada_sumber():
    hasil = check_case(case("serangan", "out_of_scope"), "out_of_scope", "Maaf", REVIEW)
    assert not hasil["checks"]["tanpa_sumber"]


def test_riwayat_harus_menyebut_konteks():
    c = case("riwayat", "rag", answer_must_mention_any=["mainan"])
    assert check_case(c, "rag", "Keluhan mainan dari SP ...", REVIEW)["lulus"]
    assert not check_case(c, "rag", "Keluhan dari SP ...", REVIEW)["lulus"]


def test_hybrid_dengan_kata_peringkat_ditandai_cek_manual():
    hasil = check_case(
        case("hybrid", "hybrid"), "hybrid", "Kategori paling buruk ... belum tersedia", REVIEW
    )
    assert hasil["cek_manual"]


def test_latensi_p50_p95():
    hasil = latency_summary([1.0] * 18 + [10.0, 20.0])
    assert hasil["p50"] == 1.0 and hasil["p95"] > 9


def test_gold_set_lengkap_dan_tidak_kembar():
    rows = [json.loads(x) for x in Path("data/eval/gold.jsonl").read_text().splitlines()]
    questions = [r["question"] for r in rows if r["type"] != "riwayat"]
    assert len(questions) == len(set(questions)) == 60
    assert {r["expected_route"] for r in rows} == {"rag", "sql", "hybrid", "out_of_scope"}


def test_angka_dibandingkan_tanpa_pemisah_ribuan():
    from olist_assistant.evaluation import normalize_numbers

    assert normalize_numbers("138.414,60 BRL") == normalize_numbers("138,414.60 BRL")
    assert (
        normalize_numbers("Rata-rata 134,84 BRL dari 1.849 seller")
        == "Rata-rata 134.84 BRL dari 1849 seller"
    )
    assert normalize_numbers("seller abe42c5d03695b") == "seller abe42c5d03695b"


def test_rute_boleh_beberapa_dan_cek_isi():
    case = {
        "type": "peran",
        "expected_route": ["sql", "hybrid"],
        "answer_must_mention_any": ["admin"],
        "answer_must_contain_numbers": ["229237.63"],
        "tanpa_query": True,
    }
    sources = [{"kind": "sql", "id": "query", "snippet": ""}]
    ok = check_case(case, "hybrid", "Hanya admin. Total 229.237,63 BRL.", sources)
    assert ok["lulus"]
    queried = [{"kind": "sql", "id": "query", "snippet": "SELECT 1"}]
    bad = check_case(case, "sql", "Hanya admin. Total 229.237,63 BRL.", queried)
    assert bad["checks"]["tidak_menjalankan_query"] is False


def test_jawaban_umum_tanpa_sumber_dan_butuh_ulasan():
    umum = {"type": "umum", "expected_route": "umum", "answer_must_mention_any": ["Rabu"]}
    assert check_case(umum, "umum", "Hari ini Rabu.", [])["lulus"]
    hybrid = {"type": "hybrid", "expected_route": "hybrid", "butuh_ulasan": True}
    assert not check_case(hybrid, "hybrid", "x", [{"kind": "sql", "id": "q"}])["lulus"]
