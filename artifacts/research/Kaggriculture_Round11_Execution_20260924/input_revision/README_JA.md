# Round11 改訂研究パッケージ

2026-09-24／revision 2。前回のRound11プロンプトではなく、`CODEX_ROUND11_REVISED_PROMPT_JA.md`を使用する。旧版はreference/へ保存した参考記録であり、先に実行する必要はない。

## 最初に開くもの

| ファイル | 用途 |
|---|---|
| REPORT_JA.md | 新しい実戦再集計・128対戦・公開研究・結論 |
| CODEX_ROUND11_REVISED_PROMPT_JA.md | 新しいCodexスレッドへ渡す自己完結の依頼文 |
| EXPERIMENT_PLAN_JA.md | 候補、対照、進め方、停止・採用判断 |
| CHECKLIST_JA.md | 実物・因果比較・学習・提出互換性の確認 |
| SOURCE_MAP_JA.md / SOURCE_REGISTRY.json | 原典、保存版、確認できた範囲と未確認部分 |
| evidence/ | 新しい計算結果、128対戦リプレイ、対応比較 |
| inputs/ / engine_cppsim/ | 使用した無変更の4agent・前回の約定表・添付由来のC++ソース |
| scripts/ | 移植可能な再計算スクリプト。executed/には実際に実行した版も保存 |
| MANIFEST.json | ファイル単位のSHA-256 |

今回新規に保存・確認した対戦は128ユニーク条件。新規学習0・Kaggle提出0。公式Pythonランタイムでの新規全ゲーム0。添付cppsimを実戦3軌跡で照合してから使用した。

公開71戦の原raw ZIPは容量重複を避けるため本ZIPには再同梱していない。再計算には元の`round10_b1_herd_safe_submission_56509493(1).zip`を使用する。新規128対戦のrawとその4agentは同梱済みである。新しい公開候補の完成ソースを全て同梱しているわけではない。

## 保存結果の検証

```bash
python scripts/verify_package.py
```

## raw 71戦の追加分析を再計算

`orjson`が必要。自分の実売量・相手の正解数量には同梱の前回検算済み約定表を使用する。

```bash
python scripts/expanded_online.py --battle-zip "/path/to/round10_b1_herd_safe_submission_56509493(1).zip"
```

## 3実戦の環境一致／128開発対戦を再実行

Python/C++コンパイラとpybind11等のビルド依存が必要。`engine_cppsim/README.md`と`pyproject.toml`を確認する。この作業はローカルであり、Kaggleへ自動提出しない。

```bash
python -m pip install ./engine_cppsim
python scripts/parity_smoke.py --battle-zip "/path/to/round10_b1_herd_safe_submission_56509493(1).zip"
```

Linux/macOSでは別出力先を明示する。

```bash
export R11_OUTPUT="$PWD/recomputed_evidence"
python scripts/run_panel.py
python scripts/summarize_panel.py
```

PowerShellでは次のようにする。

```powershell
$env:R11_OUTPUT = Join-Path (Get-Location) "recomputed_evidence"
python scripts/run_panel.py
python scripts/summarize_panel.py
```

同じ出力先でコード・agent・engineを変更してキャッシュを再利用しない。保存証拠evidence/を上書きしない。実際に使った元スクリプトはscripts/executed/にあり、そこには今回環境の絶対パスが残る。通常の再実行にはscripts/直下を使う。

C++版の一致3試合は全状態での同値性保証ではない。新しい候補を採用する前に、Codex側で固定公式Python版と最終提出ローダーの比較も行う。
