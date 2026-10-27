"""Antarmuka Streamlit OLIST Insight Assistant.

Halaman ini tidak memanggil LLM, Qdrant, atau SQLite secara langsung. Semuanya
lewat REST API di AWS, jadi kunci OpenAI dan Qdrant tidak pernah ada di sini.
Yang disimpan di st.secrets hanya alamat API dan API key aplikasi.
"""

import uuid

import requests
import streamlit as st
from tabel import bentuk_grafik, data_grafik, ke_csv

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
        # Token kedaluwarsa atau akun dicabut. Bersihkan seluruh sesi, termasuk
        # riwayat, lalu langsung kembali ke halaman login (audit 25 Okt, S08).
        keluar("Sesi login berakhir. Silakan login ulang.")
        st.rerun()
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


def keluar(pesan: str | None = None) -> None:
    """Hapus semua yang melekat pada login, supaya tidak tersisa di komputer bersama."""
    st.session_state.token = None
    st.session_state.pengguna = None
    st.session_state.pending = None
    st.session_state.login_error = pesan
    percakapan_baru()


def logout() -> None:
    keluar()


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
            + (" · dari cache" if proses.get("cache") else "")
        )
    if data.get("table"):
        tabel = data["table"]
        st.dataframe(tabel, hide_index=True, width="stretch")
        # Grafik hanya untuk tabel satu label dan satu angka (#62). Tabel lain tetap tabel.
        bentuk = bentuk_grafik(tabel)
        if bentuk:
            gambar = st.line_chart if bentuk["jenis"] == "line" else st.bar_chart
            gambar(data_grafik(tabel, bentuk), x=bentuk["label"], y=bentuk["angka"])
        st.download_button(
            "Unduh CSV",
            ke_csv(tabel),
            file_name=f"olist-{data.get('request_id', 'hasil')[:8]}.csv",
            mime="text/csv",
            key=f"csv-{data.get('request_id', id(pesan))}",
        )
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


NEGARA_BAGIAN = ["Semua", "SP", "RJ", "MG", "RS", "PR", "SC", "BA", "DF", "GO", "ES", "PE", "CE"]


def halaman_cari_produk() -> None:
    """Cari produk dan rekomendasi beralasan (#13), untuk semua peran."""
    st.subheader("Cari produk")
    st.caption(
        "Produk diurutkan dengan skor terbobot dari ulasan pembeli. Data OLIST tidak memuat "
        "nama atau foto produk, jadi produk disebut dengan ID-nya."
    )
    daftar, error = api("GET", "/analytics/kategori", params={"limit": 100, "min_order": 30})
    if error:
        st.error(error)
        return
    kategori = sorted(r["kategori"] for r in daftar["data"])
    with st.form("cari_produk"):
        kolom = st.columns(4)
        pilihan = kolom[0].selectbox(
            "Kategori", kategori, index=kategori.index("toys") if "toys" in kategori else 0
        )
        harga_min = kolom[1].number_input(
            "Harga minimal (BRL)", min_value=0.0, value=0.0, step=10.0
        )
        harga_max = kolom[2].number_input(
            "Harga maksimal (BRL)", min_value=1.0, value=200.0, step=10.0
        )
        negara = kolom[3].selectbox("Negara bagian seller", NEGARA_BAGIAN)
        cari = st.form_submit_button("Cari", type="primary")
    if cari:
        params = {"kategori": pilihan, "harga_min": harga_min, "harga_max": harga_max}
        if negara != "Semua":
            params["negara_bagian_seller"] = negara
        with st.spinner("Mencari produk dan membaca ulasannya..."):
            hasil, error = api("GET", "/rekomendasi", params=params)
        st.session_state.rekomendasi = (hasil, error)
    hasil, error = st.session_state.get("rekomendasi", (None, None))
    if error:
        st.error(error)
    if not hasil:
        return
    if not hasil["produk"]:
        st.info(
            "Tidak ada produk dengan minimal 5 ulasan untuk filter ini. Coba longgarkan filter."
        )
        return
    for urutan, p in enumerate(hasil["produk"], start=1):
        with st.container(border=True):
            st.markdown(
                f"**{urutan}. Produk `{p['product_id'][:12]}`**, kategori {hasil['kategori']}"
            )
            kolom = st.columns(4)
            kolom[0].metric(
                "Skor ulasan",
                f"{p['rata_skor']:.2f}",
                f"{p['jumlah_ulasan']} ulasan",
                delta_color="off",
            )
            kolom[1].metric("Rata-rata harga", f"R$ {p['rata_harga_brl']:.2f}")
            kolom[2].metric("Terlambat", f"{p['persen_terlambat'] or 0:.1f}%")
            kolom[3].metric("Seller di", p["negara_bagian_seller"] or "-")
            st.write(p["alasan"])
            if p["ulasan"]:
                with st.expander(f"Ulasan pendukung, {len(p['ulasan'])}"):
                    for u in p["ulasan"]:
                        st.caption(f"Skor {u['skor']}: {u['cuplikan'] or '(tanpa teks)'}")
    st.caption(hasil["catatan"])


