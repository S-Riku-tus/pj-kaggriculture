"""Causal library table, shared-seed uncertainty, and emitted/committed contracts."""

# ruff: noqa: E402, E501, B023, E731

from __future__ import annotations

import argparse
import copy
import gzip
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluation.replay import action, observation
from scripts.evaluation.runner import _import_module
from scripts.evaluation.safety import _apply_fields, simulate_turn
from scripts.research_20260911 import EVAL, OUT, digest, save


def read_replay(path):
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def seed_ci(rows, repetitions=5000):
    groups = defaultdict(list)
    for row in rows:
        groups[row["seed"]].append(row["delta_win_score"])
    means = [sum(v) / len(v) for v in groups.values()]
    rng = random.Random(20260911)
    samples = sorted(sum(rng.choices(means, k=len(means))) / len(means) for _ in range(repetitions))
    return {"seed_blocks": len(means), "ci95": [samples[int(0.025 * repetitions)], samples[int(0.975 * repetitions)]],
            "method": "resample whole seeds; both seats and all sources move together; conditional on this source pool"}


def table():
    datasets = {}
    for folder in sorted(EVAL.glob("v*/development")):
        path = folder / "pairs.jsonl"
        if path.exists():
            datasets[folder.parent.name] = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    records = {}
    summaries = {}
    for version, rows in datasets.items():
        summaries[version] = {
            "n": len(rows), "baseline": dict(Counter(r["control"]["result"] for r in rows)),
            "candidate": dict(Counter(r["treatment"]["result"] for r in rows)),
            "loss_to_win": sum(r["loss_to_win"] for r in rows), "win_to_loss": sum(r["win_to_loss"] for r in rows),
            "safe_loss_to_win": sum(r["loss_to_win"] and r["behavioral_isolation_valid"] and not r["candidate_new_major_regressions"] for r in rows),
            "hard_safety_pairs": sum(bool(r["candidate_new_major_regressions"]) for r in rows),
            "safety_reasons": dict(Counter(reason for r in rows for reason in r["candidate_new_major_regressions"])),
            "invalid": sum(not r["behavioral_isolation_valid"] for r in rows), "seed_ci": seed_ci(rows),
        }
        for row in rows:
            key = f"{row['lineage_id']}/{row['seed']}/{row['seat']}"
            record = records.setdefault(key, {"key": key, "source": row["lineage_id"], "seed": row["seed"], "seat": row["seat"], "baseline": row["control"], "routes": {}})
            assert record["baseline"] == row["control"]
            record["routes"][version] = {
                "result": row["treatment"]["result"], "score": row["treatment"]["score"],
                "ours": row["treatment"]["ours"], "theirs": row["treatment"]["theirs"],
                "delta_self": row["delta_self_coin"], "delta_opponent": row["delta_opponent_coin"], "delta_margin": row["delta_margin"],
                "safe": row["behavioral_isolation_valid"] and not row["candidate_new_major_regressions"],
                "safety_reasons": row["candidate_new_major_regressions"],
                "activated": row["incremental_treatment"], "divergence": row["divergence_audit"],
            }
    flips, oracle_sum = [], 0.0
    for key, record in records.items():
        best = max([record["baseline"]["score"], *(r["score"] for r in record["routes"].values() if r["safe"])])
        record["oracle_score"] = best
        record["oracle_gain"] = best - record["baseline"]["score"]
        oracle_sum += record["oracle_gain"]
        if record["baseline"]["result"] == "loss" and best == 1:
            flips.append(key)
    save(OUT / "route_value_table.json", {
        "summaries": summaries, "records": list(records.values()),
        "offline_oracle": {"scope": "observed spent development only; outcome-selected diagnostic, not deployable policy",
                           "safe_loss_to_win_keys": flips, "delta_score": oracle_sum / len(records) if records else None},
    })
    print(json.dumps({"summaries": summaries, "oracle_flips": flips}, indent=2), flush=True)


def contract(version, limit=0):
    path = EVAL / version / "development/pairs.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    prereg = json.loads((OUT / "options_preregistration.json").read_text(encoding="utf-8"))
    variant = next(v for v in prereg["variants"] if v["version"] == version)
    output = EVAL / version / "contracts.jsonl"
    old = [json.loads(x) for x in output.read_text(encoding="utf-8").splitlines()] if output.exists() else []
    done = {r["key"] for r in old}
    for row in rows[:limit or None]:
        key = f"{row['lineage_id']}/{row['seed']}/{row['seat']}"
        if key in done:
            continue
        replay_path = Path(row["replay_artifacts"]["treatment"])
        replay = read_replay(replay_path)
        seat = row["seat"]
        module = _import_module(ROOT / variant["runtime"], "contract")
        original_agent = module.base.agent
        captured = {}

        def spy(*args):
            result = original_agent(*args)
            captured["action"] = copy.deepcopy(result)
            return result

        module.base.agent = spy
        counts = Counter()
        trace = []
        previous_extra = 0
        for step in range(719):
            obs = copy.deepcopy(observation(replay, step, seat))
            emitted = module.agent(obs, replay["configuration"])
            recorded = action(replay, step, seat)
            counts["action_fidelity_mismatch"] += emitted != recorded
            original = captured["action"]
            counts["field_rewrite"] += any(original.get(k) != emitted.get(k) for k in ("farmer", "hands"))
            keep = lambda a: [o for o in a.get("market", []) if o[0] != "SELL"]
            counts["required_order_changed"] += keep(original) != keep(emitted)
            counts["oversized_action"] += len(emitted.get("market", [])) > 10
            diagnostic = module.policy_diagnostics(obs)["research_decision"]
            extra = diagnostic["extra_sale_orders"] - previous_extra
            previous_extra = diagnostic["extra_sale_orders"]
            if step < variant["start"]:
                counts["before_start_rewrite"] += emitted != original
                continue
            if not diagnostic["eligible"]:
                continue
            farms = copy.deepcopy(obs["farms"])
            privates = [copy.deepcopy(observation(replay, step, p)["private"]) for p in (0, 1)]
            actions = [action(replay, step, p) for p in (0, 1)]
            _apply_fields(farms, privates, actions, obs["day"])
            projected = module.base.base._project_shed(obs, original, replay["configuration"])
            counts["shed_projection_mismatch"] += projected != privates[seat]["shed"]
            if extra or emitted != original:
                events = simulate_turn(replay, step)[seat]
                new_sales = [e for e in events if e["kind"] == "market_commit" and e.get("slot", 99) < extra]
                counts["extra_sale_orders"] += extra
                counts["extra_sale_units"] += sum(e["committed"] for e in new_sales)
                counts["extra_sale_cash"] += sum(e.get("cash_delta", 0) for e in new_sales)
                counts["failed_extra_sale"] += sum(e["committed"] != e["requested"] for e in new_sales)
                trace.append({"step": step, "requested_base": original, "emitted": emitted,
                              "before_private": obs["private"], "after_private": observation(replay, step + 1, seat)["private"],
                              "workers": {k: obs["farms"][seat][k] for k in ("farmer", "hands")},
                              "money_before": obs["farms"][seat]["money"], "money_after": observation(replay, step + 1, seat)["farms"][seat]["money"],
                              "extra_order_count": extra, "engine_events": events})
        result = {"key": key, "replay_sha256": digest(replay_path), "counts": dict(counts), "trace": trace}
        with output.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")
        print(version, key, dict(counts), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["table", "contract"])
    parser.add_argument("--version")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.mode == "table":
        table()
    else:
        contract(args.version, args.limit)


if __name__ == "__main__":
    main()
