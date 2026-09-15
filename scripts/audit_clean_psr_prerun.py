"""Offline preregistration audits for the clean-PSR experiment.

This script consumes only already-spent v116/control replays and repository
metadata.  It does not run a game or inspect any reserved-seed replay body.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import importlib.util
import json
import sys
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EXP = ROOT / "experiments/research_20260914_clean_psr"
PAIRS = ROOT / "data/evaluation/research_20260914_lowcash/discovery/pairs.jsonl"
REPLAYS = ROOT / "data/evaluation/research_20260914_lowcash/discovery/replays"
POLICY = ROOT / "experiments/research_20260914_lowcash/runtime/v116_mooman_complete/policy.py"
OLD_TAPE = ROOT / "experiments/research_20260914_next_strategy/opponent_tape_audit.json"


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def replay(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def locate_replay(row: dict[str, Any], arm: str = "treatment") -> Path:
    stored = row.get("replay_artifacts", {}).get(arm)
    if stored:
        return Path(stored)
    return REPLAYS / "discovery" / row["lineage_id"] / f"seed_{row['seed']}_seat_{row['seat']}" / f"{arm}.json.gz"


def literal_assignment(source: str, wanted: set[str]) -> dict[str, Any]:
    import ast

    values: dict[str, Any] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                values[target.id] = ast.literal_eval(node.value)
    if set(values) != wanted:
        raise RuntimeError(f"missing constants: {wanted - set(values)}")
    return values


def recompute_tape(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source = POLICY.read_text(encoding="utf-8")
    values = literal_assignment(source, {"_TAPE_POS", "_TAPE2_POS", "_E030_N"})
    contexts = []
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    for row in sorted(rows, key=lambda item: (item["lineage_id"], item["seed"], item["seat"])):
        rep = replay(locate_replay(row))
        seat = int(row["seat"])
        hits = hits2 = 0
        for step in sorted(values["_TAPE_POS"]):
            observation = rep["steps"][step][seat]["observation"]
            farm = observation["farms"][1 - seat]
            actual = [list(farm.get("farmer") or []), [list(v) for v in farm.get("hands") or []]]
            hits += actual == values["_TAPE_POS"][step]
            hits2 += actual == values["_TAPE2_POS"][step]
        step1 = rep["steps"][1][seat]["observation"]
        wheat = int(step1["market"]["inventory"]["WHEAT"])
        inferred = 10000 - wheat - int(values["_E030_N"])
        n13 = 10 <= inferred <= 16
        tape = hits >= 7
        tape2 = hits2 >= 7 and n13
        mode = "tape" if tape else "tape2" if tape2 else "other"
        safety = list(row["candidate_new_major_regressions"])
        record = {
            "source": row["lineage_id"],
            "seed": row["seed"],
            "seat": seat,
            "position_hits": hits,
            "tape2_position_hits": hits2,
            "step1_wheat_inventory": wheat,
            "inferred_other_demand": inferred,
            "n13_gate": n13,
            "selected_mode": mode,
            "control_result": row["control"]["result"],
            "treatment_result": row["treatment"]["result"],
            "loss_to_win": bool(row["loss_to_win"]),
            "raw_safety_reasons": safety,
            "raw_safe": not safety,
        }
        contexts.append(record)
        counter = by_source[row["lineage_id"]]
        counter["contexts"] += 1
        counter["tape"] += tape
        counter["tape2"] += tape2
        counter["loss_to_win"] += bool(row["loss_to_win"])
        counter["loss_to_win_raw_unsafe"] += bool(row["loss_to_win"] and safety)
        counter["loss_to_win_raw_safe"] += bool(row["loss_to_win"] and not safety)
    old = json.loads(OLD_TAPE.read_text(encoding="utf-8"))
    agreement = all(
        int(by_source[source]["tape2"]) == int(old["by_opponent"][source]["tape2_signature_gate_matches"])
        for source in by_source
    )
    return {
        "created_at": now(),
        "purpose": "independent recomputation from the 32 already-spent treatment replays",
        "replay_scope": {"contexts": len(contexts), "new_games": 0, "spent": True},
        "source_sha256": sha(POLICY),
        "prior_audit_sha256": sha(OLD_TAPE),
        "prior_audit_gate_counts_match": agreement,
        "by_source": {key: dict(value) for key, value in sorted(by_source.items())},
        "contexts": contexts,
        "causal_limit": "temporal co-occurrence and ablation targets; does not identify a single-action causal effect",
    }


def summarize_subset(rows: list[dict[str, Any]]) -> dict[str, Any]:
    from scripts.evaluation.statistics import summarize_pairs

    return summarize_pairs(rows)


def actual_action(rep: dict[str, Any], step: int, seat: int) -> Any:
    # Record zero is the environment's initial placeholder. The response to
    # observation t is stored on state record t+1.
    return rep["steps"][step + 1][seat].get("action")


def load_policy() -> Any:
    for name in list(sys.modules):
        if name == "kaggriculture" or name.startswith("kaggriculture."):
            del sys.modules[name]
    name = f"_v116_sidecar_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, POLICY)
    if spec is None or spec.loader is None:
        raise ImportError(POLICY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sidecar_trace(row: dict[str, Any]) -> dict[str, Any]:
    rep = replay(locate_replay(row))
    seat = int(row["seat"])
    module = load_policy()
    current: dict[str, Any] = {"step": None, "events": []}
    layer_names = (
        "_pre_sweep_agent",
        "_sweep",
        "_opening_guard",
        "_e030_prebuy",
        "_pre_orak_agent",
        "_orak_front_run",
        "_open_guard",
        "_psr_act",
        "_feed_g",
        "_carrot_swap",
        "_carrot_seeds",
        "_eager_sell",
        "_sells_first",
    )
    for layer in layer_names:
        original = getattr(module, layer, None)
        if not callable(original):
            continue

        def make_wrapper(name: str, function: Any):
            def wrapped(*args: Any, **kwargs: Any) -> Any:
                returned = function(*args, **kwargs)
                if isinstance(returned, dict):
                    current["events"].append({"layer": name, "action": copy.deepcopy(returned)})
                return returned

            return wrapped

        setattr(module, layer, make_wrapper(layer, original))
    observer = module._tape_observe

    def traced_observer(obs: Any) -> Any:
        result = observer(obs)
        current["events"].append({"layer": "_tape_observe", "state": copy.deepcopy(module._tape_state)})
        return result

    module._tape_observe = traced_observer
    records = []
    mismatches = []
    configuration = rep.get("configuration") or {}
    for step in range(min(719, len(rep.get("steps") or []) - 1)):
        current["step"] = step
        current["events"] = []
        obs = copy.deepcopy(rep["steps"][step][seat]["observation"])
        reconstructed_step = "step" not in obs
        obs.setdefault("step", step)
        emitted = module.agent_entry(obs, configuration)
        expected = actual_action(rep, step, seat)
        matches = emitted == expected
        if not matches and len(mismatches) < 20:
            mismatches.append({"step": step, "emitted": emitted, "replay": expected})
        records.append(
            {
                "step": step,
                "observation_step_reconstructed": reconstructed_step,
                "layers": current["events"],
                "final": emitted,
                "replay_action": expected,
                "matches_replay": matches,
                "tape_state": copy.deepcopy(module._tape_state),
            }
        )
    sidecar = EXP / "sidecar/v116" / f"{row['lineage_id']}_{row['seed']}_{seat}.json.gz"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(sidecar, "wt", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, separators=(",", ":"))
    return {
        "source": row["lineage_id"],
        "seed": row["seed"],
        "seat": seat,
        "steps": len(records),
        "action_mismatch_count": sum(not record["matches_replay"] for record in records),
        "mismatch_examples": mismatches,
        "sidecar": str(sidecar.relative_to(ROOT)),
        "sidecar_sha256": sha(sidecar),
    }


def existing_sidecar_trace(row: dict[str, Any]) -> dict[str, Any] | None:
    """Return a verified summary for a completed context, else request recompute."""
    seat = int(row["seat"])
    sidecar = EXP / "sidecar/v116" / f"{row['lineage_id']}_{row['seed']}_{seat}.json.gz"
    if not sidecar.exists():
        return None
    try:
        with gzip.open(sidecar, "rt", encoding="utf-8") as handle:
            records = json.load(handle)
    except (OSError, EOFError, json.JSONDecodeError):
        return None
    if len(records) != 719 or any(record.get("step") != step for step, record in enumerate(records)):
        return None
    if seat == 1 and not all(record.get("observation_step_reconstructed") for record in records):
        return None
    # Reconcile completed sidecars against the immutable replay. Seat-one
    # sidecars made before public step reconstruction were rejected above.
    rep = replay(locate_replay(row))
    corrected = False
    for record in records:
        expected = actual_action(rep, int(record["step"]), seat)
        matches = record.get("final") == expected
        if record.get("replay_action") != expected or record.get("matches_replay") != matches:
            record["replay_action"] = expected
            record["matches_replay"] = matches
            corrected = True
    if corrected:
        with gzip.open(sidecar, "wt", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, separators=(",", ":"))
    mismatches = [
        {
            "step": record["step"],
            "emitted": record.get("final"),
            "replay": record.get("replay_action"),
        }
        for record in records
        if not record.get("matches_replay")
    ]
    return {
        "source": row["lineage_id"],
        "seed": row["seed"],
        "seat": seat,
        "steps": len(records),
        "action_mismatch_count": len(mismatches),
        "mismatch_examples": mismatches[:20],
        "sidecar": str(sidecar.relative_to(ROOT)),
        "sidecar_sha256": sha(sidecar),
        "resumed_from_complete_sidecar": True,
    }


def field_state(obs: dict[str, Any], seat: int, unit: int) -> dict[str, Any]:
    farm = obs["farms"][seat]
    positions = [farm.get("farmer") or [], *(farm.get("hands") or [])]
    position = positions[unit] if unit < len(positions) else []
    tile = None
    if len(position) == 2:
        x, y = map(int, position)
        if 0 <= y < len(farm.get("tiles") or []) and 0 <= x < len(farm["tiles"][y]):
            tile = farm["tiles"][y][x]
    invs = obs.get("private", {}).get("inventories") or []
    return {
        "position": position,
        "tile": tile,
        "unit_inventory": invs[unit] if unit < len(invs) else {},
        "shed": obs.get("private", {}).get("shed") or {},
        "seeds": obs.get("private", {}).get("seeds") or {},
    }


def infer_noop(event: dict[str, Any], state: dict[str, Any]) -> str:
    action = event.get("action") or []
    op = action[0] if action else "MALFORMED"
    tile = state.get("tile")
    position = state.get("position") or []
    inv = state.get("unit_inventory") or {}
    if op in {"NORTH", "SOUTH", "EAST", "WEST"}:
        return "boundary movement ignored"
    if op == "PLANT":
        return "occupied/locked tile or atomic seed shortage"
    if op == "WATER":
        return "unit is not on an unwatered crop (position drift or duplicate work)"
    if op == "HARVEST":
        return "unit is not on a positive-yield crop/animal (position drift or premature schedule)"
    if op in {"FEED", "CARE", "COLLECT_FERTILIZER"}:
        return "unit is not on an eligible animal or required resource/state is absent"
    if op in {"PICKUP", "DROP", "PLACE"}:
        return f"shed adjacency/tile/inventory contract failed; position={position}, inventory={inv}"
    return f"engine state made {op} inapplicable; tile={tile!r}"


def first_event_map(rows: list[dict[str, Any]]) -> dict[str, Any]:
    from scripts.evaluation.lifecycle import analyze_lifecycle

    contexts = []
    reasons = Counter()
    for row in sorted(rows, key=lambda item: (item["lineage_id"], item["seed"], item["seat"])):
        if not row["candidate_new_major_regressions"]:
            continue
        rep = replay(locate_replay(row))
        seat = int(row["seat"])
        examples = row["safety"]["treatment"].get("engine_action_examples") or []
        life = analyze_lifecycle(rep, seat)
        found: dict[str, Any] = {}
        for reason in row["candidate_new_major_regressions"]:
            reasons[reason] += 1
            if reason == "new_all_step_silent_field_noop":
                event = next((event for event in examples if event.get("kind") == "silent_field_noop"), None)
                if event:
                    step = int(event["step"])
                    obs = rep["steps"][step][seat]["observation"]
                    state = field_state(obs, seat, int(event.get("unit", 0)))
                    found[reason] = {
                        **event,
                        "actual_state": state,
                        "engine_reason": infer_noop(event, state),
                    }
            elif reason in {
                "new_all_step_silent_market_noop",
                "new_all_step_partial_market_commit",
            }:
                partial = reason.endswith("partial_market_commit")
                event = next(
                    (
                        event
                        for event in examples
                        if event.get("kind") == "market_commit"
                        and (
                            0 < int(event.get("committed", 0)) < int(event.get("requested", 0))
                            if partial
                            else int(event.get("committed", 0)) == 0 and int(event.get("requested", 0)) > 0
                        )
                    ),
                    None,
                )
                if event:
                    step = int(event["step"])
                    obs = rep["steps"][step][seat]["observation"]
                    item = event.get("item")
                    op = event.get("op")
                    available = int(obs.get("private", {}).get("shed", {}).get(item, 0) or 0)
                    reason_text = (
                        "oversized SELL exceeded shed inventory"
                        if op == "SELL"
                        else "BUY/HIRE/LAND order stopped by cash/state availability"
                    )
                    found[reason] = {
                        **event,
                        "requested_order": (rep["steps"][step + 1][seat].get("action") or {}).get("market", [])[
                            int(event.get("slot", 0))
                        ],
                        "actual_state": {
                            "money": obs["farms"][seat]["money"],
                            "shed_item_units": available,
                            "market_inventory": obs.get("market", {}).get("inventory", {}).get(item),
                            "market_price": obs.get("market", {}).get("prices", {}).get(item),
                        },
                        "engine_reason": reason_text,
                    }
            elif reason == "new_crop_to_weed":
                event = next(
                    (
                        event
                        for event in life["examples"]
                        if event.get("cause") in {"water_death", "field_action", "lifespan_end"}
                    ),
                    None,
                )
                if event:
                    cause = event["cause"]
                    found[reason] = {
                        **event,
                        "classification": {
                            "lifespan_end": "natural lifespan decay",
                            "water_death": "required WATER omitted or route/position drift",
                            "field_action": "route field action converted the crop to weed",
                        }[cause],
                    }
            elif reason == "new_spawned_weed":
                event = next((event for event in life["examples"] if event.get("cause") == "empty_random_weed"), None)
                found[reason] = event or {
                    "first_step": None,
                    "classification": (
                        "natural RNG on an empty unlocked tile; exact first tile not retained "
                        "by lifecycle examples"
                    ),
                }
            elif reason == "new_animal_loss":
                first = None
                for step in range(1, len(rep["steps"])):
                    before = rep["steps"][step - 1][seat]["observation"]["farms"][seat]["tiles"]
                    after = rep["steps"][step][seat]["observation"]["farms"][seat]["tiles"]
                    for y, (left_row, right_row) in enumerate(zip(before, after, strict=False)):
                        for x, (left, right) in enumerate(zip(left_row, right_row, strict=False)):
                            if (
                                isinstance(left, dict)
                                and left.get("animal")
                                and not (isinstance(right, dict) and right.get("animal"))
                            ):
                                obs = rep["steps"][step - 1][seat]["observation"]
                                wheat = int(obs.get("private", {}).get("shed", {}).get("WHEAT", 0) or 0) + sum(
                                    int(inv.get("WHEAT", 0) or 0)
                                    for inv in obs.get("private", {}).get("inventories", [])
                                )
                                first = {
                                    "step": step - 1,
                                    "xy": [x, y],
                                    "animal": left.get("animal"),
                                    "tile": left,
                                    "available_wheat": wheat,
                                    "classification": "resource shortage"
                                    if wheat <= 0
                                    else "required FEED omitted/position drift",
                                }
                                break
                        if first:
                            break
                    if first:
                        break
                found[reason] = first
        first_steps = [
            int(value.get("step"))
            for value in found.values()
            if isinstance(value, dict) and value.get("step") is not None
        ]
        first_step = min(first_steps) if first_steps else None
        divergence = row.get("divergence_audit") or {}
        public_step = divergence.get("first_public_observation_divergence_step")
        contexts.append(
            {
                "source": row["lineage_id"],
                "seed": row["seed"],
                "seat": seat,
                "outcome": f"{row['control']['result']}->{row['treatment']['result']}",
                "first_safety_step": first_step,
                "relative_to_step216": None
                if first_step is None
                else ("before" if first_step < 216 else "at_or_after"),
                "relative_to_tape2_selection": None
                if first_step is None
                else ("before" if first_step <= 12 else "after"),
                "first_public_divergence_step": public_step,
                "relative_to_public_divergence": None
                if first_step is None or public_step is None
                else ("before" if first_step < public_step else "at_or_after"),
                "events": found,
            }
        )
    return {
        "created_at": now(),
        "scope": "already-spent v116 treatment replays; first-event contract diagnostics, no gate relaxation",
        "contexts_with_raw_safety": len(contexts),
        "reason_pair_counts": dict(reasons),
        "contexts": contexts,
        "causal_limit": "ordering is reported but is not treated as proof of the win mechanism",
    }


def seed_ledger() -> dict[str, Any]:
    reserved = set(range(10091101, 10091113))
    fresh = set(range(10091901, 10091913))
    proposed = set(range(10091421, 10091437))
    target = reserved | fresh | proposed
    actual_records: list[dict[str, Any]] = []
    mentions: list[dict[str, Any]] = []
    excluded = {".git", ".venv", ".uv-cache", "vendor", "node_modules", "__pycache__"}
    text_suffixes = {".json", ".jsonl", ".md", ".py", ".txt", ".csv", ".log"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in excluded for part in path.parts):
            continue
        if path.suffix.lower() not in text_suffixes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        found = sorted(seed for seed in target if str(seed) in text)
        if found:
            mentions.append({"path": str(path.relative_to(ROOT)), "seeds": found})
        if path.suffix.lower() != ".jsonl":
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            seeds = {
                int(value[key])
                for key in ("seed", "requested_seed", "resolved_seed")
                if isinstance(value.get(key), int)
            }
            for seed in sorted(seeds & target):
                actual_records.append({"path": str(path.relative_to(ROOT)), "line": number, "seed": seed})
    used = {row["seed"] for row in actual_records}
    return {
        "created_at": now(),
        "method": "repository-wide UTF-8 text scan plus structured JSONL seed-field audit; caches/vendor excluded",
        "mentions": mentions,
        "structured_usage_records": actual_records,
        "promotion": {
            "range": [10091101, 10091112],
            "used": sorted(used & reserved),
            "status": "UNUSED" if not used & reserved else "USED",
        },
        "fresh": {
            "range": [10091901, 10091912],
            "used": sorted(used & fresh),
            "status": "UNUSED" if not used & fresh else "USED",
        },
        "new_development": {
            "range": [10091421, 10091436],
            "used": sorted(used & proposed),
            "status": "UNUSED" if not used & proposed else "USED",
        },
        "limitation": (
            "Compressed replay bodies are indexed by their JSONL pair records; opaque binary "
            "contents are not treated as proof of non-use."
        ),
    }


def main() -> None:
    rows = read_rows(PAIRS)
    if len(rows) != 32:
        raise RuntimeError(f"expected 32 prior pairs, found {len(rows)}")
    tape_path = EXP / "tape_confounding_audit.json"
    if tape_path.exists():
        tape = json.loads(tape_path.read_text(encoding="utf-8"))
    else:
        tape = recompute_tape(rows)
        save(tape_path, tape)
    safety_path = EXP / "safety_first_event_map.json"
    if safety_path.exists():
        safety = json.loads(safety_path.read_text(encoding="utf-8"))
    else:
        safety = first_event_map(rows)
        save(safety_path, safety)
    traces = []
    for row in rows:
        trace = existing_sidecar_trace(row)
        traces.append(trace if trace is not None else sidecar_trace(row))
    if any(trace["action_mismatch_count"] for trace in traces):
        raise RuntimeError("offline layer tracer did not reproduce a frozen replay action stream")
    layer_map = {
        "created_at": now(),
        "source": str(POLICY.relative_to(ROOT)),
        "source_sha256": sha(POLICY),
        "method": (
            "offline replay-observation re-execution with return-value wrappers; "
            "no engine or candidate action changed"
        ),
        "layers": [
            {"order": 1, "name": "v56/backbone + sweep/opening/E030", "entry": "_pre_orak_agent"},
            {"order": 2, "name": "self-route phantom horizon", "entry": "_orak_front_run"},
            {
                "order": 3,
                "name": "known-opponent tape observer/future SELL override",
                "entry": "_tape_observe/_tape_preds",
                "prohibited": True,
            },
            {"order": 4, "name": "opening churn guard", "entry": "_open_guard"},
            {"order": 5, "name": "clean embedded PSR hybrid from step216", "entry": "_psr_act"},
            {
                "order": 6,
                "name": "feed/carrot/eager/sells-first",
                "entry": "_feed_g/_carrot_swap/_carrot_seeds/_eager_sell/_sells_first",
            },
        ],
        "traces": traces,
        "all_final_actions_reproduced": True,
    }
    save(EXP / "source_layer_map.json", layer_map)
    sensitivity = {
        "created_at": now(),
        "frozen_reference": "R0_v116_frozen_reference",
        "all": summarize_subset(rows),
        "exclude_mooman_self": summarize_subset([row for row in rows if row["lineage_id"] != "mooman_e052a"]),
        "exclude_tape2_sources": summarize_subset(
            [row for row in rows if row["lineage_id"] not in {"mooman_e052a", "souvik_v4"}]
        ),
        "exclude_psr_kaito_near_lineage": summarize_subset(
            [row for row in rows if row["lineage_id"] == "qeinstein_moev2"]
        ),
        "interpretation": "source exclusions are sensitivity analyses, not selectors",
    }
    save(EXP / "r0_sensitivity.json", sensitivity)
    ledger = seed_ledger()
    save(EXP / "seed_ledger.json", ledger)
    print(
        json.dumps(
            {
                "tape_match": tape["prior_audit_gate_counts_match"],
                "safety_contexts": safety["contexts_with_raw_safety"],
                "traces": len(traces),
                "seed_status": {key: ledger[key]["status"] for key in ("promotion", "fresh", "new_development")},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
