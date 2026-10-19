"""Fine-tune IndoBERT-lite sebagai router intent, lalu ekspor ke ONNX int8.

Langkah:
1. Dataset dan split per templat sama persis dengan baseline TF-IDF + LR.
2. Loop training PyTorch manual (AdamW), mengikuti hands-on deck
   "Fine Tuning Transformers & BERT". Kombinasi learning rate dan epoch
   dipilih memakai split val.
3. Split test dipakai sekali di akhir untuk angka yang dilaporkan.
4. Model terbaik diekspor ke ONNX lalu dikuantisasi dinamis int8, supaya
   container cukup memakai onnxruntime tanpa PyTorch.
5. Semua parameter, metrik per epoch, dan artefak dicatat di MLflow (backend SQLite mlflow.db).

Contoh:
    uv run --group train python scripts/train_router_finetune.py
"""

import copy
import json
import random
import time
from pathlib import Path

import mlflow
import numpy as np
import onnxruntime as ort
import torch
from onnxruntime.quantization import QuantType, quantize_dynamic
from onnxruntime.quantization.shape_inference import quant_pre_process
from sklearn.metrics import f1_score
from transformers import AutoModelForSequenceClassification, BertTokenizerFast

from olist_assistant.router.dataset import build_dataset
from olist_assistant.router.templates import LABELS

BASE_MODEL = "indobenchmark/indobert-lite-base-p1"
MAX_LENGTH = 64
BATCH_SIZE = 16
LEARNING_RATES = (2e-5, 5e-5)
MAX_EPOCHS = 12
SEED = 42

OUT_DIR = Path("models/router")
REPORT = Path("reports/router_finetune.json")
LABEL2ID = {label: i for i, label in enumerate(LABELS)}


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def device() -> torch.device:
    return torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def encode(tokenizer, texts):
    return tokenizer(
        texts, padding=True, truncation=True, max_length=MAX_LENGTH, return_tensors="pt"
    )


def predict(model, tokenizer, texts, dev) -> list[int]:
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), 64):
            batch = {k: v.to(dev) for k, v in encode(tokenizer, texts[i : i + 64]).items()}
            out.extend(model(**batch).logits.argmax(-1).cpu().tolist())
    return out


def macro_f1(model, tokenizer, texts, labels, dev) -> float:
    predicted = predict(model, tokenizer, texts, dev)
    return round(f1_score([LABEL2ID[y] for y in labels], predicted, average="macro"), 4)


def train_one(lr, tokenizer, data, dev):
    """Latih satu learning rate, kembalikan model di epoch val terbaik."""
    set_seed(SEED)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL,
        num_labels=len(LABELS),
        id2label=dict(enumerate(LABELS)),
        label2id=LABEL2ID,
    ).to(dev)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    (x_train, y_train), (x_val, y_val) = data["train"], data["val"]
    order = list(range(len(x_train)))
    best = {"val_macro_f1": -1.0}
    history = []
    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        random.shuffle(order)
        total = 0.0
        for i in range(0, len(order), BATCH_SIZE):
            idx = order[i : i + BATCH_SIZE]
            batch = encode(tokenizer, [x_train[j] for j in idx])
            batch = {k: v.to(dev) for k, v in batch.items()}
            target = torch.tensor([LABEL2ID[y_train[j]] for j in idx], device=dev)
            loss = model(**batch, labels=target).loss
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total += loss.item() * len(idx)
        val = macro_f1(model, tokenizer, x_val, y_val, dev)
        row = {"epoch": epoch, "train_loss": round(total / len(order), 4), "val_macro_f1": val}
        history.append(row)
        mlflow.log_metrics(
            {f"lr{lr}_train_loss": row["train_loss"], f"lr{lr}_val_macro_f1": val}, step=epoch
        )
        print(f"  lr={lr} epoch {epoch:2d} loss {row['train_loss']:.4f} val macro-F1 {val}")
        if val > best["val_macro_f1"]:
            best = {
                "lr": lr,
                "epoch": epoch,
                "val_macro_f1": val,
                "state": copy.deepcopy(
                    {k: v.detach().cpu() for k, v in model.state_dict().items()}
                ),
            }
    return best, history


def export_onnx(model, tokenizer) -> dict:
    model = model.to("cpu").eval()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sample = encode(tokenizer, ["contoh pertanyaan"])
    fp32 = OUT_DIR / "router.fp32.onnx"
    names = ["input_ids", "attention_mask", "token_type_ids"]
    torch.onnx.export(
        model,
        tuple(sample[n] for n in names),
        str(fp32),
        input_names=names,
        output_names=["logits"],
        dynamic_axes={n: {0: "batch", 1: "seq"} for n in names} | {"logits": {0: "batch"}},
        opset_version=17,
        dynamo=False,
    )
    # Pra-proses (optimasi graph dan shape inference) sebelum kuantisasi.
    # Tanpa ini, bobot ALBERT yang dipakai bersama banyak lapis tetap tersimpan
    # dua kali, versi int8 dan versi fp32, sehingga ukuran hampir tidak turun.
    pre = OUT_DIR / "router.pre.onnx"
    quant_pre_process(str(fp32), str(pre), skip_symbolic_shape=True)
    int8 = OUT_DIR / "router.onnx"
    quantize_dynamic(str(pre), str(int8), weight_type=QuantType.QInt8)
    pre.unlink()
    sizes = {
        "fp32_mb": round(fp32.stat().st_size / 1e6, 1),
        "int8_mb": round(int8.stat().st_size / 1e6, 1),
    }
    fp32.unlink()
    tokenizer.backend_tokenizer.save(str(OUT_DIR / "tokenizer.json"))
    (OUT_DIR / "labels.json").write_text(json.dumps(list(LABELS)))
    return sizes


