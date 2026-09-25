# Kaggriculture Learning Round 7 実験報告

## 結論

Round7の実装・訓練・診断・開発評価は完了した。選択候補は
`learning_round7_20260922_arm_b_plan_v3.tar.gz`、SHA-256は
`fe3b5bd9b14ec64208fc9360c38b9aaf5cc1b44547dca2b6eee3d24d0aaf1fca` である。

この候補はRound6の開始直後の無給餌を解消し、開発48戦の全試合で初回家畜生産と回収まで到達した。平均終局自資金はRound6 sequence BCの8,401.81から17,895.94へ、平均資金差は-143,519.85から-133,928.35へ改善した。土地拡張も19/48から42/48へ増えた。これは閉ループで確認できた研究上の改善である。

一方、v122/v123/v124に対する戦績は0勝0分48敗であり、短期目標の「明確な勝ち越し」は達成していない。各anchorの点推定60%以上・片側95%下限50%超の条件はいずれも未達である。昇格は見送り、sealed seed `2026110701..2026110732` は開封していない。Kaggle提出、外部アカウント変更、有料計算資源利用、ネットワーク取得は実施していない。

最終候補には学習済み全行動方策に加えて明示的な家畜task-completion executorが入る。この改善を独立全行動BCの成功とは呼ばない。独立BCのArm A/Bは継続して訓練済みだが、Arm B単体と数量ledger単体はday1反例を完了できなかった。

## 実物と再現性

Phase 0でHEAD `0631a91e65d808cab70baad722ef8ac144b1c44a` と既存の未コミット・staged差分を記録し、Round6成果物を上書きしなかった。監査添付ZIPの実物hashは `de2b4c673767dfb97d8905facc48848f80c0aed2494439b31df75f4b41407407` である。監査が参照した `learning_round6_20260922.zip` 自体はローカルに存在しなかったため、repoに存在するRound6ソース・重み・replayを「監査ZIP同梱物」とは扱っていない。

照合した主な凍結物は次の通りで、いずれも指定hashと一致した。

| 実物 | SHA-256 |
|---|---|
| Round6 sequence BC | `f8d1bc6ea5d69ef8777013995c63aa88e83f8a5c1402b184f356153d2d372434` |
| v122 | `edf5b32565f8c4530959b94df36858a6a64c651d4b42b7aa612ddaca02e9a88c` |
| v123 | `0d5296587b1ba6f68cbd7bd5943f164269071b03b852ee3982ce22958edc33f6` |
| v124 | `cdc74eb6ae47c53e9c2edfeea45dc55603c67ebfdba48164081458f79c4f46fc` |
| 最終V3 | `fe3b5bd9b14ec64208fc9360c38b9aaf5cc1b44547dca2b6eee3d24d0aaf1fca` |

固定engineは `kaggle-environments==1.32.7`、ゲームソースSHA-256は `bc8a54879ef02c7ea64b8b333d6a976f0ea65c4949149d01f463f23bccee653e`、path loaderの `agent.py` は `9b7682ce9921c8f34080a8be0f7b41598cc12ac7eb14d24e4b707883f25213b6` である。

Round6最終archiveをrepo外へ単独展開し、固定loaderが行う空globalsの `exec` 経路で読み込むと `KeyError("'__name__' not in globals")` になった。通常import成功は公式path loader成功ではなかった。Round7では相対import前提を除去し、最後のcallableが `agent` になるwrapperを用いた。V3は固定 `build_agent(path, {}, "kaggriculture")` とrepo外fresh importの両方を通過し、day1 traceでも同じ出力を再現した。

教師manifestにはsubmission 56216119の579 episode-seatがあり、欠損・size不一致はない。今回の因果検査に使ったepisode 109590135 seat 1の実ファイルhashは `ac674040b640ec24b9cf163170342eccdfc8bdc25809834f307053fc5e555466` でmanifestと一致する。全教師payload約1 GBは証拠bundleへ重複収録せず、全manifest・split・この因果episodeを収録する。

## Phase 0: 真の失敗原因

