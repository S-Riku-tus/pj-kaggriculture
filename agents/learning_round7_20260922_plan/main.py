"""Independent learned policy with a small learned-intent task-completion state."""

import runtime as _runtime


def agent(observation, configuration=None):
    return _runtime.agent_plan(observation, configuration)
