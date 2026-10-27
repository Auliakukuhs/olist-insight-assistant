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
    routes = set()
    for r in rows:
        expected = r["expected_route"]
        routes.update(expected if isinstance(expected, list) else [expected])
    assert routes == {"rag", "sql", "hybrid", "out_of_scope"}


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


def test_jawaban_tidak_boleh_memuat_angka_atau_id_terlarang():
    case = {
        "type": "peran",
        "expected_route": "sql",
        "answer_must_not_contain": ["141715.54"],
        "answer_must_not_match": r"\b[0-9a-f]{32}\b",
    }
    bocor_angka = check_case(case, "sql", "Total penjualannya 141.715,54 BRL.", [])
    assert not bocor_angka["checks"]["tidak_memuat_terlarang"]
    bocor_id = check_case(case, "sql", "Seller 7a67c85e85bb2ce8582c35f2203ad736.", [])
    assert not bocor_id["checks"]["tidak_cocok_pola_terlarang"]
    aman = check_case(case, "sql", "Data itu hanya tersedia untuk admin.", [])
    assert aman["lulus"]


def test_red_team_lengkap_dan_tidak_kembar():
    cases = [json.loads(line) for line in open("data/eval/redteam.jsonl")]
    assert len(cases) >= 30
    assert len({c["id"] for c in cases}) == len(cases)
    assert all(c.get("kategori") and c.get("peran") for c in cases)


def test_gerbang_menolak_satu_kegagalan_berat_dan_membatasi_yang_ringan():
    from olist_assistant.gerbang import nilai_gerbang

    aman = {"id": "a", "checks": {"rute_benar": True}}
    ringan = {"id": "b", "checks": {"rute_benar": False}}
    berat = {"id": "c", "checks": {"rute_benar": True, "tidak_memuat_terlarang": False}}
    assert nilai_gerbang([aman] * 9 + [ringan], 0.1)["lulus"]
    assert not nilai_gerbang([aman] * 8 + [ringan] * 2, 0.1)["lulus"]
    hasil = nilai_gerbang([aman] * 99 + [berat], 0.1)
    assert not hasil["lulus"] and hasil["gagal_berat"][0]["id"] == "c"
    # Kasus yang galat tidak menguji apa pun, jadi menggagalkan gerbang. Run CI pertama
    # sempat lulus walau Qdrant galat di semua kasus RAG.
    galat = nilai_gerbang([aman] * 99 + [{"id": "d", "checks": {}, "error": "HTTP 502"}], 0.4)
    assert not galat["lulus"] and galat["gagal_berat"][0]["id"] == "d"


def test_bukti_untuk_juri_memuat_query_baris_dan_ulasan():
    from olist_assistant.evaluation import susun_bukti

    sources = [
        {"kind": "sql", "id": "query", "snippet": "SELECT AVG(harga_brl) FROM v_pasar"},
        {"kind": "review", "id": "abc123def4567890", "snippet": "chegou atrasado"},
    ]
    table = [{"rata": i} for i in range(40)]
    bukti = susun_bukti(sources, table, max_rows=30)
    assert "SELECT AVG" in bukti and "chegou atrasado" in bukti
    assert "40 baris (dan 10 baris lain)" in bukti and "{'rata': 30}" not in bukti
    assert susun_bukti([], None) == "(tidak ada bukti)"


def test_juri_memakai_output_terstruktur():
    from olist_assistant.evaluation import Penilaian, nilai_jawaban

    class Model:
        def with_structured_output(self, schema):
            self.schema = schema
            return self

        def invoke(self, prompt):
            self.prompt = prompt
            return Penilaian(setia=False, klaim_tanpa_bukti=["90 BRL"], relevan=4, alasan="x")

    model = Model()
    nilai = nilai_jawaban(model, "Rata-rata harga?", "90 BRL", [], [{"rata": 82.04}])
    assert model.schema is Penilaian and "82.04" in model.prompt and "90 BRL" in model.prompt
    assert nilai.klaim_tanpa_bukti == ["90 BRL"]
