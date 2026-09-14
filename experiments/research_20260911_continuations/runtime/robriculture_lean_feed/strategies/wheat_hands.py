"""Shop-demand-aware catch crop: WHEAT instead of CARROT (experiment #46, ADR-0007).

Foundation: `mixed_hands`, the current champion — the `wide_hands` 10-tile melon
crew, a CARROT catch-crop filling each plot's post-melon idle tail, one dairy cow,
and the sell-before-hire market ordering. Everything is reused *verbatim* by
importing the champion's helpers; the melon loop, hiring, navigation, cow line and
market plumbing are byte-for-byte identical.

The single variable under test is **which crop fills the idle tail**. The champion
picks CARROT because `choose_catch_crop` ranks by profit-per-occupied-day at *base*
prices: carrot 85/3 ~= 28.3/day beats wheat 90/4 = 22.5/day. But realized clearing
price is driven by shop-demand SCARCITY, not base price — a product demanded by
many shops has its market inventory drained fast, lifting its price. WHEAT is
demanded by **five** shops (BAKERY, PIZZA_SHOP, BRUNCH_SPOT, ICE_CREAM_SHOP,
FARMERS_MARKET); CARROT by two (PET_CAFE, FARMERS_MARKET). The hypothesis: wheat
clears high enough above base that its realized per-day profit overtakes carrot's,
despite carrot's higher sticker price.

Wheat is *also* the cow's feed here, so crop-wheat and feed-wheat must not
cross-contaminate. They are reconciled with a single rule: **sell shed wheat down
to the feed buffer, never below it.** The catch-crop harvest tops the shed up; the
cow eats a couple of units off the top (free feed the champion had to buy); the
surplus is sold into wheat's scarce market. The early-game feed-buffer BUY still
fires before any catch wheat exists, exactly as in the champion — so the cow is
never starved.
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

#: The one variable: the tail catch crop is fixed to WHEAT (the champion picks
#: CARROT by base-price profit-per-day). Wheat is also cow feed, so the sell rule
#: below retains a feed buffer in the shed.
CATCH_CROP = "WHEAT"


def choose_catch_crop(day: int, season_days: int = SEASON_DAYS):
    """WHEAT whenever it can still reach full maturity before the buzzer, else
    ``None``. This is the champion's `catch_hands.choose_catch_crop` with the crop
    forced to wheat — the single variable of this experiment."""
    return CATCH_CROP if ch.cc_plantable(CATCH_CROP, day, season_days) else None


def _sell_orders_keep_feed(shed) -> list:
    """Liquidate the shed like the champion, but sell WHEAT only down to the cow's
    feed buffer — never below it. Crop-wheat surplus clears into wheat's scarce
    market; ``dh.WHEAT_BUFFER`` units stay in the shed for the farmer to FEED with,
    so the catch-crop harvest doubles as free feed."""
    orders = []
    for order in hh.sell_orders(shed):
        if order[1] == "WHEAT":
            sellable = order[2] - dh.WHEAT_BUFFER
            if sellable > 0:
                orders.append(["SELL", "WHEAT", sellable])
        else:
            orders.append(order)
    return orders


class WheatHandsStrategy(Strategy):
    name = "wheat_hands"

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
        catch = choose_catch_crop(day, season_days)
        melon_open = hh.plantable(MELON, day, season_days)

        # --- Market: product SELLs FIRST (carrot/melon/milk + wheat surplus) so
        # the price-sensitive melon SELL sits ahead of the HIRE orders and always
        # clears the 10-order/turn cap. WHEAT is sold down to the feed buffer. ---
        market: list = _sell_orders_keep_feed(shed)

        # --- Hire the crew (mornings only). While melon is plantable this is the
        # champion's rule; in the tail it keeps the crew staffing the catch crop. ---
        n_hire = 0
        if hour == 0:
            n_hire = ch.plan_hands_multicrop(
                day, money, hh.max_live_index(tiles, PLOTS), catch, season_days, MAX_HANDS
            )
            market.extend([["HIRE"]] * n_hire)

        # --- One action per worker. Melon then wheat on each plot; the farmer
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
                # only if the plot wants nothing today — real melon/wheat work
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

            # On its plot: melon loop, then the wheat catch-crop in the tail.
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

        # --- Seed restock: melon in the melon phase, wheat in the tail.
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

        # Keep a small WHEAT buffer for feeding. Once the wheat catch-crop is
        # harvesting this rarely fires (the shed stays topped up); it still covers
        # the early game before any catch wheat exists, exactly as the champion.
        pasture_started = (
            ct is not None or shed.get("COW", 0) > 0 or farmer_inv.get("COW", 0) > 0
        )
        wheat_on_hand = shed.get("WHEAT", 0) + farmer_inv.get("WHEAT", 0)
        if pasture_started and wheat_on_hand < dh.WHEAT_BUFFER and len(market) < 10:
            want = dh.WHEAT_BUFFER - wheat_on_hand
            if money >= dh.COW_MONEY_BUFFER:  # never spend melon working capital
                market.append(["BUY_PRODUCT", "WHEAT", want])

        return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


STRATEGY = WheatHandsStrategy
