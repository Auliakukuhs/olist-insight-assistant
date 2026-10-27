"""Kamus data (#5) tidak boleh tertinggal dari view ETL.

Isi lengkap docs/KAMUS-DATA.md dibangun ulang dengan `uv run python
scripts/kamus_data.py`, yang gagal bila ada kolom tanpa keterangan. Test ini hanya
memeriksa strukturnya, karena membangun seluruh kamus butuh sekitar 45 detik.
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from olist_assistant.api.analytics import db_path

spec = importlib.util.spec_from_file_location("kamus_data", Path("scripts/kamus_data.py"))
kamus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kamus)


@pytest.mark.skipif(not db_path().exists(), reason="data/olist.db belum dibuat ETL (#4)")
def test_setiap_view_dan_kolom_punya_keterangan():
    conn = sqlite3.connect(f"file:{db_path()}?mode=ro", uri=True)
    try:
        assert kamus.kolom_tanpa_keterangan(conn) == []
        view_db = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'view'")}
        assert set(kamus.VIEW) == view_db
    finally:
        conn.close()


def test_format_angka_indonesia():
    assert kamus.ribuan(112650) == "112.650"
    assert kamus.persen(3.0) == "3%" and kamus.persen(0.83) == "0,8%"
