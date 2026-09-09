import numpy as np

from scripts.analyze_sheep_option_value_e2 import (
    _fit_logistic,
    _known_town_demand,
    _metrics,
    _predict_logistic,
)


def test_known_town_demand_uses_frozen_window() -> None:
    observation = {"town": {"unlocked_shops": ["YARN_STORE"]}}

    demand = _known_town_demand(observation, 216, 288)

    assert demand["WOOL"] == 39
    assert demand["MILK"] == 3


def test_balanced_logistic_separates_simple_training_data() -> None:
    features = np.array([[-3.0], [-2.0], [-1.0], [1.0], [2.0], [3.0]])
    labels = np.array([0, 0, 0, 1, 1, 1])

    beta, location, scale = _fit_logistic(features, labels)
    probabilities = _predict_logistic(beta, location, scale, features)
    metrics = _metrics(labels, probabilities)

    assert metrics["sensitivity"] == 1.0
    assert metrics["specificity"] == 1.0
    assert probabilities[0] < probabilities[-1]
