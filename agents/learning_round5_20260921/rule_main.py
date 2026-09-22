"""Explicit-selector Round5 runtime on the same BC base and executor."""

try:
    from .policy_runtime import RuntimePolicy
except ImportError:
    from policy_runtime import RuntimePolicy  # type: ignore

_runtime = RuntimePolicy("rule")
reset_runtime_state = _runtime.reset_runtime_state
policy_diagnostics = _runtime.diagnostics
policy_trace = _runtime.coordinator.policy_trace
agent = _runtime.agent
