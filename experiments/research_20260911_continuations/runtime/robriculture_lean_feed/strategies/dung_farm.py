"""A micro-herd kept as a fertilizer mine, on the champion's crop line (#206).

`FERTILIZER` has the gentlest glut curve in the game -- base 100, `linear/0.40`
both sides. It is in no shop and excluded from ``TOWN_CENTER_PRODUCTS``, so
nothing ever drains the market inventory and the price only ever falls; but it
falls slowly, where every other market collapses. Cumulative revenue selling from
the anchor is 9,010 for the first 100 units, 16,020 for 200 and 24,040 for 400,
and the winning field's median fertilizer revenue is 16,794 (#157). So the mine
is bounded but real, and ``COLLECT_FERTILIZER`` is a free byproduct of any tile
that holds an animal: no land, no seed, no growing time.

The hypothesis #206 states: **two to four head, fed on bought wheat, tended by
one dedicated hand**, mine that curve without the crop line paying for it.

What the champion actually does, measured before writing a line of this module
(seed 100 vs `meta_bot`, `harness.episode_analysis`):

    dense_farm   30 planted at day 16   8 head   152 FEED   FERTILIZER 9,820

So the premise of #206's first declared alternative -- "free money the champion
has been leaving on the table" -- is **false**: `dense_farm` inherits
`field_rival`'s two herders and its eleven-head ramp, and it is already mining
fertilizer. What is left to ask is the honest half of the same question, and it
is the half #196 warned about: the champion spends **two of eleven workers** on
that herd, and every feeding is a round trip to the shed. This module keeps one
hand on four head and returns the other to the crop clusters, with the crop caps
untouched, so the difference measured is labour, not density.

`field_rival` and `dense_farm` are both untouched. The benchmark is frozen (it
is the measuring stick), and `dense_farm` is the champion this is measured
against; both would move the thing under test.

**REJECTED** on the criterion #206 declared, kaggle-environments 1.32.7, seeds
300-315 fresh, sides alternated:

    vs dense_farm (the champion)   8/16 = 50%   bar >= 60%   FAIL
    vs meta_bot                   12/16 = 75%   bar >= 90%   FAIL (champion 75%)
    vs field_rival                10/16 = 62%   bar >= 90%   FAIL (champion 94%)
    vs neuropilot                 15/16 = 94%                     (champion 94%)
    vs the four remaining anchors 16/16 = 100%                    (champion 100%)

The necessary condition was met, so this is #206's declared alternative 2 rather
than #187's null: 4 head standing, 87-89 FEED, 30 planted at day 16, fertilizer
6,388-6,829 against a 3,000 bar, and the herd escaped once across sixteen
seasons where the champion's eight-head herd loses four head a season.

What it cost, medians over the same sixteen seeds against a common opponent
(`meta_bot`, so both farms sell into the same market rather than into each
other):

                          dung_farm   dense_farm
    melon revenue            18,469       18,469
    strawberry revenue       22,127       21,362
    wool revenue             20,047       24,555
    fertilizer revenue        6,441        9,820
    WATER / PLANT actions     687/106      687/106

The tenth crop hand bought **766 in strawberry** -- 1.5% of the crop line -- and
changed nothing else, because at these caps the crop line is **cap-bound, not
labour-bound**: STRAWBERRY 22 + WHEAT 8 is 30 tiles, and nine workers already
service 30. The four head it released were worth 3,379 in fertilizer and 6,096
in wool. So the shed round trip #196 measured is not what a second herder costs
here; the second herder costs nothing at this density, and retiring it simply
gives up its herd.

One thing found on the way that is not about this hypothesis: feed is not cheap.
Wheat's base is 25, but five of the eight town shops consume wheat, so the
market price climbs 25 -> 49 across a season while fertilizer's falls 100 -> 65.
And the feed buffer churns -- 254 units bought against 89 feedings.
"""

from __future__ import annotations

from strategies import dense_farm as df
from strategies import field_rival as fr
from strategies import hired_hands as hh