def onnx_predict(texts, tokenizer) -> tuple[list[int], float]:
    session = ort.InferenceSession(str(OUT_DIR / "router.onnx"), providers=["CPUExecutionProvider"])
    out, started = [], time.perf_counter()
    for text in texts:
        enc = tokenizer([text], truncation=True, max_length=MAX_LENGTH, return_tensors="np")
        feeds = {
            k: enc[k].astype(np.int64) for k in ("input_ids", "attention_mask", "token_type_ids")
        }
        out.append(int(session.run(["logits"], feeds)[0].argmax(-1)[0]))
    return out, (time.perf_counter() - started) / len(texts) * 1000


def main() -> None:
    examples = build_dataset()
    data = {
        split: (
            [e.text for e in examples if e.split == split],
            [e.label for e in examples if e.split == split],
        )
        for split in ("train", "val", "test")
    }
    dev = device()
    tokenizer = BertTokenizerFast.from_pretrained(BASE_MODEL)
    sizes = {split: len(texts) for split, (texts, _) in data.items()}
    print(f"device {dev}, ukuran split {sizes}")

    mlflow.set_tracking_uri("sqlite:///mlflow.db")
    mlflow.set_experiment("router-intent")
    with mlflow.start_run(run_name="indobert-lite-finetune"):
        mlflow.log_params(
            {
                "base_model": BASE_MODEL,
                "max_length": MAX_LENGTH,
                "batch_size": BATCH_SIZE,
                "learning_rates": str(LEARNING_RATES),
                "max_epochs": MAX_EPOCHS,
                "seed": SEED,
                "optimizer": "AdamW",
                "split": "per templat",
            }
        )
        runs, histories = [], {}
        for lr in LEARNING_RATES:
            best, history = train_one(lr, tokenizer, data, dev)
            runs.append(best)
            histories[str(lr)] = history
        best = max(runs, key=lambda r: r["val_macro_f1"])
        print(f"terpilih lr={best['lr']} epoch {best['epoch']} val macro-F1 {best['val_macro_f1']}")

        # Attention eager supaya graph ONNX tidak membekukan cabang SDPA saat tracing.
        model = AutoModelForSequenceClassification.from_pretrained(
            BASE_MODEL,
            num_labels=len(LABELS),
            id2label=dict(enumerate(LABELS)),
            label2id=LABEL2ID,
            attn_implementation="eager",
        )

        model.load_state_dict(best["state"])
        x_test, y_test = data["test"]
        torch_pred = predict(model.to(dev), tokenizer, x_test, dev)
        y_ids = [LABEL2ID[y] for y in y_test]
        torch_f1 = round(f1_score(y_ids, torch_pred, average="macro"), 4)

        sizes = export_onnx(model, tokenizer)
        onnx_pred, ms = onnx_predict(x_test, tokenizer)
        onnx_f1 = round(f1_score(y_ids, onnx_pred, average="macro"), 4)
        per_class = f1_score(y_ids, onnx_pred, average=None, labels=list(range(len(LABELS))))
        agreement = round(
            sum(a == b for a, b in zip(torch_pred, onnx_pred, strict=True)) / len(x_test), 4
        )
        errors = [
            {"text": t, "label": y, "predicted": LABELS[p]}
            for t, y, p in zip(x_test, y_test, onnx_pred, strict=True)
            if LABELS[p] != y
        ]
        baseline = json.loads(Path("reports/router_baseline.json").read_text())["test"]["macro_f1"]
        report = {
            "base_model": BASE_MODEL,
            "selected": {k: best[k] for k in ("lr", "epoch", "val_macro_f1")},
            "history": histories,
            "test_macro_f1_torch_fp32": torch_f1,
            "test_macro_f1_onnx_int8": onnx_f1,
            "test_f1_per_class_onnx_int8": {
                name: round(float(v), 4) for name, v in zip(LABELS, per_class, strict=True)
            },
            "baseline_tfidf_lr_test_macro_f1": baseline,
            "torch_vs_onnx_agreement": agreement,
            "onnx_cpu_ms_per_query": round(ms, 2),
            "model_size": sizes,
            "test_errors": errors,
        }
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        mlflow.log_metrics(
            {
                "test_macro_f1_torch_fp32": torch_f1,
                "test_macro_f1_onnx_int8": onnx_f1,
                "onnx_cpu_ms_per_query": ms,
                "onnx_int8_mb": sizes["int8_mb"],
            }
        )
        mlflow.log_artifact(str(REPORT))
        print(
            json.dumps(
                {k: v for k, v in report.items() if k not in ("history", "test_errors")}, indent=2
            )
        )


if __name__ == "__main__":
    main()
