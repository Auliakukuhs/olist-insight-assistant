"""Bangun dataset router dari templat, dengan split per templat."""

import random
from dataclasses import dataclass

from olist_assistant.router.templates import (
    CATEGORIES,
    CITIES,
    LABELS,
    PERIODS,
    PREFIXES,
    PRICES,
    STATES,
    TEMPLATES,
)

SPLIT_SHARE = {"train": 0.7, "val": 0.15}


@dataclass(frozen=True)
class Example:
    text: str
    label: str
    template_id: str
    split: str


def _fill(template: str, rng: random.Random) -> str:
    cat, cat2 = rng.sample(CATEGORIES, 2)
    return template.format(
        cat=cat,
        cat2=cat2,
        city=rng.choice(CITIES),
        state=rng.choice(STATES),
        period=rng.choice(PERIODS),
        price=rng.choice(PRICES),
    )


def _assign_splits(template_ids: list[str], rng: random.Random) -> dict[str, str]:
    """Bagi templat satu label ke train, val, test. Tiap split minimal satu templat."""
    ids = template_ids[:]
    rng.shuffle(ids)
    n = len(ids)
    n_val = max(1, round(n * SPLIT_SHARE["val"]))
    n_test = max(1, n - round(n * SPLIT_SHARE["train"]) - n_val)
    n_train = n - n_val - n_test
    return {
        tid: "train" if i < n_train else "val" if i < n_train + n_val else "test"
        for i, tid in enumerate(ids)
    }


def build_dataset(per_template: int = 6, seed: int = 42) -> list[Example]:
    rng = random.Random(seed)
    examples: list[Example] = []
    for label in LABELS:
        ids = [f"{label}-{i:02d}" for i in range(len(TEMPLATES[label]))]
        splits = _assign_splits(ids, rng)
        for tid, template in zip(ids, TEMPLATES[label], strict=True):
            seen: set[str] = set()
            for _ in range(per_template * 3):
                prefix, body = rng.choice(PREFIXES), _fill(template, rng)
                text = prefix + (body[0].lower() + body[1:] if prefix else body)
                if text in seen:
                    continue
                seen.add(text)
                examples.append(Example(text, label, tid, splits[tid]))
                if len(seen) == per_template:
                    break
    return examples
