"""Official-loader-safe wrapper around the frozen Round6 learned policy."""

import policy as _policy


def agent(observation, configuration=None):
    return _policy.agent(observation, configuration)
