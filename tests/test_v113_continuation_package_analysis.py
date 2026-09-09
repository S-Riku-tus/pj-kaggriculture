from __future__ import annotations

from scripts.analyze_v113_continuation_package import (
    _dominant_no_material_lineage,
    _summarize,
    _timing,
    _window,
)


def _observation(*, after: bool) -> dict:
    own_tiles = [[
        {
            "kind": "PASTURE",
            "animal": "SHEEP" if after else "COW",
            "yield_units": 2,
        },
        {
            "kind": "PLANT",
            "crop": "WHEAT",
            "yield_units": 3,
        },
    ]]
    return {
        "farms": [
            {"tiles": own_tiles, "farmer": [0, 0], "hands": [[1, 0]]},
            {"tiles": [[]], "farmer": [0, 0], "hands": []},
        ],
        "private": {
            "shed": {"WOOL": 0 if after else 2, "WHEAT": 3 if after else 0},
            "seeds": {"CARROT": 3 if after else 0},
            "inventories": [{}, {}],
        },
        "market": {
            "prices": {
                "WHEAT": 30,
                "CARROT": 35,
                "TOMATO": 60,
                "STRAWBERRY": 120,
                "MELON": 250,
                "EGG": 50,
                "MILK": 160,
                "WOOL": 210 if after else 200,
                "FERTILIZER": 80,
            },
            "inventory": {
                "WHEAT": 10_000,
                "CARROT": 10_000,
                "TOMATO": 10_000,
                "STRAWBERRY": 10_000,
                "MELON": 10_000,
                "EGG": 10_000,
                "MILK": 10_000,
                "WOOL": 9_998 if after else 10_000,
                "FERTILIZER": 10_000,
            },
        },
    }


def test_window_extracts_bundle_and_market_exposure() -> None:
    steps = [[{}, {}] for _ in range(218)]
    steps[216][0] = {"observation": _observation(after=False)}
    steps[217][0] = {
        "observation": _observation(after=True),
        "action": {
            "farmer": ["FEED"],
            "hands": [["HARVEST"]],
            "market": [["SELL", "WOOL", 2], ["BUY_SEED", "CARROT", 3]],
        },
    }

    metrics = _window({"steps": steps}, seat=0, end=217)

    assert metrics["cow_delta"] == -1.0
    assert metrics["sheep_delta"] == 1.0
    assert metrics["feed_cow_actions"] == 1.0
    assert metrics["hand_harvest_actions"] == 1.0
    assert metrics["harvest_wheat_units"] == 3.0
    assert metrics["other_crops_buy_seed_units"] == 3.0
    assert metrics["sell_wool_units"] == 2.0
    assert metrics["private_wool_exposure_unit_steps"] == 2.0
    assert metrics["requested_sell_wool_public_value"] == 400.0
    assert metrics["market_wool_price_change"] == 10.0


def test_lineage_summary_does_not_treat_episodes_as_independent_lineages() -> None:
    def record(lineage: str, episode: int, value: float, *, material: bool) -> dict:
        return {
            "lineage": lineage,
            "episode_id": episode,
            "label": "top",
            "predicted_tilt": 2.0,
            "actual_tilt": value,
            "material_animal_change": material,
            "windows": {"h72": {"feed_actions": value}},
        }

    records = [
        record("copied", 1, 2.0, material=True),
        record("copied", 2, 4.0, material=True),
        record("distinct", 3, 9.0, material=False),
    ]

    summary = _summarize(records)

    assert summary["episodes"] == 3
    assert summary["distinct_lineages"] == 2
    assert summary["episode_weighted_means"]["h72.feed_actions"] == 5.0
    assert summary["lineage_weighted_means"]["h72.feed_actions"] == 6.0
    assert summary["lineage_profiles"]["copied"]["episodes"] == 2
    assert _dominant_no_material_lineage(records) == ("distinct", 1)


def test_sell_timing_preserves_coverage_and_quantity_weighting() -> None:
    assert _timing([]) == {
        "active": 0.0,
        "active_steps": 0.0,
        "first_step": None,
        "mean_step": None,
        "last_step": None,
    }
    assert _timing([(220, 1), (230, 3)]) == {
        "active": 1.0,
        "active_steps": 2.0,
        "first_step": 220.0,
        "mean_step": 227.5,
        "last_step": 230.0,
    }
