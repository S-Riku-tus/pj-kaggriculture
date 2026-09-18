# V120 data notice

The action cases in `model.json.gz` were mechanically derived from public
Kaggriculture competition replays downloaded for the two V119 submissions
specified by the user. V120 contains no copied third-party agent source.

The runtime artifact intentionally strips episode ids, submission ids, team
names, ratings, rewards, outcomes, and all future observations. The retained
data are current-observation feature vectors and the corresponding next action.

The offline builder selects games in which the observed policy beat V119.
That winner selection can bias local results and is explicitly not a claim of
independent holdout validation. See `model_metadata.json` for exact replay
provenance and the research report for limitations.

