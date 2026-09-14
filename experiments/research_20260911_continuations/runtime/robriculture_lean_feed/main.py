"""Import isolation and diagnostics only; native entrypoint is preserved verbatim."""
import importlib.util
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
for key in list(sys.modules):
    if key.split(".")[0] in {"kaggisim", "strategies"}:
        del sys.modules[key]
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("_rob_native", HERE / "native_entrypoint.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
_caught = []
def reset_runtime_state():
    _caught.clear()
    native._agent = native.STRATEGY()
    original = native._agent.act
    def tracked(state):
        try:
            return original(state)
        except Exception as exc:
            _caught.append({"type": type(exc).__name__, "message": str(exc)})
            raise
    native._agent.act = tracked
def agent(obs, configuration=None):
    return native.agent(obs)
def policy_diagnostics(obs):
    return {"research_decision": {"native_caught_exceptions": list(_caught), "committed": False}}
reset_runtime_state()
