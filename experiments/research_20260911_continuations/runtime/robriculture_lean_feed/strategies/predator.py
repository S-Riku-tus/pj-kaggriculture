"""predator: `field_rival` driven by a schedule genome (#199, stage 1).

Every hole in the champion found so far (#244 through #262) was found by hand
and measured on the frozen benchmark's seams. This strategy makes those seams
a search space: 26 floats in [0, 1] decode into a `Schedule` -- the crew,
land, herd and pasture ramps, the crop caps, the pivot, the cluster, the buy
order, the reserve, the floor, the feed carry and stock, and the herd
preference -- and the benchmark's own code runs it. `FROZEN` decodes to the
benchmark's constants, so `PredatorStrategy()` is `field_rival` to the value
(the gate's identity control proves it).

A benchmark opponent: never submitted, never the designation.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import permutations

from strategies import field_rival as fr

#: Breakpoint days of the ramps -- the frozen tables' own, so `FROZEN` is exact.
HAND_DAYS = (0, 8, 12, 16)
HEAD_DAYS = (0, 4, 8, 12, 16, 24)
#: A land day at or past this never comes (the season is 30 days).
NEVER = 30
#: `herd_preference` values by index; 0 is the benchmark's own rule.
PREFER = (None, "SHEEP", "COW")
#: The 24 buy orders, sorted so an index is stable.
PERMS = tuple(sorted(permutations(fr.BUY_ORDER)))

#: (field, lo, hi, count): each float maps to lo..hi; the count is how many
#: floats the field takes. Order is the genome's order.
LAYOUT = (
    ("hands", 1, 10, 4),
    ("land", 0, 31, 2),
    ("head", 0, 12, 6),
    ("pasture", 0, 8, 2),
    ("herders", 0, 3, 1),
    ("cap_melon", 0, 24, 1),
    ("cap_straw", 0, 40, 1),
    ("cap_wheat", 0, 24, 1),
    ("pivot", 4, 16, 1),
    ("cluster", 2, 8, 1),
    ("order", 0, 23, 1),
    ("reserve", 0, 3000, 1),
    ("floor", 0, 2000, 1),
    ("carry", 1, 8, 1),
    ("stock", 0, 16, 1),
    ("prefer", 0, 2, 1),
)
GENOME_LEN = sum(count for _, _, _, count in LAYOUT)


@dataclass(frozen=True)
class Schedule:
    hands: tuple          # hands at HAND_DAYS, non-decreasing
    ne_day: int           # day the second quadrant is bought; >= NEVER never
    sw_day: int           # day the third is; >= ne_day
    head: tuple           # head at HEAD_DAYS, non-decreasing
    nw_pasture: int       # NW pasture tiles (nearest-to-shed order, after tile 0)
    ne_pasture: int       # NE pasture tiles
    herders: int          # workers (1, 2, 3)[:herders] run the livestock line;
                          # 0 is inexpressible: `act` reads `()` as the frozen pair (review, #199)
    cap_melon: int
    cap_straw: int
    cap_wheat: int
    pivot: int
    cluster: int
    order: int            # index into PERMS
    reserve: int
    floor: int            # 0 = no floor
    carry: int
    stock: int            # 0 = the frozen feed_buffer rule
    prefer: int           # index into PREFER

    @classmethod
    def frozen(cls) -> "Schedule":
        """The benchmark's own constants."""
        return cls(
            hands=tuple(fr._ramp(fr.HAND_RAMP, d) for d in HAND_DAYS),
            ne_day=fr.LAND_RAMP[1][0], sw_day=fr.LAND_RAMP[2][0],
            head=tuple(fr._ramp(fr.ANIMAL_RAMP, d) for d in HEAD_DAYS),
            nw_pasture=sum(1 for t in fr.PASTURE_TILES if fr.quadrant_of(*t) == "NW"),
            ne_pasture=sum(1 for t in fr.PASTURE_TILES if fr.quadrant_of(*t) == "NE"),
            herders=len(fr.LIVESTOCK_WORKERS),
            cap_melon=fr.CROP_CAP["MELON"], cap_straw=fr.CROP_CAP["STRAWBERRY"],
            cap_wheat=fr.CROP_CAP["WHEAT"],
            pivot=fr.PIVOT_DAY, cluster=fr.CLUSTER, order=PERMS.index(fr.BUY_ORDER),
            reserve=fr.CAPITAL_RESERVE, floor=0, carry=fr.FEED_CARRY, stock=0, prefer=0,
        )


def _int(u, lo: int, hi: int) -> int:
    u = min(1.0, max(0.0, float(u)))
    return lo + int(round(u * (hi - lo)))


def _float(v: int, lo: int, hi: int) -> float:
    return 0.0 if hi == lo else (v - lo) / (hi - lo)


