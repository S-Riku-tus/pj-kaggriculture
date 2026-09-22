"""Learned-selector Round5 runtime."""

try:
    from .policy_runtime import RuntimePolicy
except ImportError:
    from policy_runtime import RuntimePolicy  # type: ignore

_runtime = RuntimePolicy("learned")
reset_runtime_state = _runtime.reset_runtime_state
policy_diagnostics = _runtime.diagnostics
policy_trace = _runtime.coordinator.policy_trace
agent = _runtime.agent
