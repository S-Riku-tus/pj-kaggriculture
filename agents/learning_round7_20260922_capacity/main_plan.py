"""Arm B learned policy with the separately identified task-plan executor."""

import model_compat  # noqa: F401 - installs the model loader before runtime imports policy
import runtime as _runtime


def policy_diagnostics(observation=None):
    return _runtime.diagnostics()


def agent(observation, configuration=None):
    return _runtime.agent_plan(observation, configuration)
