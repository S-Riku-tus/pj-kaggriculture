# Kaggriculture V10 分析・設計・検証報告

作成日: 2026-08-26  
対象: V9 submission `55732462`（取得時レート 925.1）  
研究目標: レート 3000 超。ただし、本報告・ローカル試験・反実仮想評価はレートを保証しない。

## 1. 評価原則

- 主教師は公開上位3提出の完全試合ログとし、旧エージェント戦の勝率は選択指標にしない。
- 行動一致だけでなく、24/72時間後の農場構成、生産区画、資金、資源事故、試合ごとの下位側を見る。
- 学習・検証単位は観測行ではなく試合。`train_v9_decision_policy._split()` の episode hash 分割を再利用する。
- 反実仮想比較は教師状態から1手を比較するオフポリシー診断であり、ロールアウト、勝率、レートの推定ではない。
- 学習器は戦略目標だけを補正し、給餌、在庫、予算、合法手、移動、売買上限は決定論層で保証する。

## 2. 使用データ

| 集合 | 非自己対戦の完全試合 | 用途 |
|---|---:|---|
| V9 public | 55 | 閉ループ失敗と下位例の特定 |
| Rank 1 | 133 | 戦略学習、試合hash testで方針検証 |
| Rank 2 | 130 | 上位共通/固有戦略の分離、外部検証 |
| Rank 3 | 184 | 上位共通/固有戦略の分離、外部検証 |

再現可能な集計は次に保存した。

- `data/analysis/v10_v9_teacher_gap.json`
- `data/analysis/v10_counterfactual_untouched_*.json`
- `data/analysis/v10_final_external_rank2_validation_*.json`
- `data/analysis/v10_final_external_rank3_validation_*.json`
- `data/analysis/v10_release_starter_20269701_kpis.json`
- `data/analysis/v10_vs_v9_diagnostic_20269301_kpis.json`

## 3. 分かったこと

### 3.1 上位に共通する将来状態

序盤経路は大きく異なるが、生産区画は同じ帯へ収束する。

| 教師 | 2枚目土地の中央値 | Day 7 productive | Day 12 productive | Day 24 productive |
|---|---:|---:|---:|---:|
| Rank 1 | 5 | 42 | 71 | 69 |
| Rank 2 | 5 | 38 | 69 | 69 |
| Rank 3 | 7 | 25 | 71 | 70 |

したがって「Day 7の行動列を一種類に固定する」のは誤りで、Day 12に69–71区画、Day 24に69–70区画を維持する状態目標の方が共通性が高い。

Rank 1では Wheat が Day 18/24/27 に中央値24/35/43へ増え、Strawberry は30/14/7へ減る。これは72時間先の満了作物を短期Wheatへ回す輪作であり、V9のDay 24中央値 Wheat 24、Strawberry 24は切替が遅い。

### 3.2 状況依存の分岐

- 土地拡張: Rank 1/2はDay 5、Rank 3はDay 7が中央値。単一路線ではない。
- 家畜: Milk需要が高いほどCow、Wool需要が高いほどSheepが増える。V9はCow/Sheep比の需要相関が上位より弱かった。
- 施肥: Rank 1は主にStrawberry/Tomatoへ集中する一方、Rank 2/3はWheatやMelonにも使う。これは上位共通の完全一致ルールではない。
- 資金経路: Rank 1はDay 12の資金中央値15469、Rank 3は2232.5だが、生産区画中央値は双方71。現金単独を目的にしてはいけない。

### 3.3 V9の主要な閉ループ失敗

- Day 6のRank-1 atlasはDay 7 Strawberryを約12.7と予測したが、V9実績中央値は4。戦略推定より購入・植付・移動の実現がボトルネックだった。
- V9のDay 12 productiveは中央値61.7。55試合中32試合がRank 1のDay 12 P10=62.2を下回った。
- Day 6–10でV9は1試合平均FERTILIZE 21.4、Rank 1は0。早期資本と作業時間を消費していた。
- Day 11–19でもV9は散水70.1対Rank 1の112.3、Wheat植付7.0対14.8。
- Day 20–26でも散水65.9対88.4、Wheat植付7.5対18.3。
- V9の最終ポートフォリオは上位よりCowが多く、Sheepと需要作物の反応が弱い。低需要で過剰、高需要で不足する圧縮が見られた。

