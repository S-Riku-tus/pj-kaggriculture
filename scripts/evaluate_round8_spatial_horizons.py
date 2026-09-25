"""Run free-execution horizon checks for standalone Round8 spatial archives."""

from __future__ import annotations

import gzip
import hashlib
import json
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from kaggle_environments import make

ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "experiments" / "round8_execution_reset_20260922" / "phase_c_spatial"
ARCHIVES = {
    "spatial_pure": ROOT
    / "artifacts/submissions/round8_spatial_bc_20260922_seed20260922_pure_v6.tar.gz",
    "spatial_hybrid": ROOT
    / "artifacts/submissions/round8_spatial_bc_20260922_seed20260922_hybrid_v6.tar.gz",
}
HORIZONS = (24, 96, 192)
SEED = 2026102290


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tile_metrics(observation: dict[str, Any], seat: int) -> dict[str, Any]:
    tiles = [tile for row in observation["farms"][seat]["tiles"] for tile in row if isinstance(tile, dict)]
    return {
        "money": float(observation["farms"][seat].get("money", 0)),
        "hands": len(observation["farms"][seat].get("hands", [])),
        "land": len(observation["farms"][seat].get("unlocked_quadrants", [])),
        "crops": sum(tile.get("kind") == "PLANT" for tile in tiles),
        "animals": sum(bool(tile.get("animal")) for tile in tiles),
        "yield_on_tiles": sum(int(tile.get("yield_units", 0)) for tile in tiles),
    }


def main() -> None:
    output = EXPERIMENT / "free_horizons_v2"
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    output.mkdir(parents=True)
    temp_parent = ROOT.parent / ".round8_tmp"
    temp_parent.mkdir(exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix="spatial_horizon_", dir=temp_parent) as temporary:
        temporary_path = Path(temporary)
        for arm, archive in ARCHIVES.items():
            target = temporary_path / arm
            target.mkdir()
            with tarfile.open(archive, "r:gz") as stream:
                stream.extractall(target, filter="data")
            for horizon in HORIZONS:
                env = make(
                    "kaggriculture",
                    configuration={"episodeSteps": horizon + 1, "seed": SEED},
                    debug=True,
                )
                env.run([str(target / "main.py"), "pass"])
                replay = env.toJSON()
                replay_path = output / f"{arm}_{horizon}_turns.json.gz"
                with gzip.open(replay_path, "wt", encoding="utf-8") as stream:
                    json.dump(replay, stream, ensure_ascii=False, separators=(",", ":"))
                final = replay["steps"][-1][0]["observation"]
                first_hire = first_land = None
                max_hands = max_crops = max_animals = 0
                for record, states in enumerate(replay["steps"]):
                    observation = states[0]["observation"]
                    metrics = tile_metrics(observation, 0)
                    max_hands = max(max_hands, int(metrics["hands"]))
                    max_crops = max(max_crops, int(metrics["crops"]))
                    max_animals = max(max_animals, int(metrics["animals"]))
                    action = states[0].get("action") or {}
                    if first_hire is None and any(order and order[0] == "HIRE" for order in action.get("market", [])):
                        first_hire = record
                    if first_land is None and int(metrics["land"]) > 1:
                        first_land = record
                rows.append(
                    {
                        "arm": arm,
                        "archive": str(archive.relative_to(ROOT)),
                        "archive_sha256": sha256(archive),
                        "opponent": "built-in pass",
                        "seed": SEED,
                        "requested_decisions": horizon,
                        "stored_states": len(replay["steps"]),
                        "actual_decisions": len(replay["steps"]) - 1,
                        "statuses": [state["status"] for state in replay["steps"][-1]],
                        "final": tile_metrics(final, 0),
                        "first_hire_record": first_hire,
                        "first_land_record": first_land,
                        "max_hands": max_hands,
                        "max_crops": max_crops,
                        "max_animals": max_animals,
                        "replay": str(replay_path.relative_to(ROOT)),
                        "replay_sha256": sha256(replay_path),
                        "teacher_state_reinjection": False,
                    }
                )
    summary = output / "summary.json"
    summary.write_text(
        json.dumps(
            {
                "created_at_utc": datetime.now(UTC).isoformat(),
                "purpose": "free execution smoke checks; not a strength or generalization estimate",
                "engine": {
                    "path": str(
                        Path(".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py")
                    ),
                    "sha256": sha256(
                        ROOT
                        / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
                    ),
                },
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "files": [
            {
                "path": str(path.relative_to(ROOT)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
            for path in sorted(output.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