#: The head-count band #206 declared before any code existed, so the herd cannot
#: quietly grow to fit a result.
DECLARED_BAND = (2, 4)

#: The head this farm runs. The top of the declared band, chosen up front rather
#: than swept: the glut curve is what the hypothesis is about, four head collect
#: roughly 110 units over a season, and 110 units is still on the near-linear
#: part of it (100 units -> 9,010). Sweeping 2/3/4 and shipping the best of three
#: at a 6,000-11,200 noise floor (#181) would be selecting noise.
HERD_HEAD = 4

#: One hand, not the benchmark's two. Index 1 so the herder is the earliest hand
#: the crew ramp hires -- the herd has to be standing before the crop area
#: outgrows one quadrant.
LIVESTOCK_WORKERS = (1,)

#: The ramp to `HERD_HEAD`. Held to the benchmark's early shape -- one head from
#: day 0, so the pasture is built and stocked while the crop line is still small
#: -- and then flat, where the benchmark keeps climbing to eleven.
ANIMAL_RAMP = ((0, 1), (4, 2), (8, HERD_HEAD))


def animal_target(day: int) -> int:
    """Head to be running on `day` (1 -> 4, then flat)."""
    return fr._ramp(ANIMAL_RAMP, day)


def crop_slot(worker: int):
    """Crop-cluster slot for a worker index, or ``None`` for the herder.

    The benchmark's own rule with a one-worker livestock crew, which is what
    hands the freed hand a cluster: ten crop workers of `CLUSTER` tiles each
    against the champion's nine.
    """
    if worker in LIVESTOCK_WORKERS:
        return None
    return worker if worker < LIVESTOCK_WORKERS[0] else worker - len(LIVESTOCK_WORKERS)


def crop_cluster(worker: int):
    """The tiles worker `worker` is responsible for -- ``()`` for the herder."""
    slot = crop_slot(worker)
    if slot is None:
        return ()
    return fr.CROP_TILES[slot * fr.CLUSTER:(slot + 1) * fr.CLUSTER]


def active_pastures(day: int, animals: int):
    """Pasture tiles in play today.

    Never fewer than the head already on the board: an animal has to keep being
    fed after the ramp flattens, and it escapes at ``consecutive_unfed >= 2``.
    """
    return fr.PASTURE_TILES[:max(animal_target(day), animals)]


def pasture_chore(tile_xy, tile, pos, inv, shed):
    """The benchmark's pasture chore with one branch in front of it: dig a weed.

    A weed spawns on any empty tile, pasture land included.
    `field_rival._pasture_chore` treats every dict that is not an animal as a
    built structure and answers ``PLACE``, which the sim silently no-ops on a
    ``WEED`` -- so the tile never resolves and the first-match scan answers it
    again next turn, forever. Measured on seed 300: a weed landed on pasture
    (4, 3) on day 7, the herder answered PLACE fourteen times a day for the rest
    of the season, and the herd never grew past one head (2,448 fertilizer
    against a 6,545 median).

    The benchmark survives it because it runs two herders over alternating
    pastures, so a weed costs one herder's half. A single herder has no half to
    lose, which is why the fix belongs here rather than being inherited.
    `field_rival.plot_action` already digs weeds off crop tiles; this is the
    same answer for the other kind of tile.
    """
    if isinstance(tile, dict) and tile.get("kind") == "WEED":
        if [pos[0], pos[1]] == [tile_xy[0], tile_xy[1]]:
            return ["DIG"]
        return hh.step_toward(pos, tile_xy)
    return fr._pasture_chore(tile_xy, tile, pos, inv, shed)


def herd_worker_action(pastures, tiles, pos, inv, shed, hour):
    """The herder's action: the first pasture wanting something, else bank.

    `field_rival.herd_worker_action` with `pasture_chore` substituted for its
    own; the banking tail is the benchmark's, reached the same way.
    """
    for tile_xy in pastures:
        chore = pasture_chore(tile_xy, fr._tile_at(tiles, tile_xy), pos, inv, shed)
        if chore is not None:
            return chore
    return fr.herd_worker_action((), tiles, pos, inv, shed, hour)