時系列は `observation/state t -> record t+1のaction -> state t+1` と再確認した。seed 2026102201、seat 1のday1を同じRound6実物archiveでrecord 28まで再生し、保存actionと全recordが一致した。

record 27ではfarmerがWHEATを1個pickupして実際に所持した。次のrecord 28でraw MLPは、小麦を持たないhand `(4,4)` にFEEDを約0.9902で割り当て、小麦を持つfarmerにはWESTを約0.7386、FEEDを約0.0907で出した。合法maskは前者のFEEDをNORTHへ変更し、後者を再割当しなかった。そのためraw FEED要求は存在したが補正後FEEDは0になった。maskを外せば小麦を持たないactorの無効FEEDになる。

したがって原因は数量1だけではなく、raw方策の誤った役割・対象割当、補正後の再割当欠如、pickupからfeed完了までの複数ターン目的欠如の組合せである。Round7 plan armでは同じ状態でfarmerがWHEAT 2をpickupし、次recordでfarmer自身がFEEDした。

train/runtime encoderはtrain/validation/old-test各例で数値・hashが一致した。runtime入力は公開状態、当該seatのprivate、自己の既出注文履歴だけで、episode/submission/相手名/最終結果/未来Shop/未来action/相手privateは使っていない。座標はfarm0→farm1の絶対順でplayer bitを明示する設計であり、self/opponent正規化ではない。

一方、同一turn prefixの追加88特徴はtoken頻度44と直前token44だけで、`PICKUP WHEAT 1` と `PICKUP WHEAT 7` は同一特徴へ潰れた。Round7 ledgerはdecode後の数量・既知資源を逐次追跡するが、これはencoder自体の情報欠落を学習で解決したものではない。

構造化教師のencode→decodeは診断8 episode-seatでactor 57,665/57,665、market 7,329/7,329が形式一致し、actorのcanonical semantic一致も57,665/57,665だった。教師要求にはpre-action mask外のCARE/HARVEST/PICKUP等も含まれ、これを合法な正解と再定義していない。

旧方策の8 episode-seat、5,752 decisionにおけるjoint完全一致はraw 15.33%から旧補正後13.56%へ低下した一方、market sequenceは47.62%から48.30%へ改善した。よって安全補正は全撤去していない。補正変更はactor 1,767件で、合法性・inventory・経済・sequence maskを理由別transitionとして保存した。V3 final jointは2.90%まで低下しており、executorが教師action模倣を大きく上書きすることも明示する。

market ledgerはactor phaseで同turn購入品を使わず、既知inventory・倉庫容量・注文順を更新する。先行売却収入は未知価格で完全に見積もらず、保証できる1単位あたり1の下限だけを後続購入へ充当する。未知の相手注文を見た完全ledgerは仮定していない。非微分補正に通常の逆伝播が通るとは説明しておらず、学習lossは各headの教師ラベルに対するcross entropy、ledger/executorは推論後処理である。

## Phase 1: 最小契約試験

固定状態、要求、engine前後状態、成功条件を保存し、次を全てPASSさせた。

- 牛購入→倉庫→pickup→設置→給餌→care→初回生産→回収→売却。
- 複数actorによる同一小麦・家畜・作物の競合と配分。
- 種子不足時の同時PLANT全キャンセルと、合法な全体割当。
- actor phaseでは同turn購入資材を使えないこと。
- market内の先行売却収入で後続購入が可能になること。
- 土地購入後の作付・water、day 28以降は家畜生存を無条件に強制しないこと。

最終回帰試験には、6 actor時の家畜service budgetが2で、残り4 actorを非家畜仕事へ残すV3固有条件も含めた。成功判定はaction形状や非クラッシュではなく、engineの実状態変化まで確認した。

## Phase 2: 分離した学習対照

旧testは設計に使用済みなので全てdiagnostic developmentとし、checkpoint選択にはvalidationだけを使った。

Arm Aは入力、対象、split、decoder、architectureをRound6から変えず、最大50 epoch・patience 5で訓練時間だけを延長した。最初の `arm_a_extended` はbatch RNGを初期化後に再始動する再現性バグがあり除外した。修正版 `arm_a_extended_v1` は全headでRound6 epoch 10の全arrayとmax absolute difference 0.0を確認してから継続した。

