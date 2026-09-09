"""Canonical replay accessors and versioned independent-lineage hashes."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

LINEAGE_SCHEMA = "ordered-actors-market-v1"


def observation(replay: dict[str, Any], decision_step: int, seat: int) -> dict[str, Any] | None:
    """Return the observation from which action ``decision_step`` was chosen."""
    steps = replay.get("steps") or []
    if not (0 <= decision_step < len(steps)) or not (0 <= seat < len(steps[decision_step])):
        return None
    value = (steps[decision_step][seat] or {}).get("observation")
    return value if isinstance(value, dict) else None


def action(replay: dict[str, Any], decision_step: int, seat: int) -> dict[str, Any]:
    """Return the action chosen at ``decision_step`` (stored at state t+1)."""
    stored_step = decision_step + 1
    steps = replay.get("steps") or []
    if not (0 <= stored_step < len(steps)) or not (0 <= seat < len(steps[stored_step])):
        return {}
    value = (steps[stored_step][seat] or {}).get("action")
    return value if isinstance(value, dict) else {}


def decision_count(replay: dict[str, Any]) -> int:
    return max(0, len(replay.get("steps") or []) - 1)


def canonical_action(value: dict[str, Any], *, actor_ordered: bool = True) -> str:
    actors = [value.get("farmer") or ["PASS"], *(value.get("hands") or [])]
    if actor_ordered:
        field: Any = [list(row or ["PASS"]) for row in actors]
    else:
        field = sorted(Counter(json.dumps(list(row or ["PASS"]), separators=(",", ":")) for row in actors).items())
    payload = {
        "field": field,
        "market": [list(row) for row in (value.get("market") or [])],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def lineage_hash(replay: dict[str, Any], seat: int, checkpoint: int = 200) -> str:
    digest = hashlib.sha256()
    for step in range(min(checkpoint, decision_count(replay))):
        digest.update(canonical_action(action(replay, step, seat)).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()[:20]


def result_score(ours: float, theirs: float) -> float:
    return 1.0 if ours > theirs else 0.5 if ours == theirs else 0.0


def result_label(score: float) -> str:
    return "win" if score == 1.0 else "draw" if score == 0.5 else "loss"


def resolved_seed(replay: dict[str, Any], requested: int) -> int:
    info = replay.get("info") or {}
    try:
        return int(info.get("seed", requested))
    except (TypeError, ValueError):
        return requested
