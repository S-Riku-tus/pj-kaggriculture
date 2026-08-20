# pj-kaggriculture

Kaggriculture向けのversioned agent、ローカル対戦、ログ、提出物をまとめたプロジェクトです。大会公式の仕様資料は [README.md](README.md)、Getting Startedは [AGENTS.md](AGENTS.md) にそのまま残しています。

## Layout

`ptcc_pokemon_ai_buttle` の構成を参考に、提出ランタイムと実験データを分離しています。

```text
agents/
  v1/                        # v1の正本。Kaggle runtimeだけを置く
    main.py
    README.md
    metadata.json
    CHANGELOG.md
artifacts/
  submissions/               # 生成した提出tar.gz
data/
  analysis/                  # 日別状態・action構成の分析結果
  logs/                      # Kaggleから取得したagent log
  replays/                   # ローカル/Kaggle replay JSON
  runs/                      # paired matchの結果
  submissions/               # build/remote submission metadata
  summaries/                 # 複数runを集約した表やレポート
docs/                        # repository横断の戦略・benchmark文書
scripts/                     # 対戦、分析、提出物作成
tests/                       # repository横断テスト
```

現在のv1は [agents/v1](agents/v1) です。外部依存やmutable global stateを持たない単一ファイルagentで、観測から毎ターン作業を再計画します。

## Setup and validation

```powershell
$env:UV_PYTHON_INSTALL_DIR = (Join-Path (Get-Location) '.python')
$env:UV_CACHE_DIR = (Join-Path (Get-Location) '.uv-cache')
$env:UV_PROJECT_ENVIRONMENT = (Join-Path (Get-Location) '.venv')
uv sync --dev
uv run pytest
uv run ruff check .
```

## Matches and logs

starterとseedごとに両seatを入れ替えて対戦します。結果JSONは指定しなくても `data/runs/` に保存されます。

```powershell
uv run python scripts/run_match.py --opponent starter --pairs 3
```

full replayも残す場合:

```powershell
uv run python scripts/run_match.py --opponent starter --pairs 1 --save-replays
```

1 episodeの日別状態とaction構成は `data/analysis/` に保存されます。

```powershell
uv run python scripts/analyze_episode.py --opponent starter --seed 20260821
```

別versionを評価するときは `--agent agents/.../<version>` を渡します。

## Build and submit

versioned agentから提出物を作ります。

```powershell
uv run python scripts/package_submission.py `
  --agent agents/v1
```

出力は `artifacts/submissions/v1.tar.gz`、build manifestは `data/submissions/builds/` に保存されます。tar.gzのrootにはKaggleが要求する `main.py` だけが入ります。

Kaggle画面の **Drag and drop file to upload** には、単一ファイルで完結している [agents/v1/main.py](agents/v1/main.py) をそのままアップロードするのが最も簡単です。フォルダ全体、`metadata.json`、ログ類をアップロードする必要はありません。`.gz` で提出したい場合だけ、上記の `v1.tar.gz` を使います。

大会ルールへの同意とKaggle CLI認証後:

```powershell
uv run kaggle competitions submit kaggriculture `
  -f artifacts/submissions/v1.tar.gz `
  -m "v1 closed-loop economic agent"
```

戦略は [docs/strategy-v1.md](docs/strategy-v1.md)、公式環境での初回結果は [docs/benchmark-v1.md](docs/benchmark-v1.md) にあります。
