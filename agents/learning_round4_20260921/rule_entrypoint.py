"""Submission entrypoint for the Round4 explicit-rule comparison."""

try:
    from . import rule_main as _implementation
except (ImportError, KeyError):
    import rule_main as _implementation  # type: ignore

reset_runtime_state = _implementation.reset_runtime_state
policy_diagnostics = _implementation.policy_diagnostics
policy_trace = _implementation.policy_trace
# The public Kaggle loader selects the final callable in empty globals.
agent = _implementation.agent

__all__ = ["agent", "policy_diagnostics", "policy_trace", "reset_runtime_state"]
