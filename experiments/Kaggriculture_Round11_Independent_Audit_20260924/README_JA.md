# Round11独立監査の成果物

最初に `REPORT_JA.md` を読む。次のCodexへの依頼には `CODEX_ROUND12_PROMPT_JA.md` をそのまま使用できる。

## 内容と範囲

本bundleには独立再集計、診断実験の行動トレース、実行用スクリプトを含める。提出用の新規エージェントtarではない。B1を置き換えるものではない。

元の大量リプレイ、公開エージェント本体、C++エンジン、Pythonバイナリは再同梱しない。再実行にはユーザーが提供したRound11 execution、Research Revision、B1の入力ファイルを併用する。元の入力SHA256は `INPUTS.json` に記録した。コンパイル済みの共有ライブラリはこのbundleに含めていない。

今回完走した反応型の追加実行は212試合。16試合の初期診断と拡大192試合には4セルの重複があり、台帳検査4試合も同じ条件の再実行である。独立した212世界を意味しない。新規の未使用seedや未知相手によるholdoutではない。元の876本の保存行動再生は、この212試合とは別枠である。

## 再実行

Python、numpy、pandas、orjson、およびResearch Revisionの `kagsim` を使用する。こちらではPython3.13で実行した。既存のWindows環境では、リポジトリのC++ビルド手順に従って同じエンジンをimportできる状態にする。

以下の変数を実際の展開先に合わせる。`B1_MAIN` はB1アーカイブの `main.py` そのものである。元出力を上書きしないように、新しい `OUT` を用意する。

```bash
R=/path/to/round11_execution_20260924
REV=/path/to/Kaggriculture_Round11_Research_Revision_20260924
B1_MAIN=/path/to/round10_20260924_b1_herd_safe/main.py
BUNDLE=/path/to/Kaggriculture_Round11_Independent_Audit_20260924
OUT=/path/to/fresh_reproduction
mkdir -p "$OUT"

python "$BUNDLE/scripts/audit_saved.py" \
  --workspace "$R" --engine-dir "$REV/engine_cppsim" --out "$OUT" --workers 4
python "$BUNDLE/scripts/summarize_pairs.py" \
  --workspace "$R" --out "$OUT"
python "$BUNDLE/scripts/probe_cw1.py" \
  --workspace "$R" --out "$OUT/cw1_call_chain_probe.json"
python "$BUNDLE/scripts/probe_b1_equivalence.py" \
  --workspace "$R" --b1 "$B1_MAIN" --out "$OUT/b1_cw1_equivalence_recheck.json"

python "$BUNDLE/scripts/reactive_diagnostics.py" \
  --workspace "$R" --revision "$REV" --b1 "$B1_MAIN" --out "$OUT"
python "$BUNDLE/scripts/evaluate_alt_consensus.py" \
  --workspace "$R" --revision "$REV" --b1 "$B1_MAIN" --out "$OUT"
```

台帳検査では、元エンジンに存在する品目別約定カウンタを公開するbindingだけを追加する。次のスクリプトはLinuxのg++を使用する。`--headers` はpybind11のincludeディレクトリにする。今回の環境ではTorch同梱のpybind11ヘッダーを使用したが、そのヘッダーやバイナリは配布していない。

```bash
python "$BUNDLE/scripts/build_ledger_binding.py" \
  --engine-dir "$REV/engine_cppsim" --headers /path/to/pybind11/include
python "$BUNDLE/scripts/audit_runtime_ledger.py" \
  --workspace "$R" --revision "$REV" --b1 "$B1_MAIN" \
  --out "$OUT/runtime_ledger_audit.json"
python "$BUNDLE/scripts/postprocess_diagnostics.py" \
  --workspace "$R" --evidence "$OUT"
```

最初の8基準再実行の `saved_action_mismatch` と `saved_observation_mismatch` が0になることを確認する。台帳検査の終局資金も原記録と比較する。異なるPythonやコンパイラで差が出る場合は、同じ結果と断定せず差を保存する。

## 証拠の読み方

`independent_replay_audit` は保存行動の再生であり、エージェントの新規対戦ではない。`probe_*` は保存観測を与えるteacher-forced検査である。`reactive_*` と `alt_consensus_*` は双方の実方策を現在観測から呼ぶ反応型の実行である。

`reactive_initial_traces` と `reactive_consensus_traces` は、719段階の両者の最終行動、資金、価格、市場在庫、倉庫を保存したコンパクト形式である。Kaggleの全観測付きリプレイ形式ではない。ファイルのハッシュは各実行のJSONに記録した。初期実験と拡大実験は別ディレクトリで保存し、同じセルを再実行しても上書きしない。

プロファイルのreturnログには、最終出力でない一時的な候補・参照用tapeの戻り値も含む。全returnをそのまま「最終行動を順番に上書きした履歴」と解釈しない。最終action、対象関数、前後の状態を併せて確認する。

paired CSVの `first_shop_change` は街のshop状態の初回差分を意味し、市場注文の初回差分ではない。市場注文差は `own_market_changed_decisions`、代表的な最初の差分は `first_difference` を参照する。

bootstrapは24 seedを単位にし、各seedの4相手・両seatを一緒に再標本化する。Monte Carloの分位点は離散分布の境界で僅かに変わり得るため、厳密畳み込みによる値も同梱した。異なるsource-familyへの一般化区間ではない。

## 出力の検証

`FINAL_MANIFEST.json` は、manifest自身を除く同梱ファイルのSHA256とサイズを記録する。結果の要約は `EXECUTION_SCOPE.json`、入力の同一性は `INPUTS.json` を参照する。全ての解析で用いた元ファイルをこのZIPだけから復元できるという意味ではない。
