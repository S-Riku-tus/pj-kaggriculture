"""Combined crew: melon + carrot catch-crop + dairy cow (integration, ADR-0007).

This is not a clean single-variable experiment — it is an **integration** of three
already-validated wins, measured against the current champion to see whether their
sum is the new best crew:

1. `wide_hands` (#33) — the 10-tile melon crew (farmer + up to 9 hands) on the
   near band of the unlocked NW quadrant: hiring wage curve, navigation, market
   plumbing. Reused verbatim via the `hired_hands` pure helpers.
2. `catch_hands` (#27) — a CARROT catch-crop that fills every plot's ~9-day
   post-melon idle tail, selling into the decoupled CARROT market; plus the
   sell-before-hire market ordering (the +1830/game slot fix). Reused via
   `catch_hands._decide`, `plan_hands_multicrop`, `choose_catch_crop`.
3. `dairy_hands` (#32) — a COW income line built at (2,2) and tended on the
   farmer's genuinely-spare turns (milk clears ~2-2.5x base). Reused via
   `dairy_hands.cow_farmer_action` and the cow/wheat market helpers.

How the three compose without cancelling:

- **Turns.** Each melon plot needs ~1 water/day, so the farmer's plot (4,4) is
  idle most turns. Priority on the farmer is strict: real melon work at (4,4)
  wins, then carrot work on (4,4), then the cow chore on whatever turns remain —
  so the melon crew is effectively unperturbed and the cow only claims true
  slack. The carrot catch-crop lives on the *plot* (every worker's tail), the cow
  on a *separate free tile*, so they never contend for the same square.
- **Market slots.** All product SELLs (carrot, melon, milk) are emitted before
  the HIRE orders, so the price-sensitive melon SELL always clears within the
  10-order/turn cap; hires fill the remaining slots (HIRE is dawn-only, so the
  seed/cow/wheat buys land on the day's later turns when slots are free). WHEAT
  is kept out of the sell list — here it is only ever cow feed, never a catch
  crop (carrot always out-earns wheat per day), so we neither sell nor churn it.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies import catch_hands as ch
from strategies import dairy_hands as dh
from strategies import hired_hands as hh

#: Melon crop, crew width and plots — inherited from the champion via catch_hands.
MELON = ch.MELON
MAX_HANDS = ch.MAX_HANDS
PLOTS = ch.PLOTS
SEASON_DAYS = ch.SEASON_DAYS
CROPS = ch.CROPS


def _sell_orders_no_wheat(shed) -> list:
    """Liquidate the shed like `wide_hands`, but keep WHEAT (it is cow feed here,
    never a catch crop) so a slot isn't wasted selling then rebuying it."""
    return [order for order in hh.sell_orders(shed) if order[1] != "WHEAT"]


class MixedHandsStrategy(Strategy):
    name = "mixed_hands"

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
        inventories = private.get("inventories", [{}])
        farmer_inv = inventories[0] if inventories else {}

        season_days = SEASON_DAYS
        catch = ch.choose_catch_crop(day, season_days)
        melon_open = hh.plantable(MELON, day, season_days)

        # --- Market: product SELLs FIRST (carrot, melon, milk) so the price-
        # sensitive melon SELL sits ahead of the HIRE orders and always clears
        # the 10-order/turn cap. WHEAT stays out (it is cow feed). ---
        market: list = _sell_orders_no_wheat(shed)

        # --- Hire the crew (mornings only). While melon is plantable this is the
        # champion's rule; in the tail it keeps the crew staffing the catch crop. ---
        n_hire = 0
        if hour == 0:
            n_hire = ch.plan_hands_multicrop(
                day, money, hh.max_live_index(tiles, PLOTS), catch, season_days, MAX_HANDS
            )
            market.extend([["HIRE"]] * n_hire)

        # --- One action per worker. Melon then carrot on each plot; the farmer
        # (worker 0) tends the cow only on turns its plot wants nothing. ---
        positions = [me["farmer"], *hands]
        planted_this_turn: dict[str, int] = {}
        actions = []
        for i, pos in enumerate(positions):
            plot = PLOTS[i] if i < len(PLOTS) else PLOTS[-1]
            on_plot = [pos[0], pos[1]] == [plot[0], plot[1]]
            tile = hh.tile_at(tiles, plot)

            if not on_plot:
                # Off its plot. The farmer may spend the trip on a cow chore, but
                # only if the plot wants nothing today — real melon/carrot work
                # (plant/water/harvest/dig) pulls the farmer straight back.
                if i == 0:
                    pending = ch._decide(tile, day, hour, catch, season_days)
                    if pending[0] == "PASS":
                        cow = dh.cow_farmer_action(pos, tiles, farmer_inv, shed)
                        if cow is not None:
                            actions.append(cow)
                            continue
                actions.append(hh.step_toward(pos, plot))
                continue

            # On its plot: melon loop, then the carrot catch-crop in the tail.
            action = ch._decide(tile, day, hour, catch, season_days)
            if action and action[0] == "PLANT":
                # Atomic-plant rule is per crop: plant only as many of a crop this
                # turn as we hold seed for, else the sim voids every plant of it.
                crop = action[1]
                if planted_this_turn.get(crop, 0) < seeds.get(crop, 0):
                    planted_this_turn[crop] = planted_this_turn.get(crop, 0) + 1
                else:
                    action = ["WATER"] if hh._is_live_plant(tile) else ["PASS"]

            # Farmer: real plot work wins; a truly idle plot yields to the cow.
            if i == 0 and action[0] == "PASS":
                cow = dh.cow_farmer_action(pos, tiles, farmer_inv, shed)
                if cow is not None:
                    action = cow
            actions.append(action)

        farmer_action = actions[0]
        hand_actions = actions[1:]

        # --- Seed restock: melon in the melon phase, the catch crop in the tail.
        # HIRE is dawn-only, so on later turns these buys have free slots. ---
        active_plots = min(len(PLOTS), 1 + (n_hire if hour == 0 else len(hands)))
        empty_active = sum(
            1 for plot in PLOTS[:active_plots] if hh.tile_at(tiles, plot) is None
        )
        restock = MELON if melon_open else catch
        if restock is not None and empty_active > 0:
            want_seed = max(0, empty_active - seeds.get(restock, 0))
            if want_seed > 0:
                affordable = int(money // CROPS[restock]["seed"])
                buy = min(want_seed, affordable, 10 - len(market))
                if buy > 0:
                    market.append(["BUY_SEED", restock, buy])

        # --- Cow line, lowest market priority (never displaces a melon order). ---
        ct = dh._tile(tiles, dh.COW_TILE)
        cow_exists = (
            dh._is_cow(ct) or shed.get("COW", 0) > 0 or farmer_inv.get("COW", 0) > 0
        )
        if (
            not cow_exists
            and money >= dh.COW_COST + dh.COW_MONEY_BUFFER
            and len(market) < 10
        ):
            market.append(["BUY_ANIMAL", "COW", 1])

        # Keep a small WHEAT buffer for feeding once the dairy line is live.
        pasture_started = (
            ct is not None or shed.get("COW", 0) > 0 or farmer_inv.get("COW", 0) > 0
        )
        wheat_on_hand = shed.get("WHEAT", 0) + farmer_inv.get("WHEAT", 0)
        if pasture_started and wheat_on_hand < dh.WHEAT_BUFFER and len(market) < 10:
            want = dh.WHEAT_BUFFER - wheat_on_hand
            if money >= dh.COW_MONEY_BUFFER:  # never spend melon working capital
                market.append(["BUY_PRODUCT", "WHEAT", want])

        return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


STRATEGY = MixedHandsStrategy
