import subprocess
import sys
import time

import pytest

from olist_assistant.router.onnx_router import MODEL_DIR, OnnxRouter
from olist_assistant.router.templates import LABELS

pytestmark = pytest.mark.skipif(
    not (MODEL_DIR / "router.onnx").exists(), reason="model router belum dilatih"
)


@pytest.fixture(scope="module")
def router():
    return OnnxRouter()


def test_label_dan_probabilitas_valid(router):
    prediction = router.predict("Berapa rata-rata ongkir kategori mainan?")
    assert prediction.label in LABELS
    assert 0.0 < prediction.confidence <= 1.0


def test_deterministik(router):
    text = "Apa keluhan pembeli tentang parfum?"
    assert router.predict(text) == router.predict(text)


def test_kalimat_panjang_dipotong_tanpa_error(router):
    assert router.predict("kategori " * 500).label in LABELS


def test_cukup_cepat_di_cpu(router):
    router.predict("pemanasan")
    started = time.perf_counter()
    for _ in range(20):
        router.predict("Kategori apa yang paling laris tahun 2017?")
    assert (time.perf_counter() - started) / 20 < 0.2


def test_tidak_menarik_torch_atau_transformers():
    code = (
        "import sys, olist_assistant.router.onnx_router; "
        "print('torch' in sys.modules or 'transformers' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
