# Kaggriculture研究総括とlive trial運用方針（2026-09-16 JST）

## 結論

研究は止まっていたわけではない。V112以降にも複数のagentと大規模なpaired評価が作られ、V113は実際にKaggleで約1675まで観測された。しかし、現在のrepositoryでは次の三つが同じ「合格・棄却」にまとめられていた。

1. mechanismについて因果的な改善を主張できるか。
2. production Championへ昇格できるか。
3. 不確実性を減らすために限定live trialへ出してよいか。

この一体化が、研究上は誠実でも、実運用では新しいlive evidenceを得にくい状態を作った。以後はV111を凍結Championかつclean controlとして保持したまま、別のnumeric agentを`LIVE_TRIAL_CANDIDATE`として作成できるようにする。live trialは統計的有意差や3 independent ancestriesを要求しない。一方、runtime、壊れたtransaction、非終端の動植物喪失、package/license不明といったhard riskは緩めない。

次の実行では、V111だけを親にしたV117を実際に作る。第一候補は、今回特定したCOW購入による中盤資金拘束をstate-basedに扱う`midgame_land_cash_reserve_live_trial`である。完全な早期activation contractが実装上成立しなければ、事前に定めた小さい`late_land_order_resequence`へ縮退してもよいが、「新versionを作らない」で終えてはならない。V117がhard Safetyを通らない場合は提出しない。その場合、既にApache-2.0、source hash、standalone smokeが確認されているV112 exact artifactを、current-meta calibration用のfallback live trialとして再検証する。

production Championの変更はlive trialとは別判断であり、当面V111を維持する。

## 1. GitHubに保存済みの範囲と、今回まだ未保存の範囲

監査時点はbranch `main`、HEAD `21e91ece0039ed6bd74add48e0c2e46f8ba385ef`で、`origin/main`と一致していた。2026-09-16 01:37 JSTまでの次の主要成果はGitに追跡済みである。

- V111/V112/V113/V114のagent、設計・評価文書。
- V113 live E6のpost-hoc分析。
- V114/V114r1のroute-switch評価。
- 2026-09-11/12のterminal sale、Cow/Sheep/Goose continuation研究。
- 2026-09-14の`v116_mooman_complete`、clean PSR、Safety評価。
- 2026-09-15のrouter mechanism ablation。
- 2026-09-16のcurrent Top 5 replay解析、Tomato案の再評価、midgame-capacity研究用prompt。

今回の監査開始時点でGit未追跡だったのは、直近のreplay-only midgame-capacity研究である。

- [`research_20260916_v111_midgame_capacity_preregistration.md`](research_20260916_v111_midgame_capacity_preregistration.md)
- [`research_20260916_v111_midgame_capacity_report.md`](research_20260916_v111_midgame_capacity_report.md)
- [`research_20260916_v111_midgame_capacity.py`](../scripts/research_20260916_v111_midgame_capacity.py)
- [`research_20260916_v111_midgame_capacity/`](../experiments/research_20260916_v111_midgame_capacity/)

この未追跡部分が「最後に保存された時点から現在まで」の実質的な差分である。新規game、candidate、Kaggle提出は含まれず、既存replayだけを再解析した。全required JSONはload可能、記録hashは一致し、新規Pythonは`py_compile`とruff、関連testは22/22に合格している。

大きなJSONを通常Git objectへ直接入れると履歴が膨らむ。`land_relative_activation_timeline.json`は68,618,140 bytes、`midgame_cashflow_ledger.json`は33,755,210 bytesであるため、この2ファイルだけGit LFS対象にし、report、manifest、hash、その他JSONは通常Gitへ保存する構成を採る。

## 2. agentとlive evidenceの実際の履歴

