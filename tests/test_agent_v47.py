from __future__ import annotations

from agents.v47 import main as v47


def _task(position: tuple[int, int], label: str, priority: int = 9000):
    return {
        "pos": position,
        "action": ["PLANT", "WHEAT"],
        "priority": priority,
        "required": None,
        "unit": None,
        "label": label,
    }


def test_v47_disabled_matches_safe_assignment(monkeypatch) -> None:
    monkeypatch.setattr(v47, "ENABLE_ANTI_REVERSAL", False)
    positions = [(1, 1)]
    tasks = [_task((0, 1), "west"), _task((3, 1), "east")]
    assert v47._mission_assign(positions, [{}], tasks, 5 * 24) == v47.v5._assign_tasks(
        positions, [{}], tasks
    )


def test_v47_keeps_exact_feasible_mission_on_immediate_reversal(monkeypatch) -> None:
    monkeypatch.setattr(v47, "ENABLE_ANTI_REVERSAL", True)
    v47._reset(5 * 24 - 1)
    east = _task((3, 1), "east")
    assert v47._mission_assign([(1, 1)], [{}], [east], 5 * 24) == [["EAST"]]
    west = _task((1, 1), "west")
    assert v47.v5._assign_tasks([(2, 1)], [{}], [west, east]) == [["WEST"]]
    assert v47._mission_assign([(2, 1)], [{}], [west, east], 5 * 24 + 1) == [
        ["EAST"]
    ]


def test_v47_emergency_overrides_continuity(monkeypatch) -> None:
    monkeypatch.setattr(v47, "ENABLE_ANTI_REVERSAL", True)
    v47._reset(5 * 24 - 1)
    east = _task((3, 1), "east")
    assert v47._mission_assign([(1, 1)], [{}], [east], 5 * 24) == [["EAST"]]
    emergency = _task((1, 1), "urgent", priority=v47.EMERGENCY_PRIORITY)
    assert v47._mission_assign(
        [(2, 1)], [{}], [emergency, east], 5 * 24 + 1
    ) == [["WEST"]]


def test_v47_safe_empty_observation() -> None:
    assert v47.agent({}) == {"farmer": ["PASS"], "hands": [], "market": []}

