# Kaggriculture learning-next 実験報告（2026-09-21）

| arm | 新規train/fit | 教師/データ数 | 更新数 | model hash | 本番load | action変更数 | 完走数 | 勝敗/paired差 | 状態 |
|---|---:|---:|---:|---|---:|---:|---:|---|---|
| C0 | なし | 凍結Control | 0 | archive `472eb013…8452` | 66試合 | 0 | 66/66 | 62勝4敗、基準差0 | EVALUATED |
| 学習版B | あり | 850 episode、612,000状態×27 label | 1,680 | `0f4d1ec5…67df5` | 42試合/42回 | 77 turn-action | 42/42 | 42勝0敗、score差0、margin差+13.00 | INSUFFICIENT_EVIDENCE |
| 学習版A | あり | 56216119: 579 episode、2,079,454候補 | 5,656 | `30a927c1…b02` | 2試合/2回 | 1,277 turn-action | 2/2 | 0勝2敗、Win→Loss 2、score差−1.00 | REJECTED |
| 独立BC | あり | 56216119: 579 episode、actor 833,137＋market 516,635 | 3,680 | actor `3e640688…a5b4` / market `f47c6543…a62` | 2試合/4 model load | 1,437 turn-action | 2/2 | 0勝2敗、Win→Loss 2、score差−1.00 | REJECTED |

## 結論

指定された3系統は、実データ作成、実際のfit、checkpoint保存、別processでの再読込、standalone archive化、初期状態から720状態の終局対戦まで実施した。新しい学習をControlの別名にしたものではない。

Bは実戦経路へ到達し、修復後の42試合で77 turn-actionを変え、model usage上の77/77変更が成功、fallback 0だった。developmentではC0、単純予測、学習予測がすべて40勝0敗で、学習版のC0比marginは+13.85、単純版は−303.175だった。ただし主指標のpaired win-score差は0で、事前登録した「正のwin-score差」を満たさない。したがってfresh holdoutを後付けで消費せず、PROMOTABLEとはしない。現在の証拠は **INSUFFICIENT_EVIDENCE** である。

Aと独立BCは合法形式で完走したが、いずれもC0の2勝を2敗へ変えたため早期棄却した。これは「未学習」ではなく、学習・統合・closed-loop評価済みの弱い候補という判定である。レート3000到達・向上幅は主張しない。Kaggleへの提出も行っていない。

## 固定条件と監査差分

- C0は `artifacts/submissions/v126_control_candidate.tar.gz`、SHA256 `472eb013183d4d7bc320fb25532ace0d6ab6d2af46d914e0ae158486f39e8452`。v124 commit `dd928e2590687461a03c1af59d37e3e597c25416` と v125 commit `fadd7e89bfe6612ecbe2020fb724bb9064014987` はローカルで解決できた。C0を全履歴最強または無欠陥とは扱わない。
- 使用engineは `kaggle-environments==1.32.7`。実importファイルのSHA256は `bc8a5487…653e`、設定は `a82c89c1…4867`。確認時の公式masterと両方byte-identicalだったが、評価はmoving masterではなくこのローカル固定版で行った。
- CPU 22 logical cores、RAM 33.8 GB、空き289.5 GB、NumPy 2.5.2、Torch/GPUなし。小型NumPy MLPをCPUでfitした。
- ローカル公開replayは事前報告の861 viewではなく **864 view**（56216119: 579、56361903: 132、56354460: 153）。重複appearance 14をまとめると850 unique episodeだった。これは今回確認した実在データとの差分である。
- `observation[t]` に `steps[t+1].action` を対応させることを実物で確認した。720保存状態を719意思決定と区別し、MOVE/BUY/PICKUP/HARVEST/day境界、両seat、禁止フィールド不変性をテストした。
- episode単位で595/127/128へ分割し、同一episodeの重複appearanceを跨がせなかった。前処理と単純B頻度baselineはtrainだけでfitした。

