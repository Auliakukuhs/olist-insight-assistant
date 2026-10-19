"""Jalankan gold set ke supervisor sungguhan (OpenAI, Qdrant Cloud) dan simpan laporan.

Setiap kasus memakai sesi baru, kecuali kasus `riwayat` yang berpasangan
dalam satu sesi untuk menguji pertanyaan lanjutan.

Contoh:
    uv run python scripts/evaluate_gold.py                                  # gold set diagnosis
    uv run python scripts/evaluate_gold.py data/eval/gold_holdout.jsonl     # holdout buta
"""

import json
import sys
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from olist_assistant.agents.supervisor import default_supervisor
from olist_assistant.config import load_dotenv
from olist_assistant.evaluation import check_case, latency_summary

DEFAULT_GOLD = Path("data/eval/gold.jsonl")


def main() -> None:
    gold = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_GOLD
    report = Path("reports") / f"eval_{gold.stem}.json"
    load_dotenv()
    supervisor = default_supervisor()
    cases = [json.loads(line) for line in gold.read_text().splitlines() if line.strip()]
    run_id = uuid.uuid4().hex[:6]
    results = []
    for case in cases:
        session = f"eval-{run_id}-{case.get('session', case['id'])}"
        started = time.monotonic()
        try:
            state = supervisor.ask(case["question"], session)
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

    per_type = defaultdict(list)
    for r in results:
        per_type[r["type"]].append(r)
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
                "catatan": "Agent SQL belum tersedia, kasus sql dan hybrid hanya dinilai rutenya.",
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
    if supervisor.callbacks:
        from langfuse import get_client

        get_client().flush()


if __name__ == "__main__":
    main()