| Agent / 研究 | 実体 | 得られたこと | 現在の扱い |
|---|---|---|---|
| V111 | repository-owned complete route + bounded model overlay | known submission 55909167/55912910は1688.6/1730.7。現在のclean control | `PRODUCTION_CHAMPION` |
| V112 | 公開Kaito v27のApache-2.0 exact artifact | upstream表示3090.1、local source hash一致、standalone smoke合格。local新規提出ratingは未検証 | `VERIFIED_EXTERNAL_LIVE_CALIBRATION_CANDIDATE` |
| V113 | V111のCow→Sheep gate拡張 | submission 55933145で約1675、58 public episodesは44W/14L。一方pairedではL→W 0、W→L 0、spawned-weed regressionあり | `LIVE_VIABLE_CAUSAL_UNRESOLVED`、Championではない |
| V114/V114r1 | t153 route switch | originalはruntime bug、r1は32 pairsで介入0、forced deliveryは0W/32LかつSafety悪化 | `REJECTED_RESEARCH_ONLY` |
| V115p群 | sale、Sheep、Cow保持、managed Sheep/Goose | validかつhard-SafetyなしのL→Wなし。saleは安全だがmargin悪化、動物案はW→L/no-opあり | `REJECTED_RESEARCH_ONLY` |
| v116_mooman_complete | license確認済み外部complete policy | 旧32 contextsでV111 12/0/20→20/8/4、L→W 10、W→L 0。ただしraw Safety 28/32 | `REJECTED_RESEARCH_ONLY` |
| P1 clean PSR | 公開state routerをclean-room実行 | 24/0/8、V111比+0.375、L→W 14 context、W→L 2。Safety 32/32、transitive route provenance不明 | `REJECT_SAFETY_AND_PROVENANCE` |
| A0 fixed route ablation | P1のroute 0をstep 0固定 | +0.3125でP1 upliftの83.33%を保持。router固有差は+0.0625だけ | 診断用、deploy不可 |
| 最新midgame replay監査 | V111 spent 32 + Top public 30 | 資金拘束familyとland timingを切り分けた。candidate gameは0 | `REJECT_NO_FEASIBLE_CONTRACT`だが有力な設計入力 |

重要なのは、V113は「作ったが出さなかったagent」ではなくlive提出済みだという点である。一方、active remote submission 56089444はlocal V109/V110/V111/V113と99.53%近いがexact archive identityが確定していない。現在の問題はversion数の不足だけでなく、source hash、submission ID、active slot、live resultを一つのregistryで結べていないことである。

また、`agents/v116_mooman_complete/RESEARCH_STATUS.json`には`UNEVALUATED`、同directoryの`research_decision.json`には`REJECTED`が残る。後者が新しく正しいが、このようなstatus重複も運用上の危険信号である。次回からrootのmachine-readable registryを一つ正本にする。

## 3. これまで何を検証してきたか

### 3.1 V111の小さなcontinuation変更

終盤即時売却、Town同期売却、unmanaged Sheep、Cow保持、managed Sheep、managed Gooseを同一seed/opponent/seatで比較した。売却は安全に実行できたが勝敗改善がなく、平均marginは悪化した。動物変更は配置・給餌・収穫・販売を繋いでもW→L、no-op、または自己利益を相手利益が上回る問題が残った。従ってterminal saleやlate livestockを再び主仮説に戻す根拠はない。

### 3.2 complete policyとPSR

v116/P1はローカル勝敗を大きく改善した。この結果を「役に立たなかった」と表現するのは誤りである。確認できたのは、V111とかなり異なるtotal policyに大きなupsideがあることだった。

ただし同時に、動物逃亡、crop-to-weed、silent market/field no-op、partial commitが広範囲に増えた。P1はさらにV111の既存勝ちを2件失い、route dataのtransitive licenseも確定していない。したがって、そのままproductionへ転記しなかった判断は妥当である。

router ablationではP1 upliftの大部分が動的routerではなく、step 0から共通するfixed route/initial footprintを含むtotal policyにあると分かった。これは「routerをさらに調整する」優先度を下げ、openingから中盤のcapital allocationを調べる根拠になった。

### 3.3 current Top public replay

2026-09-16 00:33 JST snapshotのTop 5から30 target-seat observations、26 unique replayを保存し、22W/0D/8L、mean margin +3,459.5、P10 -2,906を観測した。これはselected opponent mix上のE1観測で、ratingやcandidate効果ではない。

step 48 field hashは22種類、step 300は30/30が異なり、単一の上位routeは存在しない。Tomato seedは22/30にあるが初回中央値320.5で、中盤capacity差より後である。上位8敗は22勝よりTomato保有が多く、SpaTaroはTomato/Gooseなしで6/6だった。従って旧Tomato案を主仮説から外した。

### 3.4 最新の資金・land・activation監査

V111の第3区画unlock中央値はstep 253付近、Topは209だった。V111はstep 209で32/32がcash 2,000未満、中央値55であり、land thresholdではなく流動性が直接制約だった。

一種類の支出familyだけを算術上延期すると、`BUY_ANIMAL:COW`は32/32 contexts、16/16 source-seed blocks、4/4 sourcesでland 2,000 + activation lower bound 11を作った。shadow上の前倒しは91–106 decisions、中央値91だった。

