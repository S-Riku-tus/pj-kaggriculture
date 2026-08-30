from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from agents.v21 import main as v21


def _candidate_tile() -> dict[str, object]:
    return {
        "kind": "PLANT",
        "crop": "STRAWBERRY",
        "planted_day": 10,
        "watered_today": False,
        "consecutive_unwatered": 0,
        "fertilized_until_day": -1,
        "yield_units": 0,
    }


def test_v21_routes_only_residual_empty_pass_units(monkeypatch) -> None:
    monkeypatch.setattr(v21, "ENABLE_PREVENTIVE_WATER", True)
    farm = {"tiles": [[_candidate_tile(), {}, {}, {}]]}
    result = v21._route_idle_preventive_water(
        {"day": 11, "hour": 20},
        farm,
        [(3, 0), (2, 0), (1, 0)],
        [{}, {"WHEAT": 1}, {}],
        [["PASS"], ["PASS"], ["HARVEST"]],
    )
    assert result == [["WEST"], ["PASS"], ["HARVEST"]]


def test_v21_preserves_cutoffs_and_feed_emergencies(monkeypatch) -> None:
    monkeypatch.setattr(v21, "ENABLE_PREVENTIVE_WATER", True)
    candidate = _candidate_tile()
    farm = {"tiles": [[candidate, {}, {}, {}]]}
    args = (farm, [(3, 0)], [{}], [["PASS"]])
    assert v21._route_idle_preventive_water({"day": 11, "hour": 13}, *args) == [["PASS"]]
    assert v21._route_idle_preventive_water({"day": 13, "hour": 20}, *args) == [["PASS"]]
    farm["tiles"][0][1] = {
        "kind": "PASTURE",
        "animal": "COW",
        "fed_today": False,
        "consecutive_unfed": 1,
    }
    assert v21._route_idle_preventive_water({"day": 11, "hour": 20}, *args) == [["PASS"]]


def test_v21_rejects_urgent_finished_and_unreachable_tiles(monkeypatch) -> None:
    monkeypatch.setattr(v21, "ENABLE_PREVENTIVE_WATER", True)
    urgent = _candidate_tile()
    urgent["consecutive_unwatered"] = 1
    finished = _candidate_tile()
    finished.update({"planted_day": 0, "yield_units": 0})
    far = _candidate_tile()
    farm = {"tiles": [[urgent, finished, {}, {}, far]]}
    assert v21._preventive_positions(farm, 30) == []
    farm = {"tiles": [[far, {}, {}, {}, {}]]}
    assert v21._route_idle_preventive_water(
        {"day": 12, "hour": 22}, farm, [(4, 0)], [{}], [["PASS"]]
    ) == [["PASS"]]


def test_v21_wrapper_runs_safe_preposition_first(monkeypatch) -> None:
    calls = []

    def safe(*args):
        calls.append(args)
        return [["EAST"]]

    monkeypatch.setattr(v21, "_SAFE_PREPOSITION", safe)
    result = v21._preposition_idle_workers(
        {"day": 11, "hour": 20},
        {"tiles": [[_candidate_tile(), {}]]},
        {},
        {},
        [(1, 0)],
        [{}],
        [],
        [["PASS"]],
    )
    assert calls
    assert result == [["EAST"]]


def test_v21_submission_is_self_contained(tmp_path: Path) -> None:
    assert v21.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}
    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v21" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v21" / entry["source"]).resolve()
        shutil.copyfile(source, submission / entry["target"])

    code = """
import os
import sys
from pathlib import Path
submission = Path(sys.argv[1]).resolve()
os.chdir(sys.argv[2])
sys.path.append(str(submission))
namespace = {}
main_path = submission / "main.py"
exec(compile(main_path.read_text(encoding="utf-8"), str(main_path), "exec"), namespace)
assert namespace["MODULE_DIR"] == submission
assert namespace["v14"].WINNER_MODEL is not None
assert namespace["v10"]._preposition_idle_workers is namespace["_preposition_idle_workers"]
assert namespace["v14"].v11.v10.MODEL is not None
assert set(namespace["agent"]({})) == {"farmer", "hands", "market"}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        capture_output=True,
        text=True,
    )
