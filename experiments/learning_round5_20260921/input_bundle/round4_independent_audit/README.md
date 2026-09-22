# Round4独立監査パッケージ

最初に `Kaggriculture_Round4_Independent_Audit_JA.md` を読み、次の実装には `Codex_Round5_Instructions_JA.md` を使用する。

今回行ったのは保存16リプレイ・報告値・manifestの独立再集計であり、新規対戦・モデル実行・再学習・Kaggle提出ではない。入力ZIPにRound4の新規ソース、モデル、最終提出archiveの実物は含まれていなかった。

## 再現

Python標準ライブラリのみ。

```bash
python audit_round4.py learning_round4_20260921.zip --out ./audit_output
```

元のZIPはユーザーが添付したものを使用する。このbundleには元ZIPや16本の元リプレイ全体は複製していない。監査コードは元ZIPを安全な一時ディレクトリへ展開し、保存記録から集計する。

## 主な証拠

- `audit_summary.json`：独立再計算の主要数値。
- `replay_integrity.json`：16本のhash、資金、seed、終局状態の照合。
- `replay_summary.csv/json`：各試合の資金と行動件数。
- `paired_decomposition.csv/json`：自分・相手・marginと店舗系列の差。
- `duplicate_harvests.json`：後続actor144回の取得量0の収穫。
- `animal_lifecycle.json`：家畜38配置/35消失。
- `animal_harvest_opportunities.json`：収量が正の家畜上で行動した観測。全件がミスという意味ではない。
- `opening_finance.json`：序盤の全joint actionと資金・小麦状態。
- `round5_regression_fixtures.json`：実ログから抽出した5局面。
- `attachment_manifest_audit.json`：入力で実物が確認できた証拠と欠落。

record kは、observation k−1から実行したactionと結果observation kを保存する。dayはengineの0始まり。fixtureは観測の抜粋であり、完全engine checkpointではない。反実仮想の継続には全状態復元または正しいprefix再生が必要。

`bundle_manifest.json`はこの監査bundle内のファイルのhash台帳。元agentの提出manifestではない。
