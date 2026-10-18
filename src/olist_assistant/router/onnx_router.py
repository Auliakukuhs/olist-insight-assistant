"""Router intent hasil fine-tuning, dijalankan dengan onnxruntime di CPU.

Container API cukup memasang onnxruntime dan tokenizers. PyTorch dan
transformers hanya dibutuhkan saat training.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

# Di repo, model ada di models/router. Di container, path diatur lewat
# ROUTER_MODEL_DIR karena paket terpasang di site-packages.
MODEL_DIR = Path(
    os.getenv("ROUTER_MODEL_DIR", Path(__file__).resolve().parents[3] / "models" / "router")
)
MAX_LENGTH = 64


@dataclass(frozen=True)
class Prediction:
    label: str
    confidence: float


class OnnxRouter:
    def __init__(self, model_dir: Path = MODEL_DIR):
        self.labels = json.loads((model_dir / "labels.json").read_text())
        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(MAX_LENGTH)
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(model_dir / "router.onnx"), options, providers=["CPUExecutionProvider"]
        )

    def predict(self, text: str) -> Prediction:
        encoding = self.tokenizer.encode(text)
        feeds = {
            "input_ids": np.array([encoding.ids], dtype=np.int64),
            "attention_mask": np.array([encoding.attention_mask], dtype=np.int64),
            "token_type_ids": np.array([encoding.type_ids], dtype=np.int64),
        }
        logits = self.session.run(["logits"], feeds)[0][0]
        probs = np.exp(logits - logits.max())
        probs /= probs.sum()
        best = int(probs.argmax())
        return Prediction(self.labels[best], float(probs[best]))
