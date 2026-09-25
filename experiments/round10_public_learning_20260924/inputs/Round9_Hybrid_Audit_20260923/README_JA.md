# Round9監査・Round10実装依頼パッケージ

## 先に読むもの

`ANALYSIS_JA.md` が分析本体。`CODEX_ROUND10_PROMPT_JA.md` は新しいCodexスレッドに入力する自己完結した依頼文。`evidence/EVIDENCE_INDEX_JA.md` は数値と出典の索引。

このパッケージは分析資料であり、新しい提出agentではない。元の191MB ZIPやポケモンのnative binary、モデル重みを重複同梱していない。新規学習・新規対戦・提出は行っていない。保存モデルの独立推論と保存対戦の監査は行った。

## 再計算する場合

Python3.11以上（hashlib.file_digest使用）、NumPy、pandas、orjsonが必要。環境ごとの差異を避けるため、同梱した `audit_environment.json` も参照する。

元Round9 ZIPを安全に展開した実験ルートを `ROUND9_ROOT` に、元ZIPを `ROUND9_ZIP` に、再計算結果の出力先を `AUDIT_EVIDENCE` に設定する。上書きを避けるため新しい出力ディレクトリを推奨する。NumPy配列はZIPから直接読む。少なくともモデル/metadata/provenance/CSV/replay/diagnosticsは展開が必要。

bashの例（各パスは自分の保存場所に置き換える）：

```bash
export ROUND9_ROOT="/path/to/round9_teacher_reproduction_and_closed_loop_bc_20260923"
export ROUND9_ZIP="/path/to/round9_teacher_reproduction_and_closed_loop_bc_20260923.zip"
export AUDIT_EVIDENCE="/path/to/recomputed_evidence"
mkdir -p "$AUDIT_EVIDENCE"
python scripts/audit_models.py
BATCH=small PANELS=development_panel_a0,development_panel_a1,development_panel_a1_v2,development_panel_a2,development_panel_a2_v2,development_panel_a2_v3 python scripts/audit_replays.py
BATCH=old64 PANELS=development_panel_a2_expanded64 python scripts/audit_replays.py
BATCH=final64 PANELS=development_panel_a2_v2_expanded64 python scripts/audit_replays.py
python scripts/audit_diagnostics.py
python scripts/aggregate_audit.py
```

PowerShellでは `export NAME=...` の代わりに `$env:NAME="..."` を使い、BATCH/PANELSも各呼び出し前に設定する。

`audit_replays.py` は固定のRound9ファイル配置と記録schemaに合わせた監査用コード。CSVが保存している元Windowsパスは実験ルート名以下へ写像する。別のRound/別schemaへそのまま流用しない。

`aggregate_audit.py` は3バッチの検証CSVと最終64試合のスナップショットを結合する。全件一括のBATCH=allにも対応するが、v2/v3全steps同値の追加チェックはBATCH=smallで行う。途中でSTART/ENDを使う場合はバッチ上書きによる欠落に注意する。

再計算スクリプトは新規ゲームや学習を行わない。`key_summary.json` や本文は監査時点の固定記録であり、別データで再計算した結果に自動追随するダッシュボードではない。

## 検証の制限

最終A2 source/提出tarと固定engineは今回の元ZIPに存在せず、最終A2コードの全行検査やengineでの再試合はできていない。ソース由来、保存報告、独立再計算を区別する。v3のゲーム証拠は8試合、64試合はv2。旧testは既に開発に使用済み。
