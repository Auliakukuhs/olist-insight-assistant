"""Membentuk dokumen RAG dari CSV OLIST.

Ada dua jenis dokumen.

- **review**, satu review satu dokumen tanpa chunking, karena komentar
  terpanjang di OLIST hanya 208 karakter.
- **category**, satu dokumen per kategori produk, supaya pertanyaan seperti
  "perlengkapan bayi" bisa dipetakan ke nama kategori aslinya.

Review melekat ke pesanan, bukan ke produk. Pesanan bisa berisi beberapa produk
dari beberapa seller, jadi metadata menyimpan semuanya dan teks tidak pernah
mengklaim review itu membahas satu produk tertentu.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# Namespace tetap untuk uuid5. Jangan diubah, kalau berubah semua ID titik di
# Qdrant ikut berubah dan ingestion ulang akan menggandakan data.
NAMESPACE = uuid.UUID("b2c425c6-1af7-4430-a6ef-a14bf66da083")
DOC_VERSION = "v1"
UNKNOWN_CATEGORY = "unknown"

CSV_FILES = {
    "reviews": "olist_order_reviews_dataset.csv",
    "items": "olist_order_items_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "translation": "product_category_name_translation.csv",
}


@dataclass(frozen=True)
class RagDocument:
    id: str
    text: str
    metadata: dict


def doc_id(*parts: str) -> str:
    """ID deterministik dari kunci alami, sama di setiap kali dibangun."""
    return str(uuid.uuid5(NAMESPACE, "|".join((DOC_VERSION, *parts))))


def load_tables(raw_dir: Path) -> dict[str, pd.DataFrame]:
    """Baca CSV sebagai teks supaya ID dengan nol di depan tidak berubah."""
    return {
        name: pd.read_csv(raw_dir / filename, dtype=str, encoding="utf-8-sig").fillna("")
        for name, filename in CSV_FILES.items()
    }


def _category_names(translation: pd.DataFrame) -> dict[str, str]:
    return dict(
        zip(
            translation["product_category_name"],
            translation["product_category_name_english"],
            strict=True,
        )
    )


def _order_context(
    items: pd.DataFrame,
    products: pd.DataFrame,
    sellers: pd.DataFrame,
    translation: pd.DataFrame,
) -> pd.DataFrame:
    """Satu baris per order_id berisi daftar produk, kategori, dan seller."""
    english = _category_names(translation)
    merged = items.merge(
        products[["product_id", "product_category_name"]], on="product_id", how="left"
    ).merge(sellers[["seller_id", "seller_city", "seller_state"]], on="seller_id", how="left")
    merged = merged.fillna("")
    merged["category"] = [
        english.get(pt, pt) or UNKNOWN_CATEGORY for pt in merged["product_category_name"]
    ]

    def unique_sorted(values: pd.Series) -> list[str]:
        return sorted({v for v in values if v})

    return merged.groupby("order_id").agg(
        product_ids=("product_id", unique_sorted),
        seller_ids=("seller_id", unique_sorted),
        categories=("category", unique_sorted),
        seller_cities=("seller_city", unique_sorted),
        seller_states=("seller_state", unique_sorted),
    )


def build_review_documents(tables: dict[str, pd.DataFrame]) -> list[RagDocument]:
    reviews = tables["reviews"].copy()
    reviews["title"] = reviews["review_comment_title"].str.strip()
    reviews["message"] = reviews["review_comment_message"].str.strip()
    reviews = reviews[(reviews["title"] != "") | (reviews["message"] != "")]
    reviews = reviews.drop_duplicates(subset=["review_id", "order_id"])

    context = _order_context(
        tables["items"], tables["products"], tables["sellers"], tables["translation"]
    )
    reviews = reviews.merge(context, left_on="order_id", right_index=True, how="left")

    documents = []
    for row in reviews.itertuples(index=False):
        categories = row.categories if isinstance(row.categories, list) else []
        cities = row.seller_cities if isinstance(row.seller_cities, list) else []
        states = row.seller_states if isinstance(row.seller_states, list) else []
        parts = [f"Ulasan pembeli dengan skor {row.review_score} dari 5."]
        if categories:
            readable = ", ".join(c.replace("_", " ") for c in categories)
            parts.append(f"Kategori produk dalam pesanan {readable}.")
        if states:
            parts.append(f"Seller berlokasi di {', '.join(cities)} ({', '.join(states)}).")
        if row.title:
            parts.append(f"Judul ulasan {row.title}.")
        if row.message:
            parts.append(f"Isi ulasan {row.message}")
        documents.append(
            RagDocument(
                id=doc_id("review", row.review_id, row.order_id),
                text=" ".join(parts),
                metadata={
                    "doc_type": "review",
                    "review_id": row.review_id,
                    "order_id": row.order_id,
                    "review_score": int(row.review_score),
                    "review_date": row.review_creation_date[:10],
                    "product_ids": row.product_ids if isinstance(row.product_ids, list) else [],
                    "seller_ids": row.seller_ids if isinstance(row.seller_ids, list) else [],
                    "categories": categories,
                    "seller_cities": cities,
                    "seller_states": states,
                },
            )
        )
    return documents


def build_category_documents(tables: dict[str, pd.DataFrame]) -> list[RagDocument]:
    english = _category_names(tables["translation"])
    counts = tables["products"]["product_category_name"].value_counts()
    documents = []
    for pt_name, product_count in sorted(counts.items()):
        if not pt_name:
            continue
        en_name = english.get(pt_name, pt_name)
        documents.append(
            RagDocument(
                id=doc_id("category", pt_name),
                text=(
                    f"Kategori produk {en_name.replace('_', ' ')} "
                    f"(nama Portugis {pt_name.replace('_', ' ')}). "
                    f"Katalog OLIST memuat {product_count} produk di kategori ini."
                ),
                metadata={
                    "doc_type": "category",
                    "category": en_name,
                    "category_pt": pt_name,
                    "product_count": int(product_count),
                },
            )
        )
    return documents


def build_all_documents(tables: dict[str, pd.DataFrame]) -> list[RagDocument]:
    return build_review_documents(tables) + build_category_documents(tables)