def _running_max(values) -> tuple:
    out, m = [], None
    for v in values:
        m = v if m is None else max(m, v)
        out.append(m)
    return tuple(out)


def decode(genome) -> Schedule:
    """The schedule a genome encodes. Floats clamp to [0, 1]; ramps are lifted
    to non-decreasing; the SW land day is lifted to the NE one."""
    if len(genome) != GENOME_LEN:
        raise ValueError(f"genome has {len(genome)} floats, expected {GENOME_LEN}")
    vals, i = {}, 0
    for name, lo, hi, count in LAYOUT:
        vals[name] = tuple(_int(u, lo, hi) for u in genome[i:i + count])
        i += count
    ne, sw = vals["land"]
    return Schedule(
        hands=_running_max(vals["hands"]), ne_day=ne, sw_day=max(ne, sw),
        head=_running_max(vals["head"]),
        nw_pasture=vals["pasture"][0], ne_pasture=vals["pasture"][1],
        herders=vals["herders"][0], cap_melon=vals["cap_melon"][0],
        cap_straw=vals["cap_straw"][0], cap_wheat=vals["cap_wheat"][0],
        pivot=vals["pivot"][0], cluster=vals["cluster"][0], order=vals["order"][0],
        reserve=vals["reserve"][0], floor=vals["floor"][0], carry=vals["carry"][0],
        stock=vals["stock"][0], prefer=vals["prefer"][0],
    )


def encode(schedule: Schedule) -> list:
    """The genome for a schedule -- `decode`'s inverse for in-range values."""
    s = schedule
    values = {
        "hands": s.hands, "land": (s.ne_day, s.sw_day), "head": s.head,
        "pasture": (s.nw_pasture, s.ne_pasture), "herders": (s.herders,),
        "cap_melon": (s.cap_melon,), "cap_straw": (s.cap_straw,), "cap_wheat": (s.cap_wheat,),
        "pivot": (s.pivot,), "cluster": (s.cluster,), "order": (s.order,),
        "reserve": (s.reserve,), "floor": (s.floor,), "carry": (s.carry,),
        "stock": (s.stock,), "prefer": (s.prefer,),
    }
    genome = []
    for name, lo, hi, count in LAYOUT:
        vs = values[name]
        if len(vs) != count:
            raise ValueError(f"{name} needs {count} values, got {len(vs)}")
        genome.extend(_float(v, lo, hi) for v in vs)
    return genome


#: The benchmark itself, as a genome.
FROZEN = encode(Schedule.frozen())


def _layout(nw: int, ne: int):
    pasture = tuple(fr._quadrant_tiles("NW")[1:1 + nw] + fr._quadrant_tiles("NE")[1:1 + ne])
    crops = tuple(t for q in fr.OWNED_QUADRANTS for t in fr._quadrant_tiles(q) if t not in pasture)
    return pasture, crops


class PredatorStrategy(fr.FieldRivalStrategy):
    """`field_rival` running a schedule genome. No genome is the benchmark."""

    name = "predator"
    benchmark = True

    def __init__(self, genome=None):
        self.schedule = decode(FROZEN if genome is None else genome)
        s = self.schedule
        self.CAPS = {"MELON": s.cap_melon, "STRAWBERRY": s.cap_straw, "WHEAT": s.cap_wheat}
        self._hands = tuple(zip(HAND_DAYS, s.hands))
        self._head = tuple(zip(HEAD_DAYS, s.head))
        self._tiles = _layout(s.nw_pasture, s.ne_pasture)

    def herd_preference(self, obs):
        return PREFER[self.schedule.prefer]

    def pasture_count(self, day, animals):
        return min(len(self._tiles[0]), max(self.herd_target(day), animals))

    def herd_target(self, day):
        return fr._ramp(self._head, day)

    def livestock_workers(self, day):
        return (1, 2, 3)[:self.schedule.herders]

    def layout(self):
        return self._tiles

    def land_target(self, day):
        s = self.schedule
        return 1 + (day >= s.ne_day) + (day >= s.sw_day)

    def hire_target(self, day):
        return fr._ramp(self._hands, day)

    def capital_reserve(self, day=None, animals=None):
        return self.schedule.reserve

    def pivot_day(self):
        return self.schedule.pivot

    def cluster_size(self):
        return self.schedule.cluster

    def buy_order(self):
        return PERMS[self.schedule.order]

    def spend_floor(self, day=None, animals=None, shed=None, prices=None):
        return self.schedule.floor or None

    def feed_carry(self, animals=None, herders=None):
        return self.schedule.carry

    def feed_stock(self, animals=None):
        return self.schedule.stock or None


STRATEGY = PredatorStrategy
