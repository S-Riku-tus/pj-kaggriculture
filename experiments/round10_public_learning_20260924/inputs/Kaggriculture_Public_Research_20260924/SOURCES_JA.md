# 情報源台帳 — 2026年9月24日

## 読み方

公式コードの確認、作者の実験報告、検索メタデータを別扱いにする。今回の公開ミラーは2026-09-23T02:00:50Zのcommit `fa7458c015982ec838cce9427b3268114ac1c784` に固定。ミラーにある原作者の文章は一次的な実験報告の保存コピーだが、原サイトの現行版とのバイト同一性は未検証である。

公開スコア・Best Score・本文でいう過去最高・現在の実行アーカイブは別物。同じ著者の版違いや別名forkを独立した相手として数えない。

## S01 — Kaggriculture official overview / timeline

原典: https://www.kaggle.com/competitions/kaggriculture/overview/citation

確認区分: 公式ページ検索取得

用途: 最終提出日2026-09-30。ゲーム目的・決済の概要。

限界: 相対日付・残り日数は検索キャッシュが古い。最新Leaderboard行は取得できていない。

## S02 — Official engine, pinned source

原典: https://github.com/Kaggle/kaggle-environments/blob/302d8e20c83822b8d4572975cdea1180b792b748/kaggle_environments/envs/kaggriculture/kaggriculture.py

確認区分: 公式コードの該当関数を直接読解

用途: 価格式、単位同時見積り、購入/売却、雇用、作物期間。

限界: ソース確認であり、Kaggle本番配備版との同一性は別途必要。コード全体の再実行は未実施。

取得ファイルのGit blob SHA: `3c202c7ee921da239356789e266b694635103fc4`。提出tarのSHA256とは異なる。

## S03 — kaggriculture-cppsim README

原典: https://github.com/destbreso/kaggriculture-cppsim/blob/f0084b916343c37bbcbdc7de9d833dc96caff78f/README.md

確認区分: 作者の説明本文を直接読解

用途: 1.32.7対応C++エンジン、L0固定列、L1対話API、失敗計測。

限界: 速度・同等性結果は作者報告。こちらではビルド・対戦を実行していない。

## S04 — cppsim ROADMAP

原典: https://github.com/destbreso/kaggriculture-cppsim/blob/f0084b916343c37bbcbdc7de9d833dc96caff78f/ROADMAP.md

確認区分: 作者の説明本文を直接読解

用途: L1実装済み、L2テンソル一括API未実装。

限界: Game APIの存在を、snapshot/clone APIの存在と読み替えない。

## S05 — cppsim L1 parity test

原典: https://github.com/destbreso/kaggriculture-cppsim/blob/f0084b916343c37bbcbdc7de9d833dc96caff78f/tests/test_l1.py

確認区分: テストコードを直接読解

用途: 両seat観測のfarm/market/town/private等と終局報酬の比較方式。

限界: 同梱の有限トレース試験であり全状態同等性の証明ではない。

## S06 — Ahmed V45: First-Turn Wheat Round Trip

原典: https://www.kaggle.com/code/ahmedberatozer/kaggriculture-v45-first-turn-wheat-round-trip

確認区分: 原作者Notebook説明の公開ミラーを読解

用途: 初手数量・注文slotで相手の初日資金を変える。作者報告620勝20敗/640。

限界: 10相手・32seed・両seatの関連した比較。今日の3000帯実力ではない。 原サイトの本文を直接取得できない箇所は、公開ミラーとの一致を未保証。

実際に読んだ保存版: https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/extracted/ahmedberatozer__kaggriculture-v45-first-turn-wheat-round-trip.md

取得ファイルのGit blob SHA: `2ea81bf1b647aa140ef91d3e976d12d7996643ea`。提出tarのSHA256とは異なる。

## S07 — Melon Threshold / Step-1 Squeeze

原典: https://www.kaggle.com/code/goodpjw2008/kaggriculture-melon-threshold-squeeze-2749

確認区分: 原作者Notebook説明の公開ミラーを読解

用途: 10対70、step1追加買戻し、種購入の閾値、逆counter。

限界: 2749は作者の過去到達報告。private上位には効かないと作者自身が限定。 原サイトの本文を直接取得できない箇所は、公開ミラーとの一致を未保証。

実際に読んだ保存版: https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/extracted/goodpjw2008__kaggriculture-melon-threshold-squeeze-2749.md

