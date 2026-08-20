from __future__ import annotations

from kaggle_environments import make

from agents.v1.main import agent


def test_agent_completes_official_environment_smoke_match() -> None:
    env = make(
        "kaggriculture",
        configuration={"episodeSteps": 120, "seed": 20260821, "weedSpawnChance": 0.0},
        debug=True,
    )
    env.run([agent, "starter"])
    final = env.steps[-1]
    assert [state.status for state in final] == ["DONE", "DONE"]
    assert final[0].reward is not None
    assert float(final[0].reward) >= 0
