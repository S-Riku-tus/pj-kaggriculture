"""Price-adaptive sell mix on the ranch (experiment #52, ADR-0007).

Foundation: `ranch_hands`, the champion — a 9-tile melon crew, a dedicated
livestock hand running a cow + sheep cluster, a WHEAT catch-crop that doubles as
feed, and the sell-before-hire market ordering. Everything is reused *verbatim*
by importing the champion's helpers; the melon loop, hiring, navigation, animal
state machine and market plumbing are byte-for-byte identical.

The single variable under test — a **price-adaptive melon sell rule**. The 1v1
ladder shares **one** melon market, and MELON is demanded by **no** town shop, so
melon inventory an opponent dumps is never drained by consumption — it just sits
there depressing the price (`market_price` falls as inventory rises above I0).
`ranch_hands` liquidates its whole melon shed every turn, so against an opponent
that *floods* melon to crash the price (a market-crash adversary — see the
`spoiler` sparring partner built for this experiment), it realises its melons at
the bottom of the trough.

This variant reads the live melon price out of the observation and adapts:

- **Healthy melon market** (price at/above ``DEPRESSED_RATIO`` of base): dump the
  melon shed exactly as the champion does. No behaviour change at all.
- **Depressed melon market** (price below the threshold): **throttle** melon
  selling to a trickle (``MELON_THROTTLE`` units/turn) so we hold melon out of
  the trough, and lean on the **next-best markets** instead — the non-melon
  products (wheat surplus, milk, wool) still clear in full, so income shifts onto
  markets the melon flood cannot erode. Because the melon price *recovers* between
  an opponent's dumps (nothing consumes the built-up inventory, but neither does
  it keep falling once dumping pauses), held melon clears later at a far better
  price than dumping it into the crash would have.
- **End-game liquidation window** (`greedy_horizon.is_endgame`): dump everything
  regardless of price — melon held past the buzzer scores nothing, so the throttle
  is lifted for the final couple of days.

Only the sell rule changes; hiring, planting, navigation and the animal line are
the champion's. The decision lives in pure module-level helpers (`melon_price`,
`melon_depressed`, `adaptive_sell_orders`) so the technique is unit-tested without
a full 720-turn game.
"""

from __future__ import annotations

from kaggisim import economy, state
from kaggisim.strategy import Strategy
from strategies import catch_hands as ch
from strategies import greedy_horizon as gh
from strategies import hired_hands as hh
from strategies import ranch_hands as rh

#: The market whose price we adapt to.
MELON = "MELON"

#: Melon's base (undepressed) price — the yardstick the throttle measures against.
MELON_BASE = economy.base_price(MELON)  # 250

#: A melon market is "depressed" once its price falls below this fraction of base.
#: 0.6 -> below $150. Normal ranch self-play only grazes this at its deepest dump
#: dip; a melon-flooding opponent drives well under it, which is when we adapt.
DEPRESSED_RATIO = 0.6

#: Melons sold per turn while the market is depressed — a trickle, not a dump, so
#: the bulk of the shed is held for the price to recover (and liquidated in the
#: end-game window regardless).
MELON_THROTTLE = 2


def melon_price(prices) -> float:
    """The live melon price from the observation, or base if none is quoted yet."""
    if not prices:
        return MELON_BASE
    return prices.get(MELON, MELON_BASE)


def melon_depressed(prices, ratio: float = DEPRESSED_RATIO) -> bool:
    """True when the shared melon market is depressed below ``ratio`` of base."""
    return melon_price(prices) < MELON_BASE * ratio


def adaptive_sell_orders(shed, prices, endgame: bool = False,
                         throttle: int = MELON_THROTTLE) -> list:
    """The champion's shed liquidation, made price-adaptive for melon.

    When melon's market is healthy — or when we are in the end-game liquidation
    window — this is exactly `ranch_hands._sell_orders_keep_feed`: dump the whole
    melon shed and clear every other product (wheat only above the feed buffer).

    When melon is depressed mid-game, the melon SELL is capped at ``throttle``
    units (the rest is held for a better price) while the non-melon orders — the
    next-best markets — pass through untouched, so the realised sell mix tilts off
    the crashed melon market and onto wheat / milk / wool.
    """
    base_orders = rh._sell_orders_keep_feed(shed)
    if endgame or not melon_depressed(prices):
        return base_orders
    throttled = []
    for order in base_orders:
        if order[1] == MELON:
            n = min(order[2], throttle)
            if n > 0:
                throttled.append(["SELL", MELON, n])
        else:
            throttled.append(order)
    return throttled


