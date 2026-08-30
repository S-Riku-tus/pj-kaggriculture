from agents.v81 import main as v81


def _farm(units: int = 1) -> dict:
    return {
        "tiles": [
            [
                {
                    "kind": "PLANT",
                    "crop": "STRAWBERRY",
                    "yield_units": units,
                    "max_lifespan_step": 552,
                }
            ]
        ]
    }


def test_disabled_candidate_is_exact_noop() -> None:
    v81.ENABLE_DECAY_HARVEST = False
    tasks = [{"pos": (0, 0), "action": ["WATER"], "priority": 14_800}]
    assert v81._protect_decaying_harvest(tasks, {"day": 23, "step": 552}, _farm()) is tasks


def test_adds_missing_one_unit_harvest_task() -> None:
    v81.ENABLE_DECAY_HARVEST = True
    tasks = v81._protect_decaying_harvest([], {"day": 23, "step": 552}, _farm())
    assert len(tasks) == 1
    assert tasks[0]["pos"] == (0, 0)
    assert tasks[0]["action"] == ["HARVEST"]
    assert tasks[0]["priority"] == v81.DECAY_HARVEST_PRIORITY
    assert tasks[0]["label"] == "decaying-crop-harvest"


def test_raises_existing_decaying_harvest_priority() -> None:
    v81.ENABLE_DECAY_HARVEST = True
    v81.RAISE_EXISTING_DECAY_HARVEST = True
    tasks = [{"pos": (0, 0), "action": ["HARVEST"], "priority": 8_800}]
    protected = v81._protect_decaying_harvest(
        tasks, {"day": 24, "step": 576}, _farm(2)
    )
    assert protected[0]["priority"] == v81.DECAY_HARVEST_PRIORITY
    assert protected[0]["label"] == "decaying-crop-harvest"


def test_missing_only_mode_preserves_existing_task() -> None:
    v81.ENABLE_DECAY_HARVEST = True
    v81.RAISE_EXISTING_DECAY_HARVEST = False
    tasks = [{"pos": (0, 0), "action": ["HARVEST"], "priority": 8_800}]
    protected = v81._protect_decaying_harvest(
        tasks, {"day": 24, "step": 576}, _farm(2)
    )
    assert protected == tasks


def test_outside_window_is_exact_noop() -> None:
    v81.ENABLE_DECAY_HARVEST = True
    v81.RAISE_EXISTING_DECAY_HARVEST = True
    tasks = [{"pos": (0, 0), "action": ["HARVEST"], "priority": 8_800}]
    assert v81._protect_decaying_harvest(
        tasks, {"day": 22, "step": 552}, _farm(2)
    ) is tasks
