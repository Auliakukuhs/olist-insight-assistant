"""Penyimpanan riwayat percakapan (checkpointer LangGraph).

Tanpa RIWAYAT_TABEL, riwayat disimpan di memori proses (InMemorySaver), cukup untuk
lokal, test, dan evaluasi. Di AWS, RIWAYAT_TABEL berisi nama tabel DynamoDB, jadi
riwayat tetap ada saat container restart atau task diganti oleh deploy (#70).
Disk task Fargate ikut hilang setiap task diganti, jadi SQLite lokal tidak cukup.

Umur sesi dibatasi RIWAYAT_UMUR_JAM (bawaan 24). DynamoDB menghapus item kedaluwarsa
lewat TTL, tetapi penghapusannya bisa tertunda beberapa hari, jadi umur juga dicek
saat riwayat dibaca (Supervisor._riwayat_kedaluwarsa).
"""

import os
from datetime import UTC, datetime, timedelta

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver

UMUR_SESI_JAM = 24


def umur_sesi() -> timedelta:
    return timedelta(hours=float(os.getenv("RIWAYAT_UMUR_JAM", str(UMUR_SESI_JAM))))


def buat_checkpointer() -> BaseCheckpointSaver:
    """InMemorySaver, atau DynamoDBSaver bila RIWAYAT_TABEL diisi."""
    tabel = os.getenv("RIWAYAT_TABEL")
    if not tabel:
        return InMemorySaver()
    from botocore.config import Config
    from langgraph_checkpoint_aws import DynamoDBSaver

    return DynamoDBSaver(
        table_name=tabel,
        region_name=os.getenv("AWS_REGION", "ap-southeast-1"),
        ttl_seconds=int(umur_sesi().total_seconds()),
        # State memuat tabel hasil SQL sampai 200 baris. Kompresi menjaga item
        # jauh di bawah batas 400 KB DynamoDB tanpa perlu bucket S3.
        enable_checkpoint_compression=True,
        # Batas waktu pendek supaya DynamoDB yang lambat tidak menahan chat.
        boto_config=Config(
            connect_timeout=2, read_timeout=5, retries={"max_attempts": 3, "mode": "standard"}
        ),
    )


def sudah_kedaluwarsa(created_at: str | None, sekarang: datetime | None = None) -> bool:
    """True bila checkpoint terakhir lebih tua dari umur sesi."""
    if not created_at:
        return False
    terakhir = datetime.fromisoformat(created_at)
    return (sekarang or datetime.now(UTC)) - terakhir > umur_sesi()
