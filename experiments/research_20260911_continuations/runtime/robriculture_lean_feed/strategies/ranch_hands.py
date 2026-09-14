"""Ranch: livestock cluster + shop-demand wheat catch-crop (integration of #45 + #46).

This is an **integration** of this round's two validated wins, not a clean
single-variable experiment. It takes the champion `livestock_hand` (#45) and
swaps its tail catch-crop from CARROT to WHEAT, borrowing `wheat_hands`' (#46)
shop-demand rationale and its feed-buffer sell rule. The measured question is
whether the two composed wins stack against the champion.

From `livestock_hand` (#45), kept byte-for-byte: the 9-tile melon crew (drops the
weakest 10th tile), and ONE WORKER (hand index 1) dedicated full-time to a COW
`(2, 2)` + SHEEP `(2, 1)` cluster — milk + wool in parallel. The melon loop,
hiring, navigation, animal state machine (`livestock_action` / `animal_chore`)
and market plumbing are reused *verbatim* by importing the champion's helpers.

The single change vs the champion — **the tail catch-crop is WHEAT, not CARROT**
(reusing `wheat_hands.choose_catch_crop`, which forces WHEAT). The champion's
`choose_catch_crop` ranks by profit-per-occupied-day at base prices, where carrot
(85/3 ~= 28.3/day) edges wheat (90/4 = 22.5/day). But realized clearing price is
driven by shop-demand scarcity: WHEAT is demanded by **five** shops, CARROT by
two, so wheat drains faster and clears higher (the #46 hypothesis, already
validated as a promotion).

The extra synergy this integration buys: wheat is *also* the animals' feed. Here
the crop-wheat feeds **BOTH** the cow and the sheep, so the same rule that made
#46 work — **sell shed wheat only down to the feed buffer, never below it** —
doubles the catch-crop harvest as free feed for two animals instead of one. The
buffer is the livestock line's larger ``WHEAT_BUFFER`` (feeds a two-animal
cluster). The catch-crop harvest tops the shed up; the livestock hand draws a
couple of units off the top each dawn to FEED; ``WHEAT_BUFFER`` units stay parked
so the cluster never starves; only the surplus clears into wheat's scarce market.
The early-game feed BUY still fires before any catch wheat exists, so the animals
are never starved during ramp-up — exactly as in both foundations.
"""

from __future__ import annotations

from kaggisim.strategy import Strategy
from strategies import catch_hands as ch
from strategies import hired_hands as hh
from strategies import wheat_hands as wht

#: Melon crop, crew width, catch-crop plumbing — inherited from the champion.
MELON = ch.MELON
CROPS = ch.CROPS
SEASON_DAYS = ch.SEASON_DAYS
MAX_HANDS = ch.MAX_HANDS  # 9 hands => 10 workers total (farmer + 9)

#: Melon plots: the champion's 10 tiles MINUS the weakest (last) one — a 9-tile
#: melon crew. The dropped tile's worker becomes the livestock hand.
MELON_PLOTS = ch.PLOTS[:-1]

#: The animal cluster — two adjacent *free* NW tiles (not melon plots).
COW_TILE = (2, 2)
SHEEP_TILE = (2, 1)

#: The shed-access tile we PICKUP from. Only (4, 4) is in the unlocked NW
#: quadrant; the other three shed-access corners ((5,4),(4,5),(5,5)) sit on
#: LOCKED tiles where every tile op (PICKUP included) silently no-ops, so a hand
#: must walk to (4, 4) before it can draw wheat or a bought animal from the shed.
SHED_TILE = (4, 4)

ANIMAL_TILE = {"COW": COW_TILE, "SHEEP": SHEEP_TILE}
ANIMAL_COST = {"COW": 400, "SHEEP": 500}

#: Keep melon working capital intact before buying an animal.
COW_MONEY_BUFFER = 600
SHEEP_MONEY_BUFFER = 600

#: Wheat: carry this many per shed trip (feeds both animals in one visit); keep
#: at least this many in the shed once the livestock line is live. WHEAT_BUFFER
#: is the feed buffer the sell rule holds back for the two-animal cluster.
WHEAT_CARRY = 2
WHEAT_BUFFER = 4


def choose_catch_crop(day: int, season_days: int = SEASON_DAYS):
    """The tail catch crop: forced to WHEAT via `wheat_hands.choose_catch_crop`
    (the #46 shop-demand pick) instead of the champion's carrot. Returns WHEAT
    while it can still reach full maturity before the buzzer, else ``None``."""
    return wht.choose_catch_crop(day, season_days)


