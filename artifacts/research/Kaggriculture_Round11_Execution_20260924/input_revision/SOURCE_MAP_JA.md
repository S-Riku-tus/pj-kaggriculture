# 情報源台帳・新規性・確認範囲

調査日：2026年9月24日。公開保存版の取得日・原作者の実験日・今回読んだ日を区別する。今回、新しいライブLeaderboardの全行や、非公開上位方策のコードを取得したとは主張しない。

Kaggleの一部ページは本文取得に失敗したため、GitHubの固定commitに保存された原作者の説明を読んだ。保存版とKaggle現行版の完全同一性は未確認である。第三者の候補順位表は探索索引に限り、原作者本文・コード・自分の対戦で確かめる。

## 原典と役割

### S01 — Kaggle公式・固定エンジン

原典：https://github.com/Kaggle/kaggle-environments/blob/302d8e20c83822b8d4572975cdea1180b792b748/kaggle_environments/envs/kaggriculture/kaggriculture.py

確認状態：公式ソースの価格定数等を固定commitで読解。

使い道：市場、植物、生産、順序、設定の規範。ライブの全runtimeを取得したとは扱わない。

識別子：`Git blob 3c202c7ee921da239356789e266b694635103fc4`


### S02 — Kaggle公式Overview/Timeline

原典：https://www.kaggle.com/competitions/kaggriculture/overview/citation

確認状態：公式本文取得。

使い道：最終提出2026-09-30、勝敗評価。相対表示の残り日数ではなく絶対日付を読む。


### S03 — More Wheat, Smarter Sales

原典：https://www.kaggle.com/code/dmitriigluzdov/kaggriculture-more-wheat-smarter-sales

実際に参照した保存版／本体所在：https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/refresh_20260923T001052Z/extracted/dmitriigluzdov__kaggriculture-more-wheat-smarter-sales.md

確認状態：原作者Markdownの公開保存版を全文読解。今回その完成方策は実行していない。

使い道：近い3軌跡まで残す相手売却予測。原作者55対戦、25対応比較中5改善0悪化は作者報告。

識別子：`Markdown Git blob 0004f025b2a6e01a90876773f51f796c08edb4c1`


### S04 — Order Book v3 Response Improvement

原典：https://www.kaggle.com/code/arsgorynich/order-book-v3-response-improvement

実際に参照した保存版／本体所在：https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/extracted/arsgorynich__order-book-v3-response-improvement.md

確認状態：原作者Markdown・掲載された追加コードを読解。独立派生版であり元作者の公式v3ではない。

使い道：相手も最終並べ替えをすることへの一段の応答。掲載原版をB1上で丸ごと再現したわけではない。

識別子：`Markdown Git blob f147ffdaf2f844c8f0480452eb109826a4af6298`


### S05 — The Moon Counts Melons

原典：https://www.kaggle.com/code/prvsiyan/kaggriculture-frontier-the-moon-counts-melons

実際に参照した保存版／本体所在：https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/refresh_20260923T001052Z/extracted/prvsiyan__kaggriculture-frontier-the-moon-counts-melons.md

確認状態：保存版の過去実験と最新section28を読解。作者の1008対戦を再実行していない。

使い道：最終注文列の最適化。前身比較のseed区間が0に接すること、正確な履歴に直しても悪化した反例。

識別子：`Markdown Git blob d6bea6aee5b6a6e4731192b7abe4958339ba6d2f; 記載された本体SHA256 178ae0f727641cf4b618ebb98ade7aa1a1bed7517281aab9849de82a59d8ed3a`


### S06 — Floor-aware Market Ledger

原典：https://www.kaggle.com/code/prvsiyan/kaggriculture-floor-aware-market-ledger-20260923

実際に参照した保存版／本体所在：https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/refresh_20260923T001052Z/extracted/prvsiyan__kaggriculture-floor-aware-market-ledger-20260923.md

確認状態：原作者保存版全文を読解。数式を今回の71実戦へ独立適用。

使い道：価格床の観測打切り。作者560対戦の方策悪化は今回の対戦数に加えない。

識別子：`Markdown Git blob 7e4bcdde4a32ca809e02ae00dcf9360d63755b6a`


### S07 — v15stack submit / notebook

原典：https://www.kaggle.com/code/wzhengbiao/kaggriculture-v15stack-submit

実際に参照した保存版／本体所在：https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/refresh_20260923T001052Z/decoded/kaggriculture-v15stack-submit__d6565929be52.py

