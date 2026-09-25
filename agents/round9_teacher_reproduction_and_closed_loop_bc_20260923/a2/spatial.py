"""Position-sensitive, leakage-safe inputs for the Round8 independent BC.

The board is represented as per-channel two-dimensional DCT coefficients.  A
4x4 basis is deliberately small enough for per-actor inference, while keeping
absolute position (unlike the Round7 tile-count summary).  The uncompressed
channel tensor is also exposed for contract tests and audit hashes.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from functools import cache
from typing import Any

import numpy as np

try:
    from .common import ACTOR_TOKENS, ANIMALS, CROPS, ITEMS
except ImportError:
    from common import ACTOR_TOKENS, ANIMALS, CROPS, ITEMS

BOARD_SIZE = 10
DCT_SIZE = 4
MAX_ACTORS = 32
KINDS = ("EMPTY", "LOCKED", "WEED", "PLANT", "COOP", "PASTURE")
RESOURCES = (*CROPS, *ANIMALS)
NUMERIC_CHANNELS = (
    "yield",
    "age",
    "mature",
    "watered_today",
    "fertilized_now",
    "fed_today",
    "cared_today",
    "fertilizer_available",
    "consecutive_unwatered",
    "consecutive_unfed",
    "pending_care_bonus",
    "remaining_lifespan",
)
GRID_CHANNELS = (
    *tuple(f"kind:{value}" for value in KINDS),
    *tuple(f"resource:{value}" for value in RESOURCES),
    *NUMERIC_CHANNELS,
)
GRID_WIDTH = 2 * len(GRID_CHANNELS) * DCT_SIZE * DCT_SIZE
ROSTER_WIDTH = MAX_ACTORS * (3 + len(ITEMS)) + MAX_ACTORS * 3
PREFIX_EXTRA_WIDTH = len(ACTOR_TOKENS) + 2 + len(RESOURCES) + 2

FIRST_YIELD_DAY = {
    "WHEAT": 2,
    "CARROT": 2,
    "TOMATO": 8,
    "STRAWBERRY": 10,
    "MELON": 10,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, str | bytes) else ()


@cache
def _dct_basis() -> np.ndarray:
    basis = np.empty((DCT_SIZE, BOARD_SIZE), dtype=np.float32)
    for frequency in range(DCT_SIZE):
        normalizer = math.sqrt(1.0 / BOARD_SIZE) if frequency == 0 else math.sqrt(2.0 / BOARD_SIZE)
        for position in range(BOARD_SIZE):
            basis[frequency, position] = normalizer * math.cos(
                math.pi * (2 * position + 1) * frequency / (2 * BOARD_SIZE)
            )
    return basis


def _tile_channels(tile: Any, day: int, step: int) -> np.ndarray:
    values = np.zeros(len(GRID_CHANNELS), dtype=np.float32)
    tile_map = _mapping(tile)
    if tile == "LOCKED":
        kind = "LOCKED"
    elif tile is None:
        kind = "EMPTY"
    else:
        kind = str(tile_map.get("kind", "EMPTY"))
    if kind in KINDS:
        values[KINDS.index(kind)] = 1.0
    resource = str(tile_map.get("crop", tile_map.get("animal", "")))
    if resource in RESOURCES:
        values[len(KINDS) + RESOURCES.index(resource)] = 1.0
    start = len(KINDS) + len(RESOURCES)
    placed_day = _number(tile_map.get("planted_day", tile_map.get("placed_day", day)), day)
    age = max(0.0, day - placed_day)
    deadline = _number(tile_map.get("max_lifespan_step"), -1)
    mature = resource in ANIMALS or age >= FIRST_YIELD_DAY.get(resource, 10**9)
    numeric = (
        min(1.0, max(0.0, _number(tile_map.get("yield_units"))) / 10.0),
        min(1.0, age / 30.0),
        float(bool(mature)),
        float(bool(tile_map.get("watered_today"))),
        float(_number(tile_map.get("fertilized_until_day"), -1) >= day),
        float(bool(tile_map.get("fed_today"))),
        float(bool(tile_map.get("cared_today"))),
        float(bool(tile_map.get("fertilizer_available"))),
        min(1.0, max(0.0, _number(tile_map.get("consecutive_unwatered"))) / 3.0),
        min(1.0, max(0.0, _number(tile_map.get("consecutive_unfed"))) / 3.0),
        min(1.0, max(0.0, _number(tile_map.get("pending_care_bonus"))) / 10.0),
        min(1.0, max(0.0, deadline - step) / 720.0) if deadline >= 0 else 1.0,
    )
    values[start:] = numeric
    return values


def raw_grid_tensor(observation: Mapping[str, Any]) -> np.ndarray:
    """Return [self/other, channel, y, x] without destroying spatial layout."""
    seat = int(_number(observation.get("player")))
    farms = _sequence(observation.get("farms"))
    day = int(_number(observation.get("day")))
    step = day * 24 + int(_number(observation.get("hour")))
    result = np.zeros((2, len(GRID_CHANNELS), BOARD_SIZE, BOARD_SIZE), dtype=np.float32)
    for role, farm_index in enumerate((seat, 1 - seat)):
        farm = _mapping(farms[farm_index]) if 0 <= farm_index < len(farms) else {}
        rows = _sequence(farm.get("tiles"))
        for y in range(BOARD_SIZE):
            row = _sequence(rows[y]) if y < len(rows) else ()
            for x in range(BOARD_SIZE):
                tile = row[x] if x < len(row) else "LOCKED"
                result[role, :, y, x] = _tile_channels(tile, day, step)
    return result


def grid_features(observation: Mapping[str, Any]) -> np.ndarray:
    tensor = raw_grid_tensor(observation)
    basis = _dct_basis()
    compressed = np.einsum("uy,rcyx,vx->rcuv", basis, tensor, basis, optimize=True)
    return compressed.reshape(-1).astype(np.float32)


def _positions(farm: Mapping[str, Any]) -> list[Sequence[Any]]:
    return [_sequence(farm.get("farmer")), *_sequence(farm.get("hands"))]


def roster_features(observation: Mapping[str, Any]) -> np.ndarray:
    """Keep every actor slot up to the engine-safe cap, with self inventories."""
    seat = int(_number(observation.get("player")))
    farms = _sequence(observation.get("farms"))
    private = _mapping(observation.get("private"))
    inventories = _sequence(private.get("inventories"))
    output: list[float] = []
    for role, farm_index in enumerate((seat, 1 - seat)):
        farm = _mapping(farms[farm_index]) if 0 <= farm_index < len(farms) else {}
        positions = _positions(farm)
        if len(positions) > MAX_ACTORS:
            raise ValueError(f"actor count {len(positions)} exceeds encoded cap {MAX_ACTORS}")
        for index in range(MAX_ACTORS):
            present = index < len(positions) and len(positions[index]) >= 2
            x = _number(positions[index][0]) if present else 0.0
            y = _number(positions[index][1]) if present else 0.0
            output.extend((float(present), x / 9.0, y / 9.0))
            if role == 0:
                inventory = _mapping(inventories[index]) if index < len(inventories) else {}
                output.extend(min(1.0, max(0.0, _number(inventory.get(item))) / 100.0) for item in ITEMS)
    result = np.asarray(output, dtype=np.float32)
    if result.size != ROSTER_WIDTH:
        raise ValueError(f"roster feature mismatch: {result.size} != {ROSTER_WIDTH}")
    return result


def make_prefix_entry(
    token: str,
    quantity: int,
    target: Mapping[str, Any] | None,
    expected_effect: bool,
    resolved_action: Sequence[Any] | None,
) -> dict[str, Any]:
    return {
        "token": str(token),
        "quantity": max(1, int(quantity)),
        "target": dict(target or {}),
        "expected_effect": bool(expected_effect),
        "resolved_action": list(resolved_action or ["PASS"]),
    }


def _prefix_token(entry: Any) -> str:
    return str(entry.get("token", "PASS")) if isinstance(entry, Mapping) else str(entry)


def prefix_token_features(entries: list[Any]) -> np.ndarray:
    counts = np.zeros(len(ACTOR_TOKENS), dtype=np.float32)
    for entry in entries:
        token = _prefix_token(entry)
        if token in ACTOR_TOKENS:
            counts[ACTOR_TOKENS.index(token)] += 1.0
    if entries:
        counts /= len(entries)
    previous = np.zeros(len(ACTOR_TOKENS), dtype=np.float32)
    if entries:
        token = _prefix_token(entries[-1])
        if token in ACTOR_TOKENS:
            previous[ACTOR_TOKENS.index(token)] = 1.0
    return np.concatenate((counts, previous))


def prefix_extra_features(entries: list[Any]) -> np.ndarray:
    quantities = np.zeros(len(ACTOR_TOKENS), dtype=np.float32)
    last_x = last_y = 0.0
    resource = np.zeros(len(RESOURCES), dtype=np.float32)
    expected = resolved_nonpass = 0.0
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        token = _prefix_token(entry)
        if token in ACTOR_TOKENS:
            quantities[ACTOR_TOKENS.index(token)] += min(100.0, _number(entry.get("quantity"))) / 100.0
        target = _mapping(entry.get("target"))
        position = _sequence(target.get("position"))
        if len(position) >= 2:
            last_x, last_y = _number(position[0]) / 9.0, _number(position[1]) / 9.0
        value = str(target.get("resource", ""))
        if value in RESOURCES:
            resource[RESOURCES.index(value)] = 1.0
        expected = float(bool(entry.get("expected_effect")))
        resolved = _sequence(entry.get("resolved_action"))
        resolved_nonpass = float(bool(resolved and resolved[0] != "PASS"))
    result = np.concatenate(
        (
            quantities,
            np.asarray((last_x, last_y), dtype=np.float32),
            resource,
            np.asarray((expected, resolved_nonpass), dtype=np.float32),
        )
    )
    if result.size != PREFIX_EXTRA_WIDTH:
        raise ValueError(f"prefix feature mismatch: {result.size} != {PREFIX_EXTRA_WIDTH}")
    return result


def shared_spatial_features(observation: Mapping[str, Any]) -> np.ndarray:
    return np.concatenate((grid_features(observation), roster_features(observation)))


def schema() -> dict[str, Any]:
    return {
        "board_shape": [2, len(GRID_CHANNELS), BOARD_SIZE, BOARD_SIZE],
        "roles": ["self", "other_public"],
        "grid_channels": list(GRID_CHANNELS),
        "compression": f"orthonormal DCT, first {DCT_SIZE}x{DCT_SIZE} coefficients per channel",
        "grid_width": GRID_WIDTH,
        "max_actor_slots": MAX_ACTORS,
        "self_actor_fields": ["present", "x", "y", *[f"inventory:{item}" for item in ITEMS]],
        "other_actor_fields": ["present", "x", "y"],
        "roster_width": ROSTER_WIDTH,
        "prefix_extra_width": PREFIX_EXTRA_WIDTH,
        "runtime_private_inputs": "self private only; opponent private, future shop/action, and result are absent",
    }