しかし、これは強さの証拠ではない。土地より前に実際に配置されたCowは32 contexts合計232頭で、その関連作業はPICKUP 174、PLACE 232、FEED 848、CARE 856、COLLECT_FERTILIZER 616だった。これらのmilk/fertilizer、worker、maintenance debtを保持しながら、新landのWheatを植付・給水・収穫・販売し、元routeへstate-basedに戻すscheduleは0件しか証明できなかった。

一方、実際のV111はland購入後1–2 decisionsでproductive actionへ進み、Topも中央値2.5だった。従って主問題は「買った後に長時間放置すること」ではなく「買える現金を作る前にCowへ強くcommitすること」である。

## 4. 現時点で確定したこと、未証明なこと

確定したこと:

- V111は安定したcontrolだが、現在Topより中盤の第3区画とproductive capacityが約36–55 decisions遅い。
- step 209付近の直接制約はcash shortageであり、単なる`BUY_LAND`発火条件ではない。
- replay上、最大の単一資金拘束familyはCOW購入である。
- Tomato、terminal sale、late livestock、router switch単独は次の主仮説ではない。
- complete policyのtotal-policy差には大きな局所upsideがある。
- V113 live提出は、local causal gateを通らなくてもlive viabilityを学べた実例である。

未証明なこと:

- COW延期で失うmilk/fertilizerと、早いlandから得るcrop revenueのどちらが大きいか。
- 早いlandをmaintenance lossなしで実働化する一般executor。
- current strong fieldに対するV111/V117の真のrelative strength。
- active remote 56089444のexact package identity。
- V112 exact artifactを今のfieldへ再提出したrating。
- opponent coin低下のうち、自分の生産、market mediation、opponent policy responseが占める割合。

## 5. なぜV111のままになったか

以前の基準は「因果的に説明でき、複数sourceへ一般化し、Safety差が0で、Freshでも勝つagentだけをnumeric versionへする」というpromotion用の基準だった。偽陽性を避けるには有効だが、次の副作用があった。

- numeric agent作成そのものが研究合格の報酬になり、試験可能なartifactを早く固定できなかった。
- local panelが古い2 ancestry中心なのに、そのpanelの完全合格をlive観測の前提にした。
- `REJECT`が「Championにしない」「提出しない」「今後参照しない」を同時に意味した。
- remote submissionとlocal archiveのhash対応を提出時に固定しなかったため、後からlive resultをversionへ帰属できなくなった。
- safe cancelのようなdelivery failureと、実際の動植物喪失を同じSafety bucketへ入れた時期があった。

したがって、基準を単純に緩めるのではなく、目的別に分ける必要がある。

## 6. 今後の4段階status

| Status | 意味 | 必須条件 |
|---|---|---|
| `RESEARCH_ARTIFACT` | 仮説・実装を保存した | source、diff、hash、license、再現command |
| `LIVE_TRIAL_CANDIDATE` | 限定的な実戦観測へ出せる | hard Safety 0、package identity、full completion、bounded local loss budget |
| `LIVE_TRIAL_SUBMITTED` | submission IDとarchive hashを固定してlive観測中 | upload時manifest、slot状態、取得episode、変更履歴 |
| `PRODUCTION_CHAMPION` | default親・clean controlとして採用 | 従来の厳格なpaired/generalization/Fresh基準または十分なlive比較と再現性 |

numeric versionは最初の段階で作ってよい。version番号は「Championになった」という意味ではなく、immutable test artifactのidentityとする。これによりV117を作りつつ、Champion V111を維持できる。

## 7. live trial gate

### 緩めないhard gate

- package source、license、hash、manifestが確定している。
- opponent/source/seed identity、private opponent state、future RNG、replay action tableをruntimeで使わない。
- import/reset/isolation、same-process連続episode、fresh-process、両seatを通る。
- smokeとtrial panelの全gameが720 statesで完了し、runtime error、timeout、negative cash、malformed action、missing hands、壊れたpartial transactionが0。
- candidate起因の非終端animal escape、water-death crop-to-weed、必要maintenance欠落が0。
- interventionは完走するか、commit前にbaselineとaction/state同一のsafe cancelを行う。

### live trialでは要求しないpromotion gate

- whole-block bootstrap 95%下限>0。
- 全source別win-score非悪化。
- 3 independent ancestries。
- W→L完全0。
- Fresh E5完了。

