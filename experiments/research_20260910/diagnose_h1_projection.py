"""Postmortem only; do not change the frozen candidate or thresholds."""

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agents.v114r1 import main as candidate
from scripts.evaluation.replay import observation

baseline = [json.loads(line) for line in (ROOT / "data/evaluation/research_20260910/discovery/baseline.jsonl").read_text(encoding="utf-8").splitlines()]
rows = []
for row in baseline:
    if row["seat"] != 0:
        continue
    with gzip.open(row["replay_path"], "rt", encoding="utf-8") as handle:
        replay = json.load(handle)
    obs = observation(replay, 153, row["seat"])
    for route in ("default", "yarn_second"):
        failure = {}
        def trace(frame, event, arg):
            if frame.f_code is candidate._route_relative_value.__code__ and event == "return" and arg is None:
                failure.update({key: frame.f_locals.get(key) for key in ("step", "order", "own_money", "hires", "lands")})
            return trace
        sys.settrace(trace)
        try:
            value = candidate._route_relative_value(obs, route, 1.0)
        finally:
            sys.settrace(None)
        rows.append({"source": row["candidate_id"], "seed": row["requested_seed"], "route": route,
                     "actual_control_completed": row["final_statuses"] == ["DONE", "DONE"],
                     "initial_cash": obs["farms"][0]["money"], "projected_value": value,
                     "first_projected_insolvency": failure})
target = ROOT / "experiments/research_20260910/h1_projection_postmortem.json"
target.write_text(json.dumps({"role": "postmortem Discovery; no retuning", "rows": rows}, indent=2), encoding="utf-8")
print("projection rows", len(rows), "infeasible", sum(r["projected_value"] is None for r in rows))
