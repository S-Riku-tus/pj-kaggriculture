# 第2library：t248の2頭購入契約

2026-09-11、v115p_immediateのDevelopment32pairs完了後、下記介入のsource作成・対戦前の登録。

即時売却は32/32発火、12W/20L、L→W/W→L=0/0、平均Δmargin=-234.875。Town後の売却比較は進行中であり、この結果を先取りしない。最初の小さな売却窓で約定は成立するが勝敗への感度が不足しているため、別decision pointの資源契約も試す。

仮説H3a：V111のdefault routeのt248にある2Cow購入を、既存V111の実行契約を用いた2Sheep購入へ変更すると、現在の需要・相手供給の組合せによって安全なL→Wが存在する。Topの家畜比率をコピーせず、既存の2つの購入・運搬・配置を一単位として比較する。V114のroute切替・Q・閾値は使用しない。

最初はV111とforced Sheepの2選択肢。selectorを作らない。t248でV111がまだ変換していない場合にだけlate_goalを与え、凍結V111の購入・pickup・place実装をそのまま使う。開始条件は既存実装通りcash>=1500、fallbackなし、同turnにBUY_ANIMAL COW 2が1件。2Sheepの費用1000、事前cashから500を残す。先行MELON売却は当てにしない。開始時点のprivate・pasture・worker位置と後続72turnの実約定を記録する。Wheat/feed/土地/作物/雇用/動線は変更しない。

現金guardを通ってもseed・棚容量・pickup・place・日次給餌・harvestが保証されたとは呼ばない。実engineの成立とt248〜320、続いてfull720を検証する。不可逆購入後はV111の既存conversion stateが運搬・配置を最後まで担当する。元のCow購入を二重に実行しない。実行不成立や新規HARVEST/CARE/FEED no-op、動物消失、weed増加は従来のhard Safetyで棄却し、利益で救済しない。

Development 10091011〜10091014、4既存Gold source、両seat32pairs。最初の4〜8pairsはruntime/delivery棄却用のみ。full rerun、固定archives、engine、source ancestry二軸、全first divergence、共通seed blockの扱いは最初の登録を継承する。介入時刻と継承取引はこの実験ではともに248だが、別引数を維持する。safe L→Wを複数状態・相手で見つけた時だけ最小gateへ進む。失敗ならlibraryを棄却し、完成policy比較か別の契約へ移る。Fresh/PROMOTE/Kaggle提出の条件は緩めない。
