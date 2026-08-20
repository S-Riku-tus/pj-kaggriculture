# v1 local benchmark

## 条件

- `kaggle-environments==1.32.7`
- 720 turns
- 同じseedごとにplayer 0 / player 1を入れ替えるpaired evaluation
- 2026-08-21実行

## 結果

| Opponent | Seeds | Games | Wins | Win rate | Mean coins | Mean opponent coins | Mean margin |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `starter` | 3 | 6 | 6 | 100% | 59,820.0 | 3,395.2 | +56,424.8 |
| `random` | 2 | 4 | 4 | 100% | 62,211.5 | 0.0 | +62,211.5 |
| v1 mirror | 2 | 4 | 2 | 50% | 56,494.0 | 56,494.0 | 0.0 |

全試合で両agentのstatusは `DONE` でした。Mirrorはseatを交換すると結果も交換され、集計上の平均marginが0になっています。

## トレースから行った修正

最初の実装はstarterに勝ったものの、同一seed・seat 0で59,680 coinsでした。日別状態を見るとDay 16にcash cropが一斉にdecayし、15 weedsが残っていました。原因は、同じpriorityのtaskを座標順にworkerへ割り当てて長距離移動を発生させ、さらに成熟作物のharvestより通常waterを優先していたことです。

次の2点を修正しました。

1. 各priority帯で「全worker × 全task」の最短pairから割り当てる
2. 成熟したone-time cropのharvestを通常waterより上にする

同一条件の再実行は67,756 coinsとなり、Day 19時点でCow 8、Sheep 4、Strawberry 16、Day 22に全4区画を運用できました。単一seedの改善幅は約13.5%です。

## 解釈上の注意

これはbuilt-in baselineに対するsmoke benchmarkであり、Leaderboard上位への強さを示すものではありません。次の比較対象はV111などのreference agentと公開上位agentです。評価では平均coinだけでなく、paired win rate、margin、animal escape、weed化、shed overflowを同時に追います。
