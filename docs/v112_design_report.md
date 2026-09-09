# Kaggriculture V112 設計・検証レポート

## 結論

V112はV111への追加ゲートではなく、設計の前提を入れ替えた独立リベースである。提出する
`agents/v112/main.py`は、Kaito Fukami氏の公開Kaggle notebook
「25/27 Strict-Future | v27 Midgame Meta Reset」Version 4が生成したApache-2.0成果物と
バイト単位で同一である。

- 公開notebook表示スコア: **3090.1**
- 公開ログ記載およびローカルV112のSHA-256:
  `f48c21166eac68d1b05a401f04f94a2eb6154e65415af64893672365ff33c7b8`
- ローカルで新規提出したV112のRating: **未検証**

「公開成果物が3090.1を記録した」ことと、「今回の新規提出が3000を超える」ことは別の主張で
ある。後者は保証しない。

## 調査範囲

### V111の最新実績

| submission | Rating | 取得試合 | 記録結果 |
|---|---:|---:|---:|
| 55909167 | 1688.6 | 52 | 45勝6敗1分 |
| 55912910 | 1730.7 | 55 | 38勝16敗1分 |

結果件数は取得した履歴の記述統計であり、Rating計算を再現する値ではない。

### 2026-08-31時点の上位教師

| 順位 | team | submission | Rating | 解析 replay |
|---:|---|---:|---:|---:|
| 1 | tetsuya | 55905066 | 2918.2 | 48 |
| 2 | Yusuke Hayashi | 55865730 | 2842.6 | 48 |
| 3 | MtN | 55867591 | 2832.2 | 48 |

各replayは720 state完走である。Ratingの異なる時期に生成された履歴なので、replay内勝率を
現在Ratingの代理にはしていない。

## 上位教師から分かったこと

### 1. 序盤は共通、継続は分岐する

Rank 1は24手までのfield/market lineageが48試合すべて同一だった。一方、field lineageの
異なる本数は100手で7、200手で38、400手で48まで増えた。marketも100手で7、200手で32、
400手で48である。

したがって、強い序盤priorは存在するが、Rank 1を単一の固定行動列として模倣するのは誤りで
ある。同じ時刻の一手だけを学習しても、店、価格、相手供給、直前の成否が作る継続状態を
再現できない。

Rank 2/3はRank 1より固定的だった。400手field lineageはそれぞれ18/25であり、200手時点の
最大lineage shareは29.2%/77.1%だった。上位を平均して一つの教師にするより、方策の違いを
分けて見る必要がある。

### 2. Rank 1は「日12の現金」を最大化していない

Rank 1は48/48試合で日12時点の現金が相手より少なく、そのうち47試合が最終的に正marginへ
回復した。これは、序盤の現金差だけを失敗状態と判定すると強い投資局面を誤って止めることを
示す。

比較として、日12でbehindだった試合の正margin回復率は次の通りだった。

| corpus | behind | 最終正margin | 回復率 |
|---|---:|---:|---:|
| current Rank 1 | 48 | 47 | 97.9% |
| current Rank 2 | 26 | 8 | 30.8% |
| current Rank 3 | 14 | 8 | 57.1% |
| V111 55909167 | 32 | 28 | 87.5% |
| V111 55912910 | 37 | 22 | 59.5% |

既知なのは現金推移と最終結果の同時発生であり、「現金behindだから勝つ」という因果ではない。
読み取るべき点は、農場資産、将来収穫、販売可能在庫を含まない現金差だけでは状態価値を表せ
ないことにある。

### 3. 資源配分は時期で大きく変わる

Rank 1の平均farm構成は次のように推移した。

| day | Wheat | Carrot | Tomato | Strawberry | Melon | Goose | Cow | Sheep |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 4 | 0.0 | 0.0 | 0.0 | 6.4 | 1.6 | 0.0 | 2.0 | 3.0 |
| 12 | 10.2 | 2.8 | 0.9 | 31.3 | 12.6 | 1.2 | 6.0 | 5.4 |
| 20 | 27.7 | 1.4 | 1.0 | 26.0 | 0.6 | 2.2 | 6.6 | 6.3 |
| 24 | 34.9 | 4.5 | 0.1 | 11.5 | 0.0 | 2.2 | 6.6 | 6.3 |
| 29 | 26.5 | 8.4 | 0.0 | 1.2 | 0.0 | 2.2 | 6.6 | 6.3 |

高単価作物を全期間保持するのではなく、Melonを早期に使い切り、Strawberryを縮小し、終盤を
Wheat中心へリセットする。V111も終盤Wheat化は持つが、日12の平均はWheat 6.6、Carrot 5.0、
Strawberry 35.9、Melon 2.9、Cow 8.7、Sheep 6.4で、Rank 1とは投資時期と中盤構成が異なる。

### 4. 需要への反応は存在するが、単純置換では再現できない

Rank 1の最大動物数は、最終店列にYarn Storeがある31試合でCow 6.03 / Sheep 7.42、ない17試合
でCow 7.76 / Sheep 4.29だった。需要と動物配分の関係は強い。

しかし、公開v27の予定CowをYarn可視時にSheepへ置換する反実仮想は、発火したペア試験で自己
coinをすべて低下させた。例として同一seed/no-op条件では169,296から143,701へ、現Rank 1
replay由来の固定相手ストリームでは74,341から72,711へ低下した。

相関は確認できても、既存ルートのCowを変えるだけでは、購入費、産出周期、販売時刻、他商品の
価格影響と整合しない。このためCow-to-Sheep overlayはV112に採用していない。

### 5. 市場は単価だけでなく順序が重要

