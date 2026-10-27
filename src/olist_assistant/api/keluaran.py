"""Pembersihan teks keluaran sebelum dikirim ke klien (audit 25 Okt, S07).

Jawaban LLM dan potongan ulasan dirender sebagai Markdown di Streamlit. Gambar
Markdown ke URL luar akan diambil browser pengguna, jadi bisa dipakai membocorkan
isi percakapan lewat alamat gambar bila model terbujuk menulisnya. Jawaban
chatbot ini tidak pernah butuh gambar, tautan, atau HTML.
"""

import re

GAMBAR = re.compile(r"!\[[^\]]*\]\([^)]*\)")
TAUTAN = re.compile(r"\[([^\]]*)\]\(\s*(?:[a-z][a-z0-9+.-]*:|//|www\.)[^)]*\)", re.IGNORECASE)
TAG_HTML = re.compile(r"</?[a-zA-Z][^>]*>")


def bersihkan(text: str) -> str:
    """Buang gambar dan tag HTML, ubah tautan menjadi teksnya saja."""
    text = GAMBAR.sub("", text)
    text = TAUTAN.sub(r"\1", text)
    return TAG_HTML.sub("", text)
