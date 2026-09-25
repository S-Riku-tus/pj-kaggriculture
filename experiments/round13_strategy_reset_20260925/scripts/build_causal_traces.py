"""Build compact, inspectable first-difference traces from reactive replays."""

from __future__ import annotations

import gzip
import json
from pathlib import Path


ROUND13 = Path(__file__).resolve().parents[1]
REPLAYS = ROUND13 / "metrics/development/replays"
CASES = [
    {
        "label": "local_margin_improvement_not_score_improvement",
        "arm": "M1_deadline_market",
        "opponent": "v57",
        "seed": 812609254,
        "seat": 1,
        "interpretation": "Both branches remain wins; margin improves because the opponent loses more cash than self. This is not a score promotion signal.",
    },
    {
        "label": "clear_worsening",
        "arm": "P_ROTATE2",
        "opponent": "barnyard",
        "seed": 812609252,
        "seat": 0,
        "interpretation": "The completed conversion changes W to L and destroys both self cash and margin.",
    },
    {
        "label": "no_effect_not_triggered",
        "arm": "P_ROTATE2",
        "opponent": "B1",
        "seed": 812609253,
        "seat": 0,
        "interpretation": "Observable trigger never fires; every final action and the terminal state match B1.",
    },
]


def load(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return json.load(stream)


def replay_path(arm: str, opponent: str, seed: int, seat: int) -> Path:
    return REPLAYS / arm / opponent / f"seed_{seed}_seat_{seat}.json.gz"


def observation_summary(observation: dict) -> dict:
    player = int(observation["player"])
    farm = observation["farms"][player]
    private = observation["private"]
    return {
        "step": int(observation["step"]),
        "day": int(observation["day"]),
        "hour": int(observation["hour"]),
        "money": farm["money"],
        "farmer": farm["farmer"],
        "hands": farm["hands"],
        "shed": private["shed"],
        "seeds": private["seeds"],
        "inventories": private["inventories"],
        "market_prices": observation["market"]["prices"],
        "market_inventory": observation["market"]["inventory"],
        "shops": observation["town"]["unlocked_shops"],
    }


def terminal_summary(replay: dict, seat: int) -> dict:
    terminal = replay["terminal"]
    rewards = terminal["rewards"]
    mine, other = float(rewards[seat]), float(rewards[1 - seat])
    return {
        "statuses": terminal["statuses"],
        "self_cash": mine,
        "opponent_cash": other,
        "margin": mine - other,
        "result": "W" if mine > other else "L" if mine < other else "D",
        "final_public_shops": terminal["observations"][seat]["town"]["unlocked_shops"],
    }


def main() -> None:
    output = []
    for case in CASES:
        arm = case["arm"]
        opponent = case["opponent"]
        seed = case["seed"]
        seat = case["seat"]
        candidate_path = replay_path(arm, opponent, seed, seat)
        baseline_path = replay_path("D0_B1", opponent, seed, seat)
        candidate, baseline = load(candidate_path), load(baseline_path)
        differences = []
        for c_decision, b_decision in zip(candidate["decisions"], baseline["decisions"]):
            c_action = c_decision["actions"][seat]
            b_action = b_decision["actions"][seat]
            if c_action != b_action:
                differences.append((c_decision, b_decision))
        first = differences[0] if differences else None
        trace = {
            **case,
            "evaluation_mode": "REACTIVE_FULLGAME",
            "candidate_replay": candidate_path.relative_to(ROUND13).as_posix(),
            "baseline_replay": baseline_path.relative_to(ROUND13).as_posix(),
            "different_action_steps": len(differences),
            "candidate_terminal": terminal_summary(candidate, seat),
            "baseline_terminal": terminal_summary(baseline, seat),
            "agent_telemetry": candidate.get("agent_telemetry", {}),
        }
        if first:
            c_decision, b_decision = first
            step = int(c_decision["step"])
            next_index = min(step + 1, len(candidate["decisions"]) - 1)
            trace["first_difference"] = {
                "pre_state": observation_summary(c_decision["observations"][seat]),
                "candidate_final_action": c_decision["actions"][seat],
                "baseline_final_action": b_decision["actions"][seat],
                "candidate_next_state": observation_summary(candidate["decisions"][next_index]["observations"][seat]),
                "baseline_next_state": observation_summary(baseline["decisions"][next_index]["observations"][seat]),
            }
        else:
            trace["first_difference"] = None
        output.append(trace)
    path = ROUND13 / "analysis/CAUSAL_TRACES.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
