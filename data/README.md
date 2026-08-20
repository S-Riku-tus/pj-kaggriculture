# Data layout

対戦・Kaggle提出から得た可変データを保存します。大きなJSONやlogはGit管理対象外ですが、各ディレクトリは `.gitkeep` で維持します。

- `analysis/`: `analyze_episode.py` が出力する日別farm/action分析
- `logs/`: Kaggle episodeから取得したagent stdout/stderr log
- `replays/`: ローカル対戦またはKaggle episodeのfull replay JSON
- `runs/`: `run_match.py` が出力するpaired match結果
- `submissions/`: build manifest、submission ID、statusなど
- `summaries/`: 複数runを横断したCSV/Markdown集計

再現に必要な小さな固定fixtureを将来追加する場合は、専用のtracked subdirectoryを作って `.gitignore` の例外にします。
