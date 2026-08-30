from agents.v53 import main as v53


def test_carrier_eligibility_excludes_animals_and_sale_goods() -> None:
    assert v53._eligible_carrier({"WHEAT": 2})
    assert v53._eligible_carrier({"WHEAT": 1, "FERTILIZER": 3})
    assert not v53._eligible_carrier({"WHEAT": 1, "COW": 1})
    assert not v53._eligible_carrier({"WHEAT": 1, "MILK": 1})


def test_new_targets_are_unique_and_nearest() -> None:
    v53._FEED_MISSIONS.clear()
    positions = [(0, 0), (5, 0)]
    inventories = [{"WHEAT": 1}, {"WHEAT": 1}]
    tasks = {(1, 0): 12100, (4, 0): 12100}
    v53._assign_new_targets(positions, inventories, tasks)
    assert v53._FEED_MISSIONS == {0: (1, 0), 1: (4, 0)}


def test_disabled_mode_matches_safe_assignment() -> None:
    v53.ENABLE_FEED_MISSIONS = False
    positions = [(0, 0)]
    inventories = [{}]
    tasks: list[dict[str, object]] = []
    assert v53._feed_mission_assign(positions, inventories, tasks, 1) == [["PASS"]]
