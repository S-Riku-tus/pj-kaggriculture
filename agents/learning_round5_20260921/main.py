"""Submission entrypoint for the Round5 learned arm."""

try:
    from . import learned_main as _implementation
except (ImportError, KeyError):
    import learned_main as _implementation  # type: ignore

reset_runtime_state = _implementation.reset_runtime_state
policy_diagnostics = _implementation.policy_diagnostics
policy_trace = _implementation.policy_trace
# Kaggle's public loader selects the last callable inserted into empty globals.
agent = _implementation.agent
