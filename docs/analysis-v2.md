# V1 / leaderboard Top 3 replay analysis and v2 design

## Scope

2026-08-21に取得した次の完全replayを対象にした。

| Label | Submission ID | Public episodes | Reported rating |
| --- | ---: | ---: | ---: |
| V1 | 55649709 | 22 | 521.9 |
| Rank 1 | 55614463 | 133 | 3170.6 |
| Rank 2 | 55623460 | 130 | 3079–3081 |
| Rank 3 | 55574890 | 184 | 3059–3062 |

勝敗と最終coin分布は全469 public episodesから集計した。行動・日別状態はV1の全22試合と、各上位提出から最終coinの分位点を均等に覆う24試合ずつを `scripts/analyze_replay_corpus.py` で再解析した。外部分析と同じ方向の結果になったが、ここで示す数値はrepository内のreplayから独立に再計算した値である。

```powershell
.\.venv\Scripts\python.exe scripts\analyze_replay_corpus.py `
  --corpus v1=data\submissions\v1_submission_55649709 `
  --corpus rank1=data\submissions\leaderboard_rank1_submission_55614463 `
  --corpus rank2=data\submissions\leaderboard_rank2_submission_55623460 `
  --corpus rank3=data\submissions\leaderboard_rank3_submission_55574890 `
  --sample 24
```

出力は `data/analysis/replay_corpus_comparison.json` と `data/analysis/replay_episode_metrics.csv`。

## Outcome gap

| Agent | Win rate | Mean coins | Median | P10 | Minimum | Maximum |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Rank 1 | 88.7% | 96,106 | 92,501 | 65,628 | 54,083 | 168,259 |
| Rank 2 | 81.5% | 100,061 | 100,006 | 75,788 | 52,550 | 173,276 |
| Rank 3 | 70.7% | 90,496 | 87,240 | 63,487 | 36,894 | 165,467 |
| **V1** | **45.5%** | **50,297** | **53,551** | **18,608** | **11,192** | **80,685** |

平均coinだけでなく下側分位の差が大きい。V1の最大値80,685は経済エンジンが機能することを示すが、P10が上位の約1/3以下である。Skill Ratingは大勝marginより勝敗を重視するため、V2は最大値より崩壊試合の底上げを目的にする。

## Reproduced behavioral gap

行動指標は前述の均等分位sampleである。

| KPI | Rank 1 | Rank 2 | Rank 3 | V1 |
| --- | ---: | ---: | ---: | ---: |
| Day 7 productive utilization | 78.9% | 76.9% | 100.0% | **34.4%** |
| Day 10 productive utilization | 86.9% | 78.4% | 88.8% | **17.3%** |
| Day 15 productive utilization | 98.8% | 96.1% | 92.3% | **48.4%** |
| Day 20 cash | 44,852 | 48,888 | 46,720 | **4,535** |
| Hand PASS rate | 3.6% | 4.4% | 19.0% | **25.5%** |
| Productive actions / HIRE | 10.94 | 10.46 | 9.73 | **6.10** |
| COLLECT_FERTILIZER / game | 291 | 332 | 349 | **57** |
| FERTILIZE / game | 60 | 184 | 129 | **15** |
| Terminal sellable inventory | 0 | 883 | 0 | **972** |
| Max Melon tiles | 11.2 | 15.5 | 12.7 | **0.0** |
| Max Strawberry tiles | 29.8 | 27.9 | 35.8 | **14.4** |

`productive utilization` は利用可能tileに占めるPlantまたは配置済みAnimalの比率で、weedや空structureを利益資産として数えていない。

## What actually separates V1 from the top agents

### 1. Capital conversion speed

Rank 1の代表的なDay 1状態は全sampleで `6 Wheat + 11 Melon + 2 Cow + 2 Sheep` だった。利用率84%で、初期$3,000の大半が長期資産へ変換済みである。Day 4には `10 Wheat + 11 Melon + 4 animals = 25/25 tiles` となる。

V1はDay 1に `10 Wheat + 8 Carrot` だけで、動物とMelonは0。第2区画を早く買う一方、Day 10の利用率は17.3%まで落ちる。問題はcashを持つことではなく、購入したcapacityと雇ったworkerを生産資産へ変えられないことにある。

### 2. Time-dependent crop rotation

上位は固定作物構成ではない。

- Day 1–10: Melonを約11–15 tile使い、最初の大きなcash eventを作る。
- Day 7–20: Strawberryを約20–36 tileへ拡大する。
- Day 24–27: StrawberryとMelonを減らし、Rank 1/3ではWheatを約35→44 tileへ増やす。
- Day 29: 新規投資を止め、収穫・持ち帰り・売却だけに近づける。

V1はMelonを使わず、Day 29でも平均10.5 Strawberryが残る。残りhorizonに対して作物の回転が遅い。

### 3. Demand-responsive portfolio

最終Town需要と最大生産capacityの相関は、同じ24試合sampleで次の通りだった。

| Agent | Milk demand ↔ Cow | Wool demand ↔ Sheep | Strawberry demand ↔ Strawberry |
| --- | ---: | ---: | ---: |
| Rank 1 | 0.606 | 0.809 | 0.565 |
| Rank 2 | 0.707 | 0.732 | 0.775 |
| Rank 3 | 0.671 | 0.343 | 0.618 |
| V1 | **0.267** | **0.080** | **0.066** |

sampleの選び方で絶対値は動くが、V1との差は一貫する。上位の本質は固定 `8C4S` ではない。Rank 1全体ではCow 6–16、Sheep 2–9の範囲を取り、Town demandに合わせてcapacityを変える。

### 4. Throughput beats price purity

V1は平均売価だけなら上位より高い。

| Agent | Milk volume | Milk mean quote | Strawberry volume | Strawberry mean quote |
| --- | ---: | ---: | ---: | ---: |
| Rank 1 | 220 | 97 | 227 | 114 |
| Rank 2 | 201 | 126 | 186 | 154 |
| Rank 3 | 212 | 92 | 253 | 130 |
| V1 | **143** | **199** | **77** | **235** |

V1は高値を待てているが、販売量が足りない。価格最大化を目的にするとcash conversion、shed capacity、残りhorizonを無視する。V2では低すぎる価格を避けつつ、初期cash不足、在庫圧迫、終盤にはvolumeと現金化を優先する。

### 5. Fertilizer is both yield and working capital

上位はAnimalから毎日Fertilizerを回収し、一部をStrawberry/Wheatへ戻し、余剰を売る。V1の15 fertilizeに対し上位は60–184。さらに初期Animalが作るFertilizerは、最初のWheat harvestまでのfeed購入資金になる。V2の最初の試作ではこの優先度が低く、初期4頭がDay 4に全滅した。平均coinは高くてもP10を壊すため不採用とし、Day 0–4のFertilizer回収をhard priorityへ上げた。

### 6. Endgame is a separate control regime

Rank 1とRank 3のsampleはterminal sellable inventoryが0。V1は平均972、僅差負けEpisode 95529660では1,828相当を残した。さらにDropした商品は同じturnのmarket actionでは売れず、次のobservationまで待つ必要がある。したがってDay 29 hour 23の回収では遅い。V2はDay 27から全商品の回収を始め、Day 29は `distance to shed + harvest/drop/sell latency` が残りturn内に入るtaskだけを作る。

## V1 strengths retained

- 22 public matchesとlocal benchmarkをruntime errorなしで完走した。
- Observationだけから毎turn再計画するclosed-loop構造で、固定replayではない。
- FEED/WATER emergency、seed overclaim防止、worker inventory物流がすでにある。
- Premium productの価格を見るmarket controllerは有用。
- 条件が合えば80k coinを出せる。

V2はこれらを捨てず、opening、capacity、portfolio、fertilizer、liquidationを置き換えた。

## V2 policy

```text
Observation
  -> Town demand + market congestion + opponent supply
  -> phase (opening / expansion / mature / rotation / liquidation)
  -> Cow / Sheep / Wheat / Strawberry / Melon targets
  -> utilization-gated land and phase-gated worker targets
  -> loss-risk and ROI ordered field tasks
  -> throughput-oriented sales
