"""Ghost opponents: a real ladder rival, replayed move for move (issue #204).

A ghost is not an agent anybody wrote. It is one of the 63 downloaded ladder
replays (#157) played back: at every turn it returns the action the real rival
actually sent at that turn. Sixty-three of them are sixty-three opponents drawn
from the field at our own rating, and nobody had to think of them first.

Two facts about the replay format decide the whole implementation, and both were
paid for in #157:

* **The action recorded at replay index `t` was chosen from, and applied to, the
  observation at index `t-1`.** So an agent looking at an observation whose
  ``step`` is `t-1` owes the action stored at index `t`. Reading the action at
  its own index prices it against the state it already produced -- that error
  scored a whole real season at 994 against an actual 48,144.
* **A ghost never improvises.** Past the end of its script, or on a slot the
  replay did not record as a dict, it PASSes. Anything else would be this module
  inventing a move and attributing it to a real player.

Deliberately **not registered**: there is no module-level ``STRATEGY`` here, so
the auto-discovery in ``strategies/__init__.py`` skips this file (no edit to that
file is needed -- CLAUDE.md). A ghost has no behaviour without a replay, and a
scriptless one is a PASS bot; registering that would put a do-nothing agent in
the tournament and under ``tests/test_no_crash.py``'s beat-random sanity floor.
Ghosts are built per replay by ``harness.ghost_bench``.

``benchmark = True`` all the same: a ghost is a measurement opponent, so if one
ever is registered, ``scripts/submit.py`` refuses to package it (ADR-0005) and
``harness.promotion.top_contender`` refuses to promote it.

**The limitation is in the design, not the discussion: a ghost cannot react.**
It plays its recorded sells whatever we do, so any strategy that exploits
passivity looks better against ghosts than it is. Ghosts are a loss-mechanism
bench and a calibration check, never a promotion gate (#204).
"""

from __future__ import annotations

from kaggisim.strategy import Strategy

#: What a ghost does when the replay has nothing to say.
PASS = {"farmer": ["PASS"], "hands": [], "market": []}


def replay_actions(steps, player):
    """One player's recorded actions, indexed by replay index.

    Index 0 is the pre-game slot and is kept so the list index *is* the replay
    index -- the offset above is the only place an off-by-one can hide, and it
    lives in `turn_index` alone. A slot the replay did not record as a dict
    (a timeout, an error string, a missing player) becomes ``None`` rather than
    a guess.
    """
    out = []
    for step in steps:
        slot = step[player] if isinstance(step, (list, tuple)) and player < len(step) else None
        action = (slot or {}).get("action")
        out.append(action if isinstance(action, dict) else None)
    return out


def turn_index(obs, fallback):
    """The replay index whose action this turn owes: ``obs["step"] + 1``.

    The framework merges player 0's shared observation into both agents' before
    calling them, so ``step`` is the env's current state index and is normally
    present. `fallback` (the ghost's own call count) covers the case where it is
    not -- a stored player-1 observation, for instance, carries no ``step``.
    """
    step = obs.get("step") if isinstance(obs, dict) else None
    return step + 1 if isinstance(step, int) else fallback


class Ghost(Strategy):
    """Replays one player's recorded actions from one downloaded replay."""

    name = "ghost"

    #: Measurement opponent only -- never packaged, never promoted.
    benchmark = True

    def __init__(self, script=None):
        #: Recorded actions indexed by replay index (see `replay_actions`).
        self.script = list(script or [])
        self.calls = 0

    @classmethod
    def from_replay(cls, replay, player):
        """A ghost of `player` in a downloaded episode replay."""
        return cls(replay_actions(replay["steps"], player))

    def reset(self):
        self.calls = 0

    def act(self, state):
        self.calls += 1
        index = turn_index(state, self.calls)
        if 0 <= index < len(self.script):
            action = self.script[index]
            if action is not None:
                return action
        return PASS
