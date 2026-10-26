"""REST API OLIST Insight Assistant."""

import logging
import os
import secrets
import threading
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Security, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader

from olist_assistant import __version__
from olist_assistant.agents.supervisor import Supervisor
from olist_assistant.api import analytics, auth
from olist_assistant.api.auth import current_user
from olist_assistant.api.keluaran import bersihkan
from olist_assistant.api.ratelimit import RateLimiter, client_ip
from olist_assistant.api.schemas import (
    ChatRequest,
    ChatResponse,
    HealthResponse,
    Pengguna,
    Proses,
    Source,
)
from olist_assistant.config import Settings, get_settings, load_dotenv

REQUIRED_ENV = ("OPENAI_API_KEY", "QDRANT_URL", "QDRANT_API_KEY")

# Menumpang logger uvicorn supaya pesan terlihat di log container (CloudWatch).
logger = logging.getLogger("uvicorn.error")

per_session = RateLimiter(int(os.getenv("RATE_LIMIT_PER_SESSION", "20")))
per_client = RateLimiter(int(os.getenv("RATE_LIMIT_PER_CLIENT", "60")))
per_account = RateLimiter(int(os.getenv("RATE_LIMIT_PER_ACCOUNT", "30")))


def _warm_up() -> None:
    """Bangun supervisor dan muat model router sebelum request pertama datang."""
    try:
        get_supervisor()
        logger.info("Supervisor siap")
    except HTTPException:
        logger.info("Kunci layanan belum ada, pemanasan dilewati")
    except Exception:
        logger.exception("Pemanasan supervisor gagal")


def periksa_konfigurasi(settings: Settings) -> None:
    """Produksi wajib punya kunci akses, rahasia token, dan akun yang valid.

    Dijalankan saat startup supaya salah konfigurasi menggagalkan container,
    bukan diam-diam membuka API (audit 25 Okt, S02).
    """
    if settings.app_env != "production":
        return
    kurang = [
        name
        for name, value in (
            ("API_ACCESS_KEY", settings.api_access_key),
            ("AUTH_SECRET", settings.auth_secret),
            ("DEMO_USERS", settings.demo_users),
        )
        if not value
    ]
    # Kunci layanan juga wajib. Tanpa ini container lolos health check tetapi setiap
    # chat dijawab 503, seperti task staging yang kehilangan OPENAI_API_KEY karena
    # galat jaringan saat deploy (26 Okt). Gagal start membuat ECS membatalkan
    # rollout dan kembali ke versi sebelumnya.
    kurang += [name for name in REQUIRED_ENV if not os.getenv(name)]
    if kurang:
        raise RuntimeError(f"Konfigurasi produksi tidak lengkap: {', '.join(kurang)}")
    auth.demo_users(settings)  # lempar ValueError bila isinya tidak valid


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_dotenv()
    periksa_konfigurasi(get_settings())
    # Di thread terpisah supaya /health langsung menjawab health check ECS.
    if os.getenv("WARMUP", "1") == "1":
        threading.Thread(target=_warm_up, daemon=True).start()
    yield


app = FastAPI(title="OLIST Insight Assistant", version=__version__, lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def validasi_gagal(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Galat validasi tanpa nilai input, supaya password tidak dipantulkan (audit S09)."""
    detail = [
        {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": detail})


# Didaftarkan sebagai skema keamanan supaya tombol Authorize di /docs mengirimnya.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, description="API_ACCESS_KEY")


def require_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_api_key: Annotated[str | None, Security(api_key_header)] = None,
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
    from olist_assistant.agents.cache import CacheJawaban
    from olist_assistant.agents.riwayat import buat_checkpointer
    from olist_assistant.agents.supervisor import default_supervisor

    return default_supervisor(checkpointer=buat_checkpointer(), cache=CacheJawaban.dari_env())


app.include_router(auth.router, dependencies=[Depends(require_api_key)])
app.include_router(analytics.router, dependencies=[Depends(require_api_key)])


def client_key(request: Request) -> str:
    return client_ip(request)


def enforce_rate_limit(session_id: str, request: Request, user: Pengguna | None = None) -> None:
    # Kuota sesi diberi nama akun, supaya session_id yang sama dari akun lain tidak
    # menghabiskan kuota orang lain. Kuota akun tidak bisa direset dengan
    # percakapan baru (audit 25 Okt, S06).
    checks = [(per_client, client_key(request))]
    if user is None:
        checks.append((per_session, session_id))
    else:
        checks += [(per_session, f"{user.username}:{session_id}"), (per_account, user.username)]
    for limiter, key in checks:
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
    user: Annotated[Pengguna | None, Depends(current_user)],
) -> ChatResponse:
    # Fungsi sinkron sengaja dipakai supaya pemanggilan LLM yang blocking
    # dijalankan FastAPI di threadpool, tidak menahan event loop.
    enforce_rate_limit(request.session_id, http_request, user)
    request_id = uuid.uuid4().hex
    # Login aktif berarti peran dari token, dan riwayat dipisah per akun supaya
    # session_id milik akun lain tidak bisa dipakai membaca percakapannya.
    if user is None:
        role, seller_id, thread = request.role, None, request.session_id
    else:
        role, seller_id = user.peran, user.seller_id
        thread = f"{user.username}:{request.session_id}"
    try:
        state = supervisor.ask(request.message, thread, role, seller_id)
    except Exception:
        logger.exception("chat gagal, request_id=%s", request_id)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Agent gagal menjawab. Sebutkan kode {request_id} saat melapor.",
        ) from None
    return ChatResponse(
        answer=bersihkan(state["answer"]),
        route=state["route"],
        sources=[
            Source(**{**s, "snippet": bersihkan(s["snippet"])} if s.get("snippet") else s)
            for s in state.get("sources", [])
        ],
        table=state.get("table"),
        proses=Proses(**state["proses"]) if state.get("proses") else None,
        request_id=request_id,
    )
