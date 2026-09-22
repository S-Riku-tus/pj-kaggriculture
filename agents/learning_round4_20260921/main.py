"""Submission entrypoint for the Round4 learned research candidate."""

try:
    from . import learned_main as _implementation
except (ImportError, KeyError):
    import learned_main as _implementation  # type: ignore

reset_runtime_state = _implementation.reset_runtime_state
policy_diagnostics = _implementation.policy_diagnostics
policy_trace = _implementation.policy_trace
# Keep this assignment after every other callable: Kaggle's public loader
# selects the last callable inserted into the empty globals dictionary.
agent = _implementation.agent

__all__ = ["agent", "policy_diagnostics", "policy_trace", "reset_runtime_state"]
