"""Wider melon crew within the free NW quadrant (experiment #33, ADR-0007).

Foundation: `hired_hands`, the current champion — a multi-tile melon crew that
caps at `MAX_HANDS = 6` (7 melon plots) even though the starting **NW quadrant is
5x5 = 25 tiles**, most of them left idle. We reuse its melon micro-loop, hiring
rule, navigation and market logic *verbatim* by importing the pure helpers.

The single technique under test — the one variable — is **crew width**: hire more
hands onto more of the already-unlocked NW quadrant. Nothing else changes; at the
champion's own size this agent is byte-for-byte `hired_hands` (verified: coin
margin 0 on every seed at `MAX_HANDS = 6`), so the win-rate delta attributes to
the extra tiles alone.

Two forces bound the useful width, and the sweet spot sits between them:

- **The hire wage escalates as `fib(k-1)`** (1, 1, 2, 3, 5, 8, 13, 21, ...) and is
  paid *every day* (hands are cleared nightly and re-hired each morning), so a big
  crew's daily wage compounds fast. Selling many more melons also depresses the
  melon price (its curve is steep on the sell side) and risks the 100-item shed
  overflow (cf. #24).
- **The 10-order/turn market cap** limits a single morning's hiring — HIRE orders
  compete with the melon sells and seed buys.

Empirically the margin peaks at **`MAX_HANDS = 9` (a 10-tile crew)**: +7 → +9
hands still earn more melons than their escalating wage costs, while wider crews
(11+) give the gain back to wages, price depression, and the dawn order cap. The
constant is the whole experiment; everything else is the champion's.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies import hired_hands as hh

#: The one crop, reused from the champion.
CROP = hh.CROP

#: Max hands to hire in a day — the single variable under test. The champion uses
#: 6; the melon margin vs the champion peaks at 9 (a 10-tile crew) before the
#: escalating hire wage and melon-price depression claw the gain back.
MAX_HANDS = 9

#: One melon plot per worker, drawn from the unlocked NW quadrant (x,y in 0..4)
#: and ordered by nearness to the farmer's shed-access spawn at (4, 4), so a
#: freshly hired hand reaches its plot in a few steps and waters it the same day.
#: The first 7 are the champion's tiles; the tail extends into the idle quadrant.
PLOTS = [
    (4, 4),                  # worker 0 (main farmer, shed-adjacent)
    (3, 4), (4, 3),          # distance 1
    (2, 4), (3, 3), (4, 2),  # distance 2
    (1, 4), (2, 3), (3, 2), (4, 1),  # distance 3
]


class WideHandsStrategy(Strategy):
    name = "wide_hands"

    def act(self, obs) -> dict:
        player = obs["player"]
        me = obs["farms"][player]
        private = obs["private"]
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        money = me["money"]
        tiles = me["tiles"]
        hands = me.get("hands", []) or []
        seeds = private.get("seeds", {})
        shed = private.get("shed", {})

        season_days = hh.SEASON_DAYS
        market: list = []

        # --- Hire the crew for the day (mornings only; hands persist all day). ---
        n_hire = 0
        if hour == 0:
            n_hire = hh.plan_hands(day, money, hh.max_live_index(tiles, PLOTS),
                                   season_days, MAX_HANDS)
            market.extend([["HIRE"]] * n_hire)

        # --- One action per existing worker: navigate to its plot, then farm it. ---
        positions = [me["farmer"], *hands]
        seeds_available = seeds.get(CROP, 0)
        planted_this_turn = 0
        actions = []
        for i, pos in enumerate(positions):
            plot = PLOTS[i] if i < len(PLOTS) else PLOTS[-1]
            if [pos[0], pos[1]] != [plot[0], plot[1]]:
                actions.append(hh.step_toward(pos, plot))
                continue
            action = hh.tile_action(hh.tile_at(tiles, plot), day, hour, season_days)
            if action and action[0] == "PLANT":
                # Atomic-plant rule: only plant as many melons this turn as we hold
                # seed for, or the sim voids every plant of the crop at once.
                if planted_this_turn < seeds_available:
                    planted_this_turn += 1
                else:
                    action = ["WATER"] if hh._is_live_plant(hh.tile_at(tiles, plot)) else ["PASS"]
            actions.append(action)

        farmer_action = actions[0]
        hand_actions = actions[1:]

        # --- Market: liquidate melons in the shed, then restock seed. ---
        market.extend(hh.sell_orders(shed))

        # Keep a seed buffer covering every active plot so arriving hands can plant
        # without stalling. Buy only the shortfall we can afford and that fits.
        active_plots = min(len(PLOTS), 1 + (n_hire if hour == 0 else len(hands)))
        empty_active = sum(
            1 for plot in PLOTS[:active_plots] if hh.tile_at(tiles, plot) is None
        )
        want_seed = max(0, empty_active - seeds_available)
        if want_seed > 0 and hh.plantable(CROP, day, season_days):
            affordable = int(money // hh.CROPS[CROP]["seed"])
            buy = min(want_seed, affordable, 10 - len(market))
            if buy > 0:
                market.append(["BUY_SEED", CROP, buy])

        return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


STRATEGY = WideHandsStrategy
