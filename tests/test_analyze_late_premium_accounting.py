from collections import Counter

from scripts.analyze_late_premium_accounting import (
    _aggregate_games,
    _on_farm_products,
    _private_products,
)


def test_product_state_counts_private_and_on_farm() -> None:
    private = {
        "shed": {"MILK": 3, "WOOL": 1},
        "inventories": [{"MILK": 2}, {"STRAWBERRY": 4}],
    }
    farm = {
        "tiles": [
            [
                {"kind": "PLANT", "crop": "MELON", "yield_units": 5},
                {"kind": "PASTURE", "animal": "SHEEP", "yield_units": 2},
                {"kind": "WEED"},
            ]
        ]
    }

    assert _private_products(private) == Counter(MILK=5, WOOL=1, STRAWBERRY=4)
    assert _on_farm_products(farm) == Counter(MELON=5, WOOL=2)


def test_aggregate_keeps_dependence_guardrail() -> None:
    def game(focal: int, opponent: int) -> dict:
        return {
            "accounting": {
                "focal": {
                    "premium_totals": {
                        key: focal
                        for key in (
                            "production",
                            "harvest",
                            "sell_units",
                            "realized_sale_value",
                            "ending_private",
                            "ending_on_farm",
                        )
                    }
                },
                "opponent": {
                    "premium_totals": {
                        key: opponent
                        for key in (
                            "production",
                            "harvest",
                            "sell_units",
                            "realized_sale_value",
                            "ending_private",
                            "ending_on_farm",
                        )
                    }
                },
            }
        }

    result = _aggregate_games([game(10, 14), game(12, 18)])

    assert result["focal"]["production"] == 11
    assert result["opponent"]["production"] == 16
    assert result["focal_minus_opponent"]["production"] == -5
    assert "dependent continuations" in result["descriptive_unit"]