def _sell_orders_keep_feed(shed) -> list:
    """Liquidate the shed like the champion, but sell crop-WHEAT only down to the
    animals' feed buffer — never below it (the #46 rule, applied to a two-animal
    cluster). The wheat catch-crop harvest tops the shed up; the livestock hand
    draws ``WHEAT_CARRY`` off it each dawn to FEED the cow and the sheep (free
    feed); ``WHEAT_BUFFER`` units stay parked so the cluster never starves; only
    the surplus clears into wheat's scarce market."""
    orders = []
    for order in hh.sell_orders(shed):
        if order[1] == "WHEAT":
            sellable = order[2] - WHEAT_BUFFER
            if sellable > 0:
                orders.append(["SELL", "WHEAT", sellable])
        else:
            orders.append(order)
    return orders


def _tile(tiles, plot):
    x, y = plot
    return tiles[y][x]


def _is_animal(tile) -> bool:
    return isinstance(tile, dict) and "animal" in tile


def _at_shed(pos) -> bool:
    return [pos[0], pos[1]] == [SHED_TILE[0], SHED_TILE[1]]


def melon_plot_for(i: int):
    """The melon plot for worker ``i``. Worker 0 (farmer) keeps `(4, 4)`; worker
    1 is the livestock hand (no melon plot); workers 2..N take the remaining 8
    melon tiles. Indices past the crew clamp to the last plot."""
    if i == 0:
        return MELON_PLOTS[0]
    if i == 1:
        return None  # the dedicated livestock hand — no melon plot
    idx = i - 1  # worker 2 -> MELON_PLOTS[1], ... worker 9 -> MELON_PLOTS[8]
    if idx >= len(MELON_PLOTS):
        idx = len(MELON_PLOTS) - 1
    return MELON_PLOTS[idx]


def animal_chore(kind: str, pos, tiles, inv, shed):
    """This turn's chore for one animal, or ``None`` when it wants nothing.

    A pure state machine: build the pasture, acquire + place the animal, then
    keep it harvested and fed (CARE only when already standing on it). Returns
    ``None`` whenever the animal is fully tended, so the caller can fall through
    to the next animal or idle.
    """
    at = ANIMAL_TILE[kind]
    ct = _tile(tiles, at)
    on_ct = [pos[0], pos[1]] == [at[0], at[1]]
    have = inv.get(kind, 0) > 0

    # --- Setup: pasture -> animal in hand -> placed. ---
    if not _is_animal(ct):
        if have:
            return ["PLACE", kind] if on_ct else hh.step_toward(pos, at)
        if ct is None:
            return ["BUILD_PASTURE"] if on_ct else hh.step_toward(pos, at)
        # Empty pasture exists; fetch the bought animal from the shed.
        if shed.get(kind, 0) > 0:
            return ["PICKUP", kind, 1] if _at_shed(pos) else hh.step_toward(pos, SHED_TILE)
        return None  # not bought yet; the market will buy it.

    # --- Maintain the placed animal. ---
    if ct.get("yield_units", 0) > 0:
        return ["HARVEST"] if on_ct else hh.step_toward(pos, at)
    if not ct.get("fed_today", False):
        if inv.get("WHEAT", 0) > 0:
            return ["FEED"] if on_ct else hh.step_toward(pos, at)
        if shed.get("WHEAT", 0) > 0:
            if _at_shed(pos):
                return ["PICKUP", "WHEAT", min(shed["WHEAT"], WHEAT_CARRY)]
            return hh.step_toward(pos, SHED_TILE)
        return None  # no wheat yet; the market will buy it.
    if not ct.get("cared_today", False) and on_ct:
        return ["CARE"]  # only care when already there; never a trip just to care.
    return None


def livestock_action(pos, tiles, inv, shed, want_sheep: bool):
    """The dedicated livestock hand's action this turn — never ``None``.

    Cow first, then (once the cow line is live) the sheep. At dawn, top up wheat
    from the shed before leaving so a single cluster visit can both harvest and
    feed. Idles at the cluster when both animals are fully tended.
    """
    kinds = ["COW"] + (["SHEEP"] if want_sheep else [])
    placed = any(_is_animal(_tile(tiles, ANIMAL_TILE[k])) for k in kinds)

    # Proactive dawn wheat pickup: grab feed while standing at the shed so the
    # trip out can harvest AND feed in one pass (avoids a harvest/feed round trip).
    if (
        placed
        and _at_shed(pos)
        and inv.get("WHEAT", 0) < WHEAT_CARRY
        and shed.get("WHEAT", 0) > 0
    ):
        return ["PICKUP", "WHEAT", min(shed["WHEAT"], WHEAT_CARRY)]

    for kind in kinds:
        chore = animal_chore(kind, pos, tiles, inv, shed)
        if chore is not None:
            return chore
    return hh.step_toward(pos, COW_TILE)  # idle toward the cluster (PASS if there)


