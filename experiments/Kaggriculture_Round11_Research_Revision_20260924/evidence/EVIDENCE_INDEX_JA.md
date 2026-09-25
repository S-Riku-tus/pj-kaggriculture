# 証拠索引

数値の意味と確認範囲は REPORT_JA.md と EXECUTION_SCOPE.json を参照する。

| 主張・検査 | 保存証拠 | 確認範囲 |
|---|---|---|
| 128の新規対戦条件、4方式の比較 | development_protocol.json / development_results.json / development_game_results.csv | 4seed×4相手×両seat×4方式。開発用・反応する相手・C++版 |
| 勝敗の変化、同値・不発火 | development_summary.json / development_paired_comparisons.csv | 元B1との同一相手・seed・seat比較。公式レートではない |
| 保存された各新規対戦の全行動・観測 | development_replays/*.json.gz | 上記128件。圧縮バイトhashはresultsとMANIFESTに保持 |
| 3実戦とC++版の一致 | cppsim_raw_parity_3.json | 全720状態×両seat×8項目。不一致0、万能な同値性保証ではない |
| 常時ゲート変更による農作業への間接影響 | gate_indirect_field_changes_example.json | 特定条件の観測と指令差。全損益の原因をこの一因に限定しない |
| 71実戦の床価格台帳 | online_extended_summary.json / online_floor_ledger_by_item.csv / online_floor_cases.csv | 自分の実売量・正解数量は前回監査済み約定表。相手の正解はオフラインのみ |
| 終端の在庫・種、固定価格注文 | online_terminal_raw_audit.csv / online_structural_order_check.json | 生産途中の廃棄ゼロや全支出最適性を意味しない |
| 作付け開始・4区画の用途 | online_first_crop_plant.csv / land_and_crop_route_check.json | d0が初日。4区画目を一律に未使用と判定しない |
| 異系統相手の敗戦112752873 | case_112752873_*decomposition.csv / case_112752873_growth_and_cash.csv | 収支・状態の記述的分解。生産変更の反実仮想ではない |
| 元Round10の実績と学習 | ../inputs/prior_audit/ / ../reference/ | 前回監査結果。今回新規に504対戦や学習を実行したわけではない |
| 外部情報 | ../SOURCE_MAP_JA.md / ../SOURCE_REGISTRY.json | 原作者報告・公開ミラー・未取得ソースを区別 |

保存ファイルの検証は `python scripts/verify_package.py`。公開71戦を再集計する場合は元のユーザー添付raw ZIPが別途必要である。新規128件のrawは本パッケージ内に存在する。
