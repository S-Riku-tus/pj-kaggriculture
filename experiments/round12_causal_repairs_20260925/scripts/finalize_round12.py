"""Generate Round12 registries, route summary, replay index and manifest."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ROUND12 = Path(__file__).resolve().parents[1]


def sha(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name, value):
    (ROUND12 / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def input_hashes():
    entries = [
        ("round11_execution", ROOT / "artifacts/research/Kaggriculture_Round11_Execution_20260924.zip", "60b04f07e0621884ea362c0d969ddd49629acca8adfb98064920bd4a57f405ce"),
        ("round11_research_revision", Path(r"C:\Users\shiba\Downloads\Kaggriculture_Round11_Research_Revision_20260924.zip"), "d42d17597285b84abc2096fbf4aa04b57fdf622f8d71587310199b5756165044"),
        ("round10_b1", ROOT / "artifacts/submissions/round10_20260924_b1_herd_safe.tar.gz", "3fff94ec235566fff3416627d2691dec2e502bc80646a9016ee15e6fc2067986"),
        ("round10_b2", ROOT / "artifacts/submissions/round10_20260924_b2_buy10_sell5.tar.gz", "70ede751deac2688a2e822f65f10069e3b98d9db9d6dd0278d7574e13acb651a"),
        ("round10_learned", ROOT / "artifacts/submissions/round10_20260924_learned_diagnostic.tar.gz", "f0e1d9012b1cf2e9556302a299c8ac459990466cd3d0a3b6cd26fa45e95c636e"),
        ("round11_independent_audit", Path(r"C:\Users\shiba\Downloads\Kaggriculture_Round11_Independent_Audit_20260924.zip"), None),
    ]
    records = {}
    for name, path, expected in entries:
        observed = sha(path) if path.is_file() else None
        records[name] = {
            "path": str(path), "exists": path.is_file(), "expected_sha256": expected,
            "observed_sha256": observed,
            "matches_expected": None if expected is None or observed is None else observed == expected,
        }
    b1 = ROOT / "experiments/Kaggriculture_Round11_Research_Revision_20260924/inputs/agents/B1.py"
    m20 = ROOT / "experiments/round11_execution_20260924/arms/m20_multi_hypothesis/main.py"
    official = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
    loader = ROOT / ".venv/Lib/site-packages/kaggle_environments/agent.py"
    records.update({
        "B1_main_py": {"path": str(b1), "observed_sha256": sha(b1), "expected_sha256": "b6553c296c556aff5b5e2d12b75618e505fa4d852afb5338414ac6d6e039cb02", "matches_expected": sha(b1) == "b6553c296c556aff5b5e2d12b75618e505fa4d852afb5338414ac6d6e039cb02"},
        "M20_main_py": {"path": str(m20), "observed_sha256": sha(m20), "expected_sha256": "98d374f58f68c5b9f263eb3ed04f724e1e0b7a4fa562b581bdac90b276492c4a", "matches_expected": sha(m20) == "98d374f58f68c5b9f263eb3ed04f724e1e0b7a4fa562b581bdac90b276492c4a", "note": "correct value generated from file; 98d374ab... is not used"},
        "installed_kaggriculture_py": {"path": str(official), "observed_sha256": sha(official), "reference_commit": "302d8e20c83822b8d4572975cdea1180b792b748", "reference_sha256_from_round10_registry": "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e", "matches_reference": sha(official) == "bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e"},
        "installed_agent_py": {"path": str(loader), "observed_sha256": sha(loader)},
    })
    return records


def route_summary():
    path = ROUND12 / "metrics/smoke_route_v6/games.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    parsed = [json.loads(row["route_metrics_json"]) for row in rows]
    losses = [metric["plants_created"].get("STRAWBERRY", 0) - metric["terminal_crops"].get("STRAWBERRY", 0) for metric in parsed]
    return {
        "scope": "8 reactive C++ full games, 2 disclosed development seeds x 2 seats x 2 market modes; not holdout",
        "games": len(rows),
        "wins": sum(row["result"] == "W" for row in rows),
        "losses": sum(row["result"] == "L" for row in rows),
        "ties": sum(row["result"] == "T" for row in rows),
        "first_strawberry_day_values": [m["first_plant_day"].get("STRAWBERRY") for m in parsed],
        "peak_strawberry_values": [m["peak_crop_count"].get("STRAWBERRY") for m in parsed],
        "harvest_strawberry_values": [m["harvest_units"].get("STRAWBERRY", 0) for m in parsed],
        "sold_strawberry_values": [m["sold_units"].get("STRAWBERRY", 0) for m in parsed],
        "strawberry_revenue_values": [m["sales_revenue"].get("STRAWBERRY", 0) for m in parsed],
        "terminal_cash_values": [float(row["self_cash"]) for row in rows],
        "drop_failures": sum(m.get("drop_failures", 0) for m in parsed),
        "continuing_crop_loss_units_inferred": losses,
        "loss_inference": "plants_created minus terminal continuing plants; controller never DIGs a live strawberry",
        "route_complete_all_games": all(m["terminal_crops"].get("STRAWBERRY") == 16 and float(row["self_cash"]) > 0 for row, m in zip(rows, parsed)),
        "maintenance_clean_all_games": all(value == 0 for value in losses),
        "decision": "REJECT_STRENGTH_AND_MAINTENANCE; retained as executable independent production path",
    }


def source_registry(inputs):
    opponents = {}
    base = ROOT / "experiments/Kaggriculture_Round11_Research_Revision_20260924/inputs/agents"
    for name in ("B1", "v57", "order_book", "metav4"):
        path = base / f"{name}.py"
        opponents[name] = {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "review": "bounded static review plus reactive execution", "license": "source bundle provenance/NOTICE applies; no relicensing asserted"}
    return {
        "official": {"commit": "302d8e20c83822b8d4572975cdea1180b792b748", "installed_version": "1.32.7", "source_hash_match": inputs["installed_kaggriculture_py"]["matches_reference"], "license": "Apache-2.0"},
        "opponents": opponents,
        "round12_new_code": {"origin": "implemented locally for this audit", "license": "repository license; no third-party code copied into route/controller patch", "review": "tests and bounded execution complete"},
        "network_acquisition": {"calls": 0, "unreviewed_code_executed": 0},
    }


def replay_index():
    panels = []
    for relative in ("metrics/smoke_route", "metrics/smoke_route_v2", "metrics/smoke_route_v3", "metrics/smoke_route_v4", "metrics/smoke_route_v5", "metrics/smoke_route_v6", "metrics/input_repairs_development", "metrics/factorial_development"):
        csv_path = ROUND12 / relative / "games.csv"
        if not csv_path.exists():
            continue
        rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig", newline="")))
        panels.append({"panel": relative, "indexed_games": len(rows), "games_csv": str(csv_path.relative_to(ROUND12)).replace("\\", "/"), "replays": [row["replay"] for row in rows]})
    return {"format": "index_to_gzip_raw_reactive_replays", "panels": panels, "indexed_game_total": sum(p["indexed_games"] for p in panels), "note": "an aborted 17-game attempt produced no games.csv and is excluded from all statistics"}


def manifest():
    skip_parts = {"__pycache__", ".pytest_cache"}
    files = []
    for path in sorted(ROUND12.rglob("*")):
        if not path.is_file() or any(part in skip_parts for part in path.parts) or path.name == "FINAL_MANIFEST.json":
            continue
        files.append({"path": str(path.relative_to(ROUND12)).replace("\\", "/"), "size": path.stat().st_size, "sha256": sha(path)})
    return {"root": str(ROUND12), "self_excluded": True, "file_count": len(files), "files": files}


def main():
    inputs = input_hashes()
    write("INPUT_HASHES.json", inputs)
    generated = json.loads((ROUND12 / "agents/generated_manifest.json").read_text(encoding="utf-8"))
    statuses = {
        "P0M0_B1": "CHAMPION_RETAINED",
        "P0_ledger_only": "CORRECTNESS_FIX_PROMISING_DEVELOPMENT_ONLY",
        "P0_censor_only": "CORRECTNESS_FIX_NO_TERMINAL_CHANGE_IN_PANEL",
        "P0_ledger_censor": "CORRECTNESS_FIX_PROMISING_DEVELOPMENT_ONLY",
        "P0M1_market": "REJECTED",
        "P1M0_strawberry_route": "REJECTED_BUT_FEASIBLE",
        "P1M1_strawberry_route": "REJECTED_BUT_FEASIBLE",
    }
    write("ARM_REGISTRY.json", {name: {**data, "status": statuses[name]} for name, data in generated.items()})
    write("SOURCE_REGISTRY.json", source_registry(inputs))
    write("MODEL_USAGE.json", {
        "training_updates": 0, "weights_saved": 0, "model_reloads": 0,
        "new_model_inferences": 0, "learned_candidate_selections": 0,
        "reason": "factorial future-looking oracle score delta was 0.0; candidate set had no terminal-score upside to learn",
        "rule_market_proposals": 198, "rule_candidate_final_changes": 106,
        "paired_downstream_action_differences": 392,
        "warning": "rule counters are not model use and downstream action differences are not direct proposals",
    })
    write("EXECUTION_SCOPE.json", {
        "saved_reactive_cpp_panel_games": 129,
        "saved_panel_breakdown": {"route_iterations": 25, "input_repairs": 40, "factorial": 64},
        "official_python_full_game_unique_cases_in_final_parity": 2,
        "paired_cpp_full_game_unique_cases_in_final_parity": 2,
        "official_python_full_game_actual_invocations": 4,
        "official_parity_note": "two cases were rerun after correcting stored-seat observation reconstruction; final evidence uses the second run",
        "aborted_panel_full_games_excluded": 17,
        "test_internal_games_not_counted": True,
        "saved_Round11_results_reaggregated": 0,
        "new_holdout_games": 0,
        "learning_updates": 0,
        "model_loads": 0,
        "model_inferences": 0,
        "learned_selections": 0,
        "kaggle_submissions": 0,
        "notebook_publications": 0,
        "git_pushes": 0,
        "paid_actions": 0,
        "network_fetches": 0,
    })
    write("HOLDOUT_PROTOCOL.json", {
        "status": "FROZEN_FOR_FUTURE_RUN; no holdout seeds generated",
        "freeze_date": "2026-09-25",
        "development_gate": {"oracle_score_delta_gt": 0, "candidate_score_delta_gt": 0, "all_opponent_score_delta_gte": 0},
        "planned_holdout": {"seed_count": 12, "seed_generation": "deterministic SHA-256 after candidate hash and this protocol are frozen", "opponents": ["B1", "v57", "order_book", "metav4"], "seats": [0, 1], "primary_metric": "win=1,tie=0.5,loss=0"},
        "acceptance": {"paired_score_delta_gt": 0, "one_sided_90_seed_cluster_bootstrap_lower_gt": 0, "each_opponent_score_delta_gte": 0, "w_to_l_lte_l_to_w": True, "critical_collapse_count": 0},
        "family_warning": "the four public opponents are related and are not treated as four independent families",
    })
    write("HOLDOUT_DECISION.json", {
        "decision": "NOT_RUN_DEVELOPMENT_GATE_FAILED",
        "new_holdout_seeds_generated": 0, "holdout_games": 0,
        "failed_conditions": {"P0M1_oracle_score_delta": 0.0, "P0M1_rule_score_delta": -8.0, "P1M0_score_delta": -12.0},
        "champion": "P0M0_B1", "champion_sha256": generated["P0M0_B1"]["sha256"],
    })
    write("metrics/route_summary.json", route_summary())
    write("metrics/input_ledger_regressions.json", {
        "seed612609264_step645": {"final_orders": [["SELL", "STRAWBERRY", 13], ["SELL", "WOOL", 7], ["BUY_SEED", "CARROT", 1]], "effective_own_fills": {"STRAWBERRY": 13, "WOOL": 7}, "opponent_wool_sale": 0, "fixed_result": "own WOOL 7 is no longer attributed to opponent"},
        "seed612609254_step456": {"item": "WOOL", "start_price": 37, "own_fill": 12, "true_opponent_fill_test_only": 12, "public_runtime_interval": {"confidence": "censored", "lower": 0, "upper": 100}, "fixed_result": "negative estimate removed; unobserved zero is not encoded as no sale"},
        "seed532609243_step668": {"classification": "REDUNDANT_WITH_BASELINE", "wool_sell_orders": 1, "quantity": 3, "double_order": False},
        "truth_usage": "simulator truth appears only in test assertions/evaluation labels, never runtime features",
    })
    replay_dir = ROUND12 / "replays"
    replay_dir.mkdir(exist_ok=True)
    write("replays/INDEX.json", replay_index())
    write("FINAL_MANIFEST.json", manifest())
    print(json.dumps({"files": json.loads((ROUND12 / "FINAL_MANIFEST.json").read_text())["file_count"], "route": route_summary()["decision"]}, indent=2))


if __name__ == "__main__":
    main()