取得ファイルのGit blob SHA: `d608cd54e83806801d9ffc749ba61d9dbb09dd20`。提出tarのSHA256とは異なる。

## S08 — The Metav4 Farm, submission v13

原典: https://www.kaggle.com/code/thomastschinkel/the-metav4-farm-submission-v13

確認区分: 原作者Notebook説明の公開ミラーを読解

用途: 公共基準への強さと実上位への差、労働費、投入/搬入、予測更新、負の結果。

限界: 作者報告。本文のトマト3日等は公式定数と不一致。報告の数値を無条件で一般化しない。 原サイトの本文を直接取得できない箇所は、公開ミラーとの一致を未保証。

実際に読んだ保存版: https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/extracted/thomastschinkel__the-metav4-farm-submission-v13.md

取得ファイルのGit blob SHA: `32d14baafb94bdd12e3a0ad7752f4eace3240e50`。提出tarのSHA256とは異なる。

## S09 — V56: Smarter Seeds and Fertilizer

原典: https://www.kaggle.com/code/ahmedberatozer/kaggriculture-v56-smarter-seeds-and-fertilizer

確認区分: 原作者Notebook説明の公開ミラーを読解

用途: 残り植付機会に種購入を合わせ、予定収穫を変えない追加施肥を削る。

限界: 比較対象は前のV56でV55ではない。全文ソースの同一性・対戦は未再検証。 原サイトの本文を直接取得できない箇所は、公開ミラーとの一致を未保証。

実際に読んだ保存版: https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/extracted/ahmedberatozer__kaggriculture-v56-smarter-seeds-and-fertilizer.md

取得ファイルのGit blob SHA: `401ece03e4b7ee15fc4121b9411ea0bc0420d320`。提出tarのSHA256とは異なる。

## S10 — V57: Funding-Order Invariant

原典: https://www.kaggle.com/code/ahmedberatozer/kaggriculture-v57-funding-order-invariant

確認区分: 原作者Notebook説明の公開ミラーを読解

用途: 売却資金より先にHIRE/BUYを動かす不具合を防ぐ。

限界: 320ゲーム=160対条件。30betterは30敗戦救済ではなく、W/L/Tの変化は4勝増・4分減。 原サイトの本文を直接取得できない箇所は、公開ミラーとの一致を未保証。

実際に読んだ保存版: https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/extracted/ahmedberatozer__kaggriculture-v57-funding-order-invariant.md

取得ファイルのGit blob SHA: `7344f87b1442a63cee26f8c955bc877907718a22`。提出tarのSHA256とは異なる。

## S11 — Herd-Safe Sale Window, Sept 22

原典: https://www.kaggle.com/code/dmitriigluzdov/kaggriculture-herd-safe-sale-window-lb-2700

確認区分: 原作者Notebook説明の公開ミラーを読解

用途: 資材保護、7turn最終回収、統合方策の再評価。

限界: タイトル2700は旧版。作者報告で16/64にガチョウ退出が残る。相手共通祖先も明示。 原サイトの本文を直接取得できない箇所は、公開ミラーとの一致を未保証。

実際に読んだ保存版: https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/refresh_20260923T001052Z/extracted/dmitriigluzdov__kaggriculture-herd-safe-sale-window-lb-2700.md

取得ファイルのGit blob SHA: `07e703b0626d185f3d14fac848831fd34d0654a5`。提出tarのSHA256とは異なる。

## S12 — Your Market List Is an Order Book

原典: https://www.kaggle.com/code/shiiin9/your-market-list-is-an-order-book

確認区分: 原作者Notebook説明の公開ミラーを読解

用途: 候補注文列の相対価格影響、将来市場在庫でトマト投資を評価。

限界: 191-53は244件で280に36件足りない。89敗→勝を未検算のまま採用しない。評価器の有限資金制約も別確認。 原サイトの本文を直接取得できない箇所は、公開ミラーとの一致を未保証。

実際に読んだ保存版: https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/extracted/shiiin9__your-market-list-is-an-order-book.md

取得ファイルのGit blob SHA: `e661757ccf7d2edb40f692fc1aff6d31971afe38`。提出tarのSHA256とは異なる。

## S13 — Public Meta Atlas, Sept 22

原典: https://www.kaggle.com/code/leoprovorov/kaggriculture-public-meta-atlas-v2

確認区分: 原作者Notebook説明の公開ミラーを読解

