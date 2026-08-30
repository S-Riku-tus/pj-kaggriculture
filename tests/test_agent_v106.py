from __future__ import annotations

import json
import shutil
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from agents.v106 import main as v106
from tests.test_agent_v105 import make_obs


def test_v106_uses_documented_animal_escape_boundary() -> None:
    farm = make_obs()["farms"][0]
    farm["tiles"][0][0] = {
        "kind": "PASTURE",
        "animal": "COW",
        "fed_today": False,
        "consecutive_unfed": 1,
    }
    assert not v106._resource_emergency(farm)
    farm["tiles"][0][0]["consecutive_unfed"] = 2
    assert v106._resource_emergency(farm)
    farm["tiles"][0][0]["fed_today"] = True
    assert not v106._resource_emergency(farm)


def test_v106_is_pure_and_submission_is_self_contained(tmp_path: Path) -> None:
    v106.reset_runtime_state()
    assert v106.ENABLE_SPEC_ACCURATE_DAILY_RECOVERY
    assert v106.v105._resource_emergency is v106._resource_emergency
    obs = make_obs(hands=2)
    before = deepcopy(obs)
    action = v106.agent(obs)
    assert obs == before
    assert set(action) == {"farmer", "hands", "market"}
    assert len(action["hands"]) == 2
    assert len(action["market"]) <= 10
    assert v106.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

    root = Path(__file__).resolve().parents[1]
    submission = tmp_path / "submission"
    elsewhere = tmp_path / "elsewhere"
    submission.mkdir()
    elsewhere.mkdir()
    manifest = root / "agents" / "v106" / "submission_manifest.json"
    for entry in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
        source = (root / "agents" / "v106" / entry["source"]).resolve()
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
assert namespace["v11"].v10.MODEL is not None
assert namespace["v105"]._resource_emergency is namespace["_resource_emergency"]
assert set(namespace["agent"]({})) == {"farmer", "hands", "market"}
"""
    subprocess.run(
        [sys.executable, "-c", code, str(submission), str(elsewhere)],
        check=True,
        cwd=elsewhere,
        capture_output=True,
        text=True,
    )
