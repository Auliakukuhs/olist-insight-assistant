"""Login sederhana dan peran pengguna.

Akun demo dibaca dari environment DEMO_USERS (JSON), token ditandatangani
HMAC-SHA256 dengan AUTH_SECRET. Keduanya disimpan di SSM, tidak di repo.

Peran selalu dibaca dari token yang ditandatangani server, bukan dari body
request, karena siapa pun yang memegang API key bisa menulis "admin" di body.
Bila AUTH_SECRET kosong (mode lokal dan tes), login mati dan peran diambil dari
body seperti sebelumnya.
"""

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from olist_assistant.api.ratelimit import RateLimiter, client_ip
from olist_assistant.api.schemas import LoginRequest, LoginResponse, Pengguna
from olist_assistant.config import Settings, get_settings

TOKEN_TTL_SECONDS = 12 * 60 * 60
SELLER_ID = re.compile(r"^[0-9a-f]{32}$")

# Sepuluh percobaan per menit per klien cukup untuk manusia, terlalu lambat
# untuk menebak password. Batas per akun mencegah tebakan dari banyak alamat.
per_client_login = RateLimiter(10)
per_account_login = RateLimiter(10)
MAX_TOKEN_LENGTH = 2048


class DemoUser(BaseModel):
    password: str
    peran: str
    seller_id: str | None = None


def demo_users(settings: Settings) -> dict[str, DemoUser]:
    if not settings.demo_users:
        return {}
    users = {name: DemoUser(**data) for name, data in json.loads(settings.demo_users).items()}
    for name, user in users.items():
        if user.peran not in ("customer", "seller", "admin"):
            raise ValueError(f"Peran akun {name} tidak dikenal")
        if user.peran == "seller" and not SELLER_ID.fullmatch(user.seller_id or ""):
            raise ValueError(f"Akun seller {name} wajib punya seller_id 32 karakter hex")
    return users


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def make_token(user: Pengguna, secret: str, now: float | None = None) -> str:
    expires = int((now or time.time()) + TOKEN_TTL_SECONDS)
    payload = _b64(json.dumps({**user.model_dump(), "exp": expires}).encode())
    return f"{payload}.{_sign(payload, secret)}"


def read_token(token: str, secret: str, now: float | None = None) -> Pengguna | None:
    """Isi token bila tanda tangannya sah dan belum kedaluwarsa."""
    if len(token) > MAX_TOKEN_LENGTH:
        return None
    try:
        payload, signature = token.split(".")
        # Bandingkan sebagai bytes. Token berisi huruf non-ASCII membuat
        # compare_digest pada str melempar TypeError, dulu menjadi HTTP 500.
        if not hmac.compare_digest(signature.encode(), _sign(payload, secret).encode()):
            return None
        data = json.loads(_unb64(payload))
    except (ValueError, TypeError, UnicodeError):
        return None
    if data.pop("exp", 0) < (now or time.time()):
        return None
    return Pengguna(**data)


# Skema Bearer, supaya Swagger mengirim header Authorization lewat tombol Authorize.
# Header bernama Authorization yang ditulis sebagai parameter biasa dibuang Swagger.
bearer = HTTPBearer(auto_error=False, description="Token dari POST /auth/login")


def current_user(
    settings: Annotated[Settings, Depends(get_settings)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)] = None,
) -> Pengguna | None:
    """Pengguna dari header Authorization. None berarti login tidak diaktifkan."""
    if settings.auth_secret is None:
        # Di produksi, login yang mati berarti salah konfigurasi. Gagal tertutup,
        # jangan menerima peran dari body (audit 25 Okt, S02).
        if settings.app_env == "production":
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE, detail="Login belum dikonfigurasi di server"
            )
        return None
    user = read_token(credentials.credentials, settings.auth_secret) if credentials else None
    if user is not None:
        # Token berlaku hanya selama akunnya masih ada dengan peran yang sama, jadi
        # akun yang dihapus atau diubah perannya langsung tidak berlaku (S05).
        account = demo_users(settings).get(user.username)
        if account is None or (account.peran, account.seller_id) != (user.peran, user.seller_id):
            user = None
    if user is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Silakan login ulang",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginResponse:
    if settings.auth_secret is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Login belum diaktifkan")
    wait = per_client_login.check(client_ip(request)) or per_account_login.check(body.username)
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Terlalu banyak percobaan login. Coba lagi dalam {wait:.0f} detik.",
            headers={"Retry-After": str(int(wait) + 1)},
        )
    account = demo_users(settings).get(body.username)
    # Bandingkan dengan password palsu bila akun tidak ada, supaya waktu jawab
    # tidak membocorkan nama akun mana yang terdaftar.
    expected = account.password if account else secrets.token_hex(16)
    if not hmac.compare_digest(body.password.encode(), expected.encode()) or account is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Username atau password salah")
    user = Pengguna(username=body.username, peran=account.peran, seller_id=account.seller_id)
    return LoginResponse(token=make_token(user, settings.auth_secret), pengguna=user)


@router.get("/me")
def me(user: Annotated[Pengguna | None, Depends(current_user)]) -> Pengguna:
    if user is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Login belum diaktifkan")
    return user
