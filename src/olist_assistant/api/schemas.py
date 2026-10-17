"""Kontrak request dan response REST API.

Streamlit dan tes hanya bergantung pada bentuk ini. Riwayat percakapan tidak
dikirim klien, tetapi disimpan server per session_id, sehingga klien tidak bisa
memalsukan percakapan sebelumnya.
"""

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["customer", "seller"]
Route = Literal["rag", "sql", "hybrid", "out_of_scope", "stub"]
CellValue = str | int | float | None


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    role: Role = "customer"


class Source(BaseModel):
    kind: Literal["review", "category", "sql"]
    id: str
    snippet: str | None = None


class ChatResponse(BaseModel):
    answer: str
    route: Route
    sources: list[Source] = Field(default_factory=list)
    table: list[dict[str, CellValue]] | None = None
    request_id: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
