# Kaggriculture Round3 監査資料

## 読む順序

1. `Kaggriculture_Round3_Independent_Audit_JA.md` — 分析の全体像、実不具合、判断軸の再設計。
2. `Codex_Round4_Instructions_JA.md` — そのまま新しいCodexスレッドへ渡せる実装依頼。
3. `audit_run_summary.json` と各JSON/CSV — 独立再集計と再現試験の機械可読な証拠。

`source_evidence/` は添付からコピーした原資料の一部であり、監査側で内容を修正していません。16本の大きなリプレイは重複同梱していないため、再現には元の `learning_round3_20260921.zip` が必要です。

## 最も重要な区別

- Round3では新しい学習・モデル推論・Kaggle提出を実行していません。
- 保存された現行probeの終局資金差は、負または0で整合しています。
- ただし収穫・給餌・復帰が意図どおり成立していません。
- 人工入力テストは判定コードの固定値を示すもので、実対戦で利益が出た証拠ではありません。
- `all_original_findings_reproduced=true` は「元の不具合を再現できた」の意味です。「修正版が正常」「強いagentができた」という意味ではありません。

## 再現方法

Python 3.9以上、標準ライブラリのみで動きます。ネットワーク・Kaggle CLI・機械学習ライブラリ・シミュレータのインストールは不要です。

```bash
python run_audit.py --input "path/to/learning_round3_20260921.zip" --output "round3_reproduced"
```

新しい出力先を使ってください。既存出力を明示的に置き換える場合のみ `--overwrite` を付けます。元ZIPは一時ディレクトリへ展開し、変更しません。

この監査は入力ZIP内の `contracts.py` をimportし、実ソースから選んだ関数を実行します。信頼できる元のユーザーZIP以外を入力しないでください。任意の未知ZIPに対するサンドボックスではありません。特定のRound3ソースを前提にした再現試験なので、修正後の別版では判定が変わるのが正常です。

元ZIP SHA-256：

```text
51f5625762895a782f34989dd2db32f1d09343ff6ff49704695254e4f1d8e870
```

## スクリプト

- `audit_replays.py`：16保存対戦のhash・終局値・C0との行動差分・初回分岐後の状態推移。
- `audit_source_and_contracts.py`：実観測へ実関数を適用し、未成熟収穫・重複給餌・復帰契約を再現。manifest照合。
- `test_report_literals.py`：一時コピーの正例・ERROR例による、報告判定の固定値検査。新規対戦ではありません。
- `run_audit.py`：安全な展開、上記3本の起動、ログと総括の保存。

個別スクリプトは `ROUND3_DIR` と `AUDIT_OUTPUT_DIR` 環境変数を使います。通常はラッパーを使用してください。

## 実施していないこと

修正版の新規engine rollout、新規訓練、最新トップ本人の新規リプレイ大量取得、オンライン提出・レート測定は行っていません。公開ルールをWebで照合しましたが、公開masterと元固定実行環境がbyte-identicalと証明したわけではありません。
