"""Coba agent RAG langsung ke Qdrant Cloud dan OpenAI.

Contoh:
    uv run python scripts/coba_agent_rag.py "Apa keluhan pembeli perlengkapan bayi?"
"""

import sys
import time

from olist_assistant.agents.rag import default_model, default_search, jawab_rag
from olist_assistant.config import load_dotenv


def main() -> None:
    load_dotenv()
    search, model = default_search(), default_model()
    for question in sys.argv[1:]:
        started = time.monotonic()
        result = jawab_rag(question, [], search, model)
        print(f"\nTANYA  {question}")
        print(f"JAWAB  {result['answer']}")
        print(f"SUMBER {[s['id'][:8] for s in result['sources']]}")
        print(f"WAKTU  {time.monotonic() - started:.1f} detik")


if __name__ == "__main__":
    main()