## 4. V10の設計

### 4.1 戦略目標層

1. V9のRank-1 atlas信頼度が0.35以上の場合だけ補正する。未満ならV9へ戻る。
2. Day 6–18では、所有済み家畜を減らさず、Milk/Wool需要に応じて未購入Cow/Sheep枠を再配分する。
3. Day 10–18で土地目標が3枚なら、需要別作物目標を維持したまま総productive目標を72とし、不足分だけWheatへ足す。
4. Day 20–27ではWheat目標を28から42へ段階的に上げ、72時間後の輪作状態を表現する。

### 4.2 決定論的実行層

- Day 6–8のStrawberry backlogを、緊急給餌・散水を除く通常作業より優先する。
- Day 6–10はFERTILIZEを行わず、肥料を運転資金として売る。
- Day 11–26の施肥はStrawberry/Tomatoだけに限定する。これはRank 1寄りであり、Rank 2/3との差は未解決。
- WATERを通常FEEDより上、緊急FEEDより下に置く。
- Day 13–26にproductiveが70未満ならPLANTを12000へ上げる。通常FEED=12100は必ず上位に残す。
- 空手で移動/停止予定の作業者が未散水作物上にいる場合、安全なら先にWATERする。未給餌が連続1日または18時以降なら上書きしない。
- 空手でPASSする作業者だけを、観測可能な未処理タスクへ事前配置する。実行済み行動や荷物持ちを奪わない。
- 購入済み家畜のshed期限切れを防ぐため、PICKUP/PLACEを13500/13400とし、緊急FEED=15400を残したまま通常の散水・植付より先に確定する。
- 売却はV9の基準行動から隔離して取得し、フィールド変更が全肥料売却を誘発しないようにした。Day 6–10肥料だけを例外とする。

## 5. 仮説検証

| 仮説/変更 | 検証 | 判断 |
|---|---|---|
| 早期肥料作業を止めればStrawberry展開へ作業を戻せる | Rank 1 testでFERTILIZE 9.9→0、Strawberry植付3.9→5.3 | 採用 |
| 現在地の安全な散水を先にすれば移動損失を減らせる | Rank 1中盤で散水70.1→90.7、必要作業再現率0.567→0.631 | 採用 |
| 総productive目標を持てばDay 12の64上限を破れる | 新規閉ループでDay 12が64固定から最大70帯へ移動 | 採用 |
| 低稼働時の植付をFEED直下へ上げれば回復を早められる | 3教師すべてで中/晩期Wheat植付と必要作業再現率が改善、事故0 | 採用 |
| 購入済み家畜を通常作業より先に配置すればshed期限切れを防げる | 追加8試合でCow 1頭の期限切れを検出。同一seed再試験2試合と別seed 8試合で消失0 | 採用 |
| 全売却をV8へ戻せば安全に資金化できる | Wheat売却F1が0.879→0.836 | 棄却 |
| Day 11–19も肥料を強制売却すれば強い | 一時的な報酬上昇はあったが教師から大きく逸脱。実装範囲バグでもあった | 棄却 |
| mission continuityを有効化すれば移動が改善する | V9 holdoutで支持されず | 棄却 |

## 6. 未使用試合への再現性

下表は各教師の完全試合集合で、4時間ごとの必要作業verb recallを比較したもの。数値はオフポリシー診断である。

| 教師/分割 | 局面 | V9 | V10 |
|---|---|---:|---:|
| Rank 1 test (39試合) | Day 11–19 | 0.567 | 0.631 |
| Rank 1 test (39試合) | Day 20–26 | 0.626 | 0.655 |
| Rank 2 validation (28試合) | Day 11–19 | 0.590 | 0.607 |
| Rank 2 validation (28試合) | Day 20–26 | 0.575 | 0.583 |
| Rank 3 validation (29試合) | Day 11–19 | 0.677 | 0.747 |
| Rank 3 validation (29試合) | Day 20–26 | 0.625 | 0.663 |

