# Kaggriculture Round3 実装・評価報告

## 結論

Round3では比較・提出基盤、実行契約、正規化/support拒否、step264市場評価器、限定的な複数ターン候補を実装し、単体試験と実ゲーム閉ループまで実行した。しかし、新しい昇格候補は得られなかった。`PROMOTABLE=false` であり、Round3のprobe archiveを強化版として提出してはいけない。Kaggle提出は実施していない。

## 入力と基準版

- 指定された監査ZIPの実SHA-256は `bd696d89d4937f1e6031baa6f6110bc28ee854a5c7785dfe0da8ffa3e76acc2f` で、指定値 `cd94e3ade1a7bd0072e7e7db688ee32685059d0fc66be62acb93fbe7d3a57220` と一致しなかった。内容はread-only quarantineへ展開し、診断補助にのみ使った。
- 既知の提出成功版 fixed_v3 は発見され、SHA-256 `f1aede2a9f4a8ad0b8f3b3cd41d1f49708b713ca1cbc4221df472dcba1201105` が既知値と一致した。
- C0 identity artifactは元C0とbyte-identical（`472eb013183d4d7bc320fb25532ace0d6ab6d2af46d914e0ae158486f39e8452`）。公式 `get_last_callable`、空globals、repo外cwd、archive実行時NumPy遮断で最後のcallableが `agent` になり、720状態を `DONE/DONE` で完走した。
- 棄却した最終probeも実archiveから公式loaderで `agent` が選択され、4状態smoke testを完走した。これは提出適格性ではなくserialization/loaderだけの証拠である。

## P1: 壊さない実行契約

- actor identity/day epoch、必要資材・現金・shed容量・期限、完全continuation、安全なrejoin境界、postcondition、abort/replanを明示する契約を追加した。
- 最終joint actionに対し、他作業者を含むPICKUP/PLACE/DROP、予約二重使用、shed容量、market slotを検査する。
- 小麦PICKUP消失、給餌予約、NORTH消失後の古い経路復帰、将来資材DROP、複数作業者競合、日付境界/index再利用を汎用fixtureで検査した。試験結果は `EXECUTOR_CONTRACT_TESTS.json` のとおり `True`。
- A2の56行/530特徴を型付き監査し、定数次元 230、旧scale≦0.00101の次元 245、正の非KEEP教師 0 を確認した。結論は `NO_POSITIVE_CANDIDATE_SUPPORT`。二値特徴を微小stdで割らず、未知job・定数binary変化・範囲外・nonfinite・model欠損はKEEPまたは安全replanにする。

## P2: step264の分解

固定エンジンと同じlockstep市場処理を実装し、価格floor、SELL/BUY_PRODUCT、資金依存注文、slot順を試験した。32条件の同一状態・同一2候補で、現予測は修正評価器でも32/32逆順を選び、ordered oracle regretは合計 5452、平均 170.375。正確な数量・順序oracleは32/32でC0順を維持し、正のoracle headroomは 0 条件だった。従って評価器だけの修正では足りず、この2順序候補集合の大型化は停止した。

## P3: 候補生成と閉ループ

固定時刻2点ではなくstep 192〜599を走査し、13056状態、384候補、33時刻、10日、4 familyを得た。経済評価は観察済みRound2条件の一部をdevelopmentとして使い、holdoutとは呼んでいない。

- `FEED_REFILL_DAY_BOUNDARY`: 4ゲームすべて悪化、平均margin差 -1089。作業者を日末まで所有する機会費用が大きく棄却。
- `HARVEST_DELIVER_DAY_BOUNDARY`: 4ゲームで差0、`SAFE_NO_EFFECT`。実行成功を経済改善とは数えていない。
- 次の候補生成として `FEED_ONCE_STATE_REPLAN` を実装。小麦1個→最寄り給餌→`fed_today`確認で状態ベース復帰に狭めたが、4ゲームすべて悪化、平均margin差 -87（qeinstein -136/-136、smart_farm -32/-44）。

両seatは独立試行として水増しせず、family×seedクラスタ内の感度として `P3_SCOPE_RESULTS.json` に併記した。正の完遂候補が0なので、selector学習は実施していない。学習済みと称するmodelも作成していない。未使用条件による最終評価は経済gate不合格のため未実施である。

## 悪化・未確認・次の一手

給餌候補は安全に完遂してもC0より悪かった。収穫納品候補は無効果だった。新しい学習モデル、変換前後誤差、閾値付近選択、未使用holdout、Kaggleレート効果は未確認（学習を開始する正例がなかったため非該当または未実施）。

次は、単発の追加サービスではなく、同一prefixから「給餌→産物回収→倉庫/販売→再投資」まで終端価値を持つ有限候補を生成し、C0 rolloutを保持したpaired continuationでoracle headroomを先に測る。正のoracle候補が得られた場合だけ、episode/family/version/day帯/jobで分割した低容量順位モデルを学習する。既知32条件と今回の4開発ゲームを未使用holdoutへ戻してはならない。
