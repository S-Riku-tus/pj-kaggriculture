# Artifact evaluation: learning_round4_20260921_learned

| Axis | Status | Reason | Evidence |
|---|---|---|---|
| PACKAGE_VALID | PASS | final archive loaded and completed the required episode checks | LEARNED_LOADER_SEAT0, LEARNED_LOADER_SEAT1, ARCHIVE_MANIFEST |
| EXECUTION_CORRECT | PASS | actor-attributed primitive effects were observed | BEFORE_AFTER_TRACES, pytest:test_learning_round4 |
| TRAINING_EXECUTED | PASS | training performed 216 optimizer updates | TRAINING_RECORD, closed_loop/CLOSED_LOOP_RESULTS |
| MODEL_USED | PASS | model inference was used 5752 times | TRAINING_RECORD, closed_loop/CLOSED_LOOP_RESULTS |
| BEHAVIORAL_FIDELITY | UNKNOWN | held-out decision delta=0.409681, but coherent multi-step plan completion was not measured | TRAINING_RECORD, EPISODE_SPLIT_MANIFEST |
| ECONOMIC_EFFECT | FAIL | mean margin delta -9479.5 is below 0 | CLOSED_LOOP_PROTOCOL, closed_loop/CLOSED_LOOP_RESULTS |
| ONLINE_EVIDENCE | UNKNOWN | no online result is attached | — |
| READY_FOR_DIAGNOSTIC_SUBMISSION | FAIL | not advanced: the limited prospective local panel averaged -9479.5 margin versus the rule arm, the smart_farm cluster was -21126, and all eight learned external games were losses | ARCHIVE_MANIFEST, BEFORE_AFTER_TRACES, CLOSED_LOOP_PROTOCOL, LEARNED_LOADER_SEAT0, LEARNED_LOADER_SEAT1, closed_loop/CLOSED_LOOP_RESULTS, pytest:test_learning_round4 |
| CHAMPION_PROMOTION | FAIL | at least one required promotion axis failed | — |

# Artifact evaluation: learning_round4_20260921_rule

| Axis | Status | Reason | Evidence |
|---|---|---|---|
| PACKAGE_VALID | PASS | final archive loaded and completed the required episode checks | RULE_LOADER_SEAT0, RULE_LOADER_SEAT1, ARCHIVE_MANIFEST |
| EXECUTION_CORRECT | PASS | actor-attributed primitive effects were observed | BEFORE_AFTER_TRACES, pytest:test_learning_round4 |
| TRAINING_EXECUTED | NOT_APPLICABLE | explicit-rule artifact | — |
| MODEL_USED | NOT_APPLICABLE | explicit-rule artifact | — |
| BEHAVIORAL_FIDELITY | UNKNOWN | unused teacher conditions were not evaluated | — |
| ECONOMIC_EFFECT | UNKNOWN | positive mean (9479.5) has a win/loss tradeoff; scope-specific judgment required | CLOSED_LOOP_PROTOCOL, closed_loop/CLOSED_LOOP_RESULTS |
| ONLINE_EVIDENCE | UNKNOWN | no online result is attached | — |
| READY_FOR_DIAGNOSTIC_SUBMISSION | FAIL | comparison arm only; it lost all eight external-family games | ARCHIVE_MANIFEST, BEFORE_AFTER_TRACES, CLOSED_LOOP_PROTOCOL, RULE_LOADER_SEAT0, RULE_LOADER_SEAT1, closed_loop/CLOSED_LOOP_RESULTS, pytest:test_learning_round4 |
| CHAMPION_PROMOTION | UNKNOWN | promotion evidence is incomplete | — |
