"""Small builders for the per-turn action dict.

These keep strategy code readable and reduce the chance of a malformed action
(which the sim silently no-ops, wasting a turn). Nothing here is required — a
strategy can always return a raw dict — but prefer these for clarity.
"""

from __future__ import annotations

MOVES = ("NORTH", "SOUTH", "EAST", "WEST")


def turn(farmer=None, hands=None, market=None) -> dict:
    """Assemble a full turn. Defaults to a safe no-op."""
    return {
        "farmer": farmer if farmer is not None else ["PASS"],
        "hands": hands if hands is not None else [],
        "market": market if market is not None else [],
    }


# --- farmer/hand single actions ---
def pass_() -> list: return ["PASS"]
def move(direction: str) -> list: return [direction]
def plant(crop: str) -> list: return ["PLANT", crop]
def water() -> list: return ["WATER"]
def harvest() -> list: return ["HARVEST"]
def fertilize() -> list: return ["FERTILIZE"]
def feed() -> list: return ["FEED"]
def care() -> list: return ["CARE"]
def collect_fertilizer() -> list: return ["COLLECT_FERTILIZER"]
def dig() -> list: return ["DIG"]
def pickup(item: str, n: int = 1) -> list: return ["PICKUP", item, n]
def drop() -> list: return ["DROP"]
def place(item: str, n: int = 1) -> list: return ["PLACE", item, n]
def build_coop() -> list: return ["BUILD_COOP"]
def build_pasture() -> list: return ["BUILD_PASTURE"]


# --- market orders ---
def buy_seed(item: str, n: int = 1) -> list: return ["BUY_SEED", item, n]
def buy_animal(item: str, n: int = 1) -> list: return ["BUY_ANIMAL", item, n]
def buy_product(item: str, n: int = 1) -> list: return ["BUY_PRODUCT", item, n]
def sell(item: str, n: int = 1) -> list: return ["SELL", item, n]
def hire() -> list: return ["HIRE"]
def buy_land() -> list: return ["BUY_LAND"]
