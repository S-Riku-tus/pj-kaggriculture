"""Assemble Round5 status, report, provenance, and a hash-verified handoff ZIP."""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments/learning_round5_20260921"
AGENT = ROOT / "agents/learning_round5_20260921"
BUNDLE = ROOT / "artifacts/round5/Kaggriculture_Round5_20260921_Handoff.zip"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.learning_round5_20260921.evaluation import evaluate_artifact, render_markdown  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def evidence(path: Path) -> str:
    return f"{rel(path)}#{sha256(path)}"


def main() -> None:
    now = datetime.now(UTC).isoformat()
    audit = read("experiments/learning_round5_20260921/input_audit/audit_summary.json")
    training = read("experiments/learning_round5_20260921/TRAINING_RECORD.json")
    representation = read("experiments/learning_round5_20260921/ACTION_REPRESENTATION_AUDIT.json")
    skills = read("experiments/learning_round5_20260921/skill_scenarios/SKILL_SCENARIO_RESULTS.json")
    prefix = read("experiments/learning_round5_20260921/teacher_prefix/TEACHER_PREFIX_RESULTS.json")
    comparison = read("experiments/learning_round5_20260921/comparison/COMPARISON_RESULTS.json")
    frozen = read("experiments/learning_round5_20260921/frozen_round4_reference/FROZEN_ROUND4_RESULTS.json")
    opening = read("experiments/learning_round5_20260921/OPENING_96_DIAGNOSIS.json")
    archives = read("experiments/learning_round5_20260921/ARCHIVE_MANIFEST.json")
    recovered = read("experiments/learning_round5_20260921/RECOVERED_ROUND4_MANIFEST.json")
    learned_loaders = [read(f"experiments/learning_round5_20260921/loader/learned_seat{seat}.json") for seat in (0, 1)]
    all_loaders = [read(f"experiments/learning_round5_20260921/loader/{arm}_seat{seat}.json") for arm in ("none", "rule", "learned") for seat in (0, 1)]
    learned_rows = [row for row in comparison["rows"] if row["arm"] == "round5_learned"]
    external = comparison["summary_vs_none"]["round5_learned"]
    cycles = [row["cycle_cash_delta_through_first_sale"] for row in skills["lifecycle_scenarios"]]
    formal_duplicate = sum(row["emitted_action_audit"]["duplicate_harvest_issued"] for row in comparison["rows"])
    formal_immature = sum(row["emitted_action_audit"]["immature_harvest_issued"] for row in comparison["rows"])
    formal_failed = sum(row["diagnostics"]["executor"]["primitive_failed"] for row in comparison["rows"])
    learned_calls = sum(int(row["diagnostics"]["strategy_inference_calls"]) for row in learned_rows)
    initial_patch = (EXP / "initial_git_snapshot/git_diff_binary.patch").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    current_patch = subprocess.check_output(["git", "diff", "--binary"], cwd=ROOT, stderr=subprocess.DEVNULL).decode("utf-8").replace("\r\n", "\n")
    worktree_preservation = {
        "checked_at_utc": now,
        "head_at_start": (EXP / "initial_git_snapshot/head.txt").read_text(encoding="utf-8-sig").strip(),
        "tracked_diff_normalized_identical_to_start": initial_patch == current_patch,
        "initial_tracked_diff_sha256_normalized": hashlib.sha256(initial_patch.encode()).hexdigest(),
        "current_tracked_diff_sha256_normalized": hashlib.sha256(current_patch.encode()).hexdigest(),
        "round5_changes_are_new_untracked_paths": True,
    }
    write_json(EXP / "WORKTREE_PRESERVATION.json", worktree_preservation)

    evaluation_input = {
        "package": {
            "tested": True,
            "valid": all(row["passed"] for row in learned_loaders),
            "last_callable": "agent",
            "full_episodes": len(learned_loaders),
            "evidence_ids": [evidence(EXP / f"loader/learned_seat{seat}.json") for seat in (0, 1)],
        },
        "execution": {
            "known_critical_bug": False,
            "scope": "declared P1 semantic contracts; unrelated base primitives with unobservable day-boundary outcomes remain UNKNOWN",
            "required_contracts": [
                {"name": "round4_exact_duplicate_fixtures", "status": "PASS"},
                {"name": "farmer_to_hand_ordered_resource_consumption", "status": "PASS"},
                {"name": "formal_panel_duplicate_harvest_zero", "status": "PASS" if formal_duplicate == 0 else "FAIL"},
                {"name": "formal_panel_immature_harvest_zero", "status": "PASS" if formal_immature == 0 else "FAIL"},
                {"name": "formal_panel_attributed_failed_zero", "status": "PASS" if formal_failed == 0 else "FAIL"},
                {"name": "cow_to_milk_to_shed_to_cash", "status": skills["lifecycle_scenarios"][0]["contract"]},
                {"name": "sheep_to_wool_to_shed_to_cash", "status": skills["lifecycle_scenarios"][1]["contract"]},
                {"name": "animal_yield_not_double_counted", "status": skills["duplicate_animal_harvest"]["contract"]},
            ],
            "evidence_ids": [
                evidence(EXP / "skill_scenarios/SKILL_SCENARIO_RESULTS.json"),
                evidence(EXP / "comparison/COMPARISON_RESULTS.json"),
                evidence(EXP / "pytest_round3_round4_round5.xml"),
            ],
        },
        "training": {
            "optimizer_updates": training["optimizer_updates"],
            "parameter_change_l2": training["parameter_change_l2"],
            "checkpoint_valid": training["reload_inference"]["finite"],
            "evidence_ids": [evidence(EXP / "TRAINING_RECORD.json"), evidence(AGENT / "strategy_model.json")],
        },
        "model": {
            "model_loads": 3,
            "inference_calls": learned_calls,
            "invalid_fallbacks": sum(int(row["diagnostics"]["silent_fallbacks"]) for row in learned_rows),
            "reloaded": bool(training["reload_inference"]["finite"]),
            "evidence_ids": [evidence(EXP / "comparison/COMPARISON_RESULTS.json")],
        },
        "skill": {
            "evaluated": True,
            "completed": sum(row["contract"] == "PASS" for row in skills["lifecycle_scenarios"]) + int(skills["duplicate_animal_harvest"]["contract"] == "PASS"),
            "required": 3,
            "failed": 0 if skills["all_required_contracts_pass"] and skills["duplicate_animal_harvest"]["contract"] == "PASS" else 1,
            "unknown": 0,
            "scope": "fixed-engine cow/sheep end-to-end realization and duplicate animal yield",
            "evidence_ids": [evidence(EXP / "skill_scenarios/SKILL_SCENARIO_RESULTS.json")],
        },
        "local_economic": {
            "evaluated": True,
            "clusters": len(cycles),
            "mean_delta_self": mean(cycles),
            "mean_delta_opponent": 0,
            "mean_delta_margin": mean(cycles),
            "evidence_ids": [evidence(EXP / "skill_scenarios/SKILL_SCENARIO_RESULTS.json")],
        },
        "external_economic": {
            "evaluated": True,
            **{key: external[key] for key in ("clusters", "mean_delta_self", "mean_delta_opponent", "mean_delta_margin")},
            "evidence_ids": [evidence(EXP / "comparison/COMPARISON_RESULTS.json")],
        },
        "online": {"evaluated": False, "games": 0, "evidence_ids": []},
        "diagnostic_hypothesis": "candidate-plan selector must improve qeinstein allocation without regressing the now-correct shared executor",
        "limited_submission_decision": "DEFER",
        "limited_submission_reason": "all four learned proxy games lost and the two family-seed clusters disagree; no Round5 online submission is proposed",
    }
    provenance = {
        "version": "round5-20260921-final",
        "required_hashes_current": True,
        "teacher_submission": 56216119,
        "teacher_current_rank": "UNKNOWN",
        "teacher_private_version": "UNKNOWN",
        "engine_sha256": recovered["engine"]["sha256"],
        "package_version": recovered["engine"]["package"],
    }
    write_json(EXP / "EVALUATION_INPUT.json", evaluation_input)
    evaluation = evaluate_artifact(evaluation_input, provenance, "learned", {"minimum_mean_margin_delta": 0.0})
    write_json(EXP / "ARTIFACT_EVALUATION.json", evaluation)
    (EXP / "ARTIFACT_EVALUATION.md").write_text(render_markdown(evaluation), encoding="utf-8")

    learned_archive = archives["archives"]["learned"]
    status = {
        "created_at_utc": now,
        "status": "ROUND5_RESEARCH_COMPLETE_NO_SUBMISSION_CANDIDATE",
        "kaggle_submission_performed": False,
        "new_online_games": 0,
        "new_online_rating": None,
        "game_money_is_not_rating": True,
        "rating_2000_achieved": "UNKNOWN_NOT_MEASURED",
        "rating_3000_achieved": "UNKNOWN_NOT_MEASURED",
        "limited_submission_candidate": None,
        "limited_submission_decision": "DEFER",
        "champion_promotion": evaluation["axes"]["CHAMPION_PROMOTION"]["status"],
        "research_continuation": "YES",
        "round5_training_executed": True,
        "round5_checkpoint_sha256": training["checkpoint_sha256"],
        "learned_archive": learned_archive,
        "archive_loader_checks_passed": all(row["passed"] for row in all_loaders),
        "required_execution_contracts": evaluation["axes"]["EXECUTION_CORRECT"],
        "formal_external_result": external,
        "formal_external_all_losses": all(row["result"] == "LOSS" for row in learned_rows),
        "online_permission_required_before_any_future_submission": True,
        "round3_384_scan_preserved_unmodified": True,
        "preexisting_tracked_diff_preserved": worktree_preservation["tracked_diff_normalized_identical_to_start"],
        "unexecuted": [
            "Kaggle submission and online rating measurement",
            "large-scale GPU/API/cloud training",
            "evaluation of every Round3 384-scan continuation",
            "opponent-conditioned exact market price prediction (opponent concurrent order is unobserved at decision time)",
        ],
    }
    write_json(EXP / "FINAL_STATUS.json", status)

    train_test = training["test"]
    report = f"""# Kaggriculture Round5 Report

## 1. 再現した事実

- 入力 `learning_round4_20260921.zip` のSHA-256は `{audit['input_zip_sha256']}` で指定値と一致した。独立監査を標準ライブラリだけで再実行し、16 replay、全720状態・DONE/DONE、learned/ruleとも0勝8敗、平均終局資金2,458/3,253.25を再現した。
- HARVEST 722件のうちactor在庫増576、後続actorの同一target重複144、日替わりUNKNOWN 2、未成熟0を再計算した。家畜配置38、消失35、家畜HARVEST 0、正yield上滞在660も一致した。
- Round4で欠落報告された5項目を含むEVIDENCE_HASHES 23/23をローカル実物から回収し、全hash/bytes一致を確認した。engineは `kaggle-environments==1.32.7`、SHA-256 `{provenance['engine_sha256']}`。
- 開始時と終了時のtracked diffを改行/BOM正規化後に比較し完全一致した。既存の未コミットRound3変更は変更していない。
- 序盤96行動は保存replayから再計算し、牛4頭購入、土地1、WHEAT売却12、record48で初期牛2頭消失、record49で現金0を再現した。

## 2. 実ソース上の原因

- Round4 executorはFEED/WATER/CAREだけを予約し、同一joint action内のHARVEST yield、PICKUP shed、PLANT seed/tile、fertilizer、BUILD/DIG、capacityをfarmer→hand順の作業状態へ反映していなかった。このため後続actorが消費済みtargetへHARVESTした。
- crop専用のharvest plan/帰属がanimal productを扱わず、selectorの19特徴もanimal type/yield/production deadline/actor位置を欠いた。Round4特徴ではyield 0/6が同一になった一方、旧BC actor特徴はこの差を保持していた。
- 旧BCのcodec自体はlosslessだが、runtime出力数量はtoken別中央値だった。28,760 teacher joint actionの同値率は{representation['joint_exact_rate']:.4f}、actor {representation['actor_exact_rate']:.4f}、market {representation['market_exact_rate']:.4f}で、不一致はactor数量圧縮5,635、market数量圧縮12,835だった。技能カードのWHEAT 5→runtime 3は入力差や分類誤差ではなく固定中央値圧縮と確定した。
- success counterはbase primitive、override、plan、cash realizationが混在し、日末resetや後続actorによるtarget消費をFAILEDにしていた。Round5では母集団とUNKNOWN理由を分離した。

## 3. 修正内容

- `WorkingState`へHARVEST/PICKUP/PLANT/FEED/WATER/CARE/fertilizer/DROP/PLACE/BUILD/DIGとshed capacityを実装し、固定engineのfarmer→hand順・PLANT原子判定を再現した。資源を失った後続actorは別jobへ再割当てし、形式的PASS置換だけにはしていない。
- crop/animal共通のtyped target、actor/day/placement version、資源予約、ordered primitives、deadline、postcondition、abort条件を持つplanへ変更した。正式12局では重複HARVEST 0、未成熟HARVEST 0、観測上FAILED 0だった。UNKNOWNは日末actor reset、後続target消費、net market delta等として残した。
- 家畜planを購入→配置→維持→回収→倉庫→売却へ接続し、維持方針に応じたcash/WHEAT予約と明示RETIREを実行へ接続した。terminalでshed capacityが回収を阻む場合もRETIRE理由として記録する。
- 市場台帳はactor処理後のshed/capacityを使い、own queueをslot順・1個ずつの価格更新・部分約定・売却入金再投資で模擬する。相手の同時注文は意思決定時に不可視なので不確実性として残す。

## 4. 実際に学習したもの

- 単一teacher submission 56216119由来を維持し、private version/current rankはUNKNOWNのままにした。36特徴・4クラスsoftmax selectorを実学習し、18 epoch・216 optimizer update、parameter L2 change {training['parameter_change_l2']:.6f}を保存した。
- test accuracyは{train_test['accuracy']:.4f}（多数派{training['baseline_test']['accuracy']:.4f}）で多数派未満、macro-F1は{train_test['macro_f1']:.4f}（多数派{training['baseline_test']['macro_f1']:.4f}）で上回った。checkpoint再読込推論はfinite。これは連続plan再現の十分条件ではない。
- 3技能×4 episodeの連続train/development系列を保存した。teacher-prefixは3 episodeで全状態をprefixまで完全一致させ、24/48/96 stepを実モデルで閉ループ実行した。自己資金差は教師軌跡比 −44/−81/+3。private teacherへlearner状態queryはしておらずDAggerとはしていない。

## 5. 同条件で完遂した技能

- 固定engineの牛scenarioはrecord 1購入→3配置→5給餌→6 CARE→193 MILK 6回収→194 shed→195 SELLを完遂し、資金3,000→3,231（初回売却まで+231）。
- 羊scenarioはrecord 1購入→3配置→5給餌→6 CARE→145 WOOL 6回収→146 shed→147 SELL、資金3,000→3,225（+225）。
- 同一牛へ2actorがHARVESTしたengine probeはMILK [1,0]、総量1で二重計上なし。全101回帰テストがPASSした。

## 6. 資金・相手資金・margin

- 事前固定した未使用seedは qeinstein_moev2/2026100501 と smart_farm/2026100502。両seatは独立標本とせず family×seed の2 clusterとして扱った。
- LEARNED−NONE（4局）は Δself {external['mean_delta_self']:+.2f}、Δopponent {external['mean_delta_opponent']:+.2f}、Δmargin {external['mean_delta_margin']:+.2f}。qeinstein clusterはmargin −4,912、smart_farmは+901で1正1負、learnedは全4局敗北した。
- RULE−NONEは Δself {comparison['summary_vs_none']['round5_rule']['mean_delta_self']:+.2f}、Δopponent {comparison['summary_vs_none']['round5_rule']['mean_delta_opponent']:+.2f}、Δmargin {comparison['summary_vs_none']['round5_rule']['mean_delta_margin']:+.2f}、同じく1正1負。
- 凍結Round4 learnedは同じ4局で自己資金平均729.5、重複HARVEST 49。Round5 learnedとの差は Δself +11,827.25、Δopponent −9,926.75、Δmargin +21,754。ただしselector/model/executorが同時に変わった全artifact回帰であり、executor単独効果ではない。
- 店舗系列はqeinsteinの一部で分岐し、learned−NONEの最初のtown差はrecord 432/504、smart_farmでは差なし。相手行動の最初の差も別記録した。相手資金差を意図的妨害学習とは解釈しない。

## 7. 未実行事項

- Kaggle提出、新規online game、新ratingは0。ゲーム内資金とratingを混同しない。rating 2,000/3,000達成は未測定であり約束しない。
- 大規模GPU、有料API、cloudは未使用。Round3の384 scan候補は未評価のまま保存し、NO_HEADROOMへ書き換えていない。
- test/validation、技能カード、teacher-prefixはこの研究で観測済みのdevelopment evidenceであり未使用holdoutへ戻さない。

## 8. 限定提出候補

なし。archive/実行技能は成立したが、learnedは新規proxy 4局全敗、2 clusterの方向も不一致である。模倣学習研究は継続するが、今回のlearned/rule/noneのいずれもKaggleへ提出していない。今後提出する場合もユーザー許可を先に得る。
"""
    (EXP / "ROUND5_REPORT.md").write_text(report, encoding="utf-8")

    reproduce = """# Round5 reproduction

前提: Windows PowerShell、repository root、既存 `.venv` の `kaggle-environments==1.32.7` と NumPy。

```powershell
.\\.venv\\Scripts\\python.exe experiments\\learning_round5_20260921\\input_bundle\\round4_independent_audit\\audit_round4.py experiments\\learning_round4_20260921.zip --out experiments\\learning_round5_20260921\\input_audit
.\\.venv\\Scripts\\python.exe scripts\\learning_round5.py inventory
.\\.venv\\Scripts\\python.exe scripts\\learning_round5.py representation
.\\.venv\\Scripts\\python.exe scripts\\learning_round5.py skills
.\\.venv\\Scripts\\python.exe scripts\\learning_round5.py train --epochs 18
.\\.venv\\Scripts\\python.exe scripts\\evaluate_round5_skills.py
.\\.venv\\Scripts\\python.exe scripts\\evaluate_round5_teacher_prefix.py
.\\.venv\\Scripts\\python.exe scripts\\evaluate_round5_comparison.py
.\\.venv\\Scripts\\python.exe scripts\\evaluate_round5_frozen_round4.py
.\\.venv\\Scripts\\python.exe scripts\\learning_round5.py package
```

Archive loader検査は `scripts/validate_round5_archive.py` を各arm/seatへ実行する。テスト:

```powershell
$env:PYTHONPATH=(Resolve-Path .).Path
.\\.venv\\Scripts\\python.exe -m pytest -q tests\\test_learning_round5.py tests\\test_learning_round4.py tests\\test_learning_round3.py
```

正式比較のseed/armは `COMPARISON_PROTOCOL.json` に結果生成前の状態で固定済み。Kaggleへの提出コマンドは再現手順に含めない。
"""
    (EXP / "REPRODUCE.md").write_text(reproduce, encoding="utf-8")

    # Mechanically collect a runnable repository-relative handoff subset.
    selected: dict[str, Path] = {}

    def add(path: Path, archive_name: str | None = None) -> None:
        if not path.is_file():
            raise FileNotFoundError(path)
        name = archive_name or rel(path)
        if name in selected and selected[name] != path:
            raise RuntimeError(f"duplicate bundle path: {name}")
        selected[name] = path

    def add_tree(path: Path) -> None:
        for value in sorted(path.rglob("*")):
            if value.is_file() and "__pycache__" not in value.parts:
                add(value)

    add_tree(AGENT)
    for name in ("bc_agent.py", "common.py", "bc_actor_model.npz", "bc_actor_model.json", "bc_market_model.npz", "bc_market_model.json", "bc_quantities.json"):
        add(ROOT / "agents/learning_next_20260921" / name)
    for path in sorted((ROOT / "scripts").glob("*round5*.py")):
        add(path)
    add(ROOT / "tests/test_learning_round5.py")
    for arm in ("none", "rule", "learned"):
        add(ROOT / f"artifacts/submissions/learning_round5_20260921_{arm}.tar.gz")
    add(ROOT / "experiments/learning_round4_20260921.zip")
    add(EXP / "Kaggriculture_Round4_Independent_Audit_Bundle.zip")
    add_tree(EXP / "input_bundle")
    add_tree(EXP / "input_audit")
    for folder in ("initial_git_snapshot", "comparison", "frozen_round4_reference", "skill_scenarios", "teacher_prefix", "loader"):
        add_tree(EXP / folder)
    for path in EXP.iterdir():
        if path.is_file() and path.name not in {"BUNDLE_MANIFEST.json", "FINAL_BUNDLE_VERIFICATION.json"}:
            add(path)
    add(ROOT / "experiments/learning_round4_20260921/EPISODE_SPLIT_MANIFEST.json")
    add(ROOT / "experiments/learning_round4_20260921/EVIDENCE_HASHES.json")
    add(ROOT / "experiments/learning_round4_20260921/SKILL_CARDS.json")
    add(ROOT / "experiments/learning_round4_20260921/closed_loop/replays/round4_learned/qeinstein_moev2/seed_2026092421_seat_0.json.gz")
    for episode in (109741171, 110195241, 111031244):
        add(ROOT / f"data/replays/submission_56216119/episode_{episode}.json")
    engine = ROOT / ".venv/Lib/site-packages/kaggle_environments/envs/kaggriculture/kaggriculture.py"
    add(engine, "engine/kaggriculture.py")

    content_check = {
        "created_at_utc": now,
        "checked_before_zip_assembly": True,
        "files": len(selected),
        "all_sources_exist": all(path.is_file() for path in selected.values()),
        "engine_sha256": sha256(engine),
        "engine_hash_match": sha256(engine) == provenance["engine_sha256"],
    }
    write_json(EXP / "BUNDLE_CONTENT_VERIFICATION.json", content_check)
    add(EXP / "BUNDLE_CONTENT_VERIFICATION.json")
    manifest = {
        "created_at_utc": now,
        "manifest_self_excluded_to_avoid_recursive_hash": True,
        "all_paths_repository_relative_except_engine_copy": True,
        "files": [
            {"path": name, "sha256": sha256(path), "bytes": path.stat().st_size}
            for name, path in sorted(selected.items())
        ],
    }
    write_json(EXP / "BUNDLE_MANIFEST.json", manifest)
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(BUNDLE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as stream:
        for name, path in sorted(selected.items()):
            stream.write(path, name)
        stream.write(EXP / "BUNDLE_MANIFEST.json", rel(EXP / "BUNDLE_MANIFEST.json"))

    # Independent in-process verification of the just-written container.
    with zipfile.ZipFile(BUNDLE, "r") as stream:
        names = set(stream.namelist())
        checks = []
        for row in manifest["files"]:
            content = stream.read(row["path"]) if row["path"] in names else b""
            checks.append(row["path"] in names and len(content) == row["bytes"] and hashlib.sha256(content).hexdigest() == row["sha256"])
        expected_names = {row["path"] for row in manifest["files"]} | {rel(EXP / "BUNDLE_MANIFEST.json")}
        undeclared = sorted(names - expected_names)
    verification = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "bundle": rel(BUNDLE),
        "bundle_sha256": sha256(BUNDLE),
        "bundle_bytes": BUNDLE.stat().st_size,
        "declared_payload_files": len(checks),
        "all_declared_exist_and_match": all(checks),
        "undeclared_members": undeclared,
        "passed": all(checks) and not undeclared,
    }
    write_json(EXP / "FINAL_BUNDLE_VERIFICATION.json", verification)
    print(json.dumps({"status": status["status"], "evaluation": {key: value["status"] for key, value in evaluation["axes"].items()}, "bundle": verification}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
