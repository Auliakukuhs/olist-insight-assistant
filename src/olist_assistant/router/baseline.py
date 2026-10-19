"""Baseline router intent: TF-IDF + Logistic Regression.

Baseline ini yang dibandingkan dengan encoder hasil fine-tuning. Bila
fine-tuning belum selesai, model inilah yang dipakai supervisor, dengan
fallback ke LLM ketika probabilitas tertingginya di bawah ambang.
"""

from collections.abc import Sequence

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline

from olist_assistant.router.templates import LABELS

ANALYZERS = {
    "word_1_2": {"analyzer": "word", "ngram_range": (1, 2)},
    "char_2_5": {"analyzer": "char_wb", "ngram_range": (2, 5)},
}


def make_pipeline(analyzer: str, c: float) -> Pipeline:
    return Pipeline(
        [
            ("tfidf", TfidfVectorizer(lowercase=True, sublinear_tf=True, **ANALYZERS[analyzer])),
            ("clf", LogisticRegression(C=c, max_iter=2000, class_weight="balanced")),
        ]
    )


def evaluate(model: Pipeline, texts: Sequence[str], labels: Sequence[str]) -> dict:
    predicted = model.predict(list(texts))
    return {
        "macro_f1": round(f1_score(labels, predicted, average="macro"), 4),
        "per_class": classification_report(
            labels, predicted, labels=list(LABELS), output_dict=True, zero_division=0
        ),
        "confusion_matrix": {
            "labels": list(LABELS),
            "matrix": confusion_matrix(labels, predicted, labels=list(LABELS)).tolist(),
        },
    }
