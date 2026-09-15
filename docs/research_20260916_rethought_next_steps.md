# Kaggriculture研究の再評価と次の一手（2026-09-16 JST）

## 結論

production ChampionはV111のまま維持する。現時点でnumeric agentを新設する根拠はない。

次に検証する価値が最も高いのはTomato追加ではなく、V111が第2回の`BUY_LAND`（通算3区画目）を行う前の資金拘束と、購入後に新しい区画を実働化するまでの遅延である。ただし「早く土地を買えば強い」とはまだ言えない。次の研究は、まず既存replayだけで `資金予約 → 第3農地購入 → 同日中の実働化 → 保守 → 収穫 → 運搬 → 売却 → state-based rejoin` が一つの完全な契約として成立するかを監査し、成立するときだけV111由来の候補を一つ作るべきである。

先に作成したTomato optionは暫定仮説だった。追加調査により、現在上位の中盤capacity差はTomato初回購入より前に発生し、Tomato量は上位サンプル内の勝ちと正に対応せず、過去のTomato/crop diversificationにも負のpaired evidenceがあることが分かった。このため同案は失効させる。

## 1. これまでに確定したこと

### 1.1 PSR/router研究は終了している

- P1 fullのV111比win-score差は`+0.375`。
- step 0で選んだroute 0を固定したA0でも`+0.3125`が残り、P1 total-policy upliftの83.33%を再現した。
- router固有差P1−A0は`+0.0625`で、qeinstein seed `10091013`の1 source-seed block、1 source、1 ancestryだけだった。事前の2-source条件を満たさない。
- P1/A0/A1/A2はraw Safety failureが32/32、W→Lが2。固定route、blob、tree、閾値はtransitive provenance/licenseも未確認である。

したがってPSRから分かったのは、「大きな差はrouter switchではなく、route選択前から共通する初期market/portfolio footprintと固定total policyにある」という範囲までである。step 0のWHEAT購入、資本温存、後続routeのどれが因果的だったかは未分離であり、P1の具体表現をV111へ移すことはできない。

### 1.2 現Leaderboard上位の公開ログは一つの固定routeを示していない

保存済みsnapshotはUTC `2026-09-15T15:33:56.343605+00:00`、JST `2026-09-16 00:33:56`である。Top 5の各active submissionからEpisodeService先頭6行を取得し、30 target-seat観測、26 unique replayを解析した。

- 観測結果は22W/0D/8L、平均margin `+3,459.5`、P10 `-2,906`。これは選択済みopponent mix上の観測で、rating推定でもpaired効果でもない。
- step 48のfield hashは22種類、step 300では30/30が異なり、portfolio continuationも30/30が異なる。上位全体を一つの固定action routeとして扱えない。
- 現上位は歴史的V111より平均でWHEAT `+3.596`、CARROT `+1.959`、TOMATO `+3.317`、STRAWBERRY `-3.612`、GOOSE `+1.782`だった。
- しかし8敗の平均Tomatoは4.25、22勝では2.98であり、SpaTaroの6観測はTomato 0・Goose 0で6勝だった。Tomato採用を勝因とする証拠ではない。
- 上位ログの絶対的なno-op、oversized sell、crop/animal lossは多い。これらをコピーしてよいという意味ではなく、V111との差分Safetyをpairedに測る必要がある。

### 1.3 最も一貫した構造差は中盤capacityだが、まだ相関である

現在Top 5の第2区画unlock中央値はstep 150、第3区画はstep 209である。歴史的V111は概ねstep 161とstep 253–266である。productive tileの概数も次のように異なる。

| step | current Top 5 勝ち | current Top 5 負け | historical V111 |
|---:|---:|---:|---:|
| 144 | 24.59 | 24.88 | 24.73 |
| 216 | 57.91 | 57.25 | 46.63 |
| 240 | 70.64 | 70.25 | 47.86 |
| 264 | 69.82 | 70.75 | 52.05 |
| 288 | 約73.5 | 約73.5 | 67.56 |
| 360 | 約73.7 | 約73.7 | 68.52 |
| 480 | 約73.3 | 約73.3 | 68.99 |
| 600 | 約70–71 | 約70–71 | 72.18 |

重要なのは三点である。