現Rank 1はMilk/Wool/Strawberryの販売quoteと対応資産数に正の相関を持ち、terminal private
inventoryは解析48試合で0だった。V112の上流v27は、公式価格曲線から各販売の自己price impactを
計算し、routeに元から存在するSELL slotだけを現在需要で補正して並べ替える。

安全境界は重要である。新しいfield行動、販売数量、販売slotをモデルが生成するのではなく、
既存SELLの順番しか変えない。相手identity推定も使用しない。

## V111の設計診断

V111の長所は、完全なexecutor、両席の時刻正規化、fallback、route外のfield行動を学習器に
出させない安全境界にある。一方、戦略自由度は実質的に「第3店Yarn時の最後のCow 2頭を
Sheepへ変える」一つである。

現Rank 1のfield lineageが200手以後ほぼ試合ごとに分岐するのに対して、V111第2提出の最大
field lineage shareは200手で50.9%、400手でも29.1%だった。V111の市場列は状態により分岐
するが、farm構成の自由度は小さい。Rating 1730.7への改善を、戦略問題が解けた証拠とは
みなさなかった。

## 採用したV112

公開v27は次の構造を持つ。

1. step 0で4 HIRE、Cow 1、Sheep 4、Wheat seed 5、Melon seed 5をまとめて購入する。
2. 初期25 tilesをMelon/WheatとPastureへ素早く配分する。
3. 中盤はStrawberry、Melon、Cow、Sheepを含む高密度farmへ移行する。
4. 追加landと多数のhandsを使って肥料回収、施肥、収穫、販売を並列化する。
5. day 20以降はWheatへ大きく更新し、終端までにprivate inventoryを売り切る。
6. Weedが予定行動を妨げたactorだけを修復し、最大8手だけ元routeを追い直す。
7. 複数SELLは公式price impactと現在Town需要で並べ替える。

V112ではこの`main.py`を修正していない。わずかなwrapper変更でも、3090.1を記録した成果物との
行動同一性を失うためである。説明、tests、metadata、attributionは提出archiveの外に置いた。

## 棄却した案

- **V111へのYarn gate追加**: farm設計の自由度不足を解消せず、既存route専用過適合になる。
- **公開v27のCow-to-Sheep置換**: 上位の相関には合うが、ペア反実仮想で自己coinが悪化した。
- **Rank 1の行動列を直接再生**: 400手field lineageが48/48で異なり、疎なshop prefixから安全に
  完全経路を再構成できない。
- **上位3方策の平均**: Rank 1の高適応方策とRank 3の固定的方策を混ぜ、実在しない中間方策に
  なる。
- **旧版対戦勝率による選択**: V112はローカルV111との2試合debugでは0勝2敗だった。この値を
  採否に使っていない。同時に、V112が全条件でV111より強いという主張も行わない。

## 検証結果

### 提出物

- `agents/v112/main.py` SHA-256は公開ログと一致。
- sourceは標準libraryのみをimportし、外部model/fileに依存しない。
- 719 actionを内包し、最初の4 HIREと両席step進行を確認。
- routeをdeep-copyしてから操作し、runtimeでfrozen routeを破壊しない。
- SELL rankerが既存SELL slotの順序だけを変えることを確認。
- exception時は現在hands数に合わせたPASSを返す。
- V112 unit tests: 6 passed。

### standalone smoke

生成archiveを別directoryへ展開し、両席で720 state完走した。starterとの2試合は平均169,257.5
coin、statusはすべてDONEだった。starter勝率は安全smoke以上の意味を持たない。

### 現上位ログ由来の固定相手ストリーム

現Rank 1-3からreward quantileで各2試合を選び、同一seedで相手の記録行動を再生した6試合は
すべてDONE、terminal private inventory 0、animal loss 0だった。平均自己coinは68,426、
debug marginは-10,718.8、最大Weedは6だった。

相手は分岐後に適応しないopen-loopなので、このmarginはlive上位への勝率ではない。負marginは
隠さず、現在metaに対する不確実性として残す。

## 事実・推測・未検証

### 分かったこと

- V112のbytesは公開スコア3090.1のnotebook出力hashと一致する。
- 現Rank 1は共通opening後に大きく分岐し、全48試合で日12現金behindから47試合を正marginへ
  回復した。
- 上位は需要に応じて動物構成を変え、終盤在庫を清算している。
- V112は両席で完走し、上位ログ由来の6固定ストリームでもterminal private inventoryとanimal
  lossを0にした。

### 推測

- 公開v27の3090.1は、V111の限定的route gateより目標Ratingに近い外部証拠である。
- 強い序盤prior、完全な中盤reset、price-impact順序、終端Wheat化の組み合わせが寄与している。
- 現Rank 1の全適応を疎なreplayだけから安全に複製するより、検証済み完全routeを採る方が今回の
  提出リスクは小さい。

### 未検証

- 新規V112提出が同じ3090.1または3000超を再現するか。
- 公開notebook評価時と現在のopponent pool差がどれだけあるか。
- Rank 1型の動的farm再設計を追加した将来版が、完全routeを壊さず改善できるか。

## 再現コマンド

```powershell
.\.venv\Scripts\python.exe .\scripts\analyze_v112_strategy.py
.\.venv\Scripts\python.exe .\scripts\evaluate_v112_teacher_forks.py --sample 2
uv run pytest -q tests\test_agent_v112.py
.\.venv\Scripts\python.exe .\scripts\package_submission.py --agent agents\v112 --output artifacts\submissions\v112.tar.gz
```

主要出力:

- `data/analysis/v112_strategy_analysis.json`
- `data/analysis/v112_teacher_fork_diagnostics.json`
- `data/runs/v112_standalone_smoke.json`
- `artifacts/submissions/v112.tar.gz`
