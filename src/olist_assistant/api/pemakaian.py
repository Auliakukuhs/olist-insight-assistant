"""Ringkasan pemakaian chatbot khusus admin, dibaca dari Langfuse (#64).

Melengkapi panel proses per jawaban dengan pandangan tingkat sistem. Angkanya
diambil lewat Langfuse Metrics API v2 yang mengagregasi di server Langfuse, jadi
API ini tidak perlu menarik ribuan observasi. Hanya trace di environment tracing
yang sama dengan server ini yang dihitung, supaya evaluasi di laptop tidak
tercampur dengan pemakaian di AWS.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from olist_assistant.agents.supervisor import langfuse_client
from olist_assistant.api.auth import current_user
from olist_assistant.api.schemas import HariPemakaian, PemakaianResponse, Pengguna
from olist_assistant.api.umpan_balik import SCORE_NAME

ROOT = "olist-supervisor"
LANGKAH_AGENT = {"agent_rag": "rag", "agent_sql": "sql", "langsung": "supervisor"}

router = APIRouter(prefix="/admin", tags=["admin"])


def environment() -> str:
    """Environment tracing server ini. Container AWS memakai production."""
    return os.getenv("LANGFUSE_TRACING_ENVIRONMENT", "default")


def _metrics(client, query: dict) -> list[dict]:
    return client.api.metrics.metrics(query=json.dumps(query)).data


def _filter(column: str, value, kind: str = "string") -> dict:
    operator = "any of" if kind == "stringOptions" else "="
    return {"column": column, "operator": operator, "value": value, "type": kind}


def _bulat(nilai) -> float | None:
    return None if nilai is None else round(float(nilai), 1)


@router.get("/pemakaian")
def pemakaian(
    user: Annotated[Pengguna | None, Depends(current_user)],
    hari: Annotated[int, Query(ge=1, le=31)] = 7,
) -> PemakaianResponse:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Silakan login")
    if user.peran != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Pemakaian hanya untuk admin")
    client = langfuse_client()
    if client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Langfuse tidak aktif")

    sampai = datetime.now(UTC)
    dari = (sampai - timedelta(days=hari - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    env = environment()
    rentang = {"fromTimestamp": dari.isoformat(), "toTimestamp": sampai.isoformat()}
    observasi = {"view": "observations", **rentang}
    di_env = _filter("environment", env)

    root_harian = _metrics(
        client,
        {
            **observasi,
            "metrics": [
                {"measure": "count", "aggregation": "count"},
                {"measure": "latency", "aggregation": "p50"},
                {"measure": "latency", "aggregation": "p95"},
            ],
            "dimensions": [],
            "timeDimension": {"granularity": "day"},
            "filters": [_filter("name", ROOT), di_env],
        },
    )
    token_harian = _metrics(
        client,
        {
            **observasi,
            "metrics": [
                {"measure": "totalTokens", "aggregation": "sum"},
                {"measure": "totalCost", "aggregation": "sum"},
            ],
            "dimensions": [],
            "timeDimension": {"granularity": "day"},
            "filters": [_filter("type", "GENERATION"), di_env],
        },
    )
    peran = _metrics(
        client,
        {
            **observasi,
            "metrics": [{"measure": "count", "aggregation": "count"}],
            "dimensions": [{"field": "tags"}],
            "filters": [_filter("name", ROOT), di_env],
        },
    )
    agent = _metrics(
        client,
        {
            **observasi,
            "metrics": [{"measure": "count", "aggregation": "count"}],
            "dimensions": [{"field": "name"}],
            "filters": [_filter("name", list(LANGKAH_AGENT), "stringOptions"), di_env],
        },
    )
    skor = _metrics(
        client,
        {
            "view": "scores-boolean",
            **rentang,
            "metrics": [{"measure": "count", "aggregation": "count"}],
            "dimensions": [{"field": "booleanValue"}],
            "filters": [_filter("name", SCORE_NAME), di_env],
        },
    )

    token = {r["time_dimension"][:10]: r for r in token_harian}
    per_hari = []
    for r in sorted(root_harian, key=lambda r: r["time_dimension"]):
        tanggal = r["time_dimension"][:10]
        t = token.get(tanggal, {})
        per_hari.append(
            HariPemakaian(
                tanggal=tanggal,
                pertanyaan=int(r.get("count_count") or 0),
                token=int(t.get("sum_totalTokens") or 0),
                biaya_usd=round(float(t.get("sum_totalCost") or 0), 4),
                latensi_p50_ms=_bulat(r.get("p50_latency")),
                latensi_p95_ms=_bulat(r.get("p95_latency")),
            )
        )
    per_peran: dict[str, int] = {}
    for r in peran:
        for tag in r.get("tags") or []:
            if tag in ("customer", "seller", "admin"):
                per_peran[tag] = per_peran.get(tag, 0) + int(r["count_count"])
    return PemakaianResponse(
        environment=env,
        dari=dari.date().isoformat(),
        sampai=sampai.date().isoformat(),
        per_hari=per_hari,
        per_peran=per_peran,
        per_agent={LANGKAH_AGENT[r["name"]]: int(r["count_count"]) for r in agent},
        umpan_balik={
            "naik": sum(
                int(r["count_count"]) for r in skor if r.get("booleanValue") in (True, 1, "true")
            ),
            "turun": sum(
                int(r["count_count"]) for r in skor if r.get("booleanValue") in (False, 0, "false")
            ),
        },
    )
