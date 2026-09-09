"""Frozen public-farm signal queries against executable Gold policies."""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluation.replay import (  # noqa: E402
    action,
    canonical_action,
    observation,
)
from scripts.evaluation.runner import _call, _import_module, _run_game  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load_replay(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def _first_tile(farm: dict[str, Any], predicate) -> tuple[int, int, dict[str, Any]] | None:
    for y, row in enumerate(farm.get("tiles") or []):
        for x, tile in enumerate(row or []):
            if isinstance(tile, dict) and predicate(tile):
                return x, y, tile
    return None


def _apply_signal(obs: dict[str, Any], focal_seat: int, treatment: str) -> dict[str, Any] | None:
    mutated = copy.deepcopy(obs)
    farms = list(mutated.get("farms") or [])
    if focal_seat >= len(farms):
        return None
    farm = farms[focal_seat]
    if treatment == "cow_to_sheep_signal_1":
        found = _first_tile(farm, lambda tile: tile.get("animal") == "COW")
        if found is None:
            return None
        _, _, tile = found
        tile["animal"] = "SHEEP"
        return mutated
    if treatment == "sheep_plus_one_free_pasture_signal":
        found = _first_tile(
            farm,
            lambda tile: tile.get("kind") == "PASTURE" and "animal" not in tile,
        )
        if found is None:
            return None
        _, _, tile = found
        tile.update(
            {
                "animal": "SHEEP",
                "placed_day": int(mutated.get("day", 0) or 0),
                "yield_units": 0,
                "consecutive_unfed": 0,
                "fed_today": False,
                "cared_today": False,
                "fertilizer_available": False,
                "pending_care_bonus": 0,
            }
        )
        return mutated
    raise ValueError(f"unknown treatment: {treatment}")


def _policy_stream(
    agent_path: Path,
    replay: dict[str, Any],
    opponent_seat: int,
    end_step: int,
    *,
    focal_seat: int,
    onset: int | None = None,
    treatment: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    module = _import_module(agent_path, f"reaction_query_{opponent_seat}_{onset}_{treatment}")
    emitted = []
    applied_steps = 0
    for step in range(end_step):
        obs = observation(replay, step, opponent_seat) or {}
        supplied = obs
        if onset is not None and treatment is not None and step >= onset:
            candidate = _apply_signal(obs, focal_seat, treatment)
            if candidate is not None:
                supplied = candidate
                applied_steps += 1
        value = _call(module.agent, supplied, replay.get("configuration") or {})
        emitted.append(value if isinstance(value, dict) else {})
    return emitted, applied_steps


def _position(farm: dict[str, Any], unit: int) -> list[int]:
    values = [farm.get("farmer") or [], *(farm.get("hands") or [])]
    return list(values[unit]) if unit < len(values) else []


def _tile(farm: dict[str, Any], position: list[int]) -> dict[str, Any] | None:
    if len(position) != 2:
        return None
    x, y = int(position[0]), int(position[1])
    tiles = farm.get("tiles") or []
    value = tiles[y][x] if 0 <= y < len(tiles) and 0 <= x < len(tiles[y]) else None
    return value if isinstance(value, dict) else None


def _field_item(farm: dict[str, Any], unit: int, row: list[Any]) -> str | None:
    if len(row) >= 2 and row[0] in {"PLANT", "PICKUP", "PLACE"}:
        return str(row[1])
    tile = _tile(farm, _position(farm, unit))
    if tile is None:
        return None
    if tile.get("crop"):
        return str(tile["crop"])
    animal = tile.get("animal")
    return {"COW": "MILK", "SHEEP": "WOOL", "GOOSE": "EGG"}.get(animal)


def _components(value: dict[str, Any], obs: dict[str, Any], seat: int) -> dict[str, Any]:
    farms = list(obs.get("farms") or [])
    farm = farms[seat] if seat < len(farms) else {}
    rows = [value.get("farmer") or ["PASS"], *(value.get("hands") or [])]
    field = []
    for unit, row in enumerate(rows):
        normalized = list(row or ["PASS"])
        field.append(
            {
                "unit": unit,
                "action": normalized,
                "operation": str(normalized[0]) if normalized else "PASS",
                "item": _field_item(farm, unit, normalized),
            }
        )
    market = []
    for slot, row in enumerate(value.get("market") or []):
        normalized = list(row or [])
        market.append(
            {
                "slot": slot,
                "action": normalized,
                "operation": str(normalized[0]) if normalized else "",
                "item": str(normalized[1]) if len(normalized) >= 2 else None,
            }
        )
    return {"field": field, "market": market}


def _first_component_difference(
    control: dict[str, Any], treatment: dict[str, Any], obs: dict[str, Any], seat: int
) -> dict[str, Any]:
    left = _components(control, obs, seat)
    right = _components(treatment, obs, seat)
    changes = []
    products = set()
    for component in ("field", "market"):
        width = max(len(left[component]), len(right[component]))
        for index in range(width):
            before = left[component][index] if index < len(left[component]) else None
            after = right[component][index] if index < len(right[component]) else None
            if before == after:
                continue
            changes.append({"component": component, "index": index, "control": before, "treatment": after})
            for row in (before, after):
                if row and row.get("item"):
                    products.add(str(row["item"]))
    return {"changes": changes, "affected_products": sorted(products)}


def _query_condition(
    agent_path: Path,
    replay: dict[str, Any],
    focal_seat: int,
    baseline: list[dict[str, Any]],
    onset: int,
    horizon: int,
    treatment: str,
) -> dict[str, Any]:
    opponent_seat = 1 - focal_seat
    onset_obs = observation(replay, onset, opponent_seat) or {}
    if _apply_signal(onset_obs, focal_seat, treatment) is None:
        return {
            "onset": onset,
            "treatment": treatment,
            "available": False,
            "responded": False,
            "reason": "required public farm target absent at onset",
        }
    end_step = min(onset + horizon + 1, len(replay.get("steps") or []) - 1)
    treated, applied_steps = _policy_stream(
        agent_path,
        replay,
        opponent_seat,
        end_step,
        focal_seat=focal_seat,
        onset=onset,
        treatment=treatment,
    )
    first = next(
        (
            step
            for step in range(onset, end_step)
            if canonical_action(baseline[step]) != canonical_action(treated[step])
        ),
        None,
    )
    result = {
        "onset": onset,
        "treatment": treatment,
        "available": True,
        "signal_applied_steps": applied_steps,
        "responded": first is not None,
        "first_response_step": first,
        "response_lag": first - onset if first is not None else None,
    }
    if first is not None:
        obs = observation(replay, first, opponent_seat) or {}
        result["first_response"] = _first_component_difference(
            baseline[first], treated[first], obs, opponent_seat
        )
        result["control_action"] = baseline[first]
        result["treatment_action"] = treated[first]
    return result


def _baseline_fidelity(
    baseline: list[dict[str, Any]], replay: dict[str, Any], opponent_seat: int
) -> dict[str, Any]:
    matches = [
        canonical_action(value) == canonical_action(action(replay, step, opponent_seat))
        for step, value in enumerate(baseline)
    ]
    mismatches = [index for index, matched in enumerate(matches) if not matched]
    return {
        "steps": len(matches),
        "matches": sum(matches),
        "fidelity": sum(matches) / len(matches) if matches else None,
        "first_mismatch_steps": mismatches[:20],
    }


def _source_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for policy_id in sorted({row["policy_id"] for row in records}):
        selected = [row for row in records if row["policy_id"] == policy_id]
        conditions = [condition for row in selected for condition in row["conditions"]]
        available = [row for row in conditions if row["available"]]
        responses = [row for row in available if row["responded"]]
        lags = [int(row["response_lag"]) for row in responses]
        result[policy_id] = {
            "source_ancestry": selected[0]["source_ancestry"],
            "seats": sorted({row["focal_seat"] for row in selected}),
            "minimum_baseline_fidelity": min(row["baseline_fidelity"]["fidelity"] for row in selected),
            "available_conditions": len(available),
            "response_conditions": len(responses),
            "response_rate": len(responses) / len(available) if available else None,
            "responding_focal_seats": sorted(
                {
                    row["focal_seat"]
                    for row in selected
                    if any(condition["available"] and condition["responded"] for condition in row["conditions"])
                }
            ),
            "minimum_response_lag": min(lags) if lags else None,
            "median_response_lag": median(lags) if lags else None,
            "affected_products": dict(
                Counter(
                    product
                    for condition in responses
                    for product in condition.get("first_response", {}).get("affected_products", [])
                )
            ),
        }
    return result


def _ancestry_summary(source_summary: dict[str, Any]) -> dict[str, Any]:
    grouped: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for policy_id, row in source_summary.items():
        grouped[row["source_ancestry"]].append((policy_id, row))
    result = {}
    for ancestry, selected in sorted(grouped.items()):
        responding_seats = sorted(
            {seat for _, row in selected for seat in row["responding_focal_seats"]}
        )
        result[ancestry] = {
            "policies": [policy_id for policy_id, _ in selected],
            "response_conditions": sum(row["response_conditions"] for _, row in selected),
            "responding_focal_seats": responding_seats,
            "replicated_both_seats": responding_seats == [0, 1],
        }
    return result


def run(preregistration: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    prereg = json.loads(preregistration.read_text(encoding="utf-8"))
    sources = prereg["sources"]
    onset_steps = [int(value) for value in prereg["onset_steps"]]
    horizon = int(prereg["response_horizon_turns"])
    seed = int(prereg["baseline_seed"])
    champion = ROOT / "agents" / "v111" / "main.py"
    formal_root = (
        ROOT
        / "data"
        / "evaluation"
        / "v113_cow_sheep_gate_e3e4_20260901_2024"
        / "replays"
        / "formal_promotion"
    )
    generated: dict[tuple[str, int], dict[str, Any]] = {}
    records = []
    baseline_provenance = []
    max_end = max(onset_steps) + horizon + 1
    treatments = [row["id"] for row in prereg["treatments"]]
    for source in sources:
        policy_id = str(source["policy_id"])
        agent_path = ROOT / source["path"]
        if _sha256(agent_path) != source["sha256"]:
            raise ValueError(f"source hash mismatch: {policy_id}")
        for focal_seat in prereg["seats"]:
            focal_seat = int(focal_seat)
            saved_path = (
                formal_root
                / policy_id
                / f"seed_{seed}_seat_{focal_seat}"
                / "control.json.gz"
            )
            if saved_path.is_file():
                replay = _load_replay(saved_path)
                replay_source = str(saved_path)
                replay_sha = _sha256(saved_path)
                generated_replay = False
            else:
                game = _run_game(
                    champion,
                    agent_path,
                    seed,
                    focal_seat,
                    720,
                    f"reaction_baseline_{policy_id}_{focal_seat}",
                )
                replay = game["replay"]
                generated[(policy_id, focal_seat)] = replay
                replay_source = f"generated:{policy_id}:seed_{seed}:seat_{focal_seat}"
                replay_sha = _json_sha256(replay)
                generated_replay = True
            opponent_seat = 1 - focal_seat
            baseline, _ = _policy_stream(
                agent_path,
                replay,
                opponent_seat,
                max_end,
                focal_seat=focal_seat,
            )
            fidelity = _baseline_fidelity(baseline, replay, opponent_seat)
            conditions = [
                _query_condition(
                    agent_path,
                    replay,
                    focal_seat,
                    baseline,
                    onset,
                    horizon,
                    treatment,
                )
                for onset in onset_steps
                for treatment in treatments
            ]
            records.append(
                {
                    "policy_id": policy_id,
                    "source_ancestry": source["source_ancestry"],
                    "seed": seed,
                    "focal_seat": focal_seat,
                    "opponent_seat": opponent_seat,
                    "baseline_replay": replay_source,
                    "baseline_replay_sha256": replay_sha,
                    "generated_replay": generated_replay,
                    "baseline_fidelity": fidelity,
                    "conditions": conditions,
                }
            )
            baseline_provenance.append((replay_source, replay_sha))
    summary = _source_summary(records)
    ancestries = _ancestry_summary(summary)
    fidelity_floor = float(
        prereg["validity_rules"]["minimum_baseline_action_fidelity_per_policy_seat"]
    )
    fidelity_valid = all(
        row["baseline_fidelity"]["fidelity"] >= fidelity_floor for row in records
    )
    replicated = [
        ancestry for ancestry, row in ancestries.items() if row["replicated_both_seats"]
    ]
    population_replication = len(replicated) >= 2
    result = {
        "format": "kaggriculture-reaction-aware-gold-policy-query-result-v1",
        "created_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
        "hypothesis_id": prereg["hypothesis_id"],
        "dataset_role": prereg["dataset_role"],
        "evidence_ceiling": prereg["evidence_ceiling"],
        "provenance": {
            "preregistration": str(preregistration),
            "preregistration_sha256": _sha256(preregistration),
            "analyzer": str(Path(__file__).resolve()),
            "analyzer_sha256": _sha256(Path(__file__).resolve()),
            "champion_sha256": _sha256(champion),
            "baseline_manifest_sha256": hashlib.sha256(
                "\n".join(f"{path}\t{digest}" for path, digest in sorted(baseline_provenance)).encode()
            ).hexdigest(),
        },
        "design": {
            "onset_steps": onset_steps,
            "response_horizon_turns": horizon,
            "treatments": treatments,
            "fixed_future_state_warning": prereg["guardrails"][0],
        },
        "validity": {
            "baseline_fidelity_floor": fidelity_floor,
            "all_policy_seats_valid": fidelity_valid,
            "invalid_policy_seats": [
                [row["policy_id"], row["focal_seat"]]
                for row in records
                if row["baseline_fidelity"]["fidelity"] < fidelity_floor
            ],
        },
        "source_summary": summary,
        "ancestry_summary": ancestries,
        "population_replication": {
            "required_replicated_ancestries": 2,
            "replicated_ancestries": replicated,
            "passed": fidelity_valid and population_replication,
        },
        "records": records,
        "guardrails": prereg["guardrails"],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    generated_root = output / "generated_baseline_replays"
    for (policy_id, focal_seat), replay in generated.items():
        target = generated_root / policy_id / f"seed_{seed}_seat_{focal_seat}.json.gz"
        target.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(target, "wt", encoding="utf-8", compresslevel=6) as handle:
            json.dump(replay, handle, ensure_ascii=False, separators=(",", ":"))
    (output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preregistration",
        type=Path,
        default=ROOT
        / "experiments"
        / "reaction_aware_gold_policy_query_20260902"
        / "preregistration.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "analysis" / "reaction_aware_gold_policy_query_20260902",
    )
    args = parser.parse_args()
    result = run(args.preregistration.resolve(), args.output.resolve())
    print(
        json.dumps(
            {
                "validity": result["validity"],
                "source_summary": result["source_summary"],
                "ancestry_summary": result["ancestry_summary"],
                "population_replication": result["population_replication"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
