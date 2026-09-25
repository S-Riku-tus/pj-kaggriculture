# Round12 reproduction

開始ディレクトリはリポジトリroot `pj-kaggriculture`。Windows PowerShell、既存 `.venv`、既存C++ engineを使う。ネットワーク取得、Kaggle提出、公開、pushは不要である。

## 1. agent生成とhash確認

```powershell
.\.venv\Scripts\python.exe experiments\round12_causal_repairs_20260925\scripts\build_round12_agents.py
```

このscriptはB1 SHA256が固定値と異なれば停止し、全armを別ファイルへ生成して `agents/generated_manifest.json` を更新する。

## 2. 必須回帰

```powershell
.\.venv\Scripts\python.exe -m pytest -q experiments\round12_causal_repairs_20260925\tests\test_round12_regressions.py
```

期待値は `7 passed`。公式loaderの空namespace、最後のcallable、両seat、連続episodeもこの中で検査する。

## 3. reactive full-game panels

既存outputへの混在を防ぐためrunnerは `games.csv` があると停止する。完全再実行はRound12ディレクトリを別の作業コピーへ複製するか、configの `output` を新しい空パスへ変更してから行う。

```powershell
.\.venv\Scripts\python.exe experiments\round12_causal_repairs_20260925\scripts\run_round12_panel.py experiments\round12_causal_repairs_20260925\configs\input_repairs_development.json
.\.venv\Scripts\python.exe experiments\round12_causal_repairs_20260925\scripts\run_round12_panel.py experiments\round12_causal_repairs_20260925\configs\factorial_development.json
```

各試合は両agentを公式 `get_last_callable` で独立loadし、719 stepすべてで現在観測から双方を呼ぶ。固定注文replayではない。gzip replayに全観測、両action、終局観測、DONE/DONE、終局資金を保存する。

## 4. 集計とparity

```powershell
.\.venv\Scripts\python.exe experiments\round12_causal_repairs_20260925\scripts\analyze_round12.py
.\.venv\Scripts\python.exe experiments\round12_causal_repairs_20260925\scripts\verify_official_parity.py
```

parityは公式Pythonを新規実行し、P0M1の実分岐ケースとP1独立経路をC++と比較する。期待値は `passed: true`。

## 5. registryとmanifest

```powershell
.\.venv\Scripts\python.exe experiments\round12_causal_repairs_20260925\scripts\finalize_round12.py
```

`INPUT_HASHES.json` の2つのRound11 ZIP不一致は既知であり、黙って一致扱いにしてはならない。`FINAL_MANIFEST.json` は自分自身とcacheだけを除外するため、文書更新後にこのcommandを最後に再実行する。

## 依存関係

- Python: repository `.venv`
- Kaggle Environments: 1.32.7
- C++ simulator: `experiments/round10_public_learning_20260924/engines/kaggriculture-cppsim`
- Windows DLL directory: `C:\msys64\ucrt64\bin`
- 対戦相手: Research Revision展開先の `inputs/agents/{B1,v57,order_book,metav4}.py`

取得scriptは今回0本、ネットワーク呼出し0回。Round11のREPRODUCEが参照した14 scriptはローカルに存在することを確認済みで、本Round12の再現は上記4 scriptだけで完結する。
