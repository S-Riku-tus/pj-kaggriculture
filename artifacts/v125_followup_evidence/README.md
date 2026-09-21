# v125実戦監査パッケージ

## 読む順番

`report.md`：分析結果・前回案の修正点・次版方針。
`codex_prompt.md`：リポジトリ内で現行コードを監査し、次版を比較実装する指示。
`tables/`：実戦の集計表とケース記録。
`fixtures/`：元リプレイから抽出した既知失敗・農場一致・単一遷移市場実験。

このパッケージにv125/v126のエージェントソースは含まれません。次版の実装や勝率改善を完了したものではありません。

## 追加ダウンロードなしで動く検証

Python 3.9以降、標準ライブラリのみ。

```sh
python scripts/verify_fixtures.py
```

検証する内容は、元の対戦における新旧4試合の位置・所持品の不整合、4頭の退出、2試合31観測点の農場構造一致、3件の市場順序変更の即時効果（+96、−37、−31）です。

**PASSは元の不具合や実験値の再現に成功したという意味であり、エージェントを修正できたという意味ではありません。** `fixture_test_results.json`に今回の実行結果を保存しています。これは同一時点の相手行動を固定した限定試験で、相手の将来反応や終局勝率を計算しません。

## 表の定義

- `performance.csv`：提出別公開対戦。自己対戦検証を除外。レートは対戦CSVを時系列に並べた末尾。
- `opponent_rating_bands.csv`：対戦時の相手レートによる区分。自分のレートによる区分ではない。
- `implementation_comparison.csv`：v124、v125、添付上位3体の行動・作付け・転用の同一定義比較。
- `realized_sales_comparison.csv`：実売却単位の価格からの数量・売上・価格1の割合。Top3の既知不一致1件を除外。
- `same_game_cash_decomposition.csv`：同じ試合の自分−相手の収支。商品、対応する種・動物購入を集約。小麦の餌利用は動物へ内部配賦していない。因果的な利益推定ではない。
- `same_game_price_quantity_decomposition.csv`：正の販売量が両者にある場合の対称的な記述的分解。反実仮想の因果効果ではない。
- `identical_layout_service_comparison.csv`：2試合で構造・配置日が一致する農場の維持・施肥・販売比較。
- `action_similarity_and_pair_states.csv`：新しい各試合から旧版へ事後的な最近傍を取った行動類似度。コード同一性、paired試験の証拠ではない。
- `audit_provenance.json` / `audit_raw_discrepancies.json`：監査範囲、残差、制約。エラーは最大10件／リプレイまで保存された監査差分であり、全てがagentの失敗という意味ではない。

日付はd0始まり。JSON記録tの行動は観測t−1からtへ進める。31の農場比較点は初期、各日境界、最終記録719。作物・家畜の種類、座標、配置日が同じことと、完全状態が同じことは区別してください。

## 元の全ZIPから基礎監査を再計算する場合

`raw_audit/`に今回使用した記録状態再同期型の集計器を収録しています。依存は`orjson`、`pandas`、`numpy`。元のbattle_logs ZIPを、episodes.csv、manifest.csv、replay JSONを内包するZIPとして一つの入力フォルダへ置きます。今回のv125外側ZIPは内部のbattle_logs ZIPを取り出して使います。ファイル名にはsubmission_数値を含めます。metadata-onlyのleaderboard ZIPは入れません。

```sh
export KAGGRI_INPUT_DIR=/absolute/path/to/inner_battle_log_zips
export KAGGRI_OUTPUT_DIR=/absolute/path/to/new_work_directory
export KAGGRI_WORKERS=4
python scripts/raw_audit/analyze_replays.py
python scripts/raw_audit/summarize.py
python scripts/raw_audit/audit_replays.py
python scripts/raw_audit/enrich_metrics.py
python scripts/raw_audit/cohort_metrics.py
```

既存キャッシュは再利用されます。別データ・別監査版なら空の出力ディレクトリを指定してください。この監査器は標準10×10盤面・本資料の1.32.7リプレイの規則向けで、一般化された完全環境ではありません。移動・新規雇用後の位置を閉ループで継続しません。各遷移の現金・物資・作用監査に限定し、未知のagentのロールアウトに流用しないでください。

元の大容量リプレイはこのZIPへ再収録していません。基礎監査の入力にはユーザーの元添付が必要です。ケース検証だけなら同梱fixturesだけで動作します。

## 出典

一次データはユーザー添付のv125二提出、v124二提出、Top1=56216119、Top2=56361903、Top3=56354460。上位番号は9月20日スナップショット上の呼称で、現在順位ではありません。公式公開実装・READMEの参照URLはreport.md末尾に記載しています。
