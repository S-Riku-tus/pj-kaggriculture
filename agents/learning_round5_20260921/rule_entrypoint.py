"""Submission entrypoint for the Round5 explicit-rule selector arm."""

try:
    from . import rule_main as _implementation
except (ImportError, KeyError):
    import rule_main as _implementation  # type: ignore

reset_runtime_state = _implementation.reset_runtime_state
policy_diagnostics = _implementation.policy_diagnostics
policy_trace = _implementation.policy_trace
agent = _implementation.agent
