"""Pure-Python inference for the trained Round5 strategy selector."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

try:
    from .features import FEATURE_NAMES, strategy_features
except ImportError:
    from features import FEATURE_NAMES, strategy_features  # type: ignore


class SkillSelector:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"required Round5 strategy model is missing: {self.path}")
        model = json.loads(self.path.read_text(encoding="utf-8"))
        if model.get("format") != "round5-softmax-skill-selector-v1":
            raise RuntimeError("Round5 strategy model format mismatch")
        if tuple(model.get("feature_names") or ()) != FEATURE_NAMES:
            raise RuntimeError("Round5 strategy feature schema mismatch")
        self.classes = [str(value) for value in model["classes"]]
        self.mean = [float(value) for value in model["mean"]]
        self.scale = [float(value) for value in model["scale"]]
        self.weights = [[float(value) for value in row] for row in model["weights"]]
        self.bias = [float(value) for value in model["bias"]]
        if not (
            len(self.mean) == len(self.scale) == len(FEATURE_NAMES)
            and len(self.weights) == len(FEATURE_NAMES)
            and all(len(row) == len(self.classes) for row in self.weights)
            and len(self.bias) == len(self.classes)
        ):
            raise RuntimeError("Round5 strategy model shape mismatch")
        self.inference_calls = 0

    def scores(self, observation: Mapping[str, Any]) -> dict[str, float]:
        values = strategy_features(observation)
        normalized = [(value - mean) / scale for value, mean, scale in zip(values, self.mean, self.scale, strict=True)]
        logits = [
            self.bias[target] + sum(normalized[index] * self.weights[index][target] for index in range(len(values)))
            for target in range(len(self.classes))
        ]
        maximum = max(logits)
        exponentials = [math.exp(max(-30.0, min(30.0, value - maximum))) for value in logits]
        total = sum(exponentials) or 1.0
        self.inference_calls += 1
        return {label: value / total for label, value in zip(self.classes, exponentials, strict=True)}


__all__ = ["SkillSelector"]