| head | train rows | best epoch | updates | parameters | validation accuracy | old-test accuracy |
|---|---:|---:|---:|---:|---:|---:|
| actor token | 579,777 | 38 | 12,212 | 43,436 | 81.99% | 81.77% |
| market token | 359,837 | 13 | 3,168 | 26,806 | 79.53% | 79.57% |
| actor quantity | 25,093 | 49 | 650 | 30,683 | 82.41% | 82.54% |
| market quantity | 125,060 | 50 | 3,100 | 21,496 | 73.05% | 73.22% |

総parameterは122,421。actor quantityとmarket quantityは上限近くまで改善しており、Round6の最大10 epochでは学習不足を除外できなかったことを確認した。

Arm Bはデータ・入力・decoder・訓練条件を固定し、2 hidden layerへ容量だけを変更した。単一の事前固定seedで、best-of-seeds選択はしていない。

| head | architecture | best epoch | updates | parameters | validation accuracy | old-test accuracy |
|---|---|---:|---:|---:|---:|---:|
| actor token | 407-128-64-44 | 30 | 9,940 | 63,340 | 83.89% | 83.53% |
| market token | 256-128-64-22 | 16 | 3,696 | 42,582 | 81.20% | 81.45% |
| actor quantity | 451-96-48-27 | 33 | 494 | 49,371 | 83.14% | 83.59% |
| market quantity | 278-96-48-56 | 40 | 2,790 | 34,184 | 78.13% | 78.49% |

総parameterは189,477。old-testの数量一致率はactorの1が98.27%、2以上が72.88%、10以上が5.56%、15以上が16.67%。marketは1が97.89%、2以上が59.88%、10以上が25.19%、15以上が11.08%である。容量増加は平均指標を改善したが、多量数量を解決していない。

Arm Cは予測済みactorの操作・数量・既知資源をledgerへ反映し、次actorの合法残量とmarket orderingを扱う独立変更である。Arm B+ledgerはday1にWHEAT 2を持った後もWESTを選びFEEDを完了しなかった。数量制約だけでは核心を解消しない反例になったため、この段階で大量対戦は行わなかった。

## Phase 3: task-completion executor

学習済み全行動出力が家畜関連のPICKUP/PLACE/BUY/FEED/CARE/COLLECTを出した時だけfarm-level goalを起動し、毎turnの観測からactorを再割当する。worker indexを日跨ぎ恒久IDにはしていない。feed、care、初回以降の回収、倉庫への運搬、売却を完了条件に含め、家畜不在・前提破綻・day 28以降で中断する。

V2 pilot後、家畜作業が全workerを消費してcrop/land方策を抑えることが分かった。V3では2 actor以下は全員、それより大きいfarmは概ね3分の1だけを同時に家畜serviceへ使う変更だけを加えた。これはV2 pilot後の開発変更であり、V2 pilot前のpreregistered変更ではない。V3の総介入数が必ず減ったわけではなく、同時占有数を制限した結果としてcrop/land/cashが改善した。

このexecutorは学習されたtask planではなく、検証可能な明示的executorである。独立全行動BC研究はArm A/Bとして残したが、最終V3の向上を独立BCの向上とは数えない。

## Prefix、pilot、48戦評価

prefix診断は4つの異なる教師episode、両seat、prefix 48/192/384/96、horizon 24/48/96/192で実施した。候補memoryはprefix以前の利用可能観測だけでwarm upし、その出力は捨てた。分岐後の相手は保存action tapeで非反応型なのでDAggerとは呼ばず、候補自身のwarm-up行動から到達可能なstateとも主張しない。現金差は順に+50、+2,178、-12,775、-6,740で、長いhorizonでは作物・土地基盤がなお崩れた。

