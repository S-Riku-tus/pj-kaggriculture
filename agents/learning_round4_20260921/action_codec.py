"""Lossless action codec used by training, tests, and audit manifests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def normalize_action(action: Mapping[str, Any], hand_count: int | None = None) -> dict[str, Any]:
    farmer = list(action.get("farmer") or ["PASS"])
    hands = [list(value or ["PASS"]) for value in action.get("hands") or []]
    if hand_count is not None:
        hands = (hands + [["PASS"]] * hand_count)[:hand_count]
    market = [list(value) for value in action.get("market") or []]
    return {"farmer": farmer, "hands": hands, "market": market}


def encode_action(action: Mapping[str, Any]) -> str:
    """Encode every target, quantity, and ordered market slot without bucketing."""
    return json.dumps(normalize_action(action), ensure_ascii=False, separators=(",", ":"))


def decode_action(encoded: str) -> dict[str, Any]:
    value = json.loads(encoded)
    if not isinstance(value, dict):
        raise ValueError("encoded action must decode to an object")
    return normalize_action(value)


__all__ = ["decode_action", "encode_action", "normalize_action"]