### 固定するbounded loss budget

local結果が不確実でも、次を満たせば1回のexploratory uploadを許容する。

- frozen confirmation panelでdelta win-scoreが`-0.0625`以上。
- W→L source-seed blocksはL→W blocksより最大1 block多いまで。
- どのsourceもdelta win-scoreが`-0.25`未満でない。
- interventionが2 sources以上、4 source-seed blocks以上で実際にcommitし、主要mediatorが記録される。

この数値はpromotionの証明ではなく、live情報を得るための損失上限である。結果を見て変更しない。

## 8. 次のV117で試すこと

V117はV111だけを親にし、Top/P1/v116のrouteやaction表を含めない。主介入は`midgame_land_cash_reserve_live_trial`である。

1. 第2区画までunlock済み、第3区画がlocked、V111自身がCOW購入を要求した時だけ、同じCOW familyの一部をdebtとして延期する。
2. cash、land cost、Wheat/feed、urgent maintenance、shed、market slots、workerをcurrent stateでpreflightする。
3. 土地購入だけで終了せず、新区画のbounded tileへV111既存familyを配置し、WATER、HARVEST、carry/drop、SELLまでstate machineで追う。
4. option専用actorを識別し、V111に渡すobservation/actionとの対応を壊さない。
5. 延期CowはFIFO debtとして、再購入・配置・maintenanceへ戻すか、明示的cancel conditionを記録する。
6. rejoinは時刻ではなく、land、tile、inventory、worker、debtが定めたstateで行う。

早期版がhard Safetyを満たせない場合、同じ実験内で結果に合わせてthreshold探索はしない。事前fallbackとして、V111がstep 248近傍で元々行う`SELL MELON + BUY_ANIMAL COW 2`が現在stateで成立し、同turnにland 2,000と元注文を全て逐次commitできる場合だけ、`BUY_LAND`を同じmarket turnへ入れ、元のt252土地注文を重複させない`late_land_order_resequence`へ縮退できる。このfallbackは大きな36–55 decision gapを解く候補とは呼ばず、package/live plumbingと小さなordering効果の試験と明記する。

どちらも作れなければ、V117 directory、failed prototype、first failure、package不適格理由を保存する。ただしnumeric artifactを作らず診断だけで終了する以前の運用へは戻さない。

## 9. V112の位置付け

V112は新しいV111改善案ではなく、公開済みcomplete policyのexact external benchmarkである。upstream artifactの表示score 3090.1、SHA-256 `f48c21166eac68d1b05a401f04f94a2eb6154e65415af64893672365ff33c7b8`、Apache-2.0、standalone completionは確認済みである。

V117がhard gateを通らない場合、unsafeなV117を提出する代わりにV112 exact packageを再検証し、まだ同hashを自チームが提出した証拠がない場合だけlive calibration候補にできる。これはV112をChampionへ自動昇格することでも、他者artifactのscoreを自分の将来ratingと呼ぶことでもない。

## 10. 提出とslotの扱い

次のpromptはTrial Gate通過後の最大1回のsubmission uploadを許可する。kernel pushは禁止する。現在の二つのactive slotを変更する操作は、既存slotを外す外部状態変更なので自動実行しない。uploadだけではmatchが開始されずslot変更が必要な場合、次のCodexは以下を提示して一度だけ確認を求める。

- 現在の2 submission ID、rating、最終match時刻。
- 新candidate version、archive SHA-256、local trial結果。
- どちらのslotを置換する提案か、その可逆性と失う観測。

submit時にはarchive hash、message、CLI response、submission IDを同じmanifestへ直ちに保存する。これで今後remote identityが`UNVERIFIED`になることを防ぐ。

## 11. 推奨順序

1. 今回の未追跡midgame研究、本文書、status registry、次回promptをGitへ保存する。
2. remote identityとactive slotをread-only監査する。
3. V117 contractを凍結し、numeric directoryを作成する。
4. import/A/A/smoke/old-spent engineeringを行う。
5. candidate hash固定後、小さいunused confirmation panelを一括実行する。
6. hard gateとbounded loss budgetを通れば最大1回uploadする。
7. live resultはcausal proofでなくE6 whole-agent evidenceとして蓄積する。
8. Champion変更は別decisionで行い、V111をすぐ上書きしない。

次回の実行promptは[`codex_next_prompt_20260916_v117_live_trial.md`](codex_next_prompt_20260916_v117_live_trial.md)である。
