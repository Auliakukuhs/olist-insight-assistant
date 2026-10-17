"""Konfigurasi dari environment.

Nilai dibaca saat dipanggil, bukan saat import, supaya tes dan CI tidak butuh
API key apa pun.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    app_env: str
    api_access_key: str | None


def get_settings() -> Settings:
    return Settings(
        app_env=os.getenv("APP_ENV", "local"),
        api_access_key=os.getenv("API_ACCESS_KEY") or None,
    )
