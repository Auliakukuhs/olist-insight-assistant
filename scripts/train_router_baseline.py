"""Latih baseline router TF-IDF + Logistic Regression dan simpan hasilnya.

Hiperparameter dipilih memakai split val. Split test hanya dipakai sekali di
akhir, untuk angka yang dilaporkan.

Contoh:
    uv run --group router python scripts/train_router_baseline.py
"""

import csv
import itertools
import json
from pathlib import Path

import joblib

from olist_assistant.router.baseline import ANALYZERS, evaluate, make_pipeline
from olist_assistant.router.dataset import build_dataset

DATASET = Path("data/router/dataset.csv")
REPORT = Path("reports/router_baseline.json")
MODEL = Path("artifacts/router_baseline.joblib")


def main() -> None:
    examples = build_dataset()
    DATASET.parent.mkdir(parents=True, exist_ok=True)
    with DATASET.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["text", "label", "template_id", "split"])
        writer.writerows((e.text, e.label, e.template_id, e.split) for e in examples)

    def part(name):
        rows = [e for e in examples if e.split == name]
        return [e.text for e in rows], [e.label for e in rows]

    (x_train, y_train), (x_val, y_val), (x_test, y_test) = map(part, ("train", "val", "test"))
    print(f"train {len(x_train)}, val {len(x_val)}, test {len(x_test)}")

    search = []
    for analyzer, c in itertools.product(ANALYZERS, (0.3, 1.0, 3.0, 10.0)):
        model = make_pipeline(analyzer, c).fit(x_train, y_train)
        score = evaluate(model, x_val, y_val)["macro_f1"]
        search.append({"analyzer": analyzer, "C": c, "val_macro_f1": score})
        print(f"{analyzer:9s} C={c:<5} val macro-F1 {score}")

    best = max(search, key=lambda r: r["val_macro_f1"])
    model = make_pipeline(best["analyzer"], best["C"]).fit(x_train, y_train)
    test = evaluate(model, x_test, y_test)
    print(f"terpilih {best}, test macro-F1 {test['macro_f1']}")

    errors = [
        {"text": t, "label": y, "predicted": p}
        for t, y, p in zip(x_test, y_test, model.predict(x_test), strict=True)
        if y != p
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "sizes": {"train": len(x_train), "val": len(x_val), "test": len(x_test)},
                "search": search,
                "selected": best,
                "test": test,
                "test_errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL)
    print(f"laporan {REPORT}, model {MODEL}, {len(errors)} salah di test")


if __name__ == "__main__":
    main()