```

主要な制御:

1. Day 0はRank 1の実測openingを採用する。
2. 第2区画は利用率90%以上、第3区画は84%以上をgateとし、第4区画は買わない。
3. CowはMilk需要を主因として5–16、SheepはYarn需要を主因として2–9へ変える。市場glutと相手供給は小さな補正だけに使う。
4. Animal増加は1日単位でramp制限し、需要が見えた瞬間にStrawberry資金を使い切らない。
5. Strawberryは需要により16–42、MelonはDay 0–9に11、Wheatは中盤25、終盤35→44を目標にする。
6. 同日大量植付によるwater/harvest spikeを避けるため、crop別の日次plant上限を持つ。
7. Day 21以降はAnimal新規投資、Day 27以降は全capital investmentを止める。
8. Day 27–28のWheatはfeedとして保持し、Day 29だけ全量売却する。

## Why v2 is not PPO/RL

RLを否定しているのではない。現時点では、次の理由でreplay-calibrated rule controllerの方が期待値が高い。

- V1の主要な失敗は既知のhard constraintとcapacity allocationで説明できる。
- Top replayは行動教師として使えるが、相手・Town・価格がconfoundedなtrajectoryであり、単純behavior cloningは別状態で不正行動を出しやすい。
- 720-step sparse terminal rewardのPPOは、survival、物流、market concurrencyをゼロから再学習するsample costが大きい。
- rule controllerならどの変更がP10、animal loss、terminal inventoryへ効いたかablationできる。

将来は、V2を安全なfallbackにして、日次portfolio targetだけをoffline imitation/contextual banditで学習するのが妥当。workerのlegal actionとFEED/WATER deadlineはruleで保護する。

## Local validation

採用版を未使用の3 seeds（20260822–20260824）、両seatでV1と直接対戦した。

| KPI | V2 | V1 |
| --- | ---: | ---: |
| Games | 6 | 6 |
| Wins | **6** | 0 |
| Mean coins | **70,684** | 36,162 |
| Median coins | **70,666** | — |
| P10 (6-game interpolation) | **62,325** | — |
| Minimum coins | **57,516** | 23,359 |
| Mean margin | **+34,522** | -34,522 |
| Animal losses | **0** | — |
| Terminal sellable inventory | mean **108** | — |
| All statuses DONE | yes | yes |

同じseed群で13 workersと高優先度CARE/plantを同時投入したablationは6勝を保ったが、V2平均coinが57,682へ低下した。追加人件費とtask contentionが増産を上回ったため不採用にした。

このlocal結果はLeaderboard上位への強さを証明しない。V1とのshared-market head-to-headでは相手の供給が価格へ影響し、3 seedsは小標本である。提出後は最低30 public episodesを集め、Win rateだけでなくP10、Day 10/15 utilization、animal loss、terminal inventory、Town-demand correlationを再計測する。

## Next experiment order

1. V2を提出し、30–50 public episodesを取得する。
2. V2 public replayを同じanalyzerへ通し、V1とTop 3に同じ定義で比較する。
3. ルーティング改善は `productive actions / HIRE` を主KPIにし、経済targetを固定したpaired ablationで行う。
4. V3ではRank 1 replayから日次portfolio targetを学習する小さなmodelを検討する。terminal policyとsurvival guardはruleのまま残す。
