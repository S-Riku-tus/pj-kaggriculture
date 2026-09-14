"""The Strategy interface every agent implements.

A Strategy is a pure decision function: given the parsed game state, return the
action dict for this turn. Keeping one signature means strategies are (a)
swappable in a submission and (b) able to fight each other in the local
tournament harness with zero glue code.

Action dict shape (per the competition spec):

    {
        "farmer": [ACTION, *args],      # exactly one action for the main farmer
        "hands":  [[ACTION, *args], ...],  # one per hired hand this day
        "market": [[ORDER, ITEM, N], ...], # up to maxMarketOrdersPerTurn (10)
    }
"""

from __future__ import annotations


class Strategy:
    """Base class for all agents. Subclass and implement `act`."""

    #: Human-readable name, shown in the tournament harness.
    name: str = "unnamed"

    #: When True, this strategy is a fixed "readonly" benchmark opponent: it is
    #: always available as a tournament/promotion opponent, but is never eligible
    #: to be designated champion (see harness.promotion.top_contender). Default
    #: False — ordinary strategies are champion contenders.
    benchmark: bool = False

    def act(self, state) -> dict:
        raise NotImplementedError

    # Optional lifecycle hook: called once at the start of an episode if the
    # runner supports it. Default no-op. Use for per-game setup/caching.
    def reset(self) -> None:
        pass


def make_agent(strategy: Strategy):
    """Wrap a Strategy into a kaggle_environments-compatible `agent(obs)`.

    Wraps `act` in a defensive try/except: a crash during evaluation is an
    automatic loss, so any unexpected error degrades to a safe PASS instead of
    killing the episode. During development set ROBRICULTURE_STRICT=1 to let
    exceptions propagate so bugs are visible.
    """
    import os
    from kaggisim.state import parse

    strict = os.environ.get("ROBRICULTURE_STRICT") == "1"

    def agent(obs):
        try:
            return strategy.act(parse(obs))
        except Exception:
            if strict:
                raise
            return {"farmer": ["PASS"], "hands": [], "market": []}

    return agent
