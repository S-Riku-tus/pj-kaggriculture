"""Observation parsing.

Right now `parse` is a thin pass-through: the competition already hands us a
well-structured dict, so strategies can use it directly. As we build out the
economic model we'll evolve this into a typed GameState with cached, convenient
accessors (my farm, opponent farm, my tiles, prices, etc.) — that refactor
happens behind this function so strategy code doesn't change.

Observation shape (per spec):
    obs = {
        "player": int,                 # 0 or 1
        "day": int, "hour": int,
        "farms": [farm, farm],         # public, indexed by player id
        "market": {"inventory": {...}, "prices": {...}},
        "town": {"unlocked_shops": [...]},
        "private": {"shed": {...}, "seeds": {...}, "inventories": [...]},
    }
"""

from __future__ import annotations


def parse(obs):
    """Return the observation as the strategy-facing state.

    Placeholder identity transform. Kept as a seam so we can introduce a typed
    GameState later without touching every strategy.
    """
    return obs


# --- Convenience helpers (use freely from strategies) ---

def my_farm(obs):
    return obs["farms"][obs["player"]]


def opponent_farm(obs):
    return obs["farms"][1 - obs["player"]]


def prices(obs):
    return obs.get("market", {}).get("prices", {})


def tile_at(farm, x, y):
    return farm["tiles"][y][x]