class RanchAdaptiveStrategy(Strategy):
    name = "ranch_adaptive"

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

        season_days = rh.SEASON_DAYS
        catch = rh.choose_catch_crop(day, season_days)
        melon_open = hh.plantable(rh.MELON, day, season_days)

        # --- Market: the one variable. The champion dumps the whole melon shed
        # here; we throttle melon when its shared market is depressed (unless we
        # are in the end-game liquidation window) and lean on the next-best
        # markets instead. Everything else about the ordering is the champion's:
        # product SELLs lead so they clear the 10-order/turn cap ahead of HIRE. ---
        prices = state.prices(obs)
        endgame = gh.is_endgame(day, season_days)
        market: list = adaptive_sell_orders(shed, prices, endgame)

        # --- Hire the crew (mornings only) — the champion's multicrop rule. ---
        n_hire = 0
        if hour == 0:
            n_hire = ch.plan_hands_multicrop(
                day,
                money,
                hh.max_live_index(tiles, rh.MELON_PLOTS),
                catch,
                season_days,
                rh.MAX_HANDS,
            )
            market.extend([["HIRE"]] * n_hire)

        # --- One action per worker. Worker 1 is the livestock hand; every other
        # worker runs the champion's melon+wheat loop on its plot. ---
        positions = [me["farmer"], *hands]
        cow_ct = rh._tile(tiles, rh.COW_TILE)
        cow_live = rh._is_animal(cow_ct)
        planted_this_turn: dict[str, int] = {}
        actions = []
        for i, pos in enumerate(positions):
            if i == 1:
                inv = inventories[i] if i < len(inventories) else {}
                actions.append(rh.livestock_action(pos, tiles, inv, shed, cow_live))
                continue

            plot = rh.melon_plot_for(i)
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

        # --- Seed restock: melon in the melon phase, the catch crop in the tail. ---
        total_workers = 1 + (n_hire if hour == 0 else len(hands))
        melon_workers = total_workers - (1 if total_workers >= 2 else 0)
        active_plots = min(len(rh.MELON_PLOTS), melon_workers)
        empty_active = sum(
            1 for plot in rh.MELON_PLOTS[:active_plots] if hh.tile_at(tiles, plot) is None
        )
        restock = rh.MELON if melon_open else catch
        if restock is not None and empty_active > 0:
            want_seed = max(0, empty_active - seeds.get(restock, 0))
            if want_seed > 0:
                affordable = int(money // rh.CROPS[restock]["seed"])
                buy = min(want_seed, affordable, 10 - len(market))
                if buy > 0:
                    market.append(["BUY_SEED", restock, buy])

        # --- Animal purchases, lowest market priority (never displace melon). ---
        cow_exists = (
            cow_live
            or shed.get("COW", 0) > 0
            or any(inv.get("COW", 0) > 0 for inv in inventories)
        )
        if (
            not cow_exists
            and money >= rh.ANIMAL_COST["COW"] + rh.COW_MONEY_BUFFER
            and len(market) < 10
        ):
            market.append(["BUY_ANIMAL", "COW", 1])

        sheep_ct = rh._tile(tiles, rh.SHEEP_TILE)
        sheep_exists = (
            rh._is_animal(sheep_ct)
            or shed.get("SHEEP", 0) > 0
            or any(inv.get("SHEEP", 0) > 0 for inv in inventories)
        )
        if (
            cow_exists
            and not sheep_exists
            and money >= rh.ANIMAL_COST["SHEEP"] + rh.SHEEP_MONEY_BUFFER
            and len(market) < 10
        ):
            market.append(["BUY_ANIMAL", "SHEEP", 1])

        # --- Keep a WHEAT buffer in the shed to feed BOTH animals. ---
        line_started = cow_exists or sheep_exists
        wheat_on_hand = shed.get("WHEAT", 0) + sum(
            inv.get("WHEAT", 0) for inv in inventories
        )
        if line_started and wheat_on_hand < rh.WHEAT_BUFFER and len(market) < 10:
            want = rh.WHEAT_BUFFER - wheat_on_hand
            if money >= rh.COW_MONEY_BUFFER:  # never spend melon working capital
                market.append(["BUY_PRODUCT", "WHEAT", want])

        return {"farmer": farmer_action, "hands": hand_actions, "market": market[:10]}


STRATEGY = RanchAdaptiveStrategy
