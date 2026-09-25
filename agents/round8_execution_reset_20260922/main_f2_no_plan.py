"""F2 execution contracts with the handwritten livestock plan disabled."""

import sys as _sys
from pathlib import Path as _Path

_MODULE_DIR = str(_Path(__file__).resolve().parent) if "__file__" in globals() else _sys.path[-1]
for _name in ("runtime", "policy", "model_compat", "common"):
    _sys.modules.pop(_name, None)
_sys.path.insert(0, _MODULE_DIR)
try:
    import model_compat as _model_compat  # noqa: F401
    import runtime as _runtime
finally:
    _sys.path.pop(0)

policy_diagnostics = _runtime.diagnostics


def agent(observation, configuration=None):
    return _runtime.agent_f2_no_plan(observation, configuration)
