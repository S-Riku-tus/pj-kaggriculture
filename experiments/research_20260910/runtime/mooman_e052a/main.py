from pathlib import Path
import importlib.util
_spec = importlib.util.spec_from_file_location("_public_policy", Path(__file__).with_name("policy.py"))
_policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_policy)
def agent(obs, configuration=None):
    return _policy.agent_entry(obs, configuration)
