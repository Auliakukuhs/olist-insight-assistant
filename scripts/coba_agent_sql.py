"""Uji agent SQL dengan LLM asli terhadap angka yang dihitung manual.

Contoh:
    uv run python scripts/coba_agent_sql.py                 # semua kasus
    uv run python scripts/coba_agent_sql.py sql-01 sql-08   # kasus tertentu

Angka acuan di data/eval/sql_contoh.jsonl dihitung langsung dengan SQL dari
data/olist.db. Sebuah kasus lulus bila semua teks di harus_memuat muncul di
jawaban (angka dibandingkan tanpa pemisah ribuan).
"""

import json
import re
import sys
import time
from pathlib import Path

from olist_assistant.agents.sql_contract import jawab_sql
from olist_assistant.config import load_dotenv

CASES = Path("data/eval/sql_contoh.jsonl")
# Seller dengan penjualan terbesar, sama dengan akun demo seller.
DEMO_SELLER = "4869f7a5dfa277a7dca6462dcf3b52b2"


def normalize(text: str) -> str:
    """Samakan 138,414.60 dan 138.414,60 menjadi 138414.6, supaya mudah dicocokkan."""

    def number(match: re.Match) -> str:
        raw = match.group(0)
        if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", raw):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
        return str(float(raw)).removesuffix(".0")

    # Hanya angka yang berdiri sendiri, bukan potongan ID seperti abe42c5d0369...
    return re.sub(r"(?<![A-Za-z0-9_])(\d[\d.,]*\d|\d)(?![A-Za-z0-9_])", number, text)


def main() -> None:
    load_dotenv()
    wanted = set(sys.argv[1:])
    cases = [json.loads(line) for line in CASES.read_text().splitlines() if line.strip()]
    passed = 0
    for case in cases:
        if wanted and case["id"] not in wanted:
            continue
        seller_id = DEMO_SELLER if case["peran"] == "seller" else None
        started = time.monotonic()
        result = jawab_sql(case["pertanyaan"], [], case["peran"], seller_id)
        answer = normalize(result["answer"])
        ok = all(normalize(text) in answer for text in case["harus_memuat"])
        if case.get("sql_harus_kosong"):
            ok = ok and result["sql"] == ""
        passed += ok
        print(
            f"{'LULUS' if ok else 'GAGAL'}  {case['id']}  [{case['peran']}]  "
            f"{time.monotonic() - started:.1f} detik"
        )
        print(f"   SQL    {result['sql'] or '(tidak ada)'}")
        print(f"   JAWAB  {result['answer'][:300]}")
    total = len(wanted) if wanted else len(cases)
    print(f"\n{passed}/{total} lulus")


if __name__ == "__main__":
    main()