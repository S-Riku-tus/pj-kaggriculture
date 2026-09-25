"""Round9 positive controls, codec audit, decoder audit, and metric negatives.

This program is deliberately diagnostic.  It uses the recorded opponent tape
and teacher physical states, and none of its scores are real-opponent results.
Every engine-effect comparison starts from the same recorded state and runs one
official kaggriculture 1.32.7 interpreter step for both actions.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import sys
import tarfile
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kaggle_environments import make

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "round9_teacher_reproduction_and_closed_loop_bc_20260923"
OUTPUT = EXPERIMENT / "contract_controls_v2"
REPLAY = ROOT / "data" / "replays" / "submission_56216119" / "episode_109118332.json"
A0_ARCHIVE = ROOT / "artifacts" / "submissions" / "round8_spatial_bc_20260922_seed20260922_pure_v6.tar.gz"
A1 = ROOT / "agents" / "round9_teacher_reproduction_and_closed_loop_bc_20260923" / "a1"
A2 = ROOT / "agents" / "round9_teacher_reproduction_and_closed_loop_bc_20260923" / "a2"
EXPECTED = {
    "replay": "94c21f59dd6fe86023fd986649fb28fc20e8eaafde0d0159418758a21d7a2a48",
    "a0_archive": "0b579c006fbc002d2873b55d9c936c149049575383e47309c9d6c0887e1a6e30",
    "engine": "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e",
}
OBS_KEYS = ("step", "day", "hour", "farms", "market", "town", "private")
MOVE = {"NORTH", "SOUTH", "EAST", "WEST"}


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value))


def core_state(states: list[Any]) -> list[dict[str, Any]]:
    result = []
    for raw in states:
        state = dict(raw)
        observation = dict(state.get("observation") or {})
        result.append(
            {
                "reward": state.get("reward"),
                "status": state.get("status"),
                "observation": {key: _plain(observation.get(key)) for key in OBS_KEYS},
            }
        )
    return result


def restore_observation(states: list[dict[str, Any]], seat: int, step: int) -> dict[str, Any]:
    public = copy.deepcopy(states[0].get("observation") or states[1].get("observation") or {})
    private = states[seat].get("observation") or {}
    public["player"] = seat
    public["private"] = copy.deepcopy(private.get("private", {}))
    public["remainingOverageTime"] = private.get("remainingOverageTime", public.get("remainingOverageTime", 60))
    public["step"] = step
    public["day"] = step // 24
    public["hour"] = step % 24
    return public


def recorded_action(replay: dict[str, Any], step: int, seat: int) -> dict[str, Any]:
    return copy.deepcopy(replay["steps"][step + 1][seat].get("action") or {})


def action_units(action: dict[str, Any]) -> list[list[Any]]:
    return [list(action.get("farmer") or ["PASS"]), *[list(v or ["PASS"]) for v in action.get("hands") or []]]


def canonical_action(action: dict[str, Any], actor_count: int) -> dict[str, Any]:
    units = (action_units(action) + [["PASS"]] * actor_count)[:actor_count]
    return {
        "farmer": units[0],
        "hands": units[1:],
        "market": [list(value) for value in action.get("market") or []],
    }


def isolated_step(
    replay: dict[str, Any], step: int, focal_action: dict[str, Any], seat: int = 0
) -> list[dict[str, Any]]:
    actions = [recorded_action(replay, step, index) for index in range(2)]
    actions[seat] = copy.deepcopy(focal_action)
    configuration = {**replay["configuration"], "seed": int(replay["info"]["seed"])}
    # Prefix placeholders preserve the framework's record index without copying
    # or trusting any earlier action.  The final element is the complete teacher state.
    environment = make(
        "kaggriculture",
        configuration=configuration,
        info={"seed": int(replay["info"]["seed"])},
        steps=[None] * step + [copy.deepcopy(replay["steps"][step])],
    )
    return core_state(environment.step(actions))


def positive_replay(replay: dict[str, Any]) -> dict[str, Any]:
    def tape(seat: int) -> Callable[[Any, Any], dict[str, Any]]:
        def agent(observation: Any, configuration: Any = None) -> dict[str, Any]:
            del configuration
            return recorded_action(replay, int(observation.step), seat)

        return agent

    configuration = {**replay["configuration"], "seed": int(replay["info"]["seed"])}
    environment = make("kaggriculture", configuration=configuration, info={"seed": int(replay["info"]["seed"])})
    actual = environment.run([tape(0), tape(1)])
    exact = 0
    first_mismatch = None
    field_mismatches = Counter()
    for index, (got, expected) in enumerate(zip(actual, replay["steps"], strict=True)):
        got_core, expected_core = core_state(got), core_state(expected)
        for seat in range(2):
            if got_core[seat] == expected_core[seat]:
                exact += 1
                continue
            if first_mismatch is None:
                first_mismatch = {"record_index": index, "seat": seat}
            for key in ("reward", "status"):
                if got_core[seat][key] != expected_core[seat][key]:
                    field_mismatches[key] += 1
            for key in OBS_KEYS:
                if got_core[seat]["observation"][key] != expected_core[seat]["observation"][key]:
                    field_mismatches[key] += 1
    return {
        "name": "teacher_replay_state_exact_match",
        "source_episode": 109118332,
        "environment_seed": int(replay["info"]["seed"]),
        "states": len(actual),
        "state_seat_numerator": exact,
        "state_seat_denominator": 2 * len(replay["steps"]),
        "ratio": exact / (2 * len(replay["steps"])),
        "first_mismatch": first_mismatch,
        "field_mismatches": dict(field_mismatches),
        "recorded_rewards": replay["rewards"],
        "replayed_rewards": [actual[-1][seat].reward for seat in range(2)],
        "recorded_statuses": replay["statuses"],
        "replayed_statuses": [actual[-1][seat].status for seat in range(2)],
        "mapping": "observation at steps[t] -> action stored in steps[t+1] -> observation at steps[t+1]",
        "classification": "REPRODUCTION_DIAGNOSTIC",
    }


def load_common():
    for name in ("common", "spatial", "spatial_policy", "policy", "runtime"):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(A2))
    try:
        import common

        return common
    finally:
        sys.path.pop(0)


def codec_audit(replay: dict[str, Any], common: Any) -> dict[str, Any]:
    actor_total = actor_exact = market_total = market_exact = eos_total = eos_exact = 0
    quantity_total = quantity_exact = 0
    first_failure = None
    for step in range(len(replay["steps"]) - 1):
        action = recorded_action(replay, step, 0)
        observation = restore_observation(replay["steps"][step], 0, step)
        actor_count = 1 + len(observation["farms"][0].get("hands", []))
        action = canonical_action(action, actor_count)
        for index, unit in enumerate(action_units(action)):
            actor_total += 1
            token = common.action_token(unit)
            quantity = int(unit[2]) if len(unit) >= 3 else 1
            decoded = common.token_action(token, quantity)
            actor_exact += int(decoded == unit)
            if len(unit) >= 3:
                quantity_total += 1
                quantity_exact += int(len(decoded) >= 3 and int(decoded[2]) == quantity)
            if decoded != unit and first_failure is None:
                first_failure = {"step": step, "actor_index": index, "input": unit, "output": decoded}
        for slot, order in enumerate(action["market"]):
            market_total += 1
            token = common.market_token(order)
            quantity = int(order[2]) if len(order) >= 3 else 1
            decoded = common.token_order(token, quantity)
            market_exact += int(decoded == order)
            if len(order) >= 3:
                quantity_total += 1
                quantity_exact += int(len(decoded) >= 3 and int(decoded[2]) == quantity)
            if decoded != order and first_failure is None:
                first_failure = {"step": step, "market_slot": slot, "input": order, "output": decoded}
        eos_total += 1
        # EOS is a sequence terminator, not an engine order passed to
        # token_order (which intentionally accepts only concrete orders).
        eos_exact += int(common.market_token([]) == "EOS")
    total, exact = actor_total + market_total + eos_total, actor_exact + market_exact + eos_exact
    return {
        "name": "codec_exact_roundtrip",
        "actor": {"numerator": actor_exact, "denominator": actor_total, "ratio": actor_exact / actor_total},
        "market_order": {
            "numerator": market_exact,
            "denominator": market_total,
            "ratio": market_exact / market_total if market_total else None,
        },
        "eos": {"numerator": eos_exact, "denominator": eos_total, "ratio": eos_exact / eos_total},
        "quantity": {
            "numerator": quantity_exact,
            "denominator": quantity_total,
            "ratio": quantity_exact / quantity_total if quantity_total else None,
        },
        "all": {"numerator": exact, "denominator": total, "ratio": exact / total},
        "first_failure": first_failure,
        "unknown_label_count": 0,
    }


def prepare_a0() -> Path:
    target = OUTPUT / "a0_archive_extract"
    if target.exists():
        raise FileExistsError(f"refusing to reuse partial output {target}")
    target.mkdir(parents=True)
    with tarfile.open(A0_ARCHIVE, "r:gz") as stream:
        stream.extractall(target, filter="data")
    return target


def load_runtime(directory: Path, label: str):
    for name in ("common", "spatial", "spatial_policy", "policy", "runtime", label):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(label, directory / "runtime.py")
    if spec is None or spec.loader is None:
        raise ImportError(directory / "runtime.py")
    sys.path.insert(0, str(directory))
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def decoder_audit(replay: dict[str, Any], runtime: Any, label: str) -> dict[str, Any]:
    actor_exact = actor_total = market_exact = market_total = joint_exact = 0
    effect_exact = 0
    differing_turns = 0
    examples = []
    reason_counts = Counter()
    for step in range(len(replay["steps"]) - 1):
        observation = restore_observation(replay["steps"][step], 0, step)
        teacher = recorded_action(replay, step, 0)
        actor_count = 1 + len(observation["farms"][0].get("hands", []))
        teacher = canonical_action(teacher, actor_count)
        final, trace = runtime.resolve_final_action(observation, teacher)
        final = canonical_action(final, actor_count)
        teacher_units, final_units = action_units(teacher), action_units(final)
        actor_total += len(teacher_units)
        actor_exact += sum(left == right for left, right in zip(teacher_units, final_units, strict=True))
        market_total += len(teacher["market"]) + 1  # EOS/list termination is a request too.
        for slot in range(len(teacher["market"])):
            market_exact += int(slot < len(final["market"]) and teacher["market"][slot] == final["market"][slot])
        market_exact += int(len(teacher["market"]) == len(final["market"]))
        same = teacher == final
        joint_exact += int(same)
        if same:
            effect_exact += 1
        else:
            differing_turns += 1
            teacher_state = isolated_step(replay, step, teacher)
            final_state = isolated_step(replay, step, final)
            equivalent = teacher_state == final_state
            effect_exact += int(equivalent)
            if len(examples) < 12:
                examples.append(
                    {
                        "step": step,
                        "day": step // 24,
                        "hour": step % 24,
                        "teacher": teacher,
                        "final": final,
                        "official_state_effect_equivalent": equivalent,
                        "trace": trace,
                    }
                )
        for row in trace.get("actors", []):
            reason_counts[f"actor:{row.get('reason')}"] += 1
        for row in trace.get("market", []):
            reason_counts[f"market:{row.get('reason')}"] += 1
    turns = len(replay["steps"]) - 1
    request_exact, request_total = actor_exact + market_exact, actor_total + market_total
    return {
        "arm": label,
        "source_episode": 109118332,
        "prediction_stage": "teacher request through final resolver then official isolated engine step",
        "actor_request_retention": {
            "numerator": actor_exact,
            "denominator": actor_total,
            "ratio": actor_exact / actor_total,
        },
        "market_request_retention_including_eos": {
            "numerator": market_exact,
            "denominator": market_total,
            "ratio": market_exact / market_total,
        },
        "all_request_retention": {
            "numerator": request_exact,
            "denominator": request_total,
            "ratio": request_exact / request_total,
        },
        "joint_turn_exact": {"numerator": joint_exact, "denominator": turns, "ratio": joint_exact / turns},
        "state_effect_equivalence": {
            "numerator": effect_exact,
            "denominator": turns,
            "ratio": effect_exact / turns,
            "official_engine_isolated_differing_turns": differing_turns,
        },
        "resolution_reasons": dict(reason_counts),
        "first_differences": examples,
        "classification": "REPRODUCTION_DIAGNOSTIC; not a real-opponent score",
    }


def mutation(action: dict[str, Any], kind: str, shifted: dict[str, Any] | None = None) -> dict[str, Any]:
    actor_count = len(action_units(action))
    if kind == "all_pass":
        return {"farmer": ["PASS"], "hands": [["PASS"]] * (actor_count - 1), "market": []}
    if kind == "movement_only":
        units = [unit if unit and unit[0] in MOVE else ["PASS"] for unit in action_units(action)]
        return {"farmer": units[0], "hands": units[1:], "market": []}
    if kind == "delete_work_candidates":
        units = [unit if unit and unit[0] in MOVE | {"PASS"} else ["PASS"] for unit in action_units(action)]
        return {"farmer": units[0], "hands": units[1:], "market": copy.deepcopy(action.get("market") or [])}
    if kind == "quantity_one":

        def one(value: list[Any]) -> list[Any]:
            return [*value[:2], 1] if len(value) >= 3 else list(value)

        units = [one(value) for value in action_units(action)]
        return {"farmer": units[0], "hands": units[1:], "market": [one(v) for v in action.get("market") or []]}
    if kind == "teacher_action_shift_plus_one":
        assert shifted is not None
        units = action_units(shifted)
        units = (units + [["PASS"]] * actor_count)[:actor_count]
        return {"farmer": units[0], "hands": units[1:], "market": copy.deepcopy(shifted.get("market") or [])}
    raise ValueError(kind)


def action_metrics(teacher: dict[str, Any], predicted: dict[str, Any], common: Any) -> Counter[str]:
    result: Counter[str] = Counter()
    teacher_units, predicted_units = action_units(teacher), action_units(predicted)
    predicted_units = (predicted_units + [["PASS"]] * len(teacher_units))[: len(teacher_units)]
    for expected, actual in zip(teacher_units, predicted_units, strict=True):
        result["actor_total"] += 1
        result["actor_token_exact"] += int(common.action_token(expected) == common.action_token(actual))
        result["actor_command_exact"] += int(expected == actual)
        if len(expected) >= 3:
            result["quantity_total"] += 1
            result["quantity_exact"] += int(len(actual) >= 3 and int(actual[2]) == int(expected[2]))
        result["predicted_work"] += int(bool(actual) and actual[0] not in MOVE | {"PASS"})
    expected_orders, actual_orders = teacher.get("market") or [], predicted.get("market") or []
    for slot in range(len(expected_orders) + 1):
        expected = expected_orders[slot] if slot < len(expected_orders) else []
        actual = actual_orders[slot] if slot < len(actual_orders) else []
        result["market_total"] += 1
        result["market_token_exact"] += int(common.market_token(expected) == common.market_token(actual))
    result["market_list_total"] += 1
    result["market_list_exact"] += int(expected_orders == actual_orders)
    result["joint_total"] += 1
    result["joint_exact"] += int(teacher == predicted)
    return result


def metric_negative_controls(replay: dict[str, Any], common: Any) -> dict[str, Any]:
    results = {}
    for kind in (
        "identity",
        "all_pass",
        "movement_only",
        "delete_work_candidates",
        "quantity_one",
        "teacher_action_shift_plus_one",
    ):
        counts: Counter[str] = Counter()
        first_difference = None
        first_effect_equivalent = None
        for step in range(len(replay["steps"]) - 1):
            observation = restore_observation(replay["steps"][step], 0, step)
            actor_count = 1 + len(observation["farms"][0].get("hands", []))
            teacher = canonical_action(recorded_action(replay, step, 0), actor_count)
            if kind == "identity":
                predicted = copy.deepcopy(teacher)
            else:
                shifted = (
                    recorded_action(replay, step + 1, 0)
                    if kind == "teacher_action_shift_plus_one" and step + 1 < len(replay["steps"]) - 1
                    else {"farmer": ["PASS"], "hands": [], "market": []}
                )
                predicted = canonical_action(mutation(teacher, kind, shifted), actor_count)
            counts.update(action_metrics(teacher, predicted, common))
            if teacher != predicted and first_difference is None:
                first_difference = {"step": step, "teacher": teacher, "predicted": predicted}
                first_effect_equivalent = isolated_step(replay, step, teacher) == isolated_step(replay, step, predicted)

        def ratio(n: str, d: str, _counts: Counter = counts) -> float | None:  # noqa: B006
            return _counts[n] / _counts[d] if _counts[d] else None

        work_denominator = counts["predicted_work"]
        results[kind] = {
            "actor_token_accuracy": {
                "numerator": counts["actor_token_exact"],
                "denominator": counts["actor_total"],
                "ratio": ratio("actor_token_exact", "actor_total"),
            },
            "actor_complete_command": {
                "numerator": counts["actor_command_exact"],
                "denominator": counts["actor_total"],
                "ratio": ratio("actor_command_exact", "actor_total"),
            },
            "market_token_accuracy": {
                "numerator": counts["market_token_exact"],
                "denominator": counts["market_total"],
                "ratio": ratio("market_token_exact", "market_total"),
            },
            "ordered_market_list": {
                "numerator": counts["market_list_exact"],
                "denominator": counts["market_list_total"],
                "ratio": ratio("market_list_exact", "market_list_total"),
            },
            "quantity_accuracy_all_rows": {
                "numerator": counts["quantity_exact"],
                "denominator": counts["quantity_total"],
                "ratio": ratio("quantity_exact", "quantity_total"),
            },
            "joint_turn_exact": {
                "numerator": counts["joint_exact"],
                "denominator": counts["joint_total"],
                "ratio": ratio("joint_exact", "joint_total"),
            },
            "work_volume": work_denominator,
            "work_effect_rate": {
                "numerator": None,
                "denominator": work_denominator,
                "ratio": None,
                "status": "NOT_APPLICABLE" if work_denominator == 0 else "NOT_OBSERVED_IN_LABEL_CONTROL",
            },
            "first_difference": first_difference,
            "first_difference_official_effect_equivalent": first_effect_equivalent,
        }
    baseline = results["identity"]
    validations = {}
    expected = {
        "all_pass": ("actor_complete_command", "joint_turn_exact", "work_volume"),
        "movement_only": ("actor_complete_command", "joint_turn_exact", "work_volume"),
        "delete_work_candidates": ("actor_complete_command", "joint_turn_exact", "work_volume"),
        "quantity_one": ("quantity_accuracy_all_rows", "actor_complete_command", "joint_turn_exact"),
        "teacher_action_shift_plus_one": (
            "actor_token_accuracy",
            "market_token_accuracy",
            "joint_turn_exact",
        ),
    }
    for kind, metrics in expected.items():
        checks = {}
        for name in metrics:
            if name == "work_volume":
                checks[name] = results[kind][name] < baseline[name]
            else:
                checks[name] = results[kind][name]["ratio"] < baseline[name]["ratio"]
        validations[kind] = {"checks": checks, "passed": all(checks.values())}
    return {
        "results": results,
        "validations": validations,
        "all_passed": all(v["passed"] for v in validations.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-decoder", action="store_true")
    args = parser.parse_args()
    if OUTPUT.exists() and any(OUTPUT.iterdir()):
        raise FileExistsError(f"refusing to overwrite non-empty output directory {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    engine = (
        ROOT / ".venv" / "Lib" / "site-packages" / "kaggle_environments" / "envs" / "kaggriculture" / "kaggriculture.py"
    )
    actual_hashes = {"replay": sha256(REPLAY), "a0_archive": sha256(A0_ARCHIVE), "engine": sha256(engine)}
    if actual_hashes != EXPECTED:
        raise RuntimeError({"expected": EXPECTED, "actual": actual_hashes})
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    common = load_common()
    positive = positive_replay(replay)
    codec = codec_audit(replay, common)
    negatives = metric_negative_controls(replay, common)
    write_json(OUTPUT / "teacher_replay_exact.json", positive)
    write_json(OUTPUT / "codec_roundtrip.json", codec)
    write_json(OUTPUT / "metric_negative_controls.json", negatives)
    decoders = {}
    if not args.skip_decoder:
        a0 = prepare_a0()
        for label, directory in (("A0_frozen", a0), ("A1_prefix_legality", A1), ("A2_prefix_retrained_code", A2)):
            runtime = load_runtime(directory, f"round9_control_{label}")
            decoders[label] = decoder_audit(replay, runtime, label)
            write_json(OUTPUT / f"teacher_through_decoder_{label}.json", decoders[label])
    write_json(
        OUTPUT / "summary.json",
        {
            "created_at_utc": now(),
            "classification": "diagnostic controls only; recorded opponent/state data are not a real-agent score",
            "hashes": actual_hashes,
            "positive_replay": positive,
            "codec": codec,
            "negative_controls_all_passed": negatives["all_passed"],
            "decoders": {
                label: {
                    "all_request_retention": value["all_request_retention"],
                    "joint_turn_exact": value["joint_turn_exact"],
                    "state_effect_equivalence": value["state_effect_equivalence"],
                }
                for label, value in decoders.items()
            },
            "new_learning_runs": 0,
            "new_real_opponent_games": 0,
            "kaggle_submissions": 0,
        },
    )


if __name__ == "__main__":
    main()
