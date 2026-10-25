"""Antarmuka Streamlit OLIST Insight Assistant.

Halaman ini tidak memanggil LLM, Qdrant, atau SQLite secara langsung. Semuanya
lewat REST API di AWS, jadi kunci OpenAI dan Qdrant tidak pernah ada di sini.
Yang disimpan di st.secrets hanya alamat API dan API key aplikasi.
"""

import uuid

import requests
import streamlit as st

API_URL = st.secrets["API_URL"].rstrip("/")
API_KEY = st.secrets.get("API_ACCESS_KEY")
TIMEOUT_SECONDS = 90

LABEL_PERAN = {"customer": "Customer", "seller": "Seller", "admin": "Admin internal"}
LABEL_AGENT = {"supervisor": "Supervisor", "rag": "Agent RAG", "sql": "Agent SQL"}
CONTOH = {
    "customer": [
        "Apa keluhan pembeli produk bayi?",
        "Berapa rata-rata ongkir untuk pembeli di RJ?",
        "Kategori apa yang paling sering terlambat, dan apa kata pembelinya?",
    ],
    "seller": [
        "Berapa total penjualan toko saya per tahun?",
        "Apa yang perlu ditingkatkan untuk produk bayi, dan berapa rata-rata harganya?",
        "Kategori apa yang paling laris di SP?",
    ],
    "admin": [
        "Siapa 5 seller dengan penjualan tertinggi di Sao Paulo?",
        "Seller mana di RJ yang persen terlambatnya paling tinggi, minimal 50 pesanan?",
        "Apa keluhan utama pembeli furniture?",
    ],
}


# ---------- Pemanggilan API ----------


def api(method: str, path: str, **kwargs) -> tuple[dict | None, str | None]:
    """Panggil API. Hasilnya (data, None) bila berhasil, (None, pesan) bila gagal."""
    headers = {}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    if st.session_state.get("token"):
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    try:
        response = requests.request(
            method, f"{API_URL}{path}", headers=headers, timeout=TIMEOUT_SECONDS, **kwargs
        )
    except requests.Timeout:
        return None, "API tidak menjawab dalam 90 detik. Coba lagi sebentar lagi."
    except requests.ConnectionError:
        return None, "Tidak bisa terhubung ke API. Periksa API_URL di secrets."
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.ok:
        return body, None
    detail = body.get("detail", "") if isinstance(body, dict) else ""
    if response.status_code == 401 and path != "/auth/login":
        # Token kedaluwarsa atau API key salah. Paksa login ulang.
        st.session_state.token = None
        return None, "Sesi login berakhir. Silakan login ulang."
    return None, f"{detail or 'API menolak permintaan'} (kode {response.status_code})"


# ---------- Status sesi ----------


