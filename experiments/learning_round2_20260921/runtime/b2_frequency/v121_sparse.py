"""V121: sparse closed-loop routing over coherent winning continuations.

V120 remains the opening policy through day 12.  Afterwards this policy
chooses a small beam of complete, state-compatible continuation examples only
at information gates.  The selected beam stays fixed between gates so field
execution can adapt to the current observation without changing macro route
on every turn.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MODEL_FORMAT = "v121-sparse-continuation-v1"
OPENING_END = 288
EXPANSION_GATE = 432
DEFAULT_GATES = (288, 360, 432, 480, 576, 648)

BALANCED = 0
MILK = 1
WOOL = 2

ROW_UNIT_COUNT = 0
ROW_SOURCE = 1
ROW_ANIMAL_ROUTE = 2
ROW_EXPANSION = 3
ROW_FEATURES = 4
ROW_ACTION = 5

_MODEL: dict[str, Any] | None = None
_STATE: dict[str, Any] = {}


def _module_dir() -> Path:
    if "__file__" in globals():
        return Path(__file__).resolve().parent
    candidates = (
        Path("/kaggle_simulations/agent"),
        *(Path(entry) for entry in reversed(sys.path) if entry),
        Path.cwd() / "agents" / "v121",
        Path.cwd(),
    )
    return next(
        (
            candidate.resolve()
            for candidate in candidates
            if (candidate / "v120_base.py").is_file()
            or (candidate.parent / "v120" / "main.py").is_file()
        ),
        Path.cwd(),
    )


def _load_base() -> Any:
    module_dir = _module_dir()
    packaged = module_dir / "v120_base.py"
    repository = module_dir.parent / "v120" / "main.py"
    source = packaged if packaged.is_file() else repository
    if not source.is_file():
        raise ImportError(f"cannot load V120 feature runtime: {source}")
    spec = importlib.util.spec_from_file_location("_kaggriculture_v121_v120_base", source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import V120 feature runtime: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base()
FEATURE_LENGTH = base.FEATURE_LENGTH


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _model_paths() -> list[Path]:
    paths: list[Path] = []
    if "__file__" in globals():
        paths.append(Path(__file__).resolve().with_name("model.json.gz"))
    paths.extend(Path(entry) / "model.json.gz" for entry in reversed(sys.path) if entry)
    paths.extend((Path("agents/v121/model.json.gz"), Path("/kaggle_simulations/agent/model.json.gz")))
    return paths


def _load_model() -> dict[str, Any]:
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    for path in _model_paths():
        if not path.is_file():
            continue
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            model = json.load(stream)
        if model.get("format") != MODEL_FORMAT:
            raise RuntimeError("v121 model format mismatch")
        if _integer(model.get("feature_length")) != FEATURE_LENGTH:
            raise RuntimeError("v121 feature schema mismatch")
        _MODEL = model
        return model
    raise FileNotFoundError("v121 model.json.gz was not found")


def reset_runtime_state() -> None:
    """Reset the per-episode sparse-route latch (also used by tests)."""
    _STATE.clear()
    _STATE.update(
        {
            "last_step": -1,
            "animal_route": None,
            "expansion": None,
            "beam": None,
            "last_gate": None,
        }
    )


reset_runtime_state()


def _own_farm(observation: Mapping[str, Any]) -> Mapping[str, Any]:
    player = _integer(observation.get("player"))
    farms = list(observation.get("farms") or [])
    return _mapping(farms[player]) if 0 <= player < len(farms) else {}


def _portfolio(observation: Mapping[str, Any]) -> dict[str, int]:
    counts = {item: 0 for item in (*base.CROPS, *base.ANIMALS)}
    for tile in base._board(_own_farm(observation)):
        data = _mapping(tile)
        crop = str(data.get("crop", ""))
        animal = str(data.get("animal", ""))
        if crop in counts:
            counts[crop] += 1
        if animal in counts:
            counts[animal] += 1
    return counts


def animal_route(observation: Mapping[str, Any]) -> int:
    """Classify the already-built day-12 portfolio; never force a suffix splice."""
    counts = _portfolio(observation)
    if counts["GOOSE"] == 0 and counts["SHEEP"] >= 8:
        return WOOL
    if counts["COW"] >= 9 and counts["SHEEP"] <= 6:
        return MILK
    return BALANCED


def tomato_demand(observation: Mapping[str, Any]) -> int:
    shops = list(_mapping(observation.get("town")).get("unlocked_shops") or [])
    return shops.count("FARMERS_MARKET") + shops.count("PIZZA_SHOP")


def expansion_preconditions(observation: Mapping[str, Any]) -> bool:
    """Require a recoverable, demand-backed fourth-land Tomato continuation."""
    farm = _own_farm(observation)
    counts = _portfolio(observation)
    land = len(set(farm.get("unlocked_quadrants") or []))
    step = _integer(observation.get("step"), 24 * _integer(observation.get("day")))
    if land >= 4 and counts["TOMATO"] >= 8:
        return True
    return (
        step <= 480
        and land == 3
        and _integer(farm.get("money")) >= 20_000
        and tomato_demand(observation) >= 3
        and animal_route(observation) != WOOL
    )


def _compatible_units(rows: Sequence[list[Any]], observation: Mapping[str, Any]) -> list[list[Any]]:
    count = base.unit_count(observation)
    compatible = [row for row in rows if _integer(row[ROW_UNIT_COUNT]) == count]
    return compatible or list(rows)


def _route_pool(rows: Sequence[list[Any]], step: int) -> list[list[Any]]:
    pool = list(rows)
    if step >= OPENING_END and _STATE.get("animal_route") is not None:
        routed = [row for row in pool if _integer(row[ROW_ANIMAL_ROUTE], -1) == _STATE["animal_route"]]
        if routed:
            pool = routed
    if step >= EXPANSION_GATE and _STATE.get("expansion") is not None:
        routed = [row for row in pool if bool(_integer(row[ROW_EXPANSION], -1)) == _STATE["expansion"]]
        if routed:
            pool = routed
    return pool


def _select_beam(
    rows: Sequence[list[Any]],
    query: Sequence[int],
    beam_size: int,
) -> tuple[int, ...]:
    best_by_source: dict[int, int] = {}
    for row in rows:
        source = _integer(row[ROW_SOURCE], -1)
        if source < 0:
            continue
        distance = base.feature_distance(query, row[ROW_FEATURES])
        best_by_source[source] = min(distance, best_by_source.get(source, distance))
    ranked = sorted(best_by_source, key=lambda source: (best_by_source[source], source))
    return tuple(ranked[: max(1, beam_size)])


def _refresh_sparse_state(
    observation: Mapping[str, Any],
    rows: Sequence[list[Any]],
    query: Sequence[int],
    model: Mapping[str, Any],
) -> None:
    step = _integer(observation.get("step"))
    last_step = _integer(_STATE.get("last_step"), -1)
    if step < last_step or (step == 0 and last_step > 0):
        reset_runtime_state()

    if step >= OPENING_END and _STATE.get("animal_route") is None:
        _STATE["animal_route"] = animal_route(observation)
    if step >= EXPANSION_GATE and _STATE.get("expansion") is None:
        _STATE["expansion"] = expansion_preconditions(observation)

    gates = tuple(_integer(value) for value in (model.get("gate_steps") or DEFAULT_GATES))
    needs_gate = step >= OPENING_END and (_STATE.get("beam") is None or step in gates)
    if needs_gate:
        pool = _route_pool(_compatible_units(rows, observation), step)
        beam = _select_beam(pool, query, _integer(model.get("beam_size"), 8))
        if beam:
            _STATE["beam"] = beam
            _STATE["last_gate"] = step
    _STATE["last_step"] = step


def _choose_row(
    observation: Mapping[str, Any],
    rows: Sequence[list[Any]],
    query: Sequence[int],
) -> list[Any]:
    step = _integer(observation.get("step"))
    pool = _route_pool(_compatible_units(rows, observation), step)
    beam = set(_STATE.get("beam") or ())
    if step >= OPENING_END and beam:
        beamed = [row for row in pool if _integer(row[ROW_SOURCE], -1) in beam]
        if beamed:
            pool = beamed
    return min(pool, key=lambda row: base.feature_distance(query, row[ROW_FEATURES]))


def policy_diagnostics() -> dict[str, Any]:
    """Expose only local runtime choices for deterministic tests and audits."""
    return {
        "animal_route": _STATE.get("animal_route"),
        "expansion": _STATE.get("expansion"),
        "beam": list(_STATE.get("beam") or ()),
        "last_gate": _STATE.get("last_gate"),
    }


def agent(observation: Mapping[str, Any], configuration: Any = None) -> dict[str, Any]:
    del configuration
    try:
        step = _integer(observation.get("step"))
        model = _load_model()
        steps = model.get("steps") or []
        rows = list(steps[step] or []) if 0 <= step < len(steps) else []
        if not rows:
            return base._normalize_output({}, observation)
        query = base.feature_vector(observation)
        _refresh_sparse_state(observation, rows, query, model)
        chosen = _choose_row(observation, rows, query)
        return base._normalize_output(chosen[ROW_ACTION], observation)
    except Exception:
        return base._normalize_output({}, observation)


if __name__ == "__main__":
    for line in sys.stdin:
        if line.strip():
            request = json.loads(line)
            result = agent(request.get("observation", request), request.get("configuration"))
            print(json.dumps(result), flush=True)
