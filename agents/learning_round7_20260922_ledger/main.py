"""Round6 weights with the Round7 quantity and sequential-market ledger."""

import runtime as _runtime


def agent(observation, configuration=None):
    return _runtime.agent_ledger(observation, configuration)