def init_state() -> None:
    defaults = {
        "token": None,
        "pengguna": None,
        "session_id": uuid.uuid4().hex,
        "messages": [],
        "total_token": 0,
        "total_biaya": 0.0,
        "pending": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def percakapan_baru() -> None:
    """session_id baru berarti riwayat baru di server."""
    st.session_state.session_id = uuid.uuid4().hex
    st.session_state.messages = []
    st.session_state.total_token = 0
    st.session_state.total_biaya = 0.0


def logout() -> None:
    st.session_state.token = None
    st.session_state.pengguna = None
    percakapan_baru()


# ---------- Halaman login ----------


def proses_login() -> None:
    """Dipanggil tombol Masuk sebelum halaman digambar ulang, jadi tidak perlu st.rerun."""
    data, error = api(
        "POST",
        "/auth/login",
        json={
            "username": st.session_state.login_username,
            "password": st.session_state.login_password,
        },
    )
    st.session_state.login_error = error
    if error:
        return
    st.session_state.token = data["token"]
    st.session_state.pengguna = data["pengguna"]
    percakapan_baru()


def halaman_login() -> None:
    st.title("OLIST Insight Assistant")
    st.caption("Chatbot multi-agent untuk data e-commerce OLIST, Brasil 2016 sampai 2018.")
    with st.form("login"):
        st.text_input("Username", key="login_username")
        st.text_input("Password", type="password", key="login_password")
        st.form_submit_button("Masuk", type="primary", on_click=proses_login)
    if st.session_state.get("login_error"):
        st.error(st.session_state.login_error)
    st.info(
        "Ada tiga peran. Customer bertanya ulasan dan data pasar, seller juga melihat "
        "data tokonya sendiri, admin melihat semua termasuk performa seluruh seller."
    )


# ---------- Tampilan satu jawaban ----------


def detail_proses(proses: dict) -> None:
    """Panel di bawah jawaban, berisi token, biaya, lama, langkah, dan tool."""
    with st.expander("Detail proses"):
        kolom = st.columns(4)
        kolom[0].metric("Token input", f"{proses['token_input']:,}")
        kolom[1].metric("Token output", f"{proses['token_output']:,}")
        kolom[2].metric("Biaya", f"${proses['biaya_usd']:.4f}")
        kolom[3].metric("Lama", f"{proses['durasi_ms'] / 1000:.1f} detik")
        if proses.get("alasan"):
            st.markdown(f"**Alasan rute.** {proses['alasan']}")
        st.dataframe(
            [
                {
                    "Langkah": s["nama"],
                    "Lama (ms)": s["durasi_ms"],
                    "Token input": s["token_input"],
                    "Token output": s["token_output"],
                }
                for s in proses["langkah"]
            ],
            hide_index=True,
            width="stretch",
        )
        if proses["tools"]:
            st.markdown("**Tool yang dipanggil.** " + ", ".join(f"`{t}`" for t in proses["tools"]))
        st.caption(
            f"Model {proses['model']}. Biaya dihitung dari harga per 1 juta token, "
            "embedding query ke Qdrant tidak ikut dihitung."
        )


def tampilkan_jawaban(pesan: dict) -> None:
    st.markdown(pesan["content"])
    data = pesan.get("data")
    if not data:
        return
    proses = data.get("proses")
    if proses:
        st.caption(
            "Ditangani oleh "
            + ", ".join(LABEL_AGENT[a] for a in proses["agent"])
            + f" · rute {data['route']}"
        )
    if data.get("table"):
        st.dataframe(data["table"], hide_index=True, width="stretch")
    sources = data.get("sources") or []
    reviews = [s for s in sources if s["kind"] != "sql"]
    queries = [s for s in sources if s["kind"] == "sql"]
    if reviews:
        with st.expander(f"Sumber ulasan, {len(reviews)} dokumen"):
            for s in reviews:
                st.markdown(f"**{s['kind']}** `{s['id'][:12]}`")
                if s.get("snippet"):
                    st.caption(s["snippet"])
    if queries:
        with st.expander("Query SQL yang dijalankan"):
            for s in queries:
                st.code(s.get("snippet") or "", language="sql")
    if proses:
        detail_proses(proses)
    if data.get("trace_id"):
        # Nilai 1 berarti jempol naik, 0 jempol turun. Disimpan ke Langfuse lewat API.
        st.feedback(
            "thumbs",
            key=f"umpan-{data['trace_id']}",
            on_change=kirim_umpan_balik,
            args=(data["trace_id"],),
        )


def kirim_umpan_balik(trace_id: str) -> None:
    nilai = st.session_state.get(f"umpan-{trace_id}")
    if nilai is None:
        return
    _, error = api("POST", "/feedback", json={"trace_id": trace_id, "suka": nilai == 1})
    if error:
        st.toast(f"Umpan balik belum tercatat. {error}")
    else:
        st.toast("Terima kasih, umpan balik tercatat.")


# ---------- Halaman chat ----------


def kirim(pertanyaan: str) -> None:
    st.session_state.messages.append({"role": "user", "content": pertanyaan})
    with st.chat_message("user"):
        st.markdown(pertanyaan)
    with st.chat_message("assistant"):
        with st.spinner("Supervisor sedang memilih agent..."):
            data, error = api(
                "POST",
                "/chat",
                json={"message": pertanyaan, "session_id": st.session_state.session_id},
            )
        if error:
            st.error(error)
            st.session_state.messages.pop()
            return
        pesan = {"role": "assistant", "content": data["answer"], "data": data}
        tampilkan_jawaban(pesan)
    st.session_state.messages.append(pesan)
    if data.get("proses"):
        st.session_state.total_token += (
            data["proses"]["token_input"] + data["proses"]["token_output"]
        )
        st.session_state.total_biaya += data["proses"]["biaya_usd"]


def halaman_chat() -> None:
    for pesan in st.session_state.messages:
        with st.chat_message(pesan["role"]):
            if pesan["role"] == "assistant":
                tampilkan_jawaban(pesan)
            else:
                st.markdown(pesan["content"])
    pertanyaan = st.chat_input("Tulis pertanyaan tentang data OLIST")
    if st.session_state.pending:
        pertanyaan, st.session_state.pending = st.session_state.pending, None
    if pertanyaan:
        kirim(pertanyaan)


# ---------- Sidebar dan alur utama ----------


def sidebar() -> None:
    pengguna = st.session_state.pengguna
    with st.sidebar:
        st.markdown(f"**{pengguna['username']}** · {LABEL_PERAN[pengguna['peran']]}")
        kolom = st.columns(2)
        kolom[0].button("Percakapan baru", on_click=percakapan_baru, width="stretch")
        kolom[1].button("Logout", on_click=logout, width="stretch")
        st.subheader("Coba tanyakan")
        for i, contoh in enumerate(CONTOH[pengguna["peran"]]):
            st.button(
                contoh,
                key=f"contoh-{i}",
                width="stretch",
                on_click=lambda c=contoh: st.session_state.update(pending=c),
            )
        st.subheader("Pemakaian sesi ini")
        st.metric("Total token", f"{st.session_state.total_token:,}")
        st.caption(f"Biaya sekitar ${st.session_state.total_biaya:.4f}")


def main() -> None:
    st.set_page_config(page_title="OLIST Insight Assistant", layout="wide")
    init_state()
    if not st.session_state.token:
        halaman_login()
        return
    halaman_chat()
    # Sidebar digambar terakhir supaya total token sudah termasuk jawaban terbaru.
    sidebar()


main()
