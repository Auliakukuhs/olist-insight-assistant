"""Pembatas jumlah request per menit, disimpan di memori proses.

Tujuannya melindungi saldo OpenAI dari spam. Batasan yang disadari, hitungan
hilang saat container restart dan tidak dibagi antar container. Itu cukup karena
service berjalan dengan tepat satu task.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import Request

# Kunci lama dibersihkan bila jumlahnya melewati batas ini, supaya memori tidak
# tumbuh oleh kunci yang hanya dipakai sekali (audit 25 Okt, S04).
MAX_KEYS = 5000


def client_ip(request: Request) -> str:
    """Alamat klien menurut load balancer.

    Load balancer AWS menambahkan alamat klien yang dilihatnya di akhir
    X-Forwarded-For. Entri sebelumnya ditulis pemanggil dan bisa dipalsukan,
    jadi yang dipakai entri terakhir (audit 25 Okt, S03).
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """Catat satu request. Kembalikan None bila boleh, atau detik tunggu bila penuh."""
        now = self.clock()
        with self._lock:
            if len(self._hits) > MAX_KEYS:
                self._buang_kedaluwarsa(now)
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return round(self.window - (now - hits[0]), 1)
            hits.append(now)
            return None

    def _buang_kedaluwarsa(self, now: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] >= self.window]:
            del self._hits[key]
