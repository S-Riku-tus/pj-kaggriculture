"""Non-promotion diagnostics: terminal upper bound and latest replay fidelity."""

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "experiments/research_20260910"


def read(path):
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    from scripts.evaluation.replay import action, observation
    from scripts.evaluation.runner import _call, _import_module

    metrics = read(ROOT / "data/analysis/research_20260910_final/current_episode_seat_metrics.json")
    manifest = read(ROOT / "data/analysis/research_20260910_final/current_replay_input_manifest.json")
    paths = {row["episode_id"]: ROOT / row["path"] for row in manifest}
    fidelity = []
    for row in metrics:
        if "unmapped" not in row["cohort"]:
            continue
        replay = read(paths[row["episode_id"]])
        for version in ("v111", "v113"):
            module = _import_module(ROOT / f"agents/{version}/main.py", "fidelity")
            mismatches = []
            errors = []
            for step in range(719):
                try:
                    emitted = _call(module.agent, observation(replay, step, row["seat"]), None)
                    if emitted != action(replay, step, row["seat"]):
                        mismatches.append(step)
                except Exception as exc:
                    errors.append({"step": step, "error": repr(exc)})
                    break
            fidelity.append(
                {
                    "episode_id": row["episode_id"],
                    "submission_id": row["submission_id"],
                    "source": f"local current {version}, not an authenticated remote archive",
                    "matching_actions": 719 - len(mismatches) if not errors else None,
                    "first_difference": mismatches[0] if mismatches else None,
                    "mismatch_steps": mismatches,
                    "errors": errors,
                    "evidence": "E1 factual-observation action fidelity; no closed-loop causal claim or hash proof",
                }
            )
    (OUT / "latest_submission_action_fidelity.json").write_text(json.dumps(fidelity, indent=2), encoding="utf-8")

    baseline = [
        json.loads(line)
        for line in (ROOT / "data/evaluation/research_20260910/discovery/baseline.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    bounds = []
    for row in baseline:
        replay = read(Path(row["replay_path"]))
        seat = row["seat"]
        before, after = observation(replay, 718, seat), observation(replay, 719, seat)
        private = after.get("private", {})
        products = before["market"]["prices"]
        stock = {
            item: sum(int(inv.get(item, 0)) for inv in [private.get("shed", {}), *private.get("inventories", [])])
            for item in products
        }
        own_upper = sum(
            stock[item] * max(before["market"]["prices"][item], after["market"]["prices"][item]) for item in stock
        )
        # Overly generous opponent-harm bound: appended sells can reduce all
        # later-slot opposing same-product revenue to $1. No future turns exist.
        our_orders = action(replay, 718, seat).get("market", [])
        opposing = action(replay, 718, 1 - seat).get("market", [])
        harm_upper = 0
        for order in opposing[len(our_orders) : 10]:
            if len(order) >= 3 and order[0] == "SELL" and stock.get(order[1], 0) > 0:
                opponent_stock = observation(replay, 718, 1 - seat).get("private", {}).get("shed", {}).get(order[1], 0)
                harm_upper += min(int(order[2]), int(opponent_stock)) * max(0, before["market"]["prices"][order[1]] - 1)
        if len(our_orders) >= 10:
            own_upper = harm_upper = 0
        bounds.append(
            {
                "source": row["candidate_id"],
                "seed": row["requested_seed"],
                "seat": seat,
                "baseline_margin": row["margin"],
                "stranded_stock": stock,
                "free_market_slots": max(0, 10 - len(our_orders)),
                "optimistic_own_gain": own_upper,
                "optimistic_opponent_harm": harm_upper,
                "could_flip_under_bound": row["margin"] < 0 < row["margin"] + own_upper + harm_upper,
            }
        )
    result = {
        "evidence": "E0/E1 optimistic terminal append-only opportunity bound, not an executable causal test",
        "scope": "H2 free SELL slots at t718; field actions and existing market orders retained",
        "caveat": (
            "Generous bound includes carried stock and ignores availability/deposit, price slippage "
            "and simultaneous-order details. It cannot prove a win, only screen insufficient opportunity on this panel."
        ),
        "games": len(bounds),
        "possible_loss_to_win": sum(r["could_flip_under_bound"] for r in bounds),
        "rows": bounds,
    }
    (OUT / "h2_terminal_opportunity_bound.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "latest_fidelity": [{k: v for k, v in r.items() if k != "mismatch_steps"} for r in fidelity],
                "h2_possible_flips": result["possible_loss_to_win"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
