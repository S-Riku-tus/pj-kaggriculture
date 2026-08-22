from __future__ import annotations

from scripts.train_v5_delta_strategy import INTENT_NAMES, _intent_label


def test_delta_intents_align_actions_to_the_previous_observation() -> None:
    replay = {
        "steps": [
            [{"action": {"farmer": ["DIG"], "hands": [], "market": []}}],
            [
                {
                    "action": {
                        "farmer": ["PLANT", "WHEAT"],
                        "hands": [["BUILD_PASTURE"], ["PLANT", "STRAWBERRY"]],
                        "market": [
                            ["BUY_ANIMAL", "COW", 2],
                            ["BUY_ANIMAL", "SHEEP", 1],
                            ["BUY_LAND", "NE"],
                        ],
                    }
                }
            ],
            [{"action": {"farmer": ["DIG"], "hands": [], "market": []}}],
            [{"action": {"farmer": ["DIG"], "hands": [], "market": []}}],
        ]
    }
    values = dict(zip(INTENT_NAMES, _intent_label(replay, seat=0, start=0, horizon=2), strict=True))
    assert values == {
        "BUY_COW": 2.0,
        "BUY_SHEEP": 1.0,
        "BUY_LAND": 1.0,
        "PLANT_WHEAT": 1.0,
        "PLANT_STRAWBERRY": 1.0,
        "BUILD_PASTURE": 1.0,
        "DIG": 1.0,
    }


def test_delta_intents_do_not_include_action_after_horizon() -> None:
    replay = {
        "steps": [
            [{"action": None}],
            [{"action": {"farmer": ["PASS"], "hands": [], "market": []}}],
            [{"action": {"farmer": ["PASS"], "hands": [], "market": []}}],
            [{"action": {"farmer": ["DIG"], "hands": [], "market": []}}],
        ]
    }
    values = dict(zip(INTENT_NAMES, _intent_label(replay, seat=0, start=0, horizon=2), strict=True))
    assert values["DIG"] == 0.0
