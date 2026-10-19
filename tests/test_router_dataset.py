from collections import Counter, defaultdict

from olist_assistant.router.dataset import build_dataset
from olist_assistant.router.templates import LABELS, TEMPLATES


def test_tiap_templat_hanya_di_satu_split():
    splits = defaultdict(set)
    for e in build_dataset():
        splits[e.template_id].add(e.split)
    assert all(len(s) == 1 for s in splits.values())


def test_tiap_label_ada_di_tiap_split():
    seen = {(e.label, e.split) for e in build_dataset()}
    assert {(label, s) for label in LABELS for s in ("train", "val", "test")} <= seen


def test_deterministik_dengan_seed_sama():
    assert build_dataset(seed=7) == build_dataset(seed=7)


def test_tidak_ada_kalimat_kembar_dalam_satu_templat():
    counts = Counter((e.template_id, e.text) for e in build_dataset())
    assert max(counts.values()) == 1


def test_ukuran_dataset_sesuai_rencana():
    examples = build_dataset()
    templates = sum(len(t) for t in TEMPLATES.values())
    assert 400 <= len(examples) <= templates * 6
