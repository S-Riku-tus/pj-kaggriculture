"""Run a hash-pinned reactive Round13 panel and retain every replay/failure."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
ROUND13 = Path(__file__).resolve().parents[1]
ROUND12_SCRIPTS = ROOT / "experiments/round12_causal_repairs_20260925/scripts"
sys.path.insert(0, str(ROUND12_SCRIPTS))
from run_round12_panel import init_kagsim, run_game  # noqa: E402


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def shop_sequence(replay: dict, seat: int) -> list[dict]:
    output = []
    previous: list[str] = []
    for record in replay["decisions"]:
        shops = list(record["observations"][seat]["town"]["unlocked_shops"])
        if shops != previous:
            output.append({"step": int(record["step"]), "shops": shops})
            previous = shops
    return output


def completion(arm: str, metrics: dict, telemetry: dict) -> tuple[bool, str]:
    if arm == "D0_B1":
        return True, "BASELINE_COMPLETE"
    if arm == "M1_deadline_market":
        created = int(telemetry.get("market_reservations_created", 0))
        filled = int(telemetry.get("market_reservations_filled", 0))
        return created > 0 and created == filled, "DEADLINES_FILLED" if created > 0 and created == filled else "NO_COMPLETE_RESERVATION"
    if arm == "P_EARLY4":
        early = int(telemetry.get("early_plants", 0)) >= 4
        first = metrics.get("first_plant_day", {}).get("STRAWBERRY")
        sold = int(metrics.get("sold_units", {}).get("STRAWBERRY", 0)) > 0
        ok = early and first is not None and int(first) <= 3 and sold
        return ok, "EARLY4_SOLD" if ok else "EARLY4_INCOMPLETE"
    if arm == "P_ROTATE2":
        started = int(telemetry.get("rotate_started", 0)) > 0
        converted = int(telemetry.get("rotate_digs", 0)) >= 2 and int(telemetry.get("rotate_plants", 0)) >= 2
        crop_sales = any(int(metrics.get("sold_units", {}).get(crop, 0)) > 0 for crop in ("WHEAT", "CARROT", "TOMATO"))
        ok = started and converted and crop_sales
        return ok, "ROTATE2_CONVERTED_AND_SOLD" if ok else "ROTATE2_INCOMPLETE"
    return False, "UNKNOWN_ARM"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config_bytes = args.config.read_bytes()
    config = json.loads(config_bytes)
    output = ROUND13 / config["output"]
    if (output / "games.csv").exists():
        raise FileExistsError(f"refusing to mix results in {output}")
    output.mkdir(parents=True, exist_ok=True)
    kagsim = init_kagsim()
    engine_module = Path(kagsim.__file__)
    engine_identity = {
        "engine_version": kagsim.ENGINE_VERSION,
        "module": str(engine_module),
        "module_sha256": sha256(engine_module),
    }
    rows: list[dict] = []
    failures: list[dict] = []
    for arm_name, arm_rel in config["arms"].items():
        arm_path = ROUND13 / arm_rel
        for opponent_name, opponent_rel in config["opponents"].items():
            opponent_path = ROOT / opponent_rel
            for seed in config["seeds"]:
                for seat in config.get("seats", [0, 1]):
                    replay_path = output / "replays" / arm_name / opponent_name / f"seed_{seed}_seat_{seat}.json.gz"
                    replay_path.parent.mkdir(parents=True, exist_ok=True)
                    started = time.perf_counter()
                    try:
                        replay, metrics = run_game(
                            arm_path,
                            opponent_path,
                            int(seed),
                            int(seat),
                            collect_route_metrics=arm_name in set(config.get("route_metric_arms", [])),
                        )
                        elapsed = time.perf_counter() - started
                        with gzip.open(replay_path, "wt", encoding="utf-8") as stream:
                            json.dump(replay, stream, separators=(",", ":"))
                        own, other = replay["terminal"]["rewards"][seat], replay["terminal"]["rewards"][1 - seat]
                        telemetry = replay.get("agent_telemetry") or {}
                        valid, status = completion(arm_name, metrics, telemetry)
                        row = {
                            "arm": arm_name,
                            "opponent": opponent_name,
                            "family": config["families"][opponent_name],
                            "seed": int(seed),
                            "seat": int(seat),
                            "evaluation_mode": config["evaluation_mode"],
                            "result": "W" if own > other else "L" if own < other else "D",
                            "score": 1.0 if own > other else 0.0 if own < other else 0.5,
                            "self_cash": own,
                            "opponent_cash": other,
                            "margin": own - other,
                            "execution_valid": valid,
                            "completion_status": status,
                            "artifact_hash": sha256(arm_path),
                            "engine_hash": engine_identity["module_sha256"],
                            "config_hash": hashlib.sha256(config_bytes).hexdigest(),
                            "opponent_hash": sha256(opponent_path),
                            "elapsed_seconds": round(elapsed, 6),
                            "shop_sequence_json": json.dumps(shop_sequence(replay, seat), separators=(",", ":")),
                            "replay": replay_path.relative_to(ROUND13).as_posix(),
                            "replay_hash": sha256(replay_path),
                            "route_metrics_json": json.dumps(metrics, separators=(",", ":")),
                            "telemetry_json": json.dumps(telemetry, separators=(",", ":")),
                        }
                        rows.append(row)
                        print(arm_name, opponent_name, seed, seat, row["result"], own, other, status, f"{elapsed:.2f}s", flush=True)
                    except Exception as error:  # preserve all failures rather than hiding them
                        failure = {
                            "arm": arm_name,
                            "opponent": opponent_name,
                            "seed": int(seed),
                            "seat": int(seat),
                            "error": repr(error),
                            "traceback": traceback.format_exc(),
                        }
                        failures.append(failure)
                        print("FAIL", json.dumps(failure, ensure_ascii=False), flush=True)
    if rows:
        with (output / "games.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (output / "failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "engine.json").write_text(json.dumps(engine_identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
