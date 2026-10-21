"""Pembatas jumlah request per menit, disimpan di memori proses.

Tujuannya melindungi saldo OpenAI dari spam. Batasan yang disadari, hitungan
hilang saat container restart dan tidak dibagi antar container. Itu cukup karena
service berjalan dengan tepat satu task.
"""

import threading
import time
from collections import defaultdict, deque


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
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return round(self.window - (now - hits[0]), 1)
            hits.append(now)
            return None
