"""Run the immutable Round4 learned archive on the preregistered Round5 panel."""

from __future__ import annotations

import gzip
import hashlib
import importlib.util
import inspect
import json
import sys
import tarfile
import tempfile
import uuid
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments/learning_round5_20260921"
OUTPUT = EXPERIMENT / "frozen_round4_reference"
ARCHIVE = ROOT / "artifacts/submissions/learning_round4_20260921_learned.tar.gz"
PROTOCOL = EXPERIMENT / "COMPARISON_PROTOCOL.json"
CURRENT = EXPERIMENT / "comparison/COMPARISON_RESULTS.json"
OPPONENTS = {
    "qeinstein_moev2": ROOT / "experiments/research_20260910/runtime/qeinstein_moev2/main.py",
    "smart_farm": ROOT / "experiments/research_20260918_v120/acquisition/smart_farm/decoded_main_1.py",
}
GENERIC = ("action_codec", "bc_agent", "common", "contracts", "executor", "features", "learned_main", "market", "selector")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_module(path: Path, label: str) -> Any:
    saved = {name: sys.modules.pop(name) for name in GENERIC if name in sys.modules}
    parent = str(path.parent)
    sys.path.insert(0, parent)
    try:
        spec = importlib.util.spec_from_file_location(f"_frozen_{label}_{uuid.uuid4().hex}", path)
        if spec is None or spec.loader is None:
            raise ImportError(path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if callable(getattr(module, "reset_runtime_state", None)):
            module.reset_runtime_state()
        return module
    finally:
        if sys.path and sys.path[0] == parent:
            sys.path.pop(0)
        for name in GENERIC:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


def call(function: Any, observation: Any, configuration: Any) -> Any:
    try:
        parameters = inspect.signature(function).parameters.values()
        accepts_two = len(list(parameters)) >= 2
    except (TypeError, ValueError):
        accepts_two = True
    return function(observation, configuration) if accepts_two else function(observation)


def audit_actions(replay: dict[str, Any], seat: int) -> dict[str, int]:
    harvest = duplicate = immature = animal = 0
    first = {"WHEAT": 2, "CARROT": 2, "TOMATO": 8, "STRAWBERRY": 10, "MELON": 10}
    for record in range(1, len(replay["steps"])):
        before = replay["steps"][record - 1][seat]["observation"]
        action = replay["steps"][record][seat].get("action") or {}
        farm = before["farms"][seat]
        positions = [farm["farmer"], *farm["hands"]]
        units = [action.get("farmer") or ["PASS"], *(action.get("hands") or [])]
        targets = Counter()
        for index, unit in enumerate(units):
            if index >= len(positions) or not unit or unit[0] != "HARVEST":
                continue
            harvest += 1
            x, y = positions[index]
            targets[(x, y)] += 1
            tile = farm["tiles"][y][x]
            if isinstance(tile, dict) and tile.get("animal"):
                animal += 1
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                immature += int(before["day"] - int(tile["planted_day"]) < first[tile["crop"]])
        duplicate += sum(max(0, value - 1) for value in targets.values())
    return {"harvest_issued": harvest, "duplicate_harvest_issued": duplicate, "immature_harvest_issued": immature, "animal_harvest_issued": animal}


def safe_extract(stage: Path) -> None:
    with tarfile.open(ARCHIVE, "r:gz") as stream:
        for member in stream.getmembers():
            target = (stage / member.name).resolve()
            if not target.is_relative_to(stage.resolve()):
                raise RuntimeError(f"unsafe member: {member.name}")
        stream.extractall(stage)


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    current = json.loads(CURRENT.read_text(encoding="utf-8"))
    rows = []
    with tempfile.TemporaryDirectory(prefix="frozen_round4_", dir=EXPERIMENT) as raw_stage:
        stage = Path(raw_stage)
        safe_extract(stage)
        for condition in protocol["conditions"]:
            for raw_seat in condition["seats"]:
                seat = int(raw_seat)
                focal_module = load_module(stage / "main.py", f"round4_{condition['family']}_{seat}")
                opponent_module = load_module(OPPONENTS[condition["family"]], f"opponent_{condition['family']}_{seat}")
                from kaggle_environments import make

                def focal(observation: Any, configuration: Any = None) -> Any:
                    return call(focal_module.agent, observation, configuration)

                def opponent(observation: Any, configuration: Any = None) -> Any:
                    return call(opponent_module.agent, observation, configuration)

                seed = int(condition["seed"])
                env = make("kaggriculture", configuration={"episodeSteps": 720, "seed": seed}, debug=True)
                env.run([focal, opponent] if seat == 0 else [opponent, focal])
                replay = env.toJSON()
                final = replay["steps"][-1]
                rewards = [float(value.get("reward") or 0) for value in final]
                replay_path = OUTPUT / "replays" / condition["family"] / f"seed_{seed}_seat_{seat}.json.gz"
                replay_path.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(replay_path, "wt", encoding="utf-8", compresslevel=6) as stream:
                    json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))
                trace = focal_module.policy_trace()
                trace_path = OUTPUT / "traces" / condition["family"] / f"seed_{seed}_seat_{seat}.jsonl"
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                trace_path.write_text("".join(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n" for value in trace), encoding="utf-8")
                rows.append({
                    "family": condition["family"], "seed": seed, "seat": seat,
                    "self_money": rewards[seat], "opponent_money": rewards[1 - seat], "margin": rewards[seat] - rewards[1 - seat],
                    "result": "WIN" if rewards[seat] > rewards[1 - seat] else "DRAW" if rewards[seat] == rewards[1 - seat] else "LOSS",
                    "statuses": [value["status"] for value in final], "stored_states": len(replay["steps"]),
                    "emitted_action_audit": audit_actions(replay, seat), "diagnostics": focal_module.policy_diagnostics(),
                    "replay": str(replay_path.relative_to(ROOT)), "replay_sha256": sha256(replay_path),
                    "trace": str(trace_path.relative_to(ROOT)), "trace_sha256": sha256(trace_path),
                })
                print(f"frozen Round4 {condition['family']} seed{seed} seat{seat}", flush=True)
    lookup = {(row["arm"], row["family"], row["seed"], row["seat"]): row for row in current["rows"]}
    paired = []
    for row in rows:
        for arm in ("round5_none", "round5_learned"):
            candidate = lookup[(arm, row["family"], row["seed"], row["seat"])]
            paired.append({
                "comparison": f"{arm}_minus_frozen_round4_whole_artifact",
                "family": row["family"], "seed": row["seed"], "seat": row["seat"],
                "delta_self": candidate["self_money"] - row["self_money"],
                "delta_opponent": candidate["opponent_money"] - row["opponent_money"],
                "delta_margin": candidate["margin"] - row["margin"],
            })
    summaries = {}
    for label in sorted({row["comparison"] for row in paired}):
        selected = [row for row in paired if row["comparison"] == label]
        summaries[label] = {key: mean(row[key] for row in selected) for key in ("delta_self", "delta_opponent", "delta_margin")}
    output = {
        "scope": "immutable Round4 learned archive on the preregistered new-seed panel",
        "archive": str(ARCHIVE.relative_to(ROOT)), "archive_sha256": sha256(ARCHIVE),
        "expected_archive_hash_match": sha256(ARCHIVE) == "664b71ef17764fcfd526fb7b2eae16b0651bec4bdb943e3c42c2ab97ea96b340",
        "causal_warning": "whole-artifact regression; selector representation/model and executor changed, so this is not a selector-only or pure-executor estimate",
        "games": len(rows), "rows": rows, "paired": paired, "summary": summaries,
    }
    write_json(OUTPUT / "FROZEN_ROUND4_RESULTS.json", output)
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
