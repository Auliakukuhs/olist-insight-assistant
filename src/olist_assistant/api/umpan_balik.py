"""Umpan balik pengguna (jempol naik atau turun) untuk satu jawaban.

Nilainya ditulis ke Langfuse sebagai score pada trace jawaban itu, jadi kualitas
jawaban bisa dilacak bersama token, biaya, dan langkah agent di trace yang sama.
Hanya pemilik jawaban yang boleh menilainya. Pemilik dicatat di memori saat
/chat menjawab, dengan batas jumlah supaya memori tidak tumbuh tanpa batas.
"""

import threading
from collections import OrderedDict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from olist_assistant.agents.supervisor import langfuse_client
from olist_assistant.api.auth import current_user
from olist_assistant.api.ratelimit import RateLimiter
from olist_assistant.api.schemas import FeedbackRequest, FeedbackResponse, Pengguna

SCORE_NAME = "umpan_balik_pengguna"


class PemilikTrace:
    """trace_id ke username, menyimpan paling banyak `batas` jawaban terakhir."""

    def __init__(self, batas: int = 5000) -> None:
        self.batas = batas
        self._data: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.Lock()

    def catat(self, trace_id: str, username: str) -> None:
        with self._lock:
            self._data[trace_id] = username
            self._data.move_to_end(trace_id)
            while len(self._data) > self.batas:
                self._data.popitem(last=False)

    def pemilik(self, trace_id: str) -> str | None:
        with self._lock:
            return self._data.get(trace_id)


pemilik_trace = PemilikTrace()
per_client_feedback = RateLimiter(30)

router = APIRouter(tags=["umpan balik"])


@router.post("/feedback")
def feedback(
    body: FeedbackRequest,
    request: Request,
    user: Annotated[Pengguna | None, Depends(current_user)],
) -> FeedbackResponse:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Umpan balik butuh login")
    wait = per_client_feedback.check(user.username)
    if wait is not None:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Terlalu banyak umpan balik. Coba lagi dalam {wait:.0f} detik.",
        )
    # Trace milik akun lain dijawab sama dengan trace yang tidak ada, supaya
    # keberadaan trace orang lain tidak bisa ditebak.
    if pemilik_trace.pemilik(body.trace_id) != user.username:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Jawaban tidak ditemukan")
    client = langfuse_client()
    if client is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Pencatatan umpan balik tidak aktif"
        )
    # score_id tetap per trace, jadi mengganti pilihan memperbarui score yang sama.
    client.create_score(
        name=SCORE_NAME,
        value=1 if body.suka else 0,
        data_type="BOOLEAN",
        trace_id=body.trace_id,
        score_id=f"{body.trace_id}-{SCORE_NAME}",
        comment=body.komentar,
        metadata={"peran": user.peran},
    )
    return FeedbackResponse(tercatat=True)
