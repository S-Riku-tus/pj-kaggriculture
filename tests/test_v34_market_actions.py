from scripts.analyze_v34_labor_value import _market_actions


def test_market_actions_preserve_multiple_orders():
    replay = {
        "steps": [
            [{}, {}],
            [
                {
                    "action": {
                        "market": [
                            ["HIRE"],
                            ["BUY_ANIMAL", "COW", 2],
                            ["SELL", "MILK", 4],
                        ]
                    }
                },
                {},
            ],
        ]
    }

    assert _market_actions(replay, 0, 0) == [
        ["HIRE"],
        ["BUY_ANIMAL", "COW", 2],
        ["SELL", "MILK", 4],
    ]


def test_market_actions_accept_legacy_single_order_shape():
    replay = {"steps": [[{}, {}], [{"action": {"market": ["HIRE"]}}, {}]]}

    assert _market_actions(replay, 0, 0) == [["HIRE"]]
