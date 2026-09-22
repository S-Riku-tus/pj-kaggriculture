# Kaggriculture Round5 Report

## 1. 再現した事実

- 入力 `learning_round4_20260921.zip` のSHA-256は `ae89c1fb503af470b3b670b810c3344f065cabd9587730316bd6d84998042572` で指定値と一致した。独立監査を標準ライブラリだけで再実行し、16 replay、全720状態・DONE/DONE、learned/ruleとも0勝8敗、平均終局資金2,458/3,253.25を再現した。
- HARVEST 722件のうちactor在庫増576、後続actorの同一target重複144、日替わりUNKNOWN 2、未成熟0を再計算した。家畜配置38、消失35、家畜HARVEST 0、正yield上滞在660も一致した。
- Round4で欠落報告された5項目を含むEVIDENCE_HASHES 23/23をローカル実物から回収し、全hash/bytes一致を確認した。engineは `kaggle-environments==1.32.7`、SHA-256 `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`。
- 開始時と終了時のtracked diffを改行/BOM正規化後に比較し完全一致した。既存の未コミットRound3変更は変更していない。
- 序盤96行動は保存replayから再計算し、牛4頭購入、土地1、WHEAT売却12、record48で初期牛2頭消失、record49で現金0を再現した。

## 2. 実ソース上の原因

- Round4 executorはFEED/WATER/CAREだけを予約し、同一joint action内のHARVEST yield、PICKUP shed、PLANT seed/tile、fertilizer、BUILD/DIG、capacityをfarmer→hand順の作業状態へ反映していなかった。このため後続actorが消費済みtargetへHARVESTした。
- crop専用のharvest plan/帰属がanimal productを扱わず、selectorの19特徴もanimal type/yield/production deadline/actor位置を欠いた。Round4特徴ではyield 0/6が同一になった一方、旧BC actor特徴はこの差を保持していた。
- 旧BCのcodec自体はlosslessだが、runtime出力数量はtoken別中央値だった。28,760 teacher joint actionの同値率は0.6056、actor 0.9804、market 0.6610で、不一致はactor数量圧縮5,635、market数量圧縮12,835だった。技能カードのWHEAT 5→runtime 3は入力差や分類誤差ではなく固定中央値圧縮と確定した。
- success counterはbase primitive、override、plan、cash realizationが混在し、日末resetや後続actorによるtarget消費をFAILEDにしていた。Round5では母集団とUNKNOWN理由を分離した。

## 3. 修正内容

- `WorkingState`へHARVEST/PICKUP/PLANT/FEED/WATER/CARE/fertilizer/DROP/PLACE/BUILD/DIGとshed capacityを実装し、固定engineのfarmer→hand順・PLANT原子判定を再現した。資源を失った後続actorは別jobへ再割当てし、形式的PASS置換だけにはしていない。
- crop/animal共通のtyped target、actor/day/placement version、資源予約、ordered primitives、deadline、postcondition、abort条件を持つplanへ変更した。正式12局では重複HARVEST 0、未成熟HARVEST 0、観測上FAILED 0だった。UNKNOWNは日末actor reset、後続target消費、net market delta等として残した。
- 家畜planを購入→配置→維持→回収→倉庫→売却へ接続し、維持方針に応じたcash/WHEAT予約と明示RETIREを実行へ接続した。terminalでshed capacityが回収を阻む場合もRETIRE理由として記録する。
- 市場台帳はactor処理後のshed/capacityを使い、own queueをslot順・1個ずつの価格更新・部分約定・売却入金再投資で模擬する。相手の同時注文は意思決定時に不可視なので不確実性として残す。

## 4. 実際に学習したもの

- 単一teacher submission 56216119由来を維持し、private version/current rankはUNKNOWNのままにした。36特徴・4クラスsoftmax selectorを実学習し、18 epoch・216 optimizer update、parameter L2 change 2.444634を保存した。
- test accuracyは0.6000（多数派0.7000）で多数派未満、macro-F1は0.5439（多数派0.2059）で上回った。checkpoint再読込推論はfinite。これは連続plan再現の十分条件ではない。
- 3技能×4 episodeの連続train/development系列を保存した。teacher-prefixは3 episodeで全状態をprefixまで完全一致させ、24/48/96 stepを実モデルで閉ループ実行した。自己資金差は教師軌跡比 −44/−81/+3。private teacherへlearner状態queryはしておらずDAggerとはしていない。

## 5. 同条件で完遂した技能

- 固定engineの牛scenarioはrecord 1購入→3配置→5給餌→6 CARE→193 MILK 6回収→194 shed→195 SELLを完遂し、資金3,000→3,231（初回売却まで+231）。
- 羊scenarioはrecord 1購入→3配置→5給餌→6 CARE→145 WOOL 6回収→146 shed→147 SELL、資金3,000→3,225（+225）。
- 同一牛へ2actorがHARVESTしたengine probeはMILK [1,0]、総量1で二重計上なし。全101回帰テストがPASSした。

## 6. 資金・相手資金・margin

- 事前固定した未使用seedは qeinstein_moev2/2026100501 と smart_farm/2026100502。両seatは独立標本とせず family×seed の2 clusterとして扱った。
- LEARNED−NONE（4局）は Δself -760.50、Δopponent +1245.00、Δmargin -2005.50。qeinstein clusterはmargin −4,912、smart_farmは+901で1正1負、learnedは全4局敗北した。
- RULE−NONEは Δself +134.00、Δopponent -229.00、Δmargin +363.00、同じく1正1負。
- 凍結Round4 learnedは同じ4局で自己資金平均729.5、重複HARVEST 49。Round5 learnedとの差は Δself +11,827.25、Δopponent −9,926.75、Δmargin +21,754。ただしselector/model/executorが同時に変わった全artifact回帰であり、executor単独効果ではない。
- 店舗系列はqeinsteinの一部で分岐し、learned−NONEの最初のtown差はrecord 432/504、smart_farmでは差なし。相手行動の最初の差も別記録した。相手資金差を意図的妨害学習とは解釈しない。

## 7. 未実行事項

- Kaggle提出、新規online game、新ratingは0。ゲーム内資金とratingを混同しない。rating 2,000/3,000達成は未測定であり約束しない。
- 大規模GPU、有料API、cloudは未使用。Round3の384 scan候補は未評価のまま保存し、NO_HEADROOMへ書き換えていない。
- test/validation、技能カード、teacher-prefixはこの研究で観測済みのdevelopment evidenceであり未使用holdoutへ戻さない。

## 8. 限定提出候補

なし。archive/実行技能は成立したが、learnedは新規proxy 4局全敗、2 clusterの方向も不一致である。模倣学習研究は継続するが、今回のlearned/rule/noneのいずれもKaggleへ提出していない。今後提出する場合もユーザー許可を先に得る。
