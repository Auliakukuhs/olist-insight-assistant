"""Bandingkan empat router pada test split yang sama, lalu simpan laporannya.

Test split berisi kalimat dari templat yang tidak pernah dilihat saat training.
Yang diukur adalah macro-F1, F1 per jalur, latensi per pertanyaan, dan biaya per
1.000 pertanyaan.

- TF-IDF + Logistic Regression, dilatih ulang dengan hiperparameter terpilih
- IndoBERT-lite fine-tuned, ONNX int8 (model yang dipakai container)
- Router LLM (gpt-4o-mini dengan prompt router supervisor)
- Router produksi: ONNX dulu, router LLM bila keyakinan ONNX di bawah 0,8

Contoh:
    uv run python scripts/bandingkan_router.py
"""

import csv
import json
import statistics
import time
from pathlib import Path

from langchain_core.callbacks import get_usage_metadata_callback
from sklearn.metrics import f1_score

from olist_assistant.agents.proses import PRICES_PER_1M
from olist_assistant.agents.supervisor import ONNX_LABELS, llm_classifier, router_classifier
from olist_assistant.config import load_dotenv
from olist_assistant.router.baseline import make_pipeline
from olist_assistant.router.onnx_router import OnnxRouter

DATASET = Path("data/router/dataset.csv")
REPORT = Path("reports/router_perbandingan.json")
LABELS = ["SQL", "RAG", "HYBRID", "OUT_OF_SCOPE"]
# Jalur supervisor ke label dataset. Sapaan dan tanggal dijawab supervisor, jadi
# di dataset router keduanya termasuk OUT_OF_SCOPE.
TO_LABEL = {"sql": "SQL", "rag": "RAG", "hybrid": "HYBRID", "out_of_scope": "OUT_OF_SCOPE"}
TO_LABEL["umum"] = "OUT_OF_SCOPE"


def load() -> tuple[list[dict], list[dict]]:
    rows = list(csv.DictReader(DATASET.open()))
    return [r for r in rows if r["split"] == "train"], [r for r in rows if r["split"] == "test"]


def ukur(nama: str, predict, texts: list[str], labels: list[str], model: str | None = None) -> dict:
    predicted, seconds, tokens_in, tokens_out = [], [], 0, 0
    for text in texts:
        with get_usage_metadata_callback() as usage:
            started = time.perf_counter()
            predicted.append(predict(text))
            seconds.append(time.perf_counter() - started)
        for meta in usage.usage_metadata.values():
            tokens_in += meta.get("input_tokens", 0)
            tokens_out += meta.get("output_tokens", 0)
    price_in, price_out = PRICES_PER_1M.get(model or "", (0.0, 0.0))
    cost = (tokens_in * price_in + tokens_out * price_out) / 1_000_000
    per_class = f1_score(labels, predicted, labels=LABELS, average=None, zero_division=0)
    salah = [
        {"teks": t, "benar": y, "tebakan": p}
        for t, y, p in zip(texts, labels, predicted, strict=True)
        if y != p
    ]
    hasil = {
        "router": nama,
        "macro_f1": round(f1_score(labels, predicted, average="macro", zero_division=0), 3),
        "akurasi": round(
            sum(y == p for y, p in zip(labels, predicted, strict=True)) / len(labels), 3
        ),
        "f1_per_jalur": {label: round(f, 2) for label, f in zip(LABELS, per_class, strict=True)},
        "latensi_ms_p50": round(statistics.median(seconds) * 1000, 1),
        "latensi_ms_p95": round(sorted(seconds)[int(len(seconds) * 0.95) - 1] * 1000, 1),
        "biaya_usd_per_1000": round(cost / len(texts) * 1000, 4),
        "token_input_rata": round(tokens_in / len(texts)),
        "salah": salah,
    }
    print(
        f"{nama:34s} macro-F1 {hasil['macro_f1']:.3f}  akurasi {hasil['akurasi']:.3f}  "
        f"p50 {hasil['latensi_ms_p50']:7.1f} ms  ${hasil['biaya_usd_per_1000']:.4f}/1000"
    )
    return hasil


def main() -> None:
    load_dotenv()
    train, test = load()
    texts, labels = [r["text"] for r in test], [r["label"] for r in test]

    tfidf = make_pipeline("char_2_5", 3.0).fit(
        [r["text"] for r in train], [r["label"] for r in train]
    )
    onnx = OnnxRouter()
    from olist_assistant.agents.rag import default_model

    model = default_model()
    llm = llm_classifier(model)
    produksi = router_classifier(onnx, llm)
    dipakai_llm = []

    def lewat_produksi(text: str) -> str:
        route, by, *_ = produksi(text, [])
        dipakai_llm.append(by.startswith("llm"))
        return TO_LABEL[route]

    hasil = [
        ukur("TF-IDF + Logistic Regression", lambda t: tfidf.predict([t])[0], texts, labels),
        ukur("IndoBERT-lite ONNX int8", lambda t: onnx.predict(t).label, texts, labels),
        ukur("Router LLM", lambda t: TO_LABEL[llm(t, [])[0]], texts, labels, model.model_name),
        ukur("Produksi (ONNX, LLM bila < 0,8)", lewat_produksi, texts, labels, model.model_name),
    ]
    hasil[-1]["porsi_ke_llm"] = round(sum(dipakai_llm) / len(dipakai_llm), 3)
    print(f"Router produksi menyerahkan {sum(dipakai_llm)} dari {len(texts)} pertanyaan ke LLM.")

    REPORT.write_text(
        json.dumps(
            {
                "test_split": {
                    "kalimat": len(texts),
                    "per_jalur": {x: labels.count(x) for x in LABELS},
                },
                "catatan": "Label ONNX dipetakan lewat ONNX_LABELS. Sapaan dihitung OUT_OF_SCOPE.",
                "onnx_labels": ONNX_LABELS,
                "hasil": hasil,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"Laporan: {REPORT}")


if __name__ == "__main__":
    main()
