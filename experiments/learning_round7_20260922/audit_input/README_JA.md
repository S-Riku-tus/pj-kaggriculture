# Round6 独立監査・Round7引継ぎセット

## 最初に読むファイル

`Kaggriculture_Round6_Independent_Audit_JA.md`は分析結果、`Codex_Round7_Instructions_JA.md`は新しいCodexスレッドへ渡す全文プロンプトである。

`evidence/`には保存replayの再集計と検証表を収録した。元のユーザーZIPや大量の教師NPYは重複同梱していない。本パッケージは新しい提出エージェントではない。新規学習・モデル推論・新規対戦は実施していない。

## 再集計

Python、pandas、numpyが必要。ユーザー提供ZIPを展開した`learning_round6_20260922`フォルダを第1引数に渡す。

```bash
python evidence/audit_round6.py /path/to/learning_round6_20260922 /path/to/new_audit_output
```

スクリプトは保存済み144replayの読み込みを行う。モデル配列は寸法・クラス順を確認するために読むだけで、モデル推論は行わない。学習時の実コードと提出tar.gzが入力ZIPにないため、それらの再現試験とは異なる。

`build_summary.py`は同じディレクトリの既存監査CSV/JSONから要約を再生成する。継続replayとruntimeの追加照合JSON、および個別事例JSONは別途保存した監査成果物であり、主スクリプトだけで全ての追加ファイルが作られるわけではない。

## 解釈上の注意

action_countsは要求数であり実行成功数ではない。snapshotのstepは保存状態index。個別事例ではrecord tのactionがstate t-1を入力にstate tを生む。animal-daysは保存各状態の配置家畜数を24で割った積算。seed book costは種子購入価格による診断的簿価であり終局スコアへ加算しない。v122/v123の結果同一性は確認したが、このセットは全行動列同一性の証明を含まない。

公開公式コードは閲覧時masterであり、固定ローカルengineのbytesと同一だと保証していない。ローダー・ソース・教師splitの再現性の不足は監査本文と次回プロンプトに明記した。
