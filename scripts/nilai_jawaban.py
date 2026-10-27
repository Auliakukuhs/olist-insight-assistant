"""Nilai kesetiaan dan relevansi jawaban dengan LLM sebagai juri (#63).

Kasus rag, sql, dan hybrid dari gold set, holdout, dan skenario mentoring
dijalankan ke supervisor sungguhan, lalu dinilai juri dari bukti yang dipegang
chatbot (query, baris hasil, dan potongan ulasan). Juri memakai model yang berbeda
dari model penjawab supaya tidak menilai buatannya sendiri, dengan temperature 0.

Contoh:
    uv run python scripts/nilai_jawaban.py
    OPENAI_JUDGE_MODEL=gpt-4o uv run python scripts/nilai_jawaban.py
"""

import json
import os
import uuid
from collections import defaultdict
from pathlib import Path

from olist_assistant.agents.supervisor import default_supervisor
from olist_assistant.config import load_dotenv
from olist_assistant.evaluation import nilai_jawaban

SUMBER = ("gold", "gold_holdout", "gold_mentoring")
JENIS = ("rag", "sql", "hybrid")
REPORT = Path("reports/juri_jawaban.json")
# Hasil per kasus ditulis segera, jadi run yang terhenti bisa dilanjutkan.
PROGRES = Path("reports/juri_jawaban.progres.jsonl")
DEMO_SELLER = "4869f7a5dfa277a7dca6462dcf3b52b2"


def main() -> None:
    load_dotenv()
    from langchain_openai import ChatOpenAI

    juri_model = os.getenv("OPENAI_JUDGE_MODEL", "gpt-4o")
    # Batas waktu dan coba ulang sama dengan model penjawab. Tanpa ini satu panggilan
    # yang menggantung menahan seluruh run (terjadi di run pertama 25 Okt).
    juri = ChatOpenAI(model=juri_model, temperature=0, timeout=60, max_retries=2)
    supervisor = default_supervisor()
    run = uuid.uuid4().hex[:6]
    hasil = [json.loads(x) for x in PROGRES.read_text().splitlines()] if PROGRES.exists() else []
    selesai = {(h["set"], h["id"]) for h in hasil}
    for nama in SUMBER:
        for line in Path(f"data/eval/{nama}.jsonl").read_text().splitlines():
            case = json.loads(line)
            if case["type"] not in JENIS or (nama, case["id"]) in selesai:
                continue
            peran = case.get("peran", "customer")
            state = supervisor.ask(
                case["question"],
                f"juri-{run}-{case['id']}",
                peran,
                DEMO_SELLER if peran == "seller" else None,
            )
            sources, table = state.get("sources", []), state.get("table")
            berbukti = bool(table) or any(s.get("snippet") for s in sources)
            if not berbukti:
                # Penolakan atau jawaban tanpa data tidak bisa dinilai kesetiaannya.
                print(f"lewati {case['id']:12s} rute={state['route']} (tanpa bukti)")
                continue
            nilai = nilai_jawaban(juri, case["question"], state["answer"], sources, table)
            baris = {
                "id": case["id"],
                "set": nama,
                "rute": state["route"],
                "pertanyaan": case["question"],
                "jawaban": state["answer"],
                **nilai.model_dump(),
            }
            hasil.append(baris)
            with PROGRES.open("a") as f:
                f.write(json.dumps(baris, ensure_ascii=False) + "\n")
            tanda = "setia" if nilai.setia else "TIDAK SETIA"
            print(f"{tanda:11s} relevan {nilai.relevan}  {case['id']:12s} rute={state['route']}")

    per_rute = defaultdict(list)
    for h in hasil:
        per_rute[h["rute"]].append(h)
    ringkasan = {
        rute: {
            "kasus": len(rows),
            "setia": sum(r["setia"] for r in rows),
            "relevan_rata": round(sum(r["relevan"] for r in rows) / len(rows), 2),
        }
        for rute, rows in sorted(per_rute.items())
    }
    total = {
        "kasus": len(hasil),
        "setia": sum(h["setia"] for h in hasil),
        "relevan_rata": round(sum(h["relevan"] for h in hasil) / max(len(hasil), 1), 2),
    }
    REPORT.write_text(
        json.dumps(
            {
                "juri": juri_model,
                "penjawab": os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini"),
                "total": total,
                "per_rute": ringkasan,
                "tidak_setia": [h for h in hasil if not h["setia"]],
                "semua": hasil,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\nSetia {total['setia']}/{total['kasus']}, relevan rata-rata {total['relevan_rata']}")
    for rute, r in ringkasan.items():
        print(f"  {rute:7s} setia {r['setia']}/{r['kasus']}  relevan {r['relevan_rata']}")
    PROGRES.unlink(missing_ok=True)
    print(f"Laporan: {REPORT}")


if __name__ == "__main__":
    main()