def market_orders(day, hour, money, hands, quadrants, animals, shed, seeds,
                  empty_plots, standing=None, caps=None):
    """The benchmark's orders with its herd ramp replaced by the micro-herd's.

    Retired rather than parameterised, because `field_rival` is frozen. It sizes
    the herd buy as ``animal_target(day) - animals - pending``, where `pending`
    is head already bought and waiting in the shed for a herder to walk them out.
    Adding the two ramps' difference to that pending count leaves exactly this
    module's target to buy, and touches nothing else: neither `COW` nor `SHEEP`
    is on the sim's `PRODUCTS` list, so the inflated entry cannot become a sell
    order, and the feed buffer is sized from `animals`, which is untouched.

    Calling the benchmark rather than copying it is deliberate: the sell sweep,
    the hire and land ramps, the seed cap and above all the ten-order truncation
    are subtle and shared, and a copy of them here would drift.
    """
    surplus = max(0, fr.animal_target(day) - animal_target(day))
    if surplus:
        shed = dict(shed or {})
        pending_kind = fr.HERD_MIX[0]
        shed[pending_kind] = shed.get(pending_kind, 0) + surplus
    return fr.market_orders(day, hour, money, hands, quadrants, animals, shed,
                            seeds, empty_plots, standing, caps=caps)


class DungFarmStrategy(df.DenseFarmStrategy):
    """`dense_farm`'s crop line, with one hand on a four-head fertilizer mine."""

    name = "dung_farm"
    benchmark = False

    #: The champion's caps, unchanged. #206's bar is additive: trading crop
    #: tiles for animals is #193/#202's question and is already answered.
    CAPS = df.DenseFarmStrategy.CAPS

    def act(self, obs) -> dict:
        player = obs["player"]
        me = obs["farms"][player]
        private = obs["private"]
        day = obs.get("day", 0)
        hour = obs.get("hour", 0)
        tiles = me["tiles"]
        hands = me.get("hands") or []
        shed = private.get("shed", {}) or {}
        seeds = private.get("seeds", {}) or {}
        inventories = private.get("inventories") or []

        standing = fr.standing_crops(tiles)
        animals = fr.count_animals(tiles)
        # One herder, so it takes the whole list. The benchmark strides the
        # pastures between its two; striding a single herder would be the same
        # list, but saying so explicitly is what keeps a second herder from
        # being reintroduced by accident.
        pastures = active_pastures(day, animals)

        positions = [me["farmer"], *hands]
        used: dict = {}
        actions = []
        for i, pos in enumerate(positions):
            inv = inventories[i] if i < len(inventories) else {}
            if i in LIVESTOCK_WORKERS:
                actions.append(herd_worker_action(pastures, tiles, pos, inv,
                                                  shed, hour))
                continue
            crop = fr.crop_for_plot(day, standing, caps=self.CAPS)
            action = fr.crop_worker_action(crop_cluster(i), tiles, pos, inv,
                                           crop, day, hour)
            if action[0] == "PLANT":
                # One seed per PLANT, and the sim silently no-ops a plant we
                # cannot pay for -- a worker past the seed count burns its turn.
                if used.get(crop, 0) < seeds.get(crop, 0):
                    used[crop] = used.get(crop, 0) + 1
                    standing[crop] = standing.get(crop, 0) + 1
                else:
                    action = ["PASS"]
            actions.append(action)

        empty = 0
        for i in range(len(positions)):
            for tile_xy in crop_cluster(i):
                if fr._tile_at(tiles, tile_xy) is None:
                    empty += 1

        market = market_orders(day, hour, me["money"], len(hands),
                               len(me.get("unlocked_quadrants") or ["NW"]),
                               animals, shed, seeds, empty, standing,
                               caps=self.CAPS)

        return {"farmer": actions[0], "hands": actions[1:], "market": market}


STRATEGY = DungFarmStrategy
