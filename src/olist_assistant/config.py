"""Konfigurasi dari environment.

Nilai dibaca saat dipanggil, bukan saat import, supaya tes dan CI tidak butuh
API key apa pun.
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_env: str
    api_access_key: str | None


def get_settings() -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV", "local"),
        api_access_key=os.getenv("API_ACCESS_KEY") or None,
    )


def load_dotenv(path: Path = Path(".env")) -> None:
    """Muat .env sederhana tanpa menimpa environment yang sudah ada.

    Dipakai saat menjalankan lokal. Di container, nilai datang dari
    environment yang disuntik saat runtime.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            os.environ.setdefault(key.strip(), value)
