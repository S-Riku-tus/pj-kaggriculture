from agents.v88 import main as v88


def _farm() -> dict:
    return {
        "tiles": [
            [None, {"kind": "PLANT", "crop": "WHEAT"}],
            [None, None],
        ]
    }


def _task(priority: int = 12_800) -> dict:
    return {
        "pos": (1, 0),
        "action": ["WATER"],
        "priority": priority,
        "unit": None,
        "required": None,
    }


def test_disabled_is_exact_noop() -> None:
    tasks = [_task()]
    old = v88.ENABLE_TASK_GOALS
    try:
        v88.ENABLE_TASK_GOALS = False
        assert v88._rerank_tasks(tasks, {}, _farm(), [(0, 0)], [{}]) is tasks
    finally:
        v88.ENABLE_TASK_GOALS = old


def test_exact_legal_moving_goal_gets_bounded_bonus(monkeypatch) -> None:
    monkeypatch.setattr(v88, "ENABLE_TASK_GOALS", True)
    monkeypatch.setattr(v88, "TASK_GOAL_MODEL", {"present": True})
    monkeypatch.setattr(v88, "_features", lambda *_args: [0.0] * 124)
    monkeypatch.setattr(v88, "_prediction", lambda _features: ("WATER:WHEAT", 0.8, False))
    monkeypatch.setattr(v88.v9, "_MISSION_PREVIOUS_ACTIONS", [["PASS"]])
    tasks = [_task()]
    reranked = v88._rerank_tasks(tasks, {}, _farm(), [(0, 0)], [{}])
    assert reranked[0]["priority"] == 12_800 + round(v88.TASK_GOAL_BONUS * 0.8)
    assert tasks[0] == _task()


def test_emergency_priority_is_never_changed(monkeypatch) -> None:
    monkeypatch.setattr(v88, "ENABLE_TASK_GOALS", True)
    monkeypatch.setattr(v88, "TASK_GOAL_MODEL", {"present": True})
    monkeypatch.setattr(v88, "_features", lambda *_args: [0.0] * 124)
    monkeypatch.setattr(v88, "_prediction", lambda _features: ("WATER:WHEAT", 0.9, False))
    monkeypatch.setattr(v88.v9, "_MISSION_PREVIOUS_ACTIONS", [["PASS"]])
    tasks = [_task(15_400)]
    assert v88._rerank_tasks(tasks, {}, _farm(), [(0, 0)], [{}]) == tasks


def test_ood_and_continuing_routes_fall_back(monkeypatch) -> None:
    monkeypatch.setattr(v88, "ENABLE_TASK_GOALS", True)
    monkeypatch.setattr(v88, "TASK_GOAL_MODEL", {"present": True})
    monkeypatch.setattr(v88, "_features", lambda *_args: [0.0] * 124)
    tasks = [_task()]

    monkeypatch.setattr(v88.v9, "_MISSION_PREVIOUS_ACTIONS", [["PASS"]])
    monkeypatch.setattr(v88, "_prediction", lambda _features: ("WATER:WHEAT", 0.9, True))
    assert v88._rerank_tasks(tasks, {}, _farm(), [(0, 0)], [{}]) is tasks

    monkeypatch.setattr(v88.v9, "_MISSION_PREVIOUS_ACTIONS", [["NORTH"]])
    monkeypatch.setattr(v88, "_prediction", lambda _features: ("WATER:WHEAT", 0.9, False))
    assert v88._rerank_tasks(tasks, {}, _farm(), [(0, 0)], [{}]) is tasks


def test_same_tile_operation_is_not_reranked(monkeypatch) -> None:
    monkeypatch.setattr(v88, "ENABLE_TASK_GOALS", True)
    monkeypatch.setattr(v88, "TASK_GOAL_MODEL", {"present": True})
    monkeypatch.setattr(v88, "_features", lambda *_args: [0.0] * 124)
    monkeypatch.setattr(v88, "_prediction", lambda _features: ("WATER:WHEAT", 0.9, False))
    monkeypatch.setattr(v88.v9, "_MISSION_PREVIOUS_ACTIONS", [["PASS"]])
    tasks = [_task()]
    assert v88._rerank_tasks(tasks, {}, _farm(), [(1, 0)], [{}]) == tasks