def halaman_pemakaian() -> None:
    """Ringkasan pemakaian dari Langfuse (#64). Tab ini hanya digambar untuk admin,
    dan API tetap menolak peran lain dengan 403."""
    st.subheader("Pemakaian")
    hari = st.select_slider(
        "Rentang", options=[1, 7, 14, 31], value=7, format_func=lambda h: f"{h} hari"
    )
    data, error = api("GET", "/admin/pemakaian", params={"hari": hari})
    if error:
        st.error(error)
        return
    per_hari = data["per_hari"]
    pertanyaan = sum(h["pertanyaan"] for h in per_hari)
    kolom = st.columns(4)
    kolom[0].metric("Pertanyaan", f"{pertanyaan:,}")
    kolom[1].metric("Token", f"{sum(h['token'] for h in per_hari):,}")
    kolom[2].metric("Biaya", f"${sum(h['biaya_usd'] for h in per_hari):.4f}")
    jempol = data["umpan_balik"]
    kolom[3].metric(
        "Umpan balik", f"{jempol['naik']} naik", f"{jempol['turun']} turun", delta_color="off"
    )
    if not per_hari:
        st.info("Belum ada pertanyaan di rentang ini.")
        return
    st.markdown("**Per hari**")
    st.dataframe(
        [
            {
                "Tanggal": h["tanggal"],
                "Pertanyaan": h["pertanyaan"],
                "Token": h["token"],
                "Biaya (USD)": h["biaya_usd"],
                "Latensi p50 (detik)": None
                if h["latensi_p50_ms"] is None
                else round(h["latensi_p50_ms"] / 1000, 1),
                "Latensi p95 (detik)": None
                if h["latensi_p95_ms"] is None
                else round(h["latensi_p95_ms"] / 1000, 1),
            }
            for h in per_hari
        ],
        hide_index=True,
        width="stretch",
    )
    kiri, kanan = st.columns(2)
    kiri.markdown("**Pertanyaan per peran**")
    kiri.dataframe(
        [{"Peran": k, "Pertanyaan": v} for k, v in sorted(data["per_peran"].items())],
        hide_index=True,
        width="stretch",
    )
    kanan.markdown("**Panggilan per agent**")
    kanan.dataframe(
        [
            {"Agent": LABEL_AGENT.get(k, k), "Panggilan": v}
            for k, v in sorted(data["per_agent"].items())
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(
        f"Sumber Langfuse, environment {data['environment']}, "
        f"{data['dari']} sampai {data['sampai']}. "
        "Jawaban dari cache tidak tercatat di Langfuse, jadi tidak ikut dihitung."
    )


def main() -> None:
    st.set_page_config(page_title="OLIST Insight Assistant", layout="wide")
    init_state()
    if not st.session_state.token:
        halaman_login()
        return
    admin = (st.session_state.pengguna or {}).get("peran") == "admin"
    tabs = st.tabs(["Chat", "Cari produk", *(["Pemakaian"] if admin else [])])
    with tabs[0]:
        halaman_chat()
    with tabs[1]:
        halaman_cari_produk()
    if admin:
        with tabs[2]:
            halaman_pemakaian()
    # Sidebar digambar terakhir supaya total token sudah termasuk jawaban terbaru.
    sidebar()


main()