過去成果物の実在確認では、Downloadsに `v125_followup_report.md`、`v125_followup_evidence.zip`、`kaggriculture_v125_analysis.md`、`kaggriculture_v125_analysis_package.zip` があり、repo内に `artifacts/v125_followup_evidence/fixtures/failed_transfers.json` があった。指定名そのままの `v126_codex_audit_prompt.md` と `kaggriculture_v125_codex_prompt.md` は見つからなかった。未追跡の `artifacts/v125_followup_evidence/` は削除・改変していない。

## 学習版B

入力は行動時点までの公開観測と自己既知履歴だけで、233特徴。1/4/24区間×9商品についてSELL要求発生と要求数量を学習した。数量は「実約定量」と偽らず、replayに保存された **要求量** である。未来、episode/submission ID、最終勝敗、相手private、seedは入力に入れていない。

MLPは233→32→54、8 epoch、1,680 Adam update。validation loss最低のcheckpointを選び、testはその後に一度だけ読んだ。保存hashは `0f4d1ec50314658d32d52a17d47f6f20be3bb5b414a764a679c9e1724b767df5`、別process再読込予測は完全一致した。

- validation Brier 0.142663、test Brier 0.143091、test数量MAE 81.822。
- testのゼロ予測はBrier 0.261870・数量MAE 82.555、時刻頻度baselineはBrier 0.134622・数量MAE 101.911。したがって学習版はゼロより良いが、確率校正では単純頻度に負け、数量では頻度より良い。全指標で優越したとはいえない。
- C0注文を候補に残し、連続SELL blockの維持・順序変更・限定的前倒しだけを比較した。固定engineと同じfloor、資金制約、単位処理、上限10注文を決定的計算器とテストで固定した。
- repair smokeは2勝0敗、4差分、margin差−4。developmentは4 family×5 seed×両seatで各arm 40試合。学習版73差分、変更成功73、fallback 0、40勝0敗、score差0、margin差+13.85。単純版は216 turn差分、model usage上118注文変更成功、40勝0敗、margin差−303.175。
- developmentのinferenceはp50 5.16 ms、p95 8.00 ms、p99 12.29 ms。ただし別process cold start最大2.36 sで、公開既定 `actTimeout=1` を超える観測がある。提出前にimport/cold-start削減が必要であり、これも昇格を止める実務上の理由である。

## 学習版A

test結果を見る前に、最大で品質検査を通過した56216119を教師に固定した。FEED/CARE/WATER/FERTILIZE/HARVEST/COLLECT_FERTILIZER/PICKUP/PLACE/DROP/PLANT/DIGの候補順位を275特徴から学習した。教師work action 2,163,233件中2,079,454件（96.13%）を候補生成器が表現し、除外はCARE 18,837、HARVEST 64,942として記録した。

MLPは275→32→11、8 epoch、5,656 update。test accuracy 0.977091、macro recall 0.978829で、期限優先baseline accuracy 0.638229を上回った。保存hash `30a927c1bb836eaecb1d9eaca07156e2091bd53401aac6b433618aff94a13b02`、別process再読込一致。

初回実装はopだけを復元してitem/quantityを落とし、turn 2以降ほぼ全軌道を壊した。失敗を保持した上で、構造化C0 action保持、合法token materialize、実task境界だけの介入、観測確認付き「倉庫移動→PICKUP→目的地移動→FEED」jobへ修正し、全データを再構築・再学習した。修復後は720状態で2/2完走、model load 2、推論2,549、job開始56・完了37・安全中断19。しかしturn 4から過剰に分岐し、1,277 turn-action差、Win→Loss 2、mean margin差−156,901。offline模倣精度がclosed-loop価値を保証しない例でありREJECTEDとした。

## 独立BC

教師は同じく56216119だけ。既存C0/v125/routerをimportせず、状態encoder、前回actor action履歴、44-class actor decoder、順序を保持する22-class market decoderを実装した。逐次decodeでseed・倉庫・現金・注文上限を予約し、環境actor順を維持した。actor表現coverageは1.0で、黙示除外はない。

