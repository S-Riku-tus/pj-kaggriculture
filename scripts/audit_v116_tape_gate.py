from __future__ import annotations

import ast
import gzip
import hashlib
import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "artifacts"
    / "opponent_pool"
    / "current_20260910"
    / "mooman"
    / "agents"
    / "kaito_v56_e052a.py"
)
REPLAYS = (
    ROOT
    / "data"
    / "evaluation"
    / "research_20260914_lowcash"
    / "discovery"
    / "replays"
)
DECISION = ROOT / "experiments" / "research_20260914_lowcash" / "final_decision.json"
OUTPUT = (
    ROOT
    / "experiments"
    / "research_20260914_next_strategy"
    / "opponent_tape_audit.json"
)


def literal_assignments(source: str) -> dict[str, object]:
    wanted = {"_TAPE_POS", "_TAPE2_POS", "_E030_N"}
    values: dict[str, object] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                values[target.id] = ast.literal_eval(node.value)
    missing = wanted - values.keys()
    if missing:
        raise RuntimeError(f"missing source constants: {sorted(missing)}")
    return values


def main() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    values = literal_assignments(source)
    tape_pos = values["_TAPE_POS"]
    tape2_pos = values["_TAPE2_POS"]
    e030_n = int(values["_E030_N"])
    decision = json.loads(DECISION.read_text(encoding="utf-8"))

    pattern = re.compile(r"replays[\\/]discovery[\\/](.*?)[\\/]seed_(\d+)_seat_(\d+)")
    contexts = []
    aggregate: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "contexts": 0,
            "tape_signature_gate_matches": 0,
            "tape2_signature_gate_matches": 0,
            "tape2_exact_10_of_10": 0,
        }
    )

    for replay_path in sorted(REPLAYS.rglob("treatment.json.gz")):
        match = pattern.search(str(replay_path))
        if match is None:
            raise RuntimeError(f"unexpected replay path: {replay_path}")
        opponent, seed, seat = match.group(1), int(match.group(2)), int(match.group(3))
        with gzip.open(replay_path, "rt", encoding="utf-8") as handle:
            replay = json.load(handle)

        hits = 0
        hits2 = 0
        for step in sorted(tape_pos):
            observation = replay["steps"][step][seat]["observation"]
            opponent_farm = observation["farms"][1 - seat]
            farmer = list(opponent_farm.get("farmer") or [])
            hands = [list(item) for item in (opponent_farm.get("hands") or [])]
            expected_farmer, expected_hands = tape_pos[step]
            expected_farmer2, expected_hands2 = tape2_pos[step]
            hits += int(farmer == expected_farmer and hands == expected_hands)
            hits2 += int(farmer == expected_farmer2 and hands == expected_hands2)

        step1 = replay["steps"][1][seat]["observation"]
        wheat_inventory = int(step1["market"]["inventory"]["WHEAT"])
        inferred_other_demand = 10000 - wheat_inventory - e030_n
        n13_gate = 10 <= inferred_other_demand <= 16
        tape_gate = hits >= 7
        tape2_gate = hits2 >= 7 and n13_gate
        selected_mode = "tape" if tape_gate else "tape2" if tape2_gate else "other"

        record = {
            "opponent": opponent,
            "seed": seed,
            "seat": seat,
            "tape_position_hits": hits,
            "tape2_position_hits": hits2,
            "step1_wheat_inventory": wheat_inventory,
            "inferred_other_demand": inferred_other_demand,
            "n13_gate": n13_gate,
            "selected_mode": selected_mode,
            "replay": str(replay_path.relative_to(ROOT)),
        }
        contexts.append(record)
        row = aggregate[opponent]
        row["contexts"] += 1
        row["tape_signature_gate_matches"] += int(tape_gate)
        row["tape2_signature_gate_matches"] += int(tape2_gate)
        row["tape2_exact_10_of_10"] += int(hits2 == 10 and n13_gate)

    source_matrix = decision["source_matrix"]
    aggregate_rows = {}
    for opponent, counts in sorted(aggregate.items()):
        metrics = source_matrix[opponent]
        aggregate_rows[opponent] = {
            **counts,
            "candidate_delta_win_score": metrics["delta_win_score"],
            "loss_to_win": metrics["loss_to_win"],
            "candidate_wdl": [
                metrics["candidate"]["wins"],
                metrics["candidate"]["draws"],
                metrics["candidate"]["losses"],
            ],
        }

    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "purpose": (
            "Post-completion audit of whether v116_mooman_complete's hard-coded "
            "opponent-route tape gate fired in the spent 32-context discovery panel."
        ),
        "source": str(SOURCE.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "replay_scope": {
            "contexts": len(contexts),
            "seeds": sorted({row["seed"] for row in contexts}),
            "both_seats": sorted({row["seat"] for row in contexts}) == [0, 1],
            "outcomes_already_spent": True,
        },
        "gate_definition": {
            "position_steps": sorted(tape_pos),
            "minimum_position_hits": 7,
            "tape2_requires_n13_gate": True,
            "n13_interval_inclusive": [10, 16],
            "future_sell_horizon": 4,
            "source_lines": {
                "position_and_future_sell_tables": [2606, 2613],
                "observer": [2616, 2649],
                "future_prediction": [2652, 2662],
            },
        },
        "by_opponent": aggregate_rows,
        "contexts": contexts,
        "interpretation": [
            (
                "The tape2 gate fires in every mooman_e052a and souvik_v4 context "
                "and never fires for ggmljs_v16 or qeinstein_moev2."
            ),
            (
                "The mooman_e052a block is also a self-match. The souvik_v4 uplift "
                "is therefore confounded with exact known-route recognition and its "
                "hard-coded future sell schedule."
            ),
            (
                "The qeinstein_moev2 uplift remains independent of this tape2 gate, "
                "but the only raw-Safety-clean L-to-W result is both seats of one seed block."
            ),
        ],
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
