import pandas as pd
import pytest

from olist_assistant.rag.documents import (
    build_category_documents,
    build_review_documents,
)


@pytest.fixture
def tables():
    reviews = pd.DataFrame(
        [
            # pesanan dua produk, dua kategori, dua seller
            ["r1", "o1", "5", "", "Chegou antes do prazo", "2018-01-02 00:00:00"],
            # baris duplikat persis, harus jadi satu dokumen
            ["r1", "o1", "5", "", "Chegou antes do prazo", "2018-01-02 00:00:00"],
            # review_id sama untuk pesanan lain, harus jadi dokumen terpisah
            ["r1", "o2", "1", "Ruim", "", "2018-02-03 00:00:00"],
            # tanpa judul dan tanpa komentar, tidak dijadikan dokumen
            ["r3", "o3", "4", "", "  ", "2018-03-04 00:00:00"],
        ],
        columns=[
            "review_id",
            "order_id",
            "review_score",
            "review_comment_title",
            "review_comment_message",
            "review_creation_date",
        ],
    )
    items = pd.DataFrame(
        [["o1", "p1", "s1"], ["o1", "p2", "s2"], ["o2", "p3", "s1"], ["o3", "p1", "s1"]],
        columns=["order_id", "product_id", "seller_id"],
    )
    products = pd.DataFrame(
        [["p1", "bebes"], ["p2", "pc_gamer"], ["p3", ""], ["p4", "bebes"]],
        columns=["product_id", "product_category_name"],
    )
    sellers = pd.DataFrame(
        [["s1", "sao paulo", "SP"], ["s2", "rio de janeiro", "RJ"]],
        columns=["seller_id", "seller_city", "seller_state"],
    )
    # pc_gamer sengaja tidak ada, seperti di data asli OLIST
    translation = pd.DataFrame(
        [["bebes", "baby"]], columns=["product_category_name", "product_category_name_english"]
    )
    return {
        "reviews": reviews,
        "items": items,
        "products": products,
        "sellers": sellers,
        "translation": translation,
    }


def by_order(documents):
    return {doc.metadata["order_id"]: doc for doc in documents}


def test_review_tanpa_teks_dibuang_dan_duplikat_digabung(tables):
    documents = build_review_documents(tables)
    assert sorted(doc.metadata["order_id"] for doc in documents) == ["o1", "o2"]


def test_review_id_sama_beda_pesanan_jadi_dua_id(tables):
    documents = build_review_documents(tables)
    assert len({doc.id for doc in documents}) == 2


def test_pesanan_multi_produk_menyimpan_semua_produk(tables):
    doc = by_order(build_review_documents(tables))["o1"]
    assert doc.metadata["product_ids"] == ["p1", "p2"]
    assert doc.metadata["categories"] == ["baby", "pc_gamer"]
    assert doc.metadata["seller_states"] == ["RJ", "SP"]
    assert "Kategori produk dalam pesanan baby, pc gamer." in doc.text
    assert "Chegou antes do prazo" in doc.text


def test_kategori_kosong_menjadi_unknown(tables):
    doc = by_order(build_review_documents(tables))["o2"]
    assert doc.metadata["categories"] == ["unknown"]
    assert doc.metadata["review_score"] == 1
    assert "Judul ulasan Ruim." in doc.text


def test_id_deterministik_di_setiap_build(tables):
    first = [doc.id for doc in build_review_documents(tables)]
    second = [doc.id for doc in build_review_documents(tables)]
    assert first == second


def test_dokumen_kategori_dengan_fallback_nama_portugis(tables):
    documents = {doc.metadata["category_pt"]: doc for doc in build_category_documents(tables)}
    assert set(documents) == {"bebes", "pc_gamer"}
    assert documents["bebes"].metadata["category"] == "baby"
    assert documents["bebes"].metadata["product_count"] == 2
    assert documents["pc_gamer"].metadata["category"] == "pc_gamer"