actor MLPは319→32→44、2,272 update、test accuracy 0.707311。market MLPは256→32→22、1,408 update、test accuracy 0.741571。hashはそれぞれ `3e64068852c8dca9da7f6399c43632daf098968b5576e25a05387742d835a5b4` と `f47c654329811e01272b0befdbcdb12e0e2b416d07860cd52f4930fc7f563a62`。

初回closed-loopの最初の失敗を履歴欠落・state aliasing・予約不足と分類し、前回action特徴と厳密な逐次予約を追加して再学習した。修復後は2/2完走、12,188推論、8,466 model action check中8,394成功、fallback 0だったが、turn 0から教師軌道を外れ、1,437/1,438 turn-actionがC0と異なり、Win→Loss 2、mean margin差−147,941.5。Replayのnearest actionをoracle/DAggerとは扱わず、追加修復の根拠となる上位oracleがないためREJECTEDとした。

## 評価、Safety、既知E

Challenge校正はC0のみ、6 family×2 seed×両seat=24試合。C0はqeinstein 3–1、mooman 3–1、smart_farm 2–2、souvik 4–0、ggmljs 4–0、robriculture 4–0だった。事前addendumどおり追加2 familyは4/4なのでdevelopmentへ加えず、元の4 familyと未使用seed 5本を使用した。相手は実行可能なpublic codeだがSilver代理であり、上位本人の反応方策Goldではない。mooman/souvik等の系譜独立性にも限界がある。

development seedではC0が40/40と再び飽和したため、Bの勝率上積みを測れなかった。marginの正値だけでは昇格させない。fresh holdoutは「developmentで正のpaired win-score」という事前条件を満たさず未実施であり、これはNOT_RUNの隠蔽ではなく、BのPROMOTABLE判定に必要な証拠が不足しているという意味である。

全primary試合は720状態、`DONE/DONE`、例外・timeout・不正形式・未完走なし。Shop履歴hashとreplayを保存した。過去のE fixtureは4 episode、failed-transfer 12件、4頭退出4件を再検証してPASSしたが、記録状態の検証に限る。C1修復の成立は主張せず、B/A/BCを待たせなかった。

初回失敗run `smoke_evaluation`、修復内容、旧model hashは削除せず `repair_history.json` に保持した。校正開始時に同一outputへ重複起動した1 processが `OSError: [Errno 22]` でexit 1になった事実も `commands.jsonl` に残した。もう一方はexit 0で24 unique組合せ・全720状態を確定し、候補評価はその完了成果物だけを使用した。

## 検証と成果物

- 全回帰試験: 318件PASS（既存303＋新規15）。Ruff PASS。pytest cacheを書けない権限warningのみで、test failureではない。
- standalone archiveは全てroot `main.py`、必要modelと推論依存のみを収録。repo外 `C:\tmp` へ展開し、別processでmodel loadと初回actionまで全archive exit 0。モデル欠損は明示失敗する。
- archive SHA256: B学習 `de65eafe…d51`、B単純 `50b8d8e4…c7fc`、A学習 `9b1f1649…4485`、A baseline `aafa4139…54a0`、独立BC `7b3da333…23f0`。
- 正本: `source_manifest.json`、`dataset_manifest.json`、`split_manifest.json`、`feature_schema.json`、`offline_metrics.json`、`model_usage.json`、`paired_results.csv`、`payoff_by_family.csv`、`evaluation_manifest.json`、`inference_benchmark.json`、`archive_manifest.json`、`commands.jsonl`、`FINAL_MANIFEST.json`。
- 再開コマンドは `RESUME_COMMANDS.md`。大容量 `.npy` とreplayは再生成可能なignore対象だが、元source hash、split、学習log、model、評価集約、archiveは保存した。

次の価値ある実験は、BについてC0が実際に負ける未使用かつ系譜の異なるGold/Silver相手を事前固定すること、Aについて単発分類ではなく「変更しない」を含む保守的gateとjob単位のsequence評価を学ぶこと、BCについて実行可能なteacher policyを確保してon-policy correctionを行うことである。現在のReplayだけから未見状態の上位oracleを創作しない。
