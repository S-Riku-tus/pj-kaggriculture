"""Packaged Round10 learned diagnostic arm."""

from policy_runtime import build_agent

_runtime = build_agent("learned")


def latest_diagnostics(*_args):
    return _runtime.round10_diagnostics()


def agent(observation, configuration=None):
    return _runtime(observation, configuration)
