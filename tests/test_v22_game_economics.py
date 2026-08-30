from __future__ import annotations

from scripts import analyze_v22_game_economics as economics


def test_one_time_crop_output_includes_initial_unit() -> None:
    assert economics._crop_output("WHEAT", False) == 4
    assert economics._crop_output("WHEAT", True) == 6
    assert economics._crop_output("CARROT", False) == 3
    assert economics._crop_output("CARROT", True) == 4


def test_melon_fertilizer_compresses_work_without_increasing_output() -> None:
    assert economics._crop_output("MELON", False) == 6
    assert economics._crop_output("MELON", True) == 6
    assert economics._crop_actions("MELON", False) == {
        "plant": 1,
        "water_lower_bound": 8,
        "harvest_lower_bound": 1,
        "fertilize_lower_bound": 0,
        "tile_actions_lower_bound": 10,
    }
    assert economics._crop_actions("MELON", True) == {
        "plant": 1,
        "water_lower_bound": 6,
        "harvest_lower_bound": 1,
        "fertilize_lower_bound": 1,
        "tile_actions_lower_bound": 9,
    }


def test_ongoing_crop_service_counts_remain_distinct() -> None:
    assert economics._crop_actions("STRAWBERRY", False)["tile_actions_lower_bound"] == 11
    assert economics._crop_actions("STRAWBERRY", True)["tile_actions_lower_bound"] == 14
