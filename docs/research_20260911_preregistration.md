# 実行可能な継続行動の研究 — 2026-09-11

Experiment: `research_20260911_continuations`。2026-09-11 04:16 UTC時点、実装・介入対戦前の登録。

Production ChampionはV111の凍結archive。V114/r1/probeは棄却を維持する。既存4sourceは実行済みGoldだが、保守的ancestryはPSR/Kaito結合群とqeinsteinの2群。新たなsourceの強さ・独立性は未確認。公開Ratingから実行artifactの強さを推定しない。

| 順位 | 仮説 / mechanism | Evidence | Upside | 主な失敗 / Safety | 複雑さ・評価可能性 / 時間 |
| --- | --- | --- | --- | --- | --- |
| 1 | 小さな売却契約。現在shedの純売却用生産物を前倒しし、相手売却より先に需要を取る | E0動的価格・E1 t293相手Wool売却、selfにWool在庫。勝敗価値は未確認 | 小〜中、資源維持が容易 | 早売り損失、相手価格利益、資金・fallback変化 | 低〜中、72turn窓＋full720 / 30〜60分 |
| 2 | 強い公開complete packageの無改変比較 | 前回E3でV111は複数sourceへ低勝率 | 大の可能性 | source依存、特定componentの誤帰属 | 中、native entrypoint・license確認 / 30〜60分 |
| 3 | 種・買付・給餌を備えたfield continuation | E0/E1で旧suffixの種・購入不成立 | 中〜大 | atomic PLANT、持物・位置・維持が破綻 | 高、24〜72turn実資源から / 60〜120分 |
| 4 | 少数の安全なrouteの最小selector | 安全なL→Wが未発見 | 条件付き中 | library自体に価値なし、結果リーク | 小、順位1/3の成功後のみ / 30〜60分 |
| 5 | public opponent calendarによる売却予測 | 旧供給ridgeはE2、短期phase未証明 | 小〜中 | MAEのみ改善、方策変更なし | 中、同じlibraryでablation / 30〜60分 |
| 6 | 収穫・寿命の調整 | 自然終了と損失の混同を修正中 | 小〜中 | 空作物を延命、掃除手数増加 | 中、失われたunitsの確認後 / 45〜90分 |
| 7 | 終盤数日の再投資停止と換金 | 最後1turnの追加売却だけでは反転なし | 未同定 | 必要feed・収穫・運搬を壊す | 中、full horizon paired / 45〜90分 |
| 8 | scarcity作物・delayed commitment | TopのE1相関 | 中〜大 | 労働・種・管理費、Town/RNG分岐 | 高 / 90分以上 |
| 9 | Mixed opening/PSRO | cycle未確認 | 条件付き | 未証明の複雑化 | 高、payoff cycle確認後のみ |

Primaryは1。狭いfield suffixの資源不整合を避けるため、実際の現在在庫から開始できる売却契約を選ぶ。これはV114閾値調整、Cow/Carrot比率の模倣ではない。即時売却とTown消費後売却の2選択肢を、V111と比較する。販売可能な在庫の存在は機構仮説の根拠であり、改善の証拠ではない。

最初の契約はdecision t361、active window t361〜431。cash >= 4000、標準engine設定、V111 fallbackなしの場合に開始できる。t360の新shopまでがlive情報。対象はSTRAWBERRY/MELON/MILK/WOOL/CARROT/TOMATO/EGGで、種・Wheat・Fertilizer・動物・土地は変えない。現在privateと同turnの自分の作業から、market前のshedを計算し、既存の購入・雇用は全件保持する。販売注文は対象品だけ再構築し、空きslotを超える新規売却は発行しない。新しいfield actionは発行しない。必要資金は0、手数はmarket slotだけ。動的価格は実engineで測定する。

即時optionは各turn、Town optionは観測時点がTown消費直後のstep%4==1で、使用可能slotに現在在庫の売却を追加する。窓外は追加売却を止める。すでに早売りした在庫への後続SELLが空売りにならないよう、対象商品の既存SELLだけを現在のmarket前在庫へcapし、完売した注文は省く。これは不可逆な売却後の終了処理であり、fieldへは介入しない。購入・運搬・seed・worker位置・daily resetの実際の一致は評価で検査する。急なcash/fallback変化があれば追加売却を停止するが、変更済み在庫の売却注文整合は最後まで担当する。

最初は使用済みDevelopment4 seeds×4 source×両seat=32pairs/option。A/Aは2source×2seeds×両seat、通常configuration、fresh module、full rerun。checkpoint高速化は使用しない。pilotは棄却専用。新しい有望libraryが得られた場合のみ、既使用Discovery4seedsも含む64pairsへ展開する。初期72turn窓でsafe L→Wがなければ、selectorを作らず、窓/別decision point/complete policy比較を別登録する。

安全gateは従来のraw crop-to-weed、random weed、動物消失、negative cash、runtime、incomplete、missing actions、field/market no-op、partial commitのcandidate-new増加を維持する。oversized SELLと必要購入の不成立を別途記録するが、旧candidate救済には使わない。t153のroute介入監査とt248の継承取引監査を分離する。Safety failureはcoinや勝率で救済しない。

実行妥当性→actual activation/約定→Safety→paired勝敗→多様性・頑健性→freshの順で判定する。oracleは結果を見た標本内の安全な最良route（baselineを含む）で、deploy可能な勝率ではない。複数の状態・相手でsafe L→Wが確認された場合だけlive観測の最小gateを作る。seed/seat/episode/opponent ancestryを分離し、未来や相手privateはlive入力にしない。

統計は両seat・全sourceをまとめたseed blockでbootstrapする。equal-source/equal-ancestryとstress重みを報告し、実測meta頻度と呼ばない。小さい2ancestryのCIをTop全体への一般化保証にしない。E4は少なくとも3つの検証済み独立ancestry、正のrobust payoff、source別非悪化、十分な発火とseed数が必要。既存frameworkのformal seed予約は10091101〜10091112、freshは10091901〜10091912。資格を満たさなければ一切実行しない。Kaggle提出は行わない。
