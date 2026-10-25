"""Kontrak request dan response REST API.

Streamlit dan tes hanya bergantung pada bentuk ini. Riwayat percakapan tidak
dikirim klien, tetapi disimpan server per session_id, sehingga klien tidak bisa
memalsukan percakapan sebelumnya.
"""

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["customer", "seller", "admin"]
Route = Literal["rag", "sql", "hybrid", "umum", "out_of_scope", "stub"]
Agent = Literal["supervisor", "rag", "sql"]
CellValue = str | int | float | None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    role: Role = Field(
        "customer",
        description="Hanya dipakai bila login tidak diaktifkan. Bila aktif, peran dari token.",
    )


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class Pengguna(BaseModel):
    username: str
    peran: Role
    seller_id: str | None = None
    """Hanya untuk peran seller. Dipakai agent SQL dan analytics, tidak pernah dari teks."""


class LoginResponse(BaseModel):
    token: str
    pengguna: Pengguna


class Langkah(BaseModel):
    """Satu langkah di graph supervisor, untuk panel proses di Streamlit."""

    nama: str
    durasi_ms: int
    token_input: int = 0
    token_output: int = 0


class Proses(BaseModel):
    """Apa yang terjadi di balik satu jawaban."""

    agent: list[Agent]
    tools: list[str]
    alasan: str | None
    """Kenapa jalur ini dipilih, dari guard, router ONNX, atau router LLM."""
    langkah: list[Langkah]
    token_input: int
    token_output: int
    biaya_usd: float
    """Estimasi dari harga model per 1 juta token. Embedding query tidak termasuk."""
    durasi_ms: int
    model: str


class Source(BaseModel):
    kind: Literal["review", "category", "sql"]
    id: str
    snippet: str | None = None


class ChatResponse(BaseModel):
    answer: str
    route: Route
    sources: list[Source] = Field(default_factory=list)
    table: list[dict[str, CellValue]] | None = None
    proses: Proses | None = None
    request_id: str
    trace_id: str | None = None
    """Trace Langfuse jawaban ini, dipakai /feedback. None bila tracing mati."""


class FeedbackRequest(BaseModel):
    trace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    suka: bool
    komentar: str | None = Field(default=None, max_length=500)


class FeedbackResponse(BaseModel):
    tercatat: bool


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
