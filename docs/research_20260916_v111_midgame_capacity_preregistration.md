# V111 midgame capacity 研究 preregistration — 2026-09-16

## 目的と証拠境界

production Champion は V111 に固定する。本研究は旧 Tomato 案、PSR repair、上位 route 模倣、単独 `BUY_LAND` 介入を行わず、旧 spent V111 control 32 contexts と保存済み current Top corpus の replay-only 診断を先に完了する。旧 replay 上の shadow counterfactual は算術上界 E1、Top 比較は cross-corpus E1、実装した candidate の paired closed-loop 差だけを E2 と呼ぶ。

Kaggle submission、kernel push、submission slot 変更は行わない。promotion `10091101–10091112`、Fresh `10091901–10091912`、旧 Development `10091421–10091436` は封印する。条件付き Development `10091521–10091536` も旧 spent gate を全て通るまでは登録・実行しない。

## 固定する replay と解析窓

- V111: router mechanism experiment の A0 spent arm に保存された V111 control 32 replays。4 sources × seeds `10091011–10091014` × 両 seat を一度ずつ使う。別 experiment の同一 replay は hash verification の比較対象にだけ使い、重複 context として数えない。
- Top: `data/current_field_20260916` の保存済み Top 5 各 active submission の先頭 6 EpisodeService rows、30 target-seat observations / 26 unique replay。旧 corpus と混ぜない。
- V111 cashflow 窓: decision step 144 から、各 context の第3農地 unlock 後 48 decisions（最大 step 314）まで。
- activation 整列窓: 第3農地 unlock を `t=0` とした `t=-96..+96`。Top は target seat だけを使う。
- snapshot は開始時点で24時間超だが、refresh は任意規定のため実施しない。保存済み corpus の再現性を優先し、candidate 結果を見た後の対象変更を防ぐ。

## 支出分類（結果を見る前に固定）

market order は engine の逐次 slot 処理で replay から再実行し、requested、committed、cash delta を order 単位で記録する。分類は次で固定する。

1. `urgent_maintenance`: 同じ game day 内の FEED/WATER、収穫可能 asset の HARVEST、shed overflow 回避の carry/drop、またはそれらに実際に使われる hand を成立させるため不可欠な支出。後で cash が戻るだけでは延期可能にしない。
2. `existing_production_continuation`: 既に unlock 済み区画の予定済み PLANT/配置を24 decisions以内に成立させる seed、animal、structure、worker、feed購入。延期時の harvest、sale、worker travel、market slot の opportunity cost を併記する。
3. `deferrable_irreversible_investment`: 購入後24 decisions以内に既存 asset の喪失を防ぐ用途へ使われず、購入済み asset がまだ shed/seed inventory に残る不可逆投資。分類は species/crop family 単位で全 context 共通にする。
4. `land_activation`: `BUY_LAND` と、第3区画を初回 productive action から harvest/carry/sale まで閉じるための追加支出。

shadow family は結果前に `BUY_ANIMAL:COW`、`BUY_SEED:STRAWBERRY`、`BUY_SEED:WHEAT`、`BUY_SEED:MELON`、`BUY_PRODUCT:WHEAT`、`HIRE` と定義する。family を context ごとに切り替えない。`BUY_PRODUCT:WHEAT` と urgent と判定された `HIRE` は、算術値を記録しても deploy 候補にしない。

## shadow capital と activation reserve

shadow cash は action、price、相手応答、Town、延期 asset の output を一切変えず、各 pre-action cash に同じ一種類の支出 family のそれ以前および当該 step の engine-committed cost を加えた算術上界とする。売上を追加せず、延期 asset が本来生んだ output も固定できるとは仮定しない。

第3農地代は engine の `LAND_PRICES[1] = 2000`。最小 activation asset は V111 自身が既に予定する WHEAT 1 tile とし、Top/P1 portfolio から選ばない。固定 activation reserve は次の `11 coin` とする。

- WHEAT seed 1: 10 coin。
- 同日 activation 用の最初の hand 1: 1 coin。既存 hand を使える場合も reserve は減らさない。
- structure / animal: 0。
- WATER、HARVEST、carry/drop、SELL: monetary cost 0。ただし worker-turn cost と market slot を別資源として必須監査する。

従って shadow threshold は `2011 coin`。maintenance reserve は当日の既存 animal 数、手持ち WHEAT、current public WHEAT price、残り FEED task から replay state ごとに別途計算し、land/activation 資金へ流用しない。最短 shadow schedule は `BUY_LAND → SW確認 → unit移動 → PLANT WHEAT → 同日WATER → lifecycle内HARVEST → carry/drop → committed SELL`。24 decisions以内に少なくとも合法 PLANT/WATER を開始でき、かつ元の urgent maintenance を上書きしないことを gate とする。

## opportunity cost

延期 family の本来の purchase から actual third-land unlock までに、購入物が field へ配置・植付された数、その asset の実 HARVEST units、SELL units、FEED/WATER/CARE task、worker travel を replay から記録する。将来 production は価格固定せず、観測された実 units と最悪 task debt（未配置 purchase、失敗する予定 PICKUP/PLACE/PLANT、追加 maintenance）を分離する。

## 実装 gate

`C1_v111_midgame_capital_commitment` は user prompt の8条件を全て満たす場合だけ作る。特に、同一 family で2 sources以上・4 source-seed blocks以上、24 decisions以上の land 前倒しと同じ24 decisions内の合法 productive action、調達から sale と state-based rejoin まで一意な executor、urgent maintenance・shed・order上限・worker位置・daily hire reset・land順序の preflight を全て要求する。

shadow threshold を満たすだけ、または field action を上書きして既存 maintenance/task debt を閉じられない場合は gate 不成立とする。完全 suffix または一般 executor が replay state から一意に証明できなければ candidate を作らず `REJECT_NO_FEASIBLE_CONTRACT` とする。gate 不合格後に Tomato、Carrot、livestock、terminal sale、reserve/step/tile数探索へ横滑りしない。

## 条件付き評価

C1 を作った場合だけ import/reset/isolation、V111/C1 A/A、発火・非発火 smoke、旧 spent 32 paired、全 gate 合格時だけ Development 16 blocks の順に進む。runtime/delivery/Safety を勝敗より先に判定し、新 raw Safety 0、W→L 0、W→D 0、safe L→W が2 blocksかつ2 sources、source別非悪化、whole-block bootstrap 95%下限>0、全 reweighting/exclusion 感度>0を固定する。一項目でも不合格なら repair や再探索をしない。

## 最終 status

`REJECT_NO_FEASIBLE_CONTRACT`、`REJECT_PROHIBITED_DEPENDENCY`、`REJECT_SAFETY`、`REJECT_NO_UPLIFT`、`PROMISING_UNPROVEN`、`E4_QUALIFIED_FRESH_SEALED` のいずれかだけを用いる。production Champion は明示的な全 gate 合格がない限り V111 のままとする。
