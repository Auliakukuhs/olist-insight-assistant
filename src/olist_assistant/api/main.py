"""REST API OLIST Insight Assistant."""

import secrets
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

from olist_assistant import __version__
from olist_assistant.api.schemas import ChatRequest, ChatResponse, HealthResponse
from olist_assistant.config import Settings, get_settings

app = FastAPI(title="OLIST Insight Assistant", version=__version__)


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Wajibkan header X-API-Key bila API_ACCESS_KEY diisi."""
    if settings.api_access_key is None:
        return
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.api_access_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="API key tidak valid")


@app.get("/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@app.post("/chat", dependencies=[Depends(require_api_key)])
def chat(request: ChatRequest) -> ChatResponse:
    # Stub F1. Supervisor LangGraph menggantikan isi fungsi ini di F3.
    # Fungsi sinkron sengaja dipakai supaya pemanggilan LLM yang blocking
    # dijalankan FastAPI di threadpool, tidak menahan event loop.
    return ChatResponse(
        answer="Layanan belum tersambung ke agent. Ini respons stub F1.",
        route="stub",
        request_id=uuid.uuid4().hex,
    )
