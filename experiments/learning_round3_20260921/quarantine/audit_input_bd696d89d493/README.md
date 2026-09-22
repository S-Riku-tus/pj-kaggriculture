# Round2 独立監査の証拠と再現方法

このZIPには、監査報告、Codex修正依頼、独立集計/モデル入力診断/状態遷移/アーカイブローダー試験の結果とスクリプトが入っています。提出用エージェントは含めていません。元の入力ZIPは別途必要です。

`audit_manifest.json` は元ZIPのhash、実行環境、検証範囲、結果ファイルのhashを記録しています。256件の保存リプレイの再検算と、新しくゲームを対戦させることは異なります。本監査で新規閉ループ対戦は実施していません。

## 実行

Python 3.12以上、NumPy、pandasが必要です。本監査時はPython 3.13.5 / NumPy 2.3.5 / pandas 2.2.3でした。これらは**監査・学習側**の依存性であり、提出用コードの依存性要件ではありません。

```text
python -m pip install numpy pandas
python run_audit.py --input /path/to/learning_round2_20260921.zip --output /path/to/new_audit_output
```

Windowsでは各パスをWindowsのパスへ置き換えてください。既に展開済みなら、`--input`へ`REPORT_JA.md`を含むディレクトリを指定できます。大量の保存リプレイを読むため、十分なディスク容量とメモリを確保してください。

`--skip-full-integrity`は256件全方式の整合性検査だけを省略します。他の診断もB2/A2のリプレイを読みます。Kaggleへの通信、提出、課金、追加学習、新規ゲーム対戦はしません。

`results/`は本監査時の実測結果です。portable版スクリプトは元の監査スクリプトの入出力パスを環境変数へ変更したものです。portable版の構文検査とsmoke検査を実施していますが、全処理をportable版からもう一度実行したわけではありません。

## 重要な読み方

- `a2_normalization_ablation.csv`は凍結モデルに同じ候補を入力した診断であり、変更後モデルの実戦成績ではありません。
- `b2_metrics_by_horizon.csv`は添付のtarget別指標を件数加重したものです。欠けている全feature配列を再生成して計算した予測ではありません。
- `loader_probe.json`は空globals/最後のcallable選択という公式loaderと同じ中核操作の隔離試験です。固定版Kaggleの全実行環境をここで再現したという意味ではありません。
- オンラインへ実際に提出されたfixed_v3アーカイブとそのオンライン対戦ログは今回の入力で確認できませんでした。オンライン成績の個別原因まで確定したとは扱わないでください。
