"""Read-only reaggregation of spent research data; no games or remote requests."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import itertools
import json
import statistics
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data/evaluation/research_20260911_continuations"
OLD = ROOT / "experiments/research_20260911_continuations"
DEFAULT_OUTPUT = ROOT / "data/analysis/research_reassessment_20260914/evidence.json"
INPUT_HASHES: dict[str, str] = {}


def read_bytes(path):
    value = path.read_bytes()
    INPUT_HASHES[path.relative_to(ROOT).as_posix()] = hashlib.sha256(value).hexdigest()
    return value


def read_json(path):
    return json.loads(read_bytes(path))


def read_rows(path):
    return [json.loads(line) for line in read_bytes(path).splitlines() if line.strip()]


def key(row):
    return f"{row['lineage_id']}/{row['seed']}/{row['seat']}"


def valid_delivery(row):
    incidents = row["candidate_incident_classification"]
    return (
        row["incremental_treatment"]
        and row["behavioral_isolation_valid"]
        and not incidents["treatment_delivery_failure"]
        and not row["candidate_new_major_regressions"]
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT / "data/analysis")
    if output.exists():
        raise SystemExit("Output already exists; choose a new path to preserve this audit.")

    decision = read_json(OLD / "final_decision.json")
    baseline, datasets, coverage = {}, {}, {}
    for version in decision["evaluations"]:
        rows = read_rows(EVAL / version / "development/pairs.jsonl")
        assert len(rows) == len({key(row) for row in rows}) == 32
        for row in rows:
            assert baseline.setdefault(key(row), row["control"]) == row["control"]
        datasets[version] = rows
        active = [row for row in rows if row["incremental_treatment"]]
        active_losses = [row for row in active if row["control"]["result"] == "loss"]
        coverage[version] = {
            "pairs": len(rows),
            "active": len(active),
            "active_control_wdl": dict(Counter(row["control"]["result"] for row in active)),
            "safe_active_control_losses": sum(valid_delivery(row) for row in active_losses),
            "safe_active_loss_seeds": sorted({row["seed"] for row in active_losses if valid_delivery(row)}),
            "active_sources": dict(Counter(row["lineage_id"] for row in active)),
            "loss_to_win_keys": [key(row) for row in rows if row["loss_to_win"]],
            "win_to_loss_keys": [key(row) for row in rows if row["win_to_loss"]],
            "safe_loss_margin_improvement_keys": [
                key(row) for row in active_losses if valid_delivery(row) and row["delta_margin"] > 0
            ],
        }
    base_rows = datasets["v115p_immediate"]
    losses = [row for row in base_rows if row["control"]["result"] == "loss"]
    margins = [-row["control"]["margin"] for row in losses]
    safe_oracle = []
    for row in base_rows:
        routes = [
            candidate for version, candidates in datasets.items() if version != "v115p_retain_cow"
            for candidate in candidates if key(candidate) == key(row) and valid_delivery(candidate)
        ]
        best = max([row["control"]["score"], *(candidate["treatment"]["score"] for candidate in routes)])
        safe_oracle.append({"key": key(row), "gain": best - row["control"]["score"]})

    checkpoints = (72, 144, 216, 248, 288, 361, 432, 480, 576)
    trajectories = []
    for row in base_rows:
        replay = json.loads(gzip.decompress(read_bytes(Path(row["replay_artifacts"]["control"]))))
        seat = row["seat"]
        assert len(replay["steps"]) == 720
        trace = {}
        for step in checkpoints:
            obs = replay["steps"][step][seat]["observation"]
            trace[str(step)] = {
                "own_money": obs["farms"][seat]["money"],
                "margin": obs["farms"][seat]["money"] - obs["farms"][1 - seat]["money"],
                "shops": obs["town"]["unlocked_shops"],
            }
        trajectories.append({
            "key": key(row), "result": row["control"]["result"], "final_margin": row["control"]["margin"],
            "checkpoints": trace,
            "stored_safety_examples_are_truncated": True,
            "stored_safety_examples": row["safety"]["control"]["engine_action_examples"],
        })
    loss_checkpoint = {
        str(step): {
            "losses": len(losses),
            "already_behind": sum(
                r["checkpoints"][str(step)]["margin"] < 0 for r in trajectories if r["result"] == "loss"
            ),
            "lead_then_loss": sum(
                r["checkpoints"][str(step)]["margin"] > 0 for r in trajectories if r["result"] == "loss"
            ),
            "median_margin": statistics.median(
                r["checkpoints"][str(step)]["margin"] for r in trajectories if r["result"] == "loss"
            ),
        } for step in checkpoints
    }
    rr = read_rows(EVAL / "complete_policy/round_robin.jsonl")
    groups = defaultdict(list)
    for row in rr:
        groups[(row["a"], row["b"])].append(row)
    edges, matchup = set(), []
    for (a, b), rows in sorted(groups.items()):
        wins = sum(row["result"] == "win" for row in rows)
        draws = sum(row["result"] == "draw" for row in rows)
        losses_n = len(rows) - wins - draws
        if wins > losses_n:
            edges.add((a, b))
        elif losses_n > wins:
            edges.add((b, a))
        matchup.append({"a": a, "b": b, "wdl": [wins, draws, losses_n]})
    nodes = sorted({node for edge in edges for node in edge})
    cycles = set()
    for size in range(3, len(nodes) + 1):
        for cycle in itertools.permutations(nodes, size):
            if cycle[0] == min(cycle) and all((cycle[i], cycle[(i + 1) % size]) in edges for i in range(size)):
                cycles.add(cycle)

    for name in ("source", "archive", "engine"):
        path = {
            "source": ROOT / "agents/v111/main.py",
            "archive": ROOT / "experiments/research_20260910/champion_v111.tar.gz",
            "engine": ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py",
        }[name]
        assert hashlib.sha256(read_bytes(path)).hexdigest() == decision["production_champion"][f"{name}_sha256"]
    trajectory_by_key = {row["key"]: row for row in trajectories}
    untested_losses = [
        {
            "key": key(row), "final_margin": row["control"]["margin"],
            "cash_at_248": trajectory_by_key[key(row)]["checkpoints"]["248"]["own_money"],
            "note": "Cash below 1500 fails one conjunct; other feasibility conditions may also fail.",
        }
        for row in datasets["v115p_managed_sheep"]
        if row["control"]["result"] == "loss" and not row["incremental_treatment"]
    ]
    postmortem = read_json(OLD / "postmortem_recomputed.json")
    lifespan = {}
    for arm in ("control", "treatment"):
        lifespan[arm] = {
            "cumulative_decay_lost_units": postmortem["totals"][f"{arm}.lost_current_units.lifespan_decay"],
            "remaining_units_at_final_weed_transition": sum(
                int(units) * count
                for record in postmortem["records"]
                for units, count in record[arm]["lifecycle"]["lifespan_end_remaining_yield"].items()
            ),
        }
    for path in (
        ROOT / "scripts/evaluation/lifecycle.py", ROOT / "scripts/research_20260911.py",
        ROOT / "scripts/analyze_continuations_20260911.py", ROOT / "scripts/finalize_research_20260912.py",
        ROOT / "scripts/managed_animal_template.py", ROOT / "scripts/retain_cow_option_template.py",
        ROOT / "agents/v115p_immediate/option.json", ROOT / "agents/v115p_town/option.json",
    ):
        read_bytes(path)
    result = {
        "created_at": datetime.now(UTC).isoformat(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "scope": "Spent Development reaggregation only; no new games, no Fresh or remote replay access.",
        "coverage": coverage, "unique_baseline_contexts": len(baseline),
        "unique_baseline_losses": len(losses),
        "loss_deficit": {"min": min(margins), "median": statistics.median(margins), "max": max(margins),
                         "within": {str(n): sum(m <= n for m in margins) for n in (2000, 5000, 10000)}},
        "oracle": {"mean_gain": statistics.mean(row["gain"] for row in safe_oracle), "rows": safe_oracle},
        "loss_checkpoints": loss_checkpoint, "control_trajectories": trajectories,
        "managed_animal_untested_losses": untested_losses,
        "lifespan_metric_semantics": lifespan,
        "round_robin": {"games": len(rr), "matchups": matchup, "strict_majority_edges": sorted(edges),
                        "strict_majority_cycles": sorted(cycles),
                        "inference": "No cycle in this sampled graph; not a proof of population transitivity."},
        "historical_leader": decision["current_leader"],
        "holdout_record": read_json(OLD / "final_holdout_audit.json"),
        "input_sha256": INPUT_HASHES,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("coverage", "loss_deficit", "loss_checkpoints", "round_robin")}, indent=2))


if __name__ == "__main__":
    main()