用途: 4公開agentのAST比較。共通194関数という作者独自集計。

限界: 私の再計算ではない。サンプル内のコード重複は全体の方策同一性ではない。 原サイトの本文を直接取得できない箇所は、公開ミラーとの一致を未保証。

実際に読んだ保存版: https://github.com/5thDimension-Sean/kaggriculture-master/blob/fa7458c015982ec838cce9427b3268114ac1c784/evidence/extracted/leoprovorov__kaggriculture-public-meta-atlas-v2.md

取得ファイルのGit blob SHA: `21786a2d0fd3b92332fc1eb05c967ef87d68bdde`。提出tarのSHA256とは異なる。

## S14 — DAgger original paper

原典: https://proceedings.mlr.press/v15/ross11a.html

確認区分: 原論文ページ

用途: 自己生成状態で学ぶ必要性を説明する理論背景。

限界: この論文はKaggricultureでの性能保証ではない。

## S15 — RL of Meta Agent: 960 Matchups and a PPO Plateau

原典: https://www.kaggle.com/competitions/kaggriculture/discussion/736439

確認区分: 作者投稿の検索取得

用途: 高レベル選択のPPOでも相手間トレードオフが出た参加者実験。

限界: 今回のページ直開きは失敗。以前の保存分析と検索取得を分離。新規ゲームの再現なし。

## S16 — How are people making RL work in Kaggriculture?

原典: https://www.kaggle.com/competitions/kaggriculture/discussion/740792

確認区分: 作者投稿の検索取得

用途: RL継続研究の存在と、適応的なログだけから学習済みと判断できない点。

限界: RL不可能とも3000達成とも証明しない。

## S17 — X-ray your agent

原典: https://www.kaggle.com/code/destbreso/x-ray-your-agent

確認区分: 公式Notebookメタデータ検索取得

用途: 意思決定言語・作業・資金診断の候補ツール。

限界: 最新版全コードの実行は未実施。

## S18 — Harvest Ledger V54

原典: https://www.kaggle.com/code/haodou092/notebookdb6965aa8e

確認区分: 公式Notebookメタデータ検索取得

用途: 公開スコア2684.2/V54という取得表示。比較候補。

限界: 以後の版も他作者資料に登場するため、V54を最新と断言しない。元版と実行物の対応が必要。

## S19 — Barnyard Economist

原典: https://www.kaggle.com/code/romanrozen/strong-barnyard-economist/notebook

確認区分: 公式Notebookメタデータ検索取得

用途: 検索表示Public/Best3034.8 V7という歴史的候補。

限界: 検索キャッシュが数週間前で、現在の3000帯対戦能力の確認ではない。

## S20 — Kaito v43 Sparse Shop Hybrid

原典: https://www.kaggle.com/code/kaitofukami/103-128-fresh-public-v43-sparse-shop-hybrid

確認区分: 公式Notebookメタデータ検索取得

用途: 過去の疎な分岐方策。今回の新規戦略の中核にはしない。

限界: 過去の3009/3090のBestを別版の現在レートとして混同しない。

## 保存済みProject資料の使用箇所

- `Round9分析改善方針.txt`: A2 v2 64戦全敗、行動/経済精度、移動過多、生産停止、戦略管理なし、Pokemonの有効/無効経路。
- `対戦ログ分析と戦術提案.txt`: v124と2026年9月20日の上位スナップショット。価格床販売、作付時期、土地の転用、施肥、維持費、CARE順序。
- `分析依頼 codex改善.txt`: B1の狭い変更範囲と改善余地55.6、B2の初回注文変更失敗、数量/確率の意味ずれ。
- `V122戦略分析と改善策.txt`、`枝分かれ · ハッカソン戦略改善案.txt`: 行単位splice、source固定案の棄却、似た農場と同一方策の混同、過去Bestと現在の強さの違い。
- `エージェント改善分析.txt`、`Round6分析方針整理.txt`、`Round8改善分析方針.txt`: 未成熟収穫、重複給餌、誤った復帰契約、正解連携を消すマスク、自己生成状態での崩壊。

これらは今回再び生リプレイ全件を計算した結果ではなく、保存された監査資料を読んで引き継いだ知見である。

## 今回読めなかったこと

9月24日のライブLeaderboardの行データ、private上位のコード、全公開提出物の完全同一性、全公開agentとの新規対戦。今回の書類を「最新全上位を再現して勝率測定したレポート」として使わない。