Rank 1では総行動差も改善したが、Rank 2/3では散水中心のV10と施肥中心の教師のアーキタイプ差により、総L1や単純一致は悪化する局面がある。必要作業再現率だけでも強さは確定しないため、採用根拠は将来状態と閉ループ安全性を併用した。

## 7. 閉ループ診断

最終安全パッチ後の新規8試合（seed 20269901–20269904、両席、対starter）は次の通り。

- 8/8正常終了、家畜損失0。
- 最大連続未給餌=1、最大連続未散水=1、日初最低資金=92。
- productive最小/平均/最大: Day 12=66/67.75/72、Day 15=68/69.125/70、Day 20=68/70.125/72、Day 24=63/67/70、Day 27=65/67.625/70。
- Day 24の下位例63は上位共通中央値69–70に未達。種を保持した植付遅延が残る。

開発中の別8試合ではCow 1頭がshed内で期限切れになる下位例を検出した。原因は3頭購入後に植付・散水がPICKUPを遅らせたことだった。家畜PICKUP/PLACE優先を追加し、失敗した同一seedの両席と上記未使用8試合で消失0を確認した。

V10対V9の診断4試合はV10が0勝4敗だった。ただしV10側は家畜損失0で、productiveはDay 12=68、Day 24=69.5だった。これは旧版専用の勝率最適化をしておらず、競合下の価値化・売却に未解決差がある証拠として扱う。

## 8. 未検証・残課題

- 実際のKaggle提出後レート。3000到達は未検証であり保証できない。
- Rank 2/3型の非premium施肥とRank 1型のpremium集中を状態から選ぶ分岐。
- Day 24の一時的な稼働低下と、種を持ったまま植付が数時間遅れる経路。
- V9より低い対戦価値になった競合状態での、需要別売却時刻と市場在庫への反応。
- atlas外状態の検出率は高いが、フォールバック自体の最悪ケース性能は限定的なローカル試験しかない。
- ローカルstarter戦の報酬や勝率は公開上位との強さ比較には使えない。

## 9. 再現コマンド

```powershell
.\.venv\Scripts\python.exe scripts\analyze_v10_gap.py
.\.venv\Scripts\python.exe scripts\analyze_v10_counterfactual.py --start-day 11 --end-day 19 --output data\analysis\v10_counterfactual_untouched_capital.json
.\.venv\Scripts\python.exe scripts\analyze_v10_counterfactual.py --source data\submissions\leaderboard_rank2_submission_55623460 --split validation --teacher-label Rank-2 --start-day 20 --end-day 26 --output data\analysis\v10_final_external_rank2_validation_rotation.json
.\.venv\Scripts\python.exe -m pytest -q tests\test_agent_v10.py tests\test_agent_v9.py
.\.venv\Scripts\python.exe scripts\package_submission.py --agent agents\v10
```

再現時は、行動一致率や対旧版勝率を単独で採用判定に使わないこと。

## 10. 提出アーカイブの単体検証

- 成果物: `artifacts/submissions/v10.tar.gz`
- build manifest: `data/submissions/builds/20260826_140639_+0900_v10.json`
- サイズ: 579,846 bytes
- SHA-256: `ac88a03d6ea44ca8291d70eda63ec44ee357e0249e5e6c07254fe06dd6c68821`
- 収録物: `main.py`、5個のモデル/特徴ファイル、`v2_base.py` から `v9_base.py` までの計14ファイル
- リポジトリ外の新規ディレクトリへ展開し、展開後の `main.py` と `starter` を seed `20269999` で720ステップ実行した。両プレイヤーの最終状態は `DONE` で、提出側 reward は153,991だった。このrewardは単一seed・starter相手なので、強さの採用指標には使用しない。
- `ruff` はV10本体、分析スクリプト、V10テストの全対象で成功した。リポジトリ全体の `pytest -q` も成功した。
