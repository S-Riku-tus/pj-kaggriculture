# EXECUTION SCOPE

このサイクルだけの実行範囲を記す。過去Round10〜12の件数は合算しない。

| 種別 | 今回の件数 | 保存/備考 |
|---|---:|---|
| 新規反応型fullgame（構造化保存） | 192 | 4 arms × 6 opponents × 4 seeds × 2 seats。全replay保存、failure 0 |
| 新規反応型smoke（console診断のみ） | 7 | P-EARLY反復3、M1 1、P-ROTATE 1、diverse opponent baseline 2。raw replay未保存の制約をgeneration logへ明記 |
| 新規反応型fullgame合計 | 199 | fixed tapeを含まない |
| fixed-tape診断 | 0 | 実施なし |
| 部分市場評価 | 0 | 実施なし |
| 固定shop等の改造環境 | 0 | 実施なし |
| 独立holdout | 0 | 全候補が事前development gateを不通過 |
| 保存観測episode読込 | 129 | Round12 INDEXの全保存試合 |
| 保存観測のitem-state row | 208,980 | train 131,220 / val 25,920 / test 51,840 |
| 最終model test推論 | 153,664 | UNKNOWN label除外後、1/4/12 horizon合計 |
| 新規学習の完了実行 | 2 | 同じ決定的27-model fit。1回目はJSON integer-key比較でreload false、比較修正後の2回目はtrue。重みhashは同一 |
| 最終学習model | 27 | 9 products × 3 horizons、各5 epoch = 135 model-epoch |
| 計画selector学習 | 0 | 正のcandidateなし。候補生成へ戻す |
| official Python fullgame | 0 | 新規対戦なし |
| official Python仕様再確認 | 1 | version/file hash/git blob identity。Round12 parity 2件は再利用で今回件数へ不算入 |
| cppsim reactive fullgame | 199 | 上記panel + smoke |
| 新規ネットcode取得 | 0 | 既存source registry/opponent poolを再利用 |
| 公開competition page確認 | 1 | HTTP 200/titleのみ。規定本文は未認証shellで再取得不可 |
| Kaggle API/CLI認証アクセス | 0 | CLI credentialsなし |
| Kaggle提出 | 0 | ユーザー判断へ残した |
| 回帰テスト | 9 | 全pass |

学習の最初の完了実行で `reload_verified=false` だった原因は、in-memoryの整数hour bucket keyとJSONの文字列keyを直接比較したことだった。重み自体の不一致ではない。保存表現をJSON正規化して再実行し、最終artifactはreload一致した。

OpenSpielの未登録game warningは `kaggle_environments` import時の既知の周辺出力であり、Kaggriculture 192試合のfailureではない。
