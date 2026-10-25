"""Jalankan gold set ke supervisor sungguhan (OpenAI, Qdrant Cloud) dan simpan laporan.

Setiap kasus memakai sesi baru, kecuali kasus yang berbagi `session` untuk
menguji pertanyaan lanjutan. Kasus boleh menulis `peran` (customer, seller,
admin). Seller memakai toko akun demo. Kata kunci `{hari_ini}` dan `{besok}`
di answer_must_mention_any diganti nama hari menurut waktu WIB saat dijalankan.

Contoh:
    uv run python scripts/evaluate_gold.py                                  # gold set diagnosis
    uv run python scripts/evaluate_gold.py data/eval/gold_holdout.jsonl     # holdout buta
    uv run python scripts/evaluate_gold.py data/eval/gold_mentoring.jsonl   # skenario mentoring 1
    uv run python scripts/evaluate_gold.py data/eval/redteam.jsonl          # red team per kategori
    uv run python scripts/evaluate_gold.py --gerbang data/eval/redteam*.jsonl  # gerbang rilis
"""

import json
import os
import sys
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from olist_assistant.agents.supervisor import default_supervisor
from olist_assistant.config import load_dotenv
from olist_assistant.evaluation import check_case, latency_summary, resolve_dates
from olist_assistant.gerbang import nilai_gerbang

DEFAULT_GOLD = Path("data/eval/gold.jsonl")
# Seller dengan penjualan terbesar, sama dengan akun demo seller.
DEMO_SELLER = "4869f7a5dfa277a7dca6462dcf3b52b2"


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--gerbang"]
    golds = [Path(a) for a in args] or [DEFAULT_GOLD]
    load_dotenv()
    supervisor = default_supervisor()
    semua = []
    for gold in golds:
        semua += evaluate_file(supervisor, gold)
    if supervisor.callbacks:
        from langfuse import get_client

        get_client().flush()
    if "--gerbang" in sys.argv:
        # Gerbang rilis: satu kegagalan berat menggagalkan run (lihat gerbang.py).
        gerbang = nilai_gerbang(semua, float(os.getenv("GERBANG_BATAS_RINGAN", "0.1")))
        Path("reports/gerbang_kode.json").write_text(
            json.dumps(gerbang, ensure_ascii=False, indent=2)
        )
        print(json.dumps({k: v for k, v in gerbang.items() if k != "gagal_ringan"}, indent=1))
        sys.exit(0 if gerbang["lulus"] else 1)


def evaluate_file(supervisor, gold: Path) -> list[dict]:
    report = Path("reports") / f"eval_{gold.stem}.json"
    cases = [json.loads(line) for line in gold.read_text().splitlines() if line.strip()]
    run_id = uuid.uuid4().hex[:6]
    results = []
    for case in cases:
        case = resolve_dates(case)
        session = f"eval-{run_id}-{case.get('session', case['id'])}"
        peran = case.get("peran", "customer")
        started = time.monotonic()
        try:
            state = supervisor.ask(
                case["question"], session, peran, DEMO_SELLER if peran == "seller" else None
            )
            route, answer, sources = state["route"], state["answer"], state.get("sources", [])
            route_by, error = state.get("route_by"), None
        except Exception as exc:  # dicatat sebagai gagal, evaluasi tetap lanjut
            route, answer, sources, error = "error", "", [], repr(exc)
            route_by = None
        seconds = time.monotonic() - started
        verdict = check_case(case, route, answer, sources)
        results.append(
            case
            | verdict
            | {
                "rute": route,
                "diputuskan_oleh": route_by,
                "detik": round(seconds, 1),
                "jawaban": answer[:400],
                "error": error,
            }
        )
        mark = "LULUS" if verdict["lulus"] else "GAGAL"
        by = (route_by or "-")[:22]
        question = case["question"][:50]
        print(f"{mark} {case['id']:15s} rute={route:13s} {by:22s} {seconds:5.1f}s  {question}")

    # Kasus red team dikelompokkan per kategori serangan, kasus lain per jenis.
    per_type = defaultdict(list)
    for r in results:
        per_type[r.get("kategori", r["type"])].append(r)
    summary = {
        kind: {
            "kasus": len(rows),
            "rute_benar": sum(r["checks"]["rute_benar"] for r in rows),
            "lulus_semua_cek": sum(r["lulus"] for r in rows),
            "latensi_detik": latency_summary([r["detik"] for r in rows]),
            "diputuskan_oleh": dict(
                Counter((r["diputuskan_oleh"] or "-").split(" ")[0] for r in rows)
            ),
        }
        for kind, rows in per_type.items()
    }
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "catatan": "Kasus tanpa angka acuan hanya dinilai rute dan sumbernya.",
                "ringkasan": summary,
                "gagal": [r for r in results if not r["lulus"]],
                "cek_manual": [r for r in results if r["cek_manual"]],
                "semua": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(json.dumps(summary, indent=2))
    return results


if __name__ == "__main__":
    main()
