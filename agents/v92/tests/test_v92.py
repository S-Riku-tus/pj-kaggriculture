from agents.v92 import main as v92


def _farm() -> dict:
    return {
        "tiles": [
            [None, {"kind": "PLANT", "crop": "WHEAT"}],
            [{"kind": "PASTURE", "animal": "COW"}, None],
        ]
    }


def _task(pos: tuple[int, int], action: str, priority: int = 12_000) -> dict:
    return {
        "pos": pos,
        "action": [action],
        "priority": priority,
        "unit": None,
        "required": None,
        "label": action.lower(),
    }


def test_disabled_is_exact_noop() -> None:
    tasks = [_task((1, 0), "WATER"), _task((0, 1), "FEED")]
    old = v92.ENABLE_CANDIDATE_RANKER
    try:
        v92.ENABLE_CANDIDATE_RANKER = False
        assert v92._annotate_tasks(tasks, {}, _farm(), [(0, 0)], [{}]) is tasks
    finally:
        v92.ENABLE_CANDIDATE_RANKER = old


def test_high_gap_worker_specific_candidate_is_annotated(monkeypatch) -> None:
    monkeypatch.setattr(v92, "ENABLE_CANDIDATE_RANKER", True)
    monkeypatch.setattr(v92, "CANDIDATE_MODEL", {"forest": [["L", 0.0]]})
    monkeypatch.setattr(v92, "OOD_MODEL", {"ood": {}})
    monkeypatch.setattr(v92, "_is_ood", lambda _features: False)
    monkeypatch.setattr(v92.v88, "_features", lambda *_args: [0.0] * 124)
    monkeypatch.setattr(v92.v9, "_MISSION_PREVIOUS_ACTIONS", [["PASS"]])
    monkeypatch.setattr(
        v92,
        "_score",
        lambda features: 0.8 if features[124 + 8] == 1.0 else 0.1,
    )
    tasks = [_task((1, 0), "WATER"), _task((0, 1), "FEED")]
    annotated = v92._annotate_tasks(tasks, {}, _farm(), [(0, 0)], [{}])
    assert annotated[0]["v92_bonus_by_unit"] == {0: v92.CANDIDATE_BONUS}
    assert "v92_bonus_by_unit" not in annotated[1]
    assert "v92_bonus_by_unit" not in tasks[0]


def test_bonus_changes_only_annotated_worker_cost() -> None:
    task = _task((1, 0), "WATER")
    task["v92_bonus_by_unit"] = {0: 700}
    positions = [(0, 0), (0, 0)]
    inventories = [{}, {}]
    density = {(1, 0): 1}
    safe_zero = v92._SAFE_ASSIGNMENT_COST(0, task, positions, inventories, density)
    safe_one = v92._SAFE_ASSIGNMENT_COST(1, task, positions, inventories, density)
    assert v92._assignment_cost(0, task, positions, inventories, density) == safe_zero - 70_000
    assert v92._assignment_cost(1, task, positions, inventories, density) == safe_one


def test_ongoing_move_and_ood_fall_back(monkeypatch) -> None:
    monkeypatch.setattr(v92, "ENABLE_CANDIDATE_RANKER", True)
    monkeypatch.setattr(v92, "CANDIDATE_MODEL", {"forest": [["L", 0.0]]})
    monkeypatch.setattr(v92, "OOD_MODEL", {"ood": {}})
    monkeypatch.setattr(v92.v88, "_features", lambda *_args: [0.0] * 124)
    tasks = [_task((1, 0), "WATER"), _task((0, 1), "FEED")]

    monkeypatch.setattr(v92.v9, "_MISSION_PREVIOUS_ACTIONS", [["NORTH"]])
    assert v92._annotate_tasks(tasks, {}, _farm(), [(0, 0)], [{}]) == tasks

    monkeypatch.setattr(v92.v9, "_MISSION_PREVIOUS_ACTIONS", [["PASS"]])
    monkeypatch.setattr(v92, "_is_ood", lambda _features: True)
    assert v92._annotate_tasks(tasks, {}, _farm(), [(0, 0)], [{}]) == tasks


def test_priority_cap_preserves_emergency_boundary(monkeypatch) -> None:
    monkeypatch.setattr(v92, "ENABLE_CANDIDATE_RANKER", True)
    monkeypatch.setattr(v92, "CANDIDATE_MODEL", {"forest": [["L", 0.0]]})
    monkeypatch.setattr(v92, "OOD_MODEL", {"ood": {}})
    monkeypatch.setattr(v92, "_is_ood", lambda _features: False)
    monkeypatch.setattr(v92.v88, "_features", lambda *_args: [0.0] * 124)
    monkeypatch.setattr(v92.v9, "_MISSION_PREVIOUS_ACTIONS", [["PASS"]])
    monkeypatch.setattr(
        v92,
        "_score",
        lambda features: 0.8 if features[124 + 8] == 1.0 else 0.1,
    )
    tasks = [_task((1, 0), "WATER", 14_800), _task((0, 1), "FEED", 15_400)]
    annotated = v92._annotate_tasks(tasks, {}, _farm(), [(0, 0)], [{}])
    assert annotated[0]["v92_bonus_by_unit"] == {0: 100}
    assert "v92_bonus_by_unit" not in annotated[1]


def test_base_rank_gate_rejects_distant_baseline_choice(monkeypatch) -> None:
    monkeypatch.setattr(v92, "ENABLE_CANDIDATE_RANKER", True)
    monkeypatch.setattr(v92, "MAX_BASE_RANK", 1)
    monkeypatch.setattr(v92, "CANDIDATE_MODEL", {"forest": [["L", 0.0]]})
    monkeypatch.setattr(v92, "OOD_MODEL", {"ood": {}})
    monkeypatch.setattr(v92, "_is_ood", lambda _features: False)
    monkeypatch.setattr(v92.v88, "_features", lambda *_args: [0.0] * 124)
    monkeypatch.setattr(v92.v9, "_MISSION_PREVIOUS_ACTIONS", [["PASS"]])
    monkeypatch.setattr(
        v92,
        "_score",
        lambda features: 0.8 if features[124 + 8] == 0.0 else 0.1,
    )
    tasks = [_task((1, 0), "WATER", 14_000), _task((0, 1), "FEED", 1_000)]
    before = v92.RUNTIME_COUNTS["base_rank_rejected"]
    annotated = v92._annotate_tasks(tasks, {}, _farm(), [(0, 0)], [{}])
    assert all("v92_bonus_by_unit" not in task for task in annotated)
    assert v92.RUNTIME_COUNTS["base_rank_rejected"] == before + 1