1. 差はstep 216–264で最大であり、Top 5のTomato初回購入中央値step 320.5より前に発生する。Tomatoはこの早期capacity差の原因ではない。
2. Top 5内では勝ちの第3区画中央値が208.5、負けが210でほぼ同じで、productive tileも勝敗間で近い。早期拡張は上位policyの共通基盤らしいが、上位内の勝因ではない。
3. step 600ではV111のproductive tileが上位平均を上回る。問題は最終面積ではなく、中盤の利用可能時間、資金回収、作業capacity、marketへの影響である可能性が高い。

### 1.4 V111の直接制約は土地閾値ではなく流動性である

旧spent 4 sources × 4 seeds × 両seatのV111 control replay 32 contextsを再利用し、actionを変えずにcash、hands、unlocked landを監査した。

| step | cash中央値 | 最小 | P10 | cash≥2000 | land状態 |
|---:|---:|---:|---:|---:|---|
| 192 | 482.0 | 392 | 415 | 0/32 | 2区画 32/32 |
| 198 | 77.0 | 17 | 17 | 0/32 | 2区画 32/32 |
| 209 | 55.0 | 17 | 17 | 0/32 | 2区画 32/32 |
| 216 | 216.0 | 17 | 17 | 0/32 | 2区画 32/32 |
| 222 | 103.5 | 30 | 59 | 0/32 | 2区画 32/32 |
| 240 | 1,403.0 | 1,375 | 1,382 | 8/32 | 2区画 32/32 |
| 248 | 1,788.5 | 899 | 899 | 2/32 | 2区画 32/32 |
| 253 | 3,379.0 | 3,115 | 3,116 | 32/32 | 3区画 24/32 |
| 264 | 6,830.0 | 6,255 | 6,258 | 32/32 | 3区画 24/32 |

上位の第3区画中央値step 209の時点で、V111は全32 contextとも2,000 coinに届かず、中央値は55である。従って`BUY_LAND`の発火stepやcash thresholdだけを早めても何も起きない。step 144–253のどの支出が現金を拘束し、何を一時的に延期すれば土地代2,000と実働化費用を同時に確保できるかを先に解く必要がある。

### 1.5 過去の失敗は「面積を増やすだけ」を否定している

- V7のbroad OOD/recovery/crop controllerはday 20のproductive tileを約66.4から70.5へ増やしたが、20戦0勝、平均差`-8,356`だった。
- bounded Carrot rotationは3W/2D/5L、平均差`-1,112`。Tomato diversificationもvisible demandがreplacement costとtimingを補えず棄却された。
- V109の「第3農地が欠けたらrule policyへ切替」は土地を購入したが、mean rewardを97,961から85,395へ落とした。
- immediate/Town sale、retain Cow、managed Sheep/Goose、unmanaged Sheepも既に無効またはW→Lを伴っている。

従って次は`BUY_LAND`単独、汎用rule fallback、作物多様化、家畜追加、終盤販売へ横滑りしてはならない。拡張の価値は、資金調達から実現売上まで閉じた一つの契約としてだけ試験できる。

## 2. 仮説の再順位付け

### 1位: `midgame_third_land_capital_and_activation_commitment`

V111の既存支出のうち一種類だけを延期または順序変更し、第3農地の土地代と明示的なactivation reserveを作る。そのうえでV111自身の既存portfolio familyを新しい区画で実働化し、保守・収穫・運搬・販売まで完了する単一packageである。

これはまだ実装推奨ではなく、最優先diagnosticである。成立条件は、同じ支出familyで2 sources以上・4 source-seed blocks以上において少なくとも1 game day早く土地を実働化できること、既存maintenanceを壊さないこと、販売までのstate-compatible contractが一意に書けることである。

### 2位: active remote package fidelityの確定

active submission `56089444`の直近8公開replayに対し、V109/V110/V111/V113は5,725/5,752 actions（99.53%）一致し、27差分は同じmarket multisetのorderだけだった。一手効果の合計はself `+12`、opponent `-29`程度で、主な戦略差を説明しない。exact archive identityは依然`UNVERIFIED`である。

これは再現性と運用のhygieneとして必要だが、新strategyの主仮説にはしない。取得済みartifactでexact hashを確定できない限り推測で埋めない。

### 3位: Town需要連動Tomato option

公開state actuatorとしての筋はあるが、現在の優先度は低い。capacity差より時間的に後で、上位内勝敗と正に対応せず、過去のcrop diversificationも負である。midgame capital仮説が不成立だったというだけで、同じspent dataを使ってTomatoへ自動的に横滑りしてはならない。別preregistrationと別data splitを必要とする将来仮説として保留する。

