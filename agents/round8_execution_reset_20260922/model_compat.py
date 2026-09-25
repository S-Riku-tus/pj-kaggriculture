"""Install a SavedMLP implementation that supports preregistered two-hidden-layer models."""

from __future__ import annotations

import json
from pathlib import Path

import common
import numpy as np


class SavedMLP:
    """ReLU MLP loaded from explicit, pickle-free NPZ arrays."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"required learned model is missing: {self.path}")
        with np.load(self.path, allow_pickle=False) as data:
            self.mean = data["mean"].astype(np.float32)
            self.scale = data["scale"].astype(np.float32)
            self.classes = [str(value) for value in data["classes"]] if "classes" in data else []
            self.layers = []
            index = 1
            while f"w{index}" in data and f"b{index}" in data:
                self.layers.append(
                    (
                        data[f"w{index}"].astype(np.float32),
                        data[f"b{index}"].astype(np.float32),
                    )
                )
                index += 1
        if len(self.layers) not in {2, 3}:
            raise ValueError(f"unsupported layer count {len(self.layers)} in {self.path}")
        self.metadata_path = self.path.with_suffix(".json")
        self.metadata = (
            json.loads(self.metadata_path.read_text(encoding="utf-8")) if self.metadata_path.is_file() else {}
        )

    def logits(self, features: np.ndarray) -> np.ndarray:
        value = (np.asarray(features, dtype=np.float32) - self.mean) / self.scale
        for index, (weight, bias) in enumerate(self.layers):
            value = value @ weight + bias
            if index < len(self.layers) - 1:
                value = np.maximum(0.0, value)
        return value

    def probabilities(self, features: np.ndarray) -> np.ndarray:
        logits = self.logits(features)
        logits -= np.max(logits)
        exp = np.exp(np.clip(logits, -30.0, 30.0))
        return exp / max(float(exp.sum()), 1e-9)


common.SavedMLP = SavedMLP
