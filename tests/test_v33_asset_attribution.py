from scripts.analyze_v33_asset_labor import _asset


def _farm_with(tile, position=(4, 4)):
    tiles = [[None for _x in range(10)] for _y in range(10)]
    x, y = position
    tiles[y][x] = tile
    return {"tiles": tiles}


def test_shed_operations_do_not_inherit_animal_on_access_tile():
    farm = _farm_with({"kind": "PASTURE", "animal": "COW"})

    assert _asset(["PICKUP", "WHEAT", 3], farm, (4, 4)) is None
    assert _asset(["DROP"], farm, (4, 4)) is None


def test_place_is_animal_work_only_on_matching_empty_structure():
    pasture = _farm_with({"kind": "PASTURE"})
    occupied = _farm_with({"kind": "PASTURE", "animal": "SHEEP"})
    empty = _farm_with(None)

    assert _asset(["PLACE", "COW"], pasture, (4, 4)) == "COW"
    assert _asset(["PLACE", "COW"], occupied, (4, 4)) is None
    assert _asset(["PLACE", "WHEAT", 5], empty, (4, 4)) is None
