"""REST API OLIST Insight Assistant."""

import logging
import os
import secrets
import threading
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from olist_assistant import __version__
from olist_assistant.agents.supervisor import Supervisor
from olist_assistant.api import analytics
from olist_assistant.api.ratelimit import RateLimiter
from olist_assistant.api.schemas import ChatRequest, ChatResponse, HealthResponse, Source
from olist_assistant.config import Settings, get_settings, load_dotenv

REQUIRED_ENV = ("OPENAI_API_KEY", "QDRANT_URL", "QDRANT_API_KEY")

# Menumpang logger uvicorn supaya pesan terlihat di log container (CloudWatch).
logger = logging.getLogger("uvicorn.error")

per_session = RateLimiter(int(os.getenv("RATE_LIMIT_PER_SESSION", "20")))
per_client = RateLimiter(int(os.getenv("RATE_LIMIT_PER_CLIENT", "60")))


def _warm_up() -> None:
    """Bangun supervisor dan muat model router sebelum request pertama datang."""
    try:
        get_supervisor()
        logger.info("Supervisor siap")
    except HTTPException:
        logger.info("Kunci layanan belum ada, pemanasan dilewati")
    except Exception:
        logger.exception("Pemanasan supervisor gagal")


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Di thread terpisah supaya /health langsung menjawab health check ECS.
    if os.getenv("WARMUP", "1") == "1":
        threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(title="OLIST Insight Assistant", version=__version__, lifespan=lifespan)


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Wajibkan header X-API-Key bila API_ACCESS_KEY diisi."""
    if settings.api_access_key is None:
        return
    if x_api_key is None or not secrets.compare_digest(x_api_key, settings.api_access_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="API key tidak valid")


@lru_cache(maxsize=1)
def get_supervisor() -> Supervisor:
    """Bangun supervisor sekali, saat permintaan pertama."""
    load_dotenv()
    missing = [key for key in REQUIRED_ENV if not os.getenv(key)]
    if missing:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Layanan agent belum dikonfigurasi di server",
        )
    from olist_assistant.agents.supervisor import default_supervisor

    return default_supervisor()


app.include_router(analytics.router, dependencies=[Depends(require_api_key)])


def client_key(request: Request) -> str:
    """Alamat klien asli. Di belakang load balancer AWS, ada di X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(session_id: str, request: Request) -> None:
    for limiter, key in ((per_client, client_key(request)), (per_session, session_id)):
        wait = limiter.check(key)
        if wait is not None:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Terlalu banyak pertanyaan. Coba lagi dalam {wait:.0f} detik.",
                headers={"Retry-After": str(int(wait) + 1)},
            )


@app.get("/health")
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@app.post("/chat", dependencies=[Depends(require_api_key)])
def chat(
    request: ChatRequest,
    http_request: Request,
    supervisor: Annotated[Supervisor, Depends(get_supervisor)],
) -> ChatResponse:
    # Fungsi sinkron sengaja dipakai supaya pemanggilan LLM yang blocking
    # dijalankan FastAPI di threadpool, tidak menahan event loop.
    enforce_rate_limit(request.session_id, http_request)
    request_id = uuid.uuid4().hex
    try:
        state = supervisor.ask(request.message, request.session_id, request.role)
    except Exception:
        logger.exception("chat gagal, request_id=%s", request_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent gagal menjawab. Sebutkan kode {request_id} saat melapor.",
        ) from None
    return ChatResponse(
        answer=state["answer"],
        route=state["route"],
        sources=[Source(**s) for s in state.get("sources", [])],
        table=state.get("table"),
        request_id=request_id,
    )