normal-start V3 pilotは事前固定2 seed×両seat×v122/v124の8戦で、v123を省略した。0勝0分8敗、平均自資金28,747.38、平均資金差-127,485.38だった。一方、初回生産・回収は8/8、土地拡張も8/8で成立し、48戦へ進める診断条件だけは満たした。

主開発48戦はseed `2026102201..2026102208`、両seat、3 anchorで除外なしに実施した。

| anchor | 勝-分-敗 | 平均自資金 | 平均資金差 | 点推定 | 片側95% Hoeffding下限 |
|---|---:|---:|---:|---:|---:|
| v122 | 0-0-16 | 16,185.81 | -137,239.69 | 0% | 0% |
| v123 | 0-0-16 | 16,185.81 | -137,239.69 | 0% | 0% |
| v124 | 0-0-16 | 21,316.19 | -127,305.69 | 0% | 0% |

v122とv123はこの集合で全結果・資金が一致したため別表は維持するが、二つの独立戦略familyとは数えない。全体は0-0-48、平均自資金17,895.94、平均資金差-133,928.35。state 192平均は土地1.0、作物10.69、家畜4.5、終局平均は土地2.77、作物10.15、家畜6.75。土地取得42戦の初回取得record平均は285.45、平均有効FEEDは152.81、CAREは132.56、家畜退出は1.42で、runtime例外は0だった。

Round6 sequence BCに対して平均自資金+9,494.13、平均資金差+9,591.50、初回生産0相当の失敗から48/48、土地拡張19/48から42/48へ改善した。しかし公式資金による勝敗は全敗のままであり、将来レートや真の勝率は保証しない。

## 推論性能

engine/対戦processと分離したagent-only subprocessをseatごとにfresh起動し、保存観測719件ずつを測った。cold start最大0.3922秒、inference p50最大0.01854秒、p95 0.02712秒、p99 0.03192秒、最大0.04990秒、peak RSS最大129,740,800 bytes、runtime例外0だった。これはこの明記したbenchmark条件の実測であり、対戦全体の時間・memoryではない。

## 実施しなかったことと残る仮説

- sealed 32 seed、Kaggle新規提出、外部取得、qeinstein比較は実施していない。
- 新しい回復label収集、DAgger、GRU、PPO、大規模探索、複数training seedは実施していない。
- 新しい未使用教師episode群を最終確認用に開封していない。旧testはdiagnostic developmentのままである。
- V3はtask executor依存が強く、教師固定特徴上の模倣精度はむしろ低下する。学習器だけが目的保持を獲得した証拠ではない。
- 多量売却数量、crop/land維持、executor介入と学習方策の非整合が未解決である。
- Shop分岐試合は除外していない。公式engineの同seed・両seat結果をそのまま使用した。

昇格を見送る主因は統計的確度不足ではなく、観測された48/48敗である。sealed 192戦を追加して確度だけを上げる合理性はない。次は未使用testを消費せず、学習されたtask stateまたは短い検証済みplan label、market大数量の構造出力、非家畜生産基盤との資源配分を開発集合で改善すべきである。

## 成果物案内

- `FINAL_STATUS.json`: 実装、研究改善、昇格の機械可読な分離。
- `RESUME.md`: 次回の安全な再開点。
- `REPRODUCE.md`: 実行コマンド。
- `phase0/`: 実物inventory、無給餌trace、data contract。
- `minimal_fixtures/engine_contracts.json`: engine前後状態を含む最小試験。
- `models/`: 全headの重み、設定、学習曲線、confusion、数量階層。
- `arm_b_plan_v3_runtime_validation.json`: 公式loader、fresh reload、day1 trace。
- `arm_b_plan_v3_stage_audit.json`: raw/decode・補正・finalのmetricsと学習重み利用hash。
- `prefix_diagnostics_arm_b_plan_v3/`: 4 prefixのreplayと結果。
- `pilot_arm_b_plan_v3/` と `development_evaluation_arm_b_plan_v3/`: 全CSV、生replay、診断trace、Shop履歴、hash。
- `ARTIFACT_SHA256.json` と `EVIDENCE_BUNDLE_SHA256.json`: 最終化時に生成する全hash一覧と証拠bundle identity。

