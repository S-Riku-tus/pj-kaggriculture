"""Steal the opening book: replay a winner's first three days (issue #207).

#187, #193 and #196 all struggled with the *opening* -- pastures built late,
animals unplaced, feed absent -- while the field stands up 8-11 animals
routinely. So the hypothesis under test is that the herd is hard to
**establish**, not hard to run, and the cheapest way past a phase we are bad at
is to not play it: replay a real winner's recorded first three days verbatim,
then hand the board to an agent that keeps livestock.

Two decisions are load-bearing and both are #207's, not this module's:

* **The hand-over target is the champion**, which #207 re-declared on
  2026-09-06 as `rival_aware` (#222): otherwise "opening + `dense_farm`" against
  `rival_aware` confounds the opening with the herd rule, and the comparison
  stops being "the field's opening, then our best agent" against "our best agent
  alone". `harness.opening_bench.contender` supplies it. This module's own
  default stays `dense_farm` -- a standalone default has to name something, and
  the drafted idea's `neuropilot` is disqualified: its evolved genome sets
  ``herd_target_scale`` to a median 0.0098, which ``_herd_targets`` rounds to
  **zero animals** (#187), abandoning the herd on the turn it took control.
* **The opening is days 0-2**, i.e. the first ``OPENING_TURNS`` turns, and the
  hand-over is the very next turn. `strategies.field_rival.FieldRivalStrategy`
  (which `dense_farm` inherits) reads the whole board every turn and carries no
  cross-turn state, so it takes over a board it did not build cleanly.

The replay half is `strategies.ghost.Ghost` unchanged -- same script, same
``turn_index`` -- because the one trap here is the one #157 already paid for:
the action recorded at replay index ``t`` was applied to the observation at
index ``t-1``. Reading it at its own index scored a whole season at 994 against
an actual 48,144.

Deliberately **not registered**, exactly as `strategies/ghost.py` is: there is
no module-level ``STRATEGY``, so the auto-discovery in ``strategies/__init__.py``
skips this file. Without a book it is `dense_farm` wearing another name, and
registering that would enter a duplicate agent in the tournament and in
``tests/test_no_crash.py``'s beat-random floor. Books are built per replay by
``harness.opening_bench``, and are never committed -- a downloaded replay is
another competitor's play, and this repo does not vendor those (ADR-0005).
"""

from __future__ import annotations

from kaggisim import economy
from kaggisim.strategy import Strategy
from strategies.dense_farm import DenseFarmStrategy
from strategies.ghost import Ghost, replay_actions, turn_index

#: Days of the opening replayed before the hand-over. #207: "a winner's first
#: three days". Days are 0-indexed in the sim, so this is days 0, 1 and 2.
OPENING_DAYS = 3

#: The opening in turns. Single-sourced from the sim's own config so a change
#: to ``turnsPerDay`` cannot silently move the hand-over out from under a
#: declared result.
OPENING_TURNS = OPENING_DAYS * economy.CONFIG_DEFAULTS["turnsPerDay"]


def shift_script(script, by: int = 1):
    """`script` with every action pushed `by` indices later.

    The **negative arm of #207's positive control**, and nothing else. A control
    that cannot fail proves nothing, so the same probe is run against a book
    deliberately holding a shift; if that arm reconstructs the source's day-3
    state too, the probe is not discriminating and the run is void.

    `by` is load-bearing and is the bench's call, not this function's:
    `harness.opening_bench.NEGATIVE_SHIFT` is **6**, because at a 72-turn
    horizon with an idle turn padding each end of the book a one-index shift
    lands the 70 working turns unchanged -- which is exactly how the first run
    of #207 voided.

    Returns a new list: the shifted arm must not corrupt the book the positive
    arm replays.
    """
    return [None] * by + list(script or [])


class OpeningBookStrategy(Strategy):
    """A recorded opening for `opening_turns` turns, then `handover` for good."""

    name = "opening_book"

    #: A contender, not a sparring partner -- this is what #207 would promote.
    benchmark = False

    def __init__(self, script=None, handover=None, opening_turns=OPENING_TURNS):
        #: The opening, replayed by the same object that replays a whole ghost.
        self.book = Ghost(script)
        #: Who plays the other 27 days.
        self.handover = DenseFarmStrategy() if handover is None else handover
        self.opening_turns = opening_turns
        self.calls = 0

    @classmethod
    def from_replay(cls, replay, player, **kwargs):
        """Book `player`'s opening out of a downloaded episode replay."""
        return cls(script=replay_actions(replay["steps"], player), **kwargs)

    def reset(self):
        """Rewind both halves. A reused instance otherwise starts the second
        season mid-book, because the turn counter never went back to zero."""
        self.calls = 0
        self.book.reset()
        reset = getattr(self.handover, "reset", None)
        if callable(reset):
            reset()

    def act(self, state):
        self.calls += 1
        if turn_index(state, self.calls) <= self.opening_turns:
            return self.book.act(state)
        return self.handover.act(state)
