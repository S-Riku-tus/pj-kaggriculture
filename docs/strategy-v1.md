# Agent v1 strategy

## 目的

v1の第一目的は、720ターンを例外なく完走しながら、生存管理・物流・現金化のclosed loopを成立させることです。固定Replayは使いません。評価対象は単独の最終coinだけでなく、seatを入れ替えた直接対戦の勝率とmarginです。

## 経済フェーズ

| Phase | Day | 方針 |
| --- | ---: | --- |
| Cash flow | 0–3 | Wheat 10、Carrot 8を植え、近い動物用6マスを空ける |
| First capital | 4–8 | 第2区画、Cow 4、Sheep 1、Strawberry 8へ段階投資 |
| Scale | 9–14 | Cow 6、Sheep 3、Wheat物流、Strawberry最大16へ拡大 |
| Mature | 15–21 | Cow 8、Sheep 4を上限にCAREとpremium生産を回す |
| Liquidate | 22–29 | 回収不能な新規投資を止め、Day 28から在庫を現金化 |

動物数に対してWheat tileは概ね `ceil(1.25 * animals)` を目標にします。相手がCow-heavyならCow上限を下げてSheepへ、Sheep-heavyなら逆へ寄せます。相手がStrawberry-heavyなら一部をTomatoに分散します。

## 1ターンの優先順位

1. Day 29の収穫・shedへの持ち帰り
2. 2日連続未給餌になり得る動物への `FEED`
3. weed化し得る作物への `WATER`
4. 通常の `FEED`、Wheatのshed pickup
5. 成熟作物・満杯になりそうな動物の `HARVEST`
6. scheduled production前の `FERTILIZE`
7. `CARE`
8. 動物pickup、Pasture建築、動物配置
9. 計画作物の `PLANT`
10. Fertilizer回収、weed除去

各タスクはpriorityを持ち、同じpriorityではManhattan距離が最短の未割当workerへ渡します。割当は次ターンに全て再計算されるため、weed、資金不足、相手構成、市場変化で予定がずれても復帰できます。

## 市場

- Feed用Wheatをおおむね3日分確保し、余剰のみ売る
- Carrot、Tomato、Eggはshedに入ったら早めに売る
- Strawberry、Milk、Wool、MelonはTown消費直後かshed圧迫時に小口売却する
- Day 28以降は価格より現金化を優先する
- shed使用量が78を超えたら在庫消失回避を優先する

## v2へ向けて記録すべき指標

- seed・seat別のwin rate、coin margin
- 日別money、動物数、作物数、land、hands
- `PASS`、移動、FEED、CARE、WATER、HARVESTのaction比率
- 商品別の生産量、売却量、平均売価、最終未売却数
- animal escape、weed化、shed overflowの発生数
- Cow/Sheep/Strawberry/Wheat/Handsを一変数ずつ変えたablation

