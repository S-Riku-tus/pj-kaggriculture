# 2026-09-14 新規研究・事前登録

Experiment `research_20260914_lowcash`。開始 2026-09-14 02:33 UTC、上限07:33 UTC。前回は完了済み。Kaggle提出禁止、production V111を維持。以下は今回の新規対戦前に登録する。

## 証拠と仮説順位

全32既使用Development contextのt216–360を、元engineのfieldとmarket実処理で再構成した。32×144×2 player-stepの現金残差は0。既存market helperの最終farm/private/marketとも一致。これはこの標準configuration・この区間の会計照合であり、全mechanicsの証明ではない。

低資金8敗戦はmooman/souvik×10091011/10091014×両seat。全てcash≥1500を満たさず、同時にt248のCow2注文も存在しない。shed容量・標準設定・fallback条件は成立する。t216–360に自己の失敗BUY/HIREは0。従って既存動物optionの未発火を、必要購入が資金不足で失敗した証拠にはできない。

mooman/10091011/seat0ではt248–288のself現金は+6777、相手+13870。Melon売却収入9048対16061、土地代は双方2000。t216–360のMelon収穫は42対72。selfも資金を増やしており、残高差の拡大だけから過剰投資とは言えない。資産構成と収穫・販売の差があるが、その因果割合は未証明。

| 順位 | 仮説・機構 | 対象敗戦・証拠 | 利益規模の根拠 | 実装・Safety・評価時間 | 棄却条件 |
| --- | --- | --- | --- | --- | --- |
| 1・Primaryへ転換 | MIT公開mooman e052a complete policyを開始時から実行 | V111の全20敗戦を含む32 context。旧相互対戦では2sourceに6/8勝、E3限定 | 数千coinの差を持つ既存全体比較。component優位は推定しない | native agent_entry・全管理既存、包装と評価拡張。raw weed/no-op増加リスク。32pairsと確認64–128pairs、実測で決定 | Safety回帰、自己対戦除外で無改善、特定source依存 |
| 2・当初仮説を保留 | 低資金状態の調達・投資・売却contract | 未発火8敗戦。しかし失敗購入0/8、Cow2注文も無し。E0/E1 | cash引下げだけでは利益を見積もれない | 新しい管理系が必要、60–120分 | 資金→必須作業失敗のつながりを示せないため今回は実装しない |
| 3 | 必要Wheatの注文順・前日調達 | 他のcontextでt234/242買付不足あり、E1 | feed欠落と後続減産があり得るが遠い敗戦も含む | field先行・容量・価格を含む契約、中規模、45–90分 | PASS置換だけ、または独立した安全勝敗改善なし |
| 4 | 生産規模・収穫運搬・再投資変更 | Melon42対72、Milk等差。E1 | 数千coinの売却差は実在するが増産分と単価の媒介は未同定 | 開始がt216より前の可能性、全管理、大、90分超 | 単なる比率模倣・資源不成立 |
| 5 | 最終数日の再投資停止・換金 | 旧361–431は反証にならない、E1 | 終端proxyは平均46coin、単純残品売却の規模は弱い | 中、45–90分 | 数千coinの敗戦を変える具体例なし |

Primary変更理由はH1の必要な因果鎖が見つからないこと。完成policy比較を独立した実験として扱い、途中介入の復帰条件を適用しない。最初のlibraryはV111＋mooman completeの2本。無差別に候補を追加しない。selector/forecastは有効library上の安全oracleが複数seed・相手に改善した場合だけ検討する。

## 凍結panelと実行契約

controlは既存V111 archive、candidateは既存mooman archiveのpolicy.pyを無改変で包装した `v116_mooman_complete`。MIT licenseを同梱し、source/runtime/archive SHA256をfreeze JSONに保存する。native入口agent_entry。live入力は標準observationとconfigurationのみ。独自にseed/opponent ID/未来/private情報を加えない。全調達・植付け・水・給餌・収穫・運搬・売却・雇用・土地管理を既存complete policyが719 decisionsまで担当する。開始時から別policyなのでV111への途中fallbackは作らない。

