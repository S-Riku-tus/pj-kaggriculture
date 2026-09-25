"""Fresh-process, both-seat clock validation for the frozen Round6 v1 archive."""

from __future__ import annotations

import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.evaluate_round6_anchors import (  # noqa: E402
    EXPERIMENT,
    _run_game,
    prepare_archives,
    read_preregistration,
    sha256,
    write_json,
)

CANDIDATE = "round6_sequence_bc_v1"
ANCHOR = "v122"
SEED = 2026102201


def execute(task: dict[str, Any]) -> dict[str, Any]:
    return _run_game(task)


def main() -> None:
    preregistration = read_preregistration()
    run_root, extracted = prepare_archives([CANDIDATE, ANCHOR])
    output = EXPERIMENT / "candidate_v1_runtime_validation"
    tasks = [
        {
            "arm": CANDIDATE,
            "opponent": ANCHOR,
            "seed": SEED,
            "seat": seat,
            "agent_main": str(extracted[CANDIDATE]),
            "opponent_main": str(extracted[ANCHOR]),
            "replay_path": str(output / f"seed_{SEED}_seat_{seat}.json.gz"),
        }
        for seat in (0, 1)
    ]
    results = []
    with ProcessPoolExecutor(max_workers=2, max_tasks_per_child=1) as executor:
        futures = [executor.submit(execute, task) for task in tasks]
        for future in as_completed(futures):
            results.append(future.result())
    archive = ROOT / preregistration["arms"][CANDIDATE]["archive"]
    rows = []
    for result in sorted(results, key=lambda value: value["seat"]):
        replay = Path(result["replay_path"])
        rows.append(
            {
                "seat": result["seat"],
                "statuses": result["statuses"],
                "stored_states": result["stored_states"],
                "elapsed_seconds": result["elapsed_seconds"],
                "cold_import_seconds": result["cold_import_seconds"],
                "inference": result["inference"],
                "replay": str(replay.relative_to(ROOT)),
                "replay_sha256": sha256(replay),
            }
        )
    payload = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "candidate": CANDIDATE,
        "archive": str(archive.relative_to(ROOT)),
        "archive_sha256": sha256(archive),
        "opponent": ANCHOR,
        "seed": SEED,
        "fresh_process_per_game": True,
        "extraction_root": str(run_root),
        "act_timeout_seconds": 1.0,
        "results": rows,
        "all_done": all(row["statuses"] == ["DONE", "DONE"] and row["stored_states"] == 720 for row in rows),
        "clock_pass": all(row["inference"]["max_seconds"] < 1.0 for row in rows),
        "online_operations": 0,
    }
    write_json(output / "summary.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
