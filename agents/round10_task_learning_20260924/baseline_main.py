from policy_runtime import build_agent

agent = build_agent("baseline")


def latest_diagnostics(*_args):
    return agent.round10_diagnostics()
