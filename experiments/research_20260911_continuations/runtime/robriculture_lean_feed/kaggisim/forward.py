"""Rebuild a steppable simulation from an observation, for lookahead.

An agent is handed an `obs`, never the environment, so planning ahead requires
reconstructing one. Everything needed is in the observation: both farms (money,
hands, hires_today, unlocked_quadrants and full tiles -- including
`max_lifespan_step`), market inventory and prices, the town's unlocked shops,
day/hour, and our own private shed/seeds/inventories.

Validated exact: rebuilding at step 240 and rolling 48 turns reproduces money,
standing plants, hand count and quadrants to the value, with the sim's weed
randomness both on and off (#159).

Depends on `kaggle_environments`, which is by definition present wherever the
agent runs and is not bundled by `build/package.py` -- consistent with
`kaggisim` depending on "stdlib + the sim". ADR-0004 constrains the agent to
Python, not to the standard library.
"""

from __future__ import annotations

import copy

TURNS_PER_DAY = 24


def rebuild(obs, episode_steps: int = 720, seed: int = 0):
    """A `kaggle_environments` env positioned at `obs`, ready to `step()`.

    `seed` cannot be recovered from an observation, so weed spawns in a rollout
    will not match the live game. That is deliberate and harmless for the use
    this exists for: every candidate is rolled under the SAME seed, so the
    comparison between them stays controlled even though each is a little wrong
    in absolute terms.

    The opponent's private shed/seeds/inventories are not in our observation
    either; their farm is reconstructed from public state, which is sufficient
    whenever the caller supplies the opponent's actions (see `ROLLOUT_PASS`).
    """
    from kaggle_environments import make

    env = make("kaggriculture",
               configuration={"episodeSteps": episode_steps, "seed": seed})
    env.reset(2)
    step = int(obs.get("step", obs.get("day", 0) * TURNS_PER_DAY + obs.get("hour", 0)))
    for i, s in enumerate(env.state):
        o = s.observation
        o["farms"] = copy.deepcopy(obs["farms"])
        o["market"] = copy.deepcopy(obs["market"])
        o["town"] = copy.deepcopy(obs["town"])
        o["day"], o["hour"] = obs["day"], obs["hour"]
        if i == int(obs.get("player", 0)):
            o["private"] = copy.deepcopy(obs["private"])
            # Read by the interpreter DURING a step to derive day/hour and the
            # decay and town-consumption schedules; it is overwritten from the
            # history length afterwards, so both this and the padding below are
            # required (#159).
            o["step"] = step
    # The interpreter takes the current step from the env's HISTORY LENGTH, not
    # from observation["step"] -- which it overwrites after every step. The
    # relationship is len(env.steps) == obs.step + 1; padding to `step` instead
    # leaves the rollout one turn out of phase, which is invisible in most
    # fields but flips `hands` (the crew is cleared at midnight) and cascades
    # from there (#159).
    while len(env.steps) < step + 1:
        env.steps.append(env.steps[-1])
    return env


#: A do-nothing opponent for rollouts. Assuming the opponent idles biases the
#: market optimistically -- they add no supply -- but applies that bias equally
#: to every candidate, which is what makes a rollout a CONTROLLED comparison of
#: our own options rather than a prediction of the game.
ROLLOUT_PASS = {"farmer": ["PASS"], "hands": [], "market": []}


def standing_value(farm, prices) -> float:
    """Money plus what the crops still in the ground would fetch today.

    A horizon short enough to afford is far shorter than a crop cycle -- melon
    occupies a tile for 12 days -- so scoring a rollout on cash alone would rate
    every planting as a pure loss. Crediting standing yield at the current
    market price is the cheapest fix that does not require simulating to harvest.
    """
    total = float(farm.get("money", 0))
    for row in farm.get("tiles") or []:
        for tile in row:
            if isinstance(tile, dict) and tile.get("kind") == "PLANT":
                total += tile.get("yield_units", 0) * prices.get(tile.get("crop"), 0)
    return total