Discovery本評価は旧4source×10091011–10091014×両seat=32 paired contexts、各arm720状態。全て新規full rerun。旧結果は比較監査用であり、新しい計算件数には加えない。runtime/delivery pilotは10091011のmooman/qeinstein両seat、候補の結果によるpanel選別に使わない。A/AはV111とcandidate各々についてqeinstein相手・10091011・両seat。fresh importと同一プロセス内再実行も確認する。

各taskはcandidate/opponent/control archive members、engine .py/.json、configuration、evaluation core、preregistration、phase manifestをhash照合する。resumeは同じidentityと重複無し完了JSONLだけ。partial JSONLは自動で捨てない。checkpoint再開は使わない。qeinsteinのsys.modules内埋込packageはarm/seat importごとに分離する。この変更が旧結果へ影響したか、新controlと旧controlのaction/stateを比較する。

raw Safetyは旧hard判定（weed、animal loss、negative cash、runtime/incomplete、no-op、partial、missing hand増加）を保持。合計改善で新規no-opを隠さないよう、step/unit/action別の新規失敗を追加集計し、安全oracleから除外する。必須購入不成立とoversized SELLを別表示する。complete source全体にraw回帰があれば、勝率が高くてもpromoteしない。自然寿命・未収穫yield・水切れ等は原因診断として併記し、判定緩和には使わない。

complete-policyの共通prefixは、初期stateの一致と、最初のaction差までの実観測とaction一致を検査する。両policyの内部stateは元々異なるので同一とは要求しない。対照armの再現とmodule resetはA/Aで確認する。Town/RNG分岐後も元engineの総policy効果に含む。

## 独立性・確認・判定

seed blockは同seedの全source・両seat。旧4sourceのancestryは保守的2群（PSR/Kaito結合群、qeinstein）。equal-source、equal-ancestry、各source±0.2の9シナリオ、mooman自己対戦除外、PSR/Kaito近縁相手除外を予め報告対象とする。stressは実meta頻度ではない。BTは補助診断でRatingに換算しない。

候補がraw Safety/履行/妥当性を通り、safe改善が少なくとも2 seed blockかつ2相手sourceに出れば、凍結を保って新規Development確認seed10091421–10091428（8blocks、64pairs）を結果を見る前に登録して実行する。throughputが十分で残り時間60分以上を確保できれば10091429–10091436の追加8blocksも最初の確認manifestに同時登録できる。確認結果を見て追加数を変えない。Safety回帰があるcomplete policyは、raw成績が有望なら改善箇所を特定する目的の未昇格確認として同じ新規seedを使えるが、E4資格とは呼ばない。

E4最低要件：検証済み独立ancestry≥3、凍結確認≥16独立seed blocks、全体active≥64、baseline敗戦上のsafe delivery≥16、safe改善≥4 seed blocksかつ≥2 ancestry、全source別win-score非悪化、9stress/equal-ancestry/exclude-selfの増分が正、whole-seed bootstrap95%下限>0、raw/追加Safety・runtime・delivery違反0。3群目が弱いanchorだけなら強いmetaへの一般化は未証明と明記する。

E5は上記を全て満たした場合だけ、予約10091901–10091912の全12blocks・同じ固定pool両seatを一度開く。合格は違反0、全体win-score増分>0、whole-seed bootstrap95%下限>0、全source非悪化、9stress増分>0。candidate/gate/threshold/source/featuresを一切調整しない。E4/E5を5時間内に合理的に完了できなければFreshは開かない。promotion予約10091101–10091112も未使用のまま保持する。

最終ラベル：PROMOTEはE4+E5合格時のみ。Safety/無改善はREJECT、正の再現成績があって資格・多様性不足ならPROMISING_UNPROVEN。research-only archiveとproduction用archiveを区別し、いずれも今回はKaggle提出しない。
