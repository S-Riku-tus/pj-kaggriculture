from __future__ import annotations

import numpy as np

from agents.learning_next_20260921.common import ACTOR_TOKENS
from scripts.train_round6_sequence_bc import FeatureView, prefix_features


def test_prefix_features_keep_counts_and_immediate_predecessor_separate() -> None:
    values = prefix_features(["NORTH", "NORTH", "PICKUP:WHEAT"])
    width = len(ACTOR_TOKENS)
    assert values.shape == (2 * width,)
    assert values[ACTOR_TOKENS.index("NORTH")] == np.float32(2 / 3)
    assert values[ACTOR_TOKENS.index("PICKUP:WHEAT")] == np.float32(1 / 3)
    assert values[width + ACTOR_TOKENS.index("PICKUP:WHEAT")] == 1
    assert values[width:].sum() == 1


def test_feature_view_applies_row_mapping_and_token_one_hot() -> None:
    base = np.asarray([[1, 2], [3, 4], [5, 6]], dtype=np.float32)
    prefix = np.asarray([[10], [20], [30]], dtype=np.float32)
    token_ids = np.asarray([0, 1, 0], dtype=np.int64)
    view = FeatureView(base, prefix=prefix, rows=np.asarray([2, 0]), token_ids=token_ids, token_width=2)
    result = view.get(np.asarray([0, 1]))
    assert result.tolist() == [[5, 6, 30, 1, 0], [1, 2, 10, 1, 0]]
