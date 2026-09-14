"""Melon-market spoiler — an adversarial sparring partner (experiment #52).

**This is a test opponent, not a contender.** It exists to stress a specific
weakness the self-play ladder cannot reveal: our melon-heavy champions share
**one** melon market with their 1v1 opponent, and MELON is demanded by **no**
town shop (see `economy.SHOP_DEMAND`), so melon inventory that gets dumped into
the market is never drained by consumption — it just sits there depressing the
price (`market_price` falls as inventory climbs above I0). A foreign ladder bot
built to *flood* melon could therefore crash the price our champion realises,
even though we dominate self-play where nobody plays that way.

`spoiler` is that flooder. It runs the widest affordable melon crew across the
free NW quadrant and **dumps every melon into the market every turn**, driving the
shared melon price down as hard and as continuously as it can. This is
deliberately *not* a good strategy for winning — flooding melon craters the
spoiler's own melon income too — its job is to be a reproducible market-crash
adversary for `ranch_adaptive` (experiment #52) to be measured against. It is a
legitimate registered agent (it plays the game by the rules and beats the random
bot), so the promotion harness can pit a challenger against it head-to-head.

Built entirely on `hired_hands`' pure melon-loop helpers (hire / navigate / farm
/ liquidate); the only differences from `wide_hands` are a wider plot set and a
larger crew cap, both turned up purely to maximise melon tonnage dumped.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies import hired_hands as hh

#: The one crop — melon, the market we are here to flood.
CROP = hh.CROP

#: Crew cap, turned up past the champions' sweet spot. A flooder does not care
#: that the escalating hire wage and self-inflicted price depression claw back
#: its own ROI past ~9 hands — more hands means more melons to dump.
MAX_HANDS = 13

#: One melon plot per worker across the unlocked NW quadrant (x,y in 0..4),
#: ordered by nearness to the farmer's shed-access spawn at (4, 4). The first ten
#: are `wide_hands`' tiles; the tail packs more of the quadrant to grow the flood.
PLOTS = [
    (4, 4),                          # worker 0 (main farmer, shed-adjacent)
    (3, 4), (4, 3),                  # distance 1
    (2, 4), (3, 3), (4, 2),          # distance 2
    (1, 4), (2, 3), (3, 2), (4, 1),  # distance 3
    (0, 4), (1, 3), (2, 2), (3, 1),  # distance 4
]


class SpoilerStrategy(Strategy):
    name = "spoiler"

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

        # --- Hire the widest affordable crew each morning to grow the flood. ---
        n_hire = 0
        if hour == 0:
            n_hire = hh.plan_hands(
                day, money, hh.max_live_index(tiles, PLOTS), season_days, MAX_HANDS
            )
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

        # --- Flood: dump every melon in the shed into the market, every turn. ---
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


STRATEGY = SpoilerStrategy
