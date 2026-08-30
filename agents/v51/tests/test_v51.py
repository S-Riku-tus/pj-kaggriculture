from agents.v51 import main as v51


def test_matching_requires_distinct_carriers() -> None:
    animals = [(0, 0), (2, 0)]
    one = {1: {(0, 0): 2, (2, 0): 2}}
    two = {**one, 2: {(0, 0): 2, (2, 0): 2}}
    assert v51._maximum_reachable_matching(one, animals, 3) == 1
    assert v51._maximum_reachable_matching(two, animals, 3) == 2


def test_matching_respects_remaining_turns() -> None:
    animals = [(0, 0)]
    routes = {1: {(0, 0): 5}}
    assert v51._maximum_reachable_matching(routes, animals, 4) == 0
    assert v51._maximum_reachable_matching(routes, animals, 5) == 1


def test_disabled_mode_preserves_task_identity() -> None:
    tasks = [{"label": "pickup-wheat", "action": ["PICKUP", "WHEAT", 3]}]
    v51.ENABLE_CAPACITY_MATCHED_WHEAT = False
    assert v51._capacity_matched_pickups(tasks, {"day": 8}, {}, [], []) is tasks
