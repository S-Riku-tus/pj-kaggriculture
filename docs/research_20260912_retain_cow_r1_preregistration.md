# H3c-r1：Cow保持 option の評価区間修正

2026-09-12。実装・再対戦前の登録。

`v115p_retain_cow` はt248で意図した `BUY_ANIMAL SHEEP 2` から `BUY_ANIMAL COW 2` への差分を発火2件で出した。しかし評価runnerのactivation windowは終端を含まないのに、manifestを`[248, 248]`としたため、この2件は`activation_outside_preregistered_window`となりinvalidである。行動replayの結果は候補選定に使わない。

`v115p_retain_cow_r1` はagentロジック、発火条件、対戦pool、Development seed、両seat、720 horizonを変えず、manifestだけを`[248, 249)`に直す。version表示とarchive identityを新しくし、invalid版を上書きしない。結果を見た閾値・特徴・行動変更はない。同じ32 pairsを0から再実行し、Freshとpromotion予約seedは使わない。

判定条件は元登録と同じ。複数相手・状態でhard SafetyなしのL→Wがなければselectorを作らない。Kaggle提出は禁止する。
