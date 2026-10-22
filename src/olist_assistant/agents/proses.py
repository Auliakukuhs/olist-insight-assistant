"""Catatan proses satu giliran, untuk panel di bawah setiap jawaban.

Callback LangChain ini menerima event dari semua run di dalam graph, termasuk
pemanggilan LLM di dalam sub-agent, karena callback diwariskan ke run anak.
Setiap pemanggilan LLM dan tool dikaitkan ke langkah terdekat di atasnya
(router, agent RAG, agent SQL, sintesis), sehingga token dan lama proses bisa
dirinci per langkah.
"""

import os
import threading
import time
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

# Harga per 1 juta token dalam USD, dari halaman harga OpenAI. Model lain
# dihitung nol.
PRICES_PER_1M = {"gpt-4o-mini": (0.15, 0.60)}

# Nama run di graph supervisor yang ditampilkan sebagai langkah.
STEP_LABELS = {
    "guard": "Guard",
    "route": "Router",
    "langsung": "Jawaban langsung supervisor",
    "rencana": "Perencana filter bersama",
    "agent_rag": "Agent RAG",
    "agent_sql": "Agent SQL",
    "cek": "Pemeriksa kecukupan",
    "sintesis": "Sintesis jawaban",
}
AGENT_OF_STEP = {"agent_rag": "rag", "agent_sql": "sql"}


class ProsesRecorder(BaseCallbackHandler):
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._parent: dict[UUID, UUID | None] = {}
        self._steps: dict[UUID, dict] = {}
        self._usage: dict[UUID | None, list[int]] = {}
        self.tools: list[str] = []

    def _remember(self, run_id: UUID, parent_run_id: UUID | None) -> None:
        with self._lock:
            self._parent[run_id] = parent_run_id

    def _step_run(self, run_id: UUID | None) -> UUID | None:
        """Run langkah terdekat di atas run ini, atau None bila tidak ada."""
        while run_id is not None and run_id not in self._steps:
            run_id = self._parent.get(run_id)
        return run_id

    def on_chain_start(self, serialized, inputs, *, run_id, parent_run_id=None, **kwargs):
        self._remember(run_id, parent_run_id)
        name = kwargs.get("name")
        if name in STEP_LABELS:
            with self._lock:
                self._steps[run_id] = {"nama": name, "mulai": time.perf_counter(), "durasi": 0}

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        with self._lock:
            step = self._steps.get(run_id)
            if step is not None:
                step["durasi"] = time.perf_counter() - step["mulai"]

    def on_chain_error(self, error, *, run_id, **kwargs):
        self.on_chain_end({}, run_id=run_id)

    def on_chat_model_start(self, serialized, messages, *, run_id, parent_run_id=None, **kwargs):
        self._remember(run_id, parent_run_id)

    def on_llm_start(self, serialized, prompts, *, run_id, parent_run_id=None, **kwargs):
        self._remember(run_id, parent_run_id)

    def on_llm_end(self, response, *, run_id, **kwargs):
        token_in = token_out = 0
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None) or {}
                token_in += usage.get("input_tokens", 0)
                token_out += usage.get("output_tokens", 0)
        with self._lock:
            total = self._usage.setdefault(self._step_run(run_id), [0, 0])
            total[0] += token_in
            total[1] += token_out

    def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id=None, **kwargs):
        self._remember(run_id, parent_run_id)
        name = kwargs.get("name") or (serialized or {}).get("name")
        if name:
            with self._lock:
                self.tools.append(name)

    def summary(self, durasi_ms: int, alasan: str | None) -> dict:
        """Ringkasan dalam bentuk schemas.Proses."""
        model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        price_in, price_out = PRICES_PER_1M.get(model, (0.0, 0.0))
        ordered = sorted(self._steps.items(), key=lambda item: item[1]["mulai"])
        langkah = []
        for run_id, step in ordered:
            token_in, token_out = self._usage.get(run_id, [0, 0])
            langkah.append(
                {
                    "nama": STEP_LABELS[step["nama"]],
                    "durasi_ms": round(step["durasi"] * 1000),
                    "token_input": token_in,
                    "token_output": token_out,
                }
            )
        token_in = sum(t[0] for t in self._usage.values())
        token_out = sum(t[1] for t in self._usage.values())
        agents = ["supervisor"] + [
            AGENT_OF_STEP[s["nama"]] for _, s in ordered if s["nama"] in AGENT_OF_STEP
        ]
        return {
            "agent": list(dict.fromkeys(agents)),
            "tools": list(dict.fromkeys(self.tools)),
            "alasan": alasan,
            "langkah": langkah,
            "token_input": token_in,
            "token_output": token_out,
            "biaya_usd": round((token_in * price_in + token_out * price_out) / 1_000_000, 6),
            "durasi_ms": durasi_ms,
            "model": model,
        }
