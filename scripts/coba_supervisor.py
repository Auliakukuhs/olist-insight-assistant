"""Coba supervisor langsung ke OpenAI dan Qdrant Cloud dalam satu sesi.

Contoh:
    uv run python scripts/coba_supervisor.py "Apa keluhan pembeli bayi?" "Kalau yang di SP?"
"""

import sys
import time
import uuid

from olist_assistant.agents.supervisor import default_supervisor
from olist_assistant.config import load_dotenv


def main() -> None:
    load_dotenv()
    supervisor = default_supervisor()
    session = uuid.uuid4().hex[:8]
    for question in sys.argv[1:]:
        started = time.monotonic()
        state = supervisor.ask(question, session)
        print(f"\nTANYA  {question}")
        print(f"RUTE   {state['route']}  ({time.monotonic() - started:.1f} detik)")
        print(f"JAWAB  {state['answer'][:400]}")
        print(f"SUMBER {[s['id'][:8] for s in state.get('sources', [])]}")


if __name__ == "__main__":
    main()
