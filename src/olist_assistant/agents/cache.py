"""Cache jawaban untuk pertanyaan pertama sesi yang berulang (#67).

Hanya pertanyaan tanpa riwayat yang di-cache, karena jawaban pertanyaan lanjutan
bergantung pada percakapan sebelumnya. Kunci memuat peran dan seller_id, jadi
jawaban seller A tidak pernah sampai ke seller B atau ke customer. Jawaban yang
disimpan sudah melewati guard, aturan peran, dan agent untuk peran yang sama,
jadi cache tidak membuka jalan pintas melewati pengaman.

Cache ada di memori proses dan kosong lagi setiap deploy, jadi prompt atau aturan
baru tidak terhalang jawaban lama.
"""

import os
import re
import threading
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Callable

# Jalur yang memanggil agent. Sapaan dan jawaban tanggal (umum) tidak disimpan,
# karena murah dan jawaban tanggal berubah setiap hari. Penolakan juga tidak.
JALUR_DISIMPAN = {"sql", "rag", "hybrid"}

Kunci = tuple[str, str, str]


def normalkan(pertanyaan: str) -> str:
    """Huruf kecil, spasi dirapikan, tanda baca di ujung dibuang."""
    teks = unicodedata.normalize("NFKC", pertanyaan).casefold()
    teks = re.sub(r"\s+", " ", teks).strip()
    return teks.rstrip(" ?!.")


class CacheJawaban:
    """LRU dengan masa berlaku. Aman dipakai banyak thread FastAPI."""

    def __init__(
        self,
        ukuran: int = 256,
        umur_detik: float = 6 * 3600,
        jam: Callable[[], float] = time.monotonic,
    ) -> None:
        self.ukuran = ukuran
        self.umur_detik = umur_detik
        self._jam = jam
        self._isi: OrderedDict[Kunci, tuple[float, dict]] = OrderedDict()
        self._kunci = threading.Lock()

    @classmethod
    def dari_env(cls) -> "CacheJawaban | None":
        """None bila CACHE_JAWABAN=0."""
        if os.getenv("CACHE_JAWABAN", "1") == "0":
            return None
        return cls(
            ukuran=int(os.getenv("CACHE_JAWABAN_UKURAN", "256")),
            umur_detik=float(os.getenv("CACHE_JAWABAN_UMUR_MENIT", "360")) * 60,
        )

    @staticmethod
    def kunci(pertanyaan: str, peran: str, seller_id: str | None) -> Kunci:
        return peran, seller_id or "", normalkan(pertanyaan)

    def ambil(self, kunci: Kunci) -> tuple[dict, float] | None:
        """Jawaban dan umurnya dalam detik, atau None bila tidak ada atau kedaluwarsa."""
        with self._kunci:
            item = self._isi.get(kunci)
            if item is None:
                return None
            disimpan, nilai = item
            umur = self._jam() - disimpan
            if umur > self.umur_detik:
                del self._isi[kunci]
                return None
            self._isi.move_to_end(kunci)
            return nilai, umur

    def simpan(self, kunci: Kunci, nilai: dict) -> None:
        with self._kunci:
            self._isi[kunci] = (self._jam(), nilai)
            self._isi.move_to_end(kunci)
            while len(self._isi) > self.ukuran:
                self._isi.popitem(last=False)

    def __len__(self) -> int:
        return len(self._isi)
