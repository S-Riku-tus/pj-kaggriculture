"""Parallel dairy income line layered on `wide_hands` (experiment #32, ADR-0007).

Foundation: `wide_hands`, the champion — a 10-tile melon crew (farmer + up to 9
hands) filling the near band of the unlocked NW quadrant. Its melon micro-loop,
hiring, navigation and market logic are reused *verbatim* by importing the pure
helpers; the hands and the whole melon economy are untouched.

The single technique under test — the one new thing — is a **cow**: build a
PASTURE on a free NW tile, buy + place one COW, and tend it on the *farmer's
spare turns* (the melon plot at (4, 4) needs only one WATER a day, leaving the
farmer idle most turns). Milk sells for 160 — 3.2x an egg — so the hypothesis is
that milk's unit value clears the bar the cheaper GOOSE line (issue with the
weaker hired_hands champion) failed: build + buy + feed cost, plus the shared
melon market's sensitivity to the farmer's within-day timing.

Cow mechanics (verified against the installed sim):

- COW costs 400, needs a PASTURE, first yields on ``placed_day + 8`` then +1 MILK
  every 2 days (capped at 6 held); FEED (1 WHEAT from farmer inventory) is needed
  or the cow *escapes* after 2 consecutive unfed days; CARE the same day as a FEED
  banks a +1 bonus consumed on the next production day.
- The cow tile must be a *free* NW tile — the 10 melon plots occupy every tile
  within Manhattan distance 3 of the shed, so the nearest free tile is distance 4;
  every feed/harvest trip is an ~8-turn round trip. The farmer has the turns (it
  waters one melon a day), so the melon plot at (4, 4) is still watered daily.

Strict melon priority: worker 0 does real melon work (WATER/HARVEST/PLANT) at
(4, 4) before any cow chore; the cow only claims the farmer's otherwise-idle
turns. Hands and all melon market orders are byte-for-byte `wide_hands`.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies import hired_hands as hh
from strategies import wide_hands as wh

CROP = wh.CROP
MAX_HANDS = wh.MAX_HANDS
PLOTS = wh.PLOTS

#: The farmer's melon plot and the NW shed-access tile (PICKUP happens here).
SHED_TILE = (4, 4)

#: The pasture tile — a *free* NW-quadrant tile (not one of the 10 melon plots),
#: at Manhattan distance 4 from the shed (the closest a free tile can be).
COW_TILE = (2, 2)

#: Buy the cow once we can comfortably afford it without starving the melon crew.
COW_COST = 400
COW_MONEY_BUFFER = 600

#: Keep this many WHEAT available (shed + carried) so the farmer can always FEED.
WHEAT_BUFFER = 2


def _tile(tiles, plot):
    x, y = plot
    return tiles[y][x]


def _is_cow(tile) -> bool:
    return isinstance(tile, dict) and "animal" in tile


def cow_farmer_action(pos, tiles, inv, shed):
    """The farmer's cow chore this turn, or ``None`` to defer to the melon loop.

    A pure state machine driven entirely off the observed tile / inventory state:
    build the pasture, acquire and place the cow, then keep it harvested, fed and
    cared. Returns ``None`` whenever the cow wants nothing, so the farmer falls
    back to its melon plot.
    """
    ct = _tile(tiles, COW_TILE)
    on_ct = [pos[0], pos[1]] == [COW_TILE[0], COW_TILE[1]]
    at_shed = [pos[0], pos[1]] == [SHED_TILE[0], SHED_TILE[1]]
    have_cow = inv.get("COW", 0) > 0

    # --- Setup: pasture -> cow in hand -> placed. ---
    if not _is_cow(ct):
        # Grab the bought cow while standing at the shed, before the first trip.
        if not have_cow and shed.get("COW", 0) > 0 and at_shed:
            return ["PICKUP", "COW", 1]
        if ct is None:
            return ["BUILD_PASTURE"] if on_ct else hh.step_toward(pos, COW_TILE)
        # Empty pasture exists.
        if have_cow:
            return ["PLACE", "COW"] if on_ct else hh.step_toward(pos, COW_TILE)
        if shed.get("COW", 0) > 0:
            return ["PICKUP", "COW", 1] if at_shed else hh.step_toward(pos, SHED_TILE)
        return None  # cow not bought yet; the market will buy it — stay on melon.

    # --- Maintain the placed cow. ---
    if ct.get("yield_units", 0) > 0:
        return ["HARVEST"] if on_ct else hh.step_toward(pos, COW_TILE)
    if not ct.get("fed_today", False):
        if inv.get("WHEAT", 0) > 0:
            return ["FEED"] if on_ct else hh.step_toward(pos, COW_TILE)
        if shed.get("WHEAT", 0) > 0:
            if at_shed:
                take = min(shed["WHEAT"], WHEAT_BUFFER)
                return ["PICKUP", "WHEAT", take]
            return hh.step_toward(pos, SHED_TILE)
        return None  # no wheat yet; the market will buy it — stay on melon.
    if not ct.get("cared_today", False) and on_ct:
        return ["CARE"]  # only care when already there; never make a trip just to care.
    return None


class DairyHandsStrategy(Strategy):
    name = "dairy_hands"

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

        season_days = hh.SEASON_DAYS
        market: list = []

        # --- Hire the melon crew (mornings only) — unchanged from wide_hands. ---
        n_hire = 0
        if hour == 0:
            n_hire = hh.plan_hands(
                day, money, hh.max_live_index(tiles, PLOTS), season_days, MAX_HANDS
            )
            market.extend([["HIRE"]] * n_hire)

        # --- One action per worker. Worker 0 (farmer) gets a cow overlay. ---
        positions = [me["farmer"], *hands]
        seeds_available = seeds.get(CROP, 0)
        planted_this_turn = 0
        actions = []
        for i, pos in enumerate(positions):
            plot = PLOTS[i] if i < len(PLOTS) else PLOTS[-1]
            if [pos[0], pos[1]] != [plot[0], plot[1]]:
                # Away from its plot: worker 0 may be on a cow errand instead.
                if i == 0:
                    cow = cow_farmer_action(pos, tiles, farmer_inv, shed)
                    if cow is not None:
                        actions.append(cow)
                        continue
                actions.append(hh.step_toward(pos, plot))
                continue
            melon = hh.tile_action(hh.tile_at(tiles, plot), day, hour, season_days)
            if melon and melon[0] == "PLANT":
                if planted_this_turn < seeds_available:
                    planted_this_turn += 1
                else:
                    melon = (
                        ["WATER"] if hh._is_live_plant(hh.tile_at(tiles, plot)) else ["PASS"]
                    )
            # Farmer: real melon work (WATER/HARVEST/PLANT) wins; else tend cow.
            if i == 0 and (melon is None or melon[0] in ("PASS", "WATER")):
                # WATER still takes priority when the plant actually needs it;
                # tile_action only returns WATER when unwatered, so honor it.
                if melon and melon[0] == "WATER":
                    actions.append(melon)
                    continue
                cow = cow_farmer_action(pos, tiles, farmer_inv, shed)
                actions.append(cow if cow is not None else melon)
                continue
            actions.append(melon)

        farmer_action = actions[0]
        hand_actions = actions[1:]

        # --- Market: melon (and any milk) sells first — unchanged priority. ---
        market.extend(hh.sell_orders(shed))

        # Melon seed restock — verbatim wide_hands logic.
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

        # --- Cow purchases, lowest priority (never displace melon orders). ---
        ct = _tile(tiles, COW_TILE)
        cow_exists = _is_cow(ct) or shed.get("COW", 0) > 0 or farmer_inv.get("COW", 0) > 0
        if (
            not cow_exists
            and money >= COW_COST + COW_MONEY_BUFFER
            and len(market) < 10
        ):
            market.append(["BUY_ANIMAL", "COW", 1])

        # Keep a small WHEAT buffer for feeding once the dairy line is live.
        pasture_started = ct is not None or shed.get("COW", 0) > 0 or farmer_inv.get("COW", 0) > 0
        wheat_on_hand = shed.get("WHEAT", 0) + farmer_inv.get("WHEAT", 0)
        if pasture_started and wheat_on_hand < WHEAT_BUFFER and len(market) < 10:
            want = WHEAT_BUFFER - wheat_on_hand
            if money >= COW_MONEY_BUFFER:  # never spend melon working capital
                market.append(["BUY_PRODUCT", "WHEAT", want])

        return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


STRATEGY = DairyHandsStrategy
