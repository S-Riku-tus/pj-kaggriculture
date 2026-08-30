from agents.v54 import main as v54


def test_matching_is_one_carrier_per_animal() -> None:
    positions = [(0, 0), (4, 0)]
    animals = [(1, 0), (3, 0)]
    assert v54._matched_animals(positions, [0], animals, 4) == {(1, 0)}
    assert v54._matched_animals(positions, [0, 1], animals, 4) == set(animals)


def test_matching_respects_day_budget() -> None:
    positions = [(0, 0)]
    animals = [(3, 0)]
    assert not v54._matched_animals(positions, [0], animals, 3)
    assert v54._matched_animals(positions, [0], animals, 4) == {(3, 0)}


def test_carrier_excludes_sale_goods() -> None:
    assert v54._eligible_carrier({"WHEAT": 2})
    assert not v54._eligible_carrier({"WHEAT": 2, "WOOL": 1})
