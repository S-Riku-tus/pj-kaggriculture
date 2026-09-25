"""Arm B learned policy with the independently tested Round7 ledger."""

import model_compat  # noqa: F401 - installs the model loader before runtime imports policy
import runtime as _runtime


def agent(observation, configuration=None):
    return _runtime.agent_ledger(observation, configuration)