確認状態：公開研究の候補台帳・機能レビュー・回収済み本体の所在を確認。本体全体の再取得・実行は未実施。

使い道：完成方策の比較候補。scriptとnotebookの同一payloadを二重計数しない。

識別子：`台帳記載の本体SHA256 d6565929be5283a5decf00c986359542ee1c106d7819815f8c69ccab35e363dd`


### S08 — A Wonderful Life

原典：https://www.kaggle.com/code/hanifnoerrofiq/a-wonderful-life

実際に参照した保存版／本体所在：https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/extracted/hanifnoerrofiq__a-wonderful-life.md

確認状態：候補台帳と説明抽出ファイルを確認。説明ファイルは空。実行コードの独立確認は次工程。

使い道：完成方策候補。タイトル・掲載スコア・EarlyCycle説明だけからB1より強いとしない。


### S09 — Pipe18 Six Layers

原典：https://www.kaggle.com/code/nathanjacob/kaggriculture-pipe18-six-layers

実際に参照した保存版／本体所在：https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/extracted/nathanjacob__kaggriculture-pipe18-six-layers.md

確認状態：原作者保存説明を読解。原版の650対戦を再実行していない。

使い道：差分抽出→単独比較→組合せ比較。E402/E410等はB1に実装済みであり新機能として再導入しない。

識別子：`Markdown Git blob aaa6fd421682ca5414fcbc0f9fbb346af2e9ba2b`


### S10 — The 2965 Master Hybrid Engine

原典：https://www.kaggle.com/code/haideptry/the-2965-master-hybrid-engine

実際に参照した保存版／本体所在：https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/extracted/haideptry__the-2965-master-hybrid-engine.md

確認状態：原作者保存説明を読解。宣伝的な勝率表を独立検証していない。

使い道：完成方策と余剰資材削減の比較候補。B1の実戦に大きな終盤種浪費があるという根拠にはならない。

識別子：`説明内本体SHA256 93831c18a43c49312a71fa67171224681c52c3fade0259403e8d8fae7973565f`


### S11 — 公開研究addendum（候補探索の二次索引）

原典：https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/KAGGRICULTURE_SCORE_WEIGHTED_EXECUTION_ADDENDUM.md

確認状態：2026-09-23 00:11 UTC付近の取得とされる保存版を読解。

使い道：候補の所在だけに用いる。9/24現在の順位、コードと掲載スコアの同一性、性能保証には使わない。


### S12 — qeinstein current research EXP338/339

原典：https://github.com/qeinstein/kaggriculture

確認状態：公開README取得。portfolio等を今回のB1と対戦させていない。

使い道：35M RL/MoEより既存portfolioが良いという作者ローカル結果。以前提出したqeinstein_moev2と同一視しない。


### S13 — Seyamalam V21 capital latch

原典：https://github.com/Seyamalam/Kaggriculture

確認状態：公開README取得。再現環境は1.32.4と記載されている。

使い道：古い環境の研究対照。currentというREADME表現だけで1.32.7上位候補へ昇格させない。

## 未確認を埋めない

Wonderfulの抽出Markdownが空でも、agent自体が空とは言わない。v15stackの完成本体を今回動かしたとは言わない。Order Book v3の原作の成績を、今回作った狭いSELL-only実験の成績へ流用しない。

## キャッシュ／版の注意

webのmaster表示ではCARROT/TOMATO/EGGの不足側が旧曲線だったが、固定commit302d8e20…の公式ソースと今回のB1にはhingeがある。今回の計算は固定版・添付の設定を用いた。URLにmasterと書いてあるだけで最新仕様と断定しない。Git blobとSHA-256も別種のハッシュとして記録する。

## 次回の取得手順

まずKaggle Code/Discussionと上記原典の現行版を、ユーザーのローカルCLIまたは利用可能な公式手段で取得する。CLIの実コマンドはインストール版のhelpで確認する。投稿時刻、lastRunTime、取得時刻、scriptVersion、埋込payloadと最終main.pyのSHA-256、依存物、ライセンス、最後のcallable、選択された設定を保存する。説明の末尾にある結果がどのコードhashに属するか必ず対応付ける。取得不能は取得不能として台帳へ残す。

Round10の旧取得一覧はreference/ROUND10_SOURCE_REGISTRY.jsonに保存した。今回の新規候補と、既に試した7候補（V56/V57/OrderBook/Metav4/HerdSafe/MelonThreshold/Barnyard）を混ぜない。