### 棄却済みまたは再開禁止

- PSR blob/tree/route/tapeの移植またはrepair。
- opponent/source/seed fingerprint selector。
- `BUY_LAND`だけ、cash thresholdだけ、汎用fallbackだけの変更。
- terminal extra sell、Sheep/Goose/Cow変形の再試験。
- 上位replayのaction sequence・portfolio targetのコピー。

## 3. 次に行うべき研究の順序

### Phase A: gameを増やさない因果監査

1. V111のstep 144から第3農地購入後48 stepsまで、成功した全market order、失敗order、cash増減、売上、hire、seed、animal、product、landをcontext別ledgerにする。
2. 支出を`必須maintenance`、`既存生産の継続`、`延期可能な不可逆投資`、`販売/回収`へ分類する。勝敗を最大化する分類変更は禁止する。
3. 第3農地unlockを相対時刻0として、最初のplant/build、productive tile増加、必要worker turns、最初のharvest、carry、実現saleまでを追う。
4. 一種類の支出familyだけを延期した算術的shadow counterfactualを作る。これはpriceや相手応答を固定した上界であり、性能証拠とは呼ばない。
5. 現上位についても同じaggregate timelineを作るが、exact routeを復元・転記しない。勝ち/負け差とsource差を併記する。
6. 「土地が早い」「稼働が早い」「売上回収が早い」「相手coinが下がる」を分離し、Evidence / Inference / Unknownを保存する。

### Phase B: 実装gate

次を全て満たす場合だけ`C1_v111_midgame_capital_commitment`を作る。

- 同じ延期可能支出familyが2 sources以上、4 source-seed blocks以上で土地代2,000と固定activation reserveを作れる。
- 第3農地を少なくとも24 decisions早くunlockするだけでなく、同じ24 decisions内に合法なproductive actionを開始できる。
- 調達、land、worker、移動、配置、WATER/FEED、HARVEST、carry、SELL、既存routeへのstate-based rejoinが一意に定義できる。
- V111の既存crop/animal familyだけを順序変更し、新しいportfolio仮説を同時に足さない。
- 既存のurgent maintenanceとshed/market order capacityを侵害しない。
- 上位やP1のroute、時刻列、閾値、action列を使わない。
- V109のbroad fallbackと異なり、変えるaction familyと終了状態が限定されている。

一つでも満たさなければ候補を作らず`REJECT_NO_FEASIBLE_CONTRACT`または`PROMISING_UNPROVEN`で終える。

### Phase C: paired評価

C1を作った場合だけ、import/reset/isolation、V111/C1 A/A、発火・非発火の両seat smokeを先に通す。その後、旧spent 4 sources × 4 seeds × 両seatの32 contextsでV111とのpaired closed-loop評価を行う。

最低gateはruntime/Safety違反0、W→L=0、W→D=0、safe L→Wが2 source-seed blocks以上かつ2 sources以上、全source非悪化、win-score差>0、whole-block bootstrap下限>0、全reweighting/除外感度>0である。一項目でも不合格ならrepairやthreshold searchを行わず、新seedを開かない。

### Phase D: 独立性とDevelopment

candidate結果を見る前に、licenseとnative callableを確認できる独立sourceを固定する。現在Topの公開replayからsource codeやbotを復元しない。適切なsourceがなければ第3 ancestryを主張せず、status上限を`PROMISING_UNPROVEN`とする。

旧spent gateを全通過した場合だけ、repository全体で未使用を確認した16 Development blocksを一括登録する。`10091521–10091536`が一つでも使用済みなら、結果を見る前に次の連続16 blocksを機械的に選ぶ。promotion `10091101–10091112`、Fresh `10091901–10091912`、旧Development `10091421–10091436`は開かない。

## 4. 現時点の判断

- production Champion: `V111`。
- numeric agent新設: なし。
- PSR/router: `REJECT_NO_UPLIFT`、research-onlyで完了。
- Tomato option: 主仮説として失効、将来の独立研究候補へ格下げ。
- 次の主仮説: `midgame_third_land_capital_and_activation_commitment`、まだ`PROMISING_UNPROVEN`未満のdiagnostic段階。
- Kaggle提出、kernel push、submission slot変更: 行っていない。
- promotion/Fresh/旧Development seeds: 開いていない。

改訂した実行promptは[`codex_next_prompt_20260916_v111_midgame_capacity.md`](codex_next_prompt_20260916_v111_midgame_capacity.md)である。
