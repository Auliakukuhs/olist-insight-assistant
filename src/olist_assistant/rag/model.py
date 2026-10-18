"""Bentuk dokumen RAG dan ID deterministik.

Modul ini sengaja tanpa pandas supaya bisa diimpor oleh API dan agent di
container, yang tidak memasang dependensi ingestion.
"""

import uuid
from dataclasses import dataclass

# Namespace tetap untuk uuid5. Jangan diubah, kalau berubah semua ID titik di
# Qdrant ikut berubah dan ingestion ulang akan menggandakan data.
NAMESPACE = uuid.UUID("b2c425c6-1af7-4430-a6ef-a14bf66da083")
DOC_VERSION = "v1"


@dataclass(frozen=True)
class RagDocument:
    id: str
    text: str
    metadata: dict


def doc_id(*parts: str) -> str:
    """ID deterministik dari kunci alami, sama di setiap kali dibangun."""
    return str(uuid.uuid5(NAMESPACE, "|".join((DOC_VERSION, *parts))))
