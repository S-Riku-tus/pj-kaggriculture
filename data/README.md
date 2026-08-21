# Data layout

対戦・Kaggle提出から得た可変データを保存します。大きなJSONやlogはGit管理対象外ですが、各ディレクトリは `.gitkeep` で維持します。

- `analysis/`: `analyze_episode.py` が出力する日別farm/action分析
- `logs/`: `fetch_submission_logs.py` がreplayから抽出した、submission・episode・seat別の観測ログ
- `replays/`: ローカル対戦、または `fetch_submission_logs.py` が取得したKaggle full replay JSON
- `runs/`: `run_match.py` が出力するpaired match結果
- `submissions/`: build manifest、submission ID、statusなど
- `summaries/`: 複数runを横断したCSV/Markdown集計

再現に必要な小さな固定fixtureを将来追加する場合は、専用のtracked subdirectoryを作って `.gitignore` の例外にします。

Kaggle提出ログの取得例:

```powershell
uv run python scripts/fetch_submission_logs.py --submission-id 55649709 --version v1 --rating 521.9
```

`--rating` はKaggle画面で確認した値をメタデータとして残すだけで、episode検索にはsubmission IDを使います。
`--version v1` を指定すると、各保存先のフォルダ名は `v1_submission_<ID>` になります。versionを省略した場合だけ `submission_<ID>` になります。
取得完了時には、manifest・metadata・対象replay・agentログをまとめた `v1_submission_<ID>_battle_logs.zip` も `submissions/v1_submission_<ID>/` に生成されます。
