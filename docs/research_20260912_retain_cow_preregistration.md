# 第4 library：V111 の late Sheep 分岐を既存 Cow 系列へ戻す

2026-09-12。実装・対戦前の登録。

Evidence: v115p_livestock は V111 が `late_goal` を選ばなかった22/32 pairsで Sheep2頭への置換を強制し、L→W 0、W→L 2、発火22件すべてで新規 silent field/market no-opを生じた。売却だけを追加した2案も全32pairsで安全に発火したが、いずれもL→W 0だった。したがって次の比較は新しい動物管理を足さず、V111自身がt216で選んだlate Sheep分岐を、V110由来の完成済みCow購入・運搬・配置・給餌系列へ戻す。

H3c: t248でlate Sheep分岐を実行できる状態の一部では、既存Cow系列を保持する方がfull-horizon勝敗で強い。これはV114の閾値調整ではない。t216のモデル判定値、相手identity、未来Town、private情報をgateに使わず、同一状態から実行可能な二つの既存行動系列の価値だけを測る。

発火条件は標準engine、fallbackなし、t248直前にV111の`late_goal`が存在し、cash>=1500であること。発火時は`late_goal`だけを消し、V111/V110の元のCow2購入以降をそのまま実行する。market、field、seed、雇用、売却、行動記憶に独自処理を追加しない。発火後はSheep分岐へ戻さない。t248の出力に`BUY_ANIMAL COW 2`がちょうど1件ない場合はinvalidとして扱い、価値の証拠に使わない。

同じ使用済みDevelopment 4 seeds（10091011–10091014）×4 sources×両seatの32 pairs。control/treatmentとも原engineで0から720まで実行し、archiveを固定し、介入前action/state一致、seed解決、完走、全step Safetyを確認する。Fresh、E4/E5、promotion予約seedは使用しない。

複数相手または複数状態でhard SafetyなしのL→Wがあり、W→Lとの関係でも純改善を示す場合だけselector候補とする。L→Wがなければselectorは作らない。単一seedのmargin改善だけでは昇格しない。Kaggle提出は禁止する。