class RanchHandsStrategy(Strategy):
    name = "ranch_hands"

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

        season_days = SEASON_DAYS
        catch = choose_catch_crop(day, season_days)
        melon_open = hh.plantable(MELON, day, season_days)

        # --- Market: product SELLs FIRST (carrot/melon/milk/wool + wheat surplus)
        # so the price-sensitive melon SELL sits ahead of the HIRE orders and
        # clears the 10-order/turn cap. Crop-WHEAT is sold only down to the
        # animals' feed buffer, so the catch-crop harvest doubles as free feed. ---
        market: list = _sell_orders_keep_feed(shed)

        # --- Hire the crew (mornings only) — champion's multicrop rule, sized on
        # the 9-tile melon crew (one worker is diverted to livestock). ---
        n_hire = 0
        if hour == 0:
            n_hire = ch.plan_hands_multicrop(
                day,
                money,
                hh.max_live_index(tiles, MELON_PLOTS),
                catch,
                season_days,
                MAX_HANDS,
            )
            market.extend([["HIRE"]] * n_hire)

        # --- One action per worker. Worker 1 is the livestock hand; every other
        # worker runs the champion's melon+wheat loop on its plot. ---
        positions = [me["farmer"], *hands]
        cow_ct = _tile(tiles, COW_TILE)
        cow_live = _is_animal(cow_ct)
        planted_this_turn: dict[str, int] = {}
        actions = []
        for i, pos in enumerate(positions):
            if i == 1:
                inv = inventories[i] if i < len(inventories) else {}
                actions.append(livestock_action(pos, tiles, inv, shed, cow_live))
                continue

            plot = melon_plot_for(i)
            on_plot = [pos[0], pos[1]] == [plot[0], plot[1]]
            if not on_plot:
                actions.append(hh.step_toward(pos, plot))
                continue

            tile = hh.tile_at(tiles, plot)
            action = ch._decide(tile, day, hour, catch, season_days)
            if action and action[0] == "PLANT":
                crop = action[1]
                if planted_this_turn.get(crop, 0) < seeds.get(crop, 0):
                    planted_this_turn[crop] = planted_this_turn.get(crop, 0) + 1
                else:
                    action = ["WATER"] if hh._is_live_plant(tile) else ["PASS"]
            actions.append(action)

        farmer_action = actions[0]
        hand_actions = actions[1:]

        # --- Seed restock: melon in the melon phase, the catch crop in the tail.
        # Count only the melon plots a present melon worker can reach. ---
        total_workers = 1 + (n_hire if hour == 0 else len(hands))
        melon_workers = total_workers - (1 if total_workers >= 2 else 0)
        active_plots = min(len(MELON_PLOTS), melon_workers)
        empty_active = sum(
            1 for plot in MELON_PLOTS[:active_plots] if hh.tile_at(tiles, plot) is None
        )
        restock = MELON if melon_open else catch
        if restock is not None and empty_active > 0:
            want_seed = max(0, empty_active - seeds.get(restock, 0))
            if want_seed > 0:
                affordable = int(money // CROPS[restock]["seed"])
                buy = min(want_seed, affordable, 10 - len(market))
                if buy > 0:
                    market.append(["BUY_SEED", restock, buy])

        # --- Animal purchases, lowest market priority (never displace melon). Buy
        # the cow first; the sheep only once the cow line is established. ---
        cow_exists = (
            cow_live
            or shed.get("COW", 0) > 0
            or any(inv.get("COW", 0) > 0 for inv in inventories)
        )
        if (
            not cow_exists
            and money >= ANIMAL_COST["COW"] + COW_MONEY_BUFFER
            and len(market) < 10
        ):
            market.append(["BUY_ANIMAL", "COW", 1])

        sheep_ct = _tile(tiles, SHEEP_TILE)
        sheep_exists = (
            _is_animal(sheep_ct)
            or shed.get("SHEEP", 0) > 0
            or any(inv.get("SHEEP", 0) > 0 for inv in inventories)
        )
        if (
            cow_exists
            and not sheep_exists
            and money >= ANIMAL_COST["SHEEP"] + SHEEP_MONEY_BUFFER
            and len(market) < 10
        ):
            market.append(["BUY_ANIMAL", "SHEEP", 1])

        # --- Keep a WHEAT buffer in the shed to feed BOTH animals. Once the wheat
        # catch-crop is harvesting this rarely fires (the shed stays topped up); it
        # still covers the early game before any catch wheat exists. ---
        line_started = cow_exists or sheep_exists
        wheat_on_hand = shed.get("WHEAT", 0) + sum(
            inv.get("WHEAT", 0) for inv in inventories
        )
        if line_started and wheat_on_hand < WHEAT_BUFFER and len(market) < 10:
            want = WHEAT_BUFFER - wheat_on_hand
            if money >= COW_MONEY_BUFFER:  # never spend melon working capital
                market.append(["BUY_PRODUCT", "WHEAT", want])

        return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


STRATEGY = RanchHandsStrategy
