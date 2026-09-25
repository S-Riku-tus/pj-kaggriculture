"""Official-loader-safe wrapper for the Arm B capacity-only learned policy."""

import model_compat  # noqa: F401 - installs the model loader before policy import
import policy as _policy


def agent(observation, configuration=None):
    return _policy.agent(observation, configuration)
