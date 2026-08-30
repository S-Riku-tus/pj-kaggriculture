"""Fetch Kaggle Episodes, replays, and observation logs for one submission.

Kaggle's current CLI does not expose simulation Episode downloads.  This
script therefore uses the public EpisodeService to discover matches and the
public episode CDN to retrieve each full replay.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LIST_EPISODES_URL = "https://www.kaggle.com/api/i/competitions.EpisodeService/ListEpisodes"
REPLAY_URL = "https://www.kaggleusercontent.com/episodes/{episode_id}.json"
HTTP_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 pj-kaggriculture-log-fetcher/1.0",
}

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "data"


@dataclass(frozen=True)
class EpisodeRecord:
    episode_id: int
    create_time: str = ""
    end_time: str = ""
    state: str = ""
    episode_type: str = ""
    agent_0_submission_id: str = ""
    agent_1_submission_id: str = ""
    agent_0_initial_score: str = ""
    agent_1_initial_score: str = ""
    agent_0_updated_score: str = ""
    agent_1_updated_score: str = ""


@dataclass(frozen=True)
class DownloadRecord:
    submission_id: int
    episode_id: int
    episode_state: str
    submission_seat: str
    opponent_submission_id: str
    team_name: str
    opponent_team_name: str
    result: str
    own_reward: str
    opponent_reward: str
    step_count: int
    replay_status: str
    agent_0_log_status: str
    agent_1_log_status: str
    replay_path: str
    log_path: str
    error: str


def post_json(url: str, body: dict[str, object]) -> dict[str, object]:
    """POST JSON to Kaggle and return the decoded object."""
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers=HTTP_HEADERS,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Kaggle API returned HTTP {exc.code} for {url}: {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Kaggle API at {url}: {exc.reason}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Kaggle API returned {type(data).__name__}, expected object")
    return data


def read_json_url(url: str) -> object:
    """GET one JSON document from Kaggle's public CDN."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": HTTP_HEADERS["User-Agent"],
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Kaggle replay CDN returned HTTP {exc.code} for {url}: {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach Kaggle replay CDN at {url}: {exc.reason}") from exc


def _agents_by_index(episode: dict[str, object]) -> dict[int, dict[str, Any]]:
    agents = episode.get("agents")
    if not isinstance(agents, list):
        return {}

    indexed: dict[int, dict[str, Any]] = {}
    for position, agent in enumerate(agents[:2]):
        if not isinstance(agent, dict):
            continue
        raw_index = agent.get("index")
        index = raw_index if isinstance(raw_index, int) else position
        indexed[index] = agent
    return indexed


def _agent_values(episode: dict[str, object], field: str) -> dict[int, str]:
    values: dict[int, str] = {}
    for index, agent in _agents_by_index(episode).items():
        value = agent.get(field)
        if isinstance(value, dict):
            value = value.get("value")
        if value is not None and not isinstance(value, dict | list | bool):
            values[index] = str(value).strip()
    return values


def parse_submission_episodes(data: dict[str, object]) -> list[EpisodeRecord]:
    """Normalize an EpisodeService response and remove duplicate IDs."""
    episodes = data.get("episodes")
    if not isinstance(episodes, list):
        preview = json.dumps(data, ensure_ascii=False)[:1000]
        raise ValueError(f"Kaggle response has no episodes list: {preview}")

    records: dict[int, EpisodeRecord] = {}
    for episode in episodes:
        if not isinstance(episode, dict):
            continue
        raw_id = str(episode.get("id", "")).strip()
        if not raw_id.isdigit():
            continue

        submission_ids = _agent_values(episode, "submissionId")
        initial_scores = _agent_values(episode, "initialScore")
        updated_scores = _agent_values(episode, "updatedScore")
        episode_id = int(raw_id)
        records.setdefault(
            episode_id,
            EpisodeRecord(
                episode_id=episode_id,
                create_time=str(episode.get("createTime") or ""),
                end_time=str(episode.get("endTime") or ""),
                state=str(episode.get("state") or ""),
                episode_type=str(episode.get("type") or ""),
                agent_0_submission_id=submission_ids.get(0, ""),
                agent_1_submission_id=submission_ids.get(1, ""),
                agent_0_initial_score=initial_scores.get(0, ""),
                agent_1_initial_score=initial_scores.get(1, ""),
                agent_0_updated_score=updated_scores.get(0, ""),
                agent_1_updated_score=updated_scores.get(1, ""),
            ),
        )
    return list(records.values())


def list_submission_episodes(
    submission_id: int,
) -> tuple[list[EpisodeRecord], dict[str, object]]:
    response = post_json(LIST_EPISODES_URL, {"submissionId": submission_id})
    return parse_submission_episodes(response), response


def _write_json(path: Path, data: object, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
        ),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: Iterable[object], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def download_replay(
    episode_id: int,
    path: Path,
    *,
    overwrite: bool,
) -> tuple[str, dict[str, Any]]:
    if path.exists() and not overwrite:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict):
            raise ValueError(f"Existing replay is not a JSON object: {path}")
        return "skipped_existing", existing

    replay = read_json_url(REPLAY_URL.format(episode_id=episode_id))
    if not isinstance(replay, dict):
        raise ValueError(f"Episode {episode_id} replay is not a JSON object")
    _write_json(path, replay, compact=True)
    return "downloaded", replay


def extract_observation_logs(replay: dict[str, Any], agent_index: int) -> list[dict[str, object]]:
    """Preserve every step containing logs for one agent seat."""
    steps = replay.get("steps")
    if not isinstance(steps, list):
        return []

    entries: list[dict[str, object]] = []
    for step_index, step in enumerate(steps):
        if not isinstance(step, list) or agent_index >= len(step):
            continue
        state = step[agent_index]
        if not isinstance(state, dict):
            continue
        observation = state.get("observation")
        if not isinstance(observation, dict):
            continue
        logs = observation.get("logs")
        if isinstance(logs, list) and logs:
            entries.append({"step": step_index, "logs": logs})
    return entries


def save_observation_logs(
    episode_id: int,
    replay: dict[str, Any],
    agent_index: int,
    path: Path,
    *,
    overwrite: bool,
) -> str:
    if path.exists() and not overwrite:
        return "skipped_existing"
    entries = extract_observation_logs(replay, agent_index)
    _write_json(
        path,
        {
            "episode_id": episode_id,
            "agent_index": agent_index,
            "source": "replay.observation.logs",
            "entries": entries,
        },
    )
    return "extracted_from_replay" if entries else "extracted_empty"


def detect_submission_seat(
    episode: EpisodeRecord,
    replay: dict[str, Any],
    submission_id: int,
) -> int | None:
    target = str(submission_id)
    if episode.agent_0_submission_id == target:
        return 0
    if episode.agent_1_submission_id == target:
        return 1

    info = replay.get("info")
    if isinstance(info, dict):
        submission_ids = info.get("SubmissionIds") or info.get("submissionIds")
        if isinstance(submission_ids, list):
            for index, value in enumerate(submission_ids[:2]):
                if str(value).strip() == target:
                    return index
    return None


def _indexed_value(value: object, index: int | None) -> object:
    if index is None or not isinstance(value, list) or index >= len(value):
        return None
    return value[index]


def summarize_replay(
    replay: dict[str, Any],
    seat: int | None,
) -> dict[str, object]:
    info = replay.get("info") if isinstance(replay.get("info"), dict) else {}
    rewards = replay.get("rewards")
    team_names = info.get("TeamNames") if isinstance(info, dict) else None
    submission_ids = info.get("SubmissionIds") if isinstance(info, dict) else None
    opponent_seat = 1 - seat if seat in (0, 1) else None
    own_reward = _indexed_value(rewards, seat)
    opponent_reward = _indexed_value(rewards, opponent_seat)

    result = "unknown"
    if isinstance(own_reward, int | float) and isinstance(opponent_reward, int | float):
        if own_reward > opponent_reward:
            result = "win"
        elif own_reward < opponent_reward:
            result = "loss"
        else:
            result = "draw"

    steps = replay.get("steps")
    return {
        "opponent_submission_id": _indexed_value(submission_ids, opponent_seat),
        "team_name": _indexed_value(team_names, seat),
        "opponent_team_name": _indexed_value(team_names, opponent_seat),
        "result": result,
        "own_reward": own_reward,
        "opponent_reward": opponent_reward,
        "step_count": len(steps) if isinstance(steps, list) else 0,
    }


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _relative(path: Path, data_dir: Path) -> str:
    return path.relative_to(data_dir).as_posix()


def submission_storage_name(submission_id: int, version: str) -> str:
    """Return a readable, filesystem-safe directory name for one submission."""
    if not version.strip():
        return f"submission_{submission_id}"
    safe_version = re.sub(r"[^A-Za-z0-9._-]+", "_", version.strip())
    safe_version = re.sub(r"_+", "_", safe_version).strip("._-")
    if not safe_version:
        raise ValueError("--version must contain at least one letter or number")
    return f"{safe_version}_submission_{submission_id}"


def create_battle_log_archive(
    *,
    data_dir: Path,
    submission_name: str,
    submission_dir: Path,
    replay_dir: Path,
    log_dir: Path,
    episode_ids: Iterable[int],
    include_logs: bool,
) -> tuple[Path, int]:
    """Create an atomic ZIP whose contents preserve the repository data layout."""
    archive_path = submission_dir / f"{submission_name}_battle_logs.zip"
    temporary_path = archive_path.with_suffix(".zip.tmp")
    files: list[Path] = []

    for name in (
        "metadata.json",
        "episodes.csv",
        "manifest.csv",
        "episode_service_response.json",
    ):
        path = submission_dir / name
        if path.is_file():
            files.append(path)

    for episode_id in episode_ids:
        replay_path = replay_dir / f"episode_{episode_id}.json"
        if replay_path.is_file():
            files.append(replay_path)
        if include_logs:
            episode_log_dir = log_dir / f"episode_{episode_id}"
            if episode_log_dir.is_dir():
                files.extend(path for path in episode_log_dir.rglob("*.json") if path.is_file())

    unique_files = sorted(set(files), key=lambda path: path.relative_to(data_dir).as_posix())
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for path in unique_files:
                relative = path.relative_to(data_dir)
                member = Path(submission_name) / "data" / relative
                archive.write(path, arcname=member.as_posix())
        temporary_path.replace(archive_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return archive_path, len(unique_files)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download all Kaggle battle data associated with one submission ID.")
    parser.add_argument("--submission-id", "--submission", type=int, required=True)
    parser.add_argument(
        "--version",
        default="",
        help="Local agent version to record in metadata, for example v1.",
    )
    parser.add_argument(
        "--rating",
        type=float,
        help="Rating shown on Kaggle when fetched; stored as user-provided metadata.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="Data root (default: project data directory).",
    )
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--max-episodes", type=int, default=0)
    parser.add_argument(
        "--skip-episodes",
        type=int,
        default=0,
        help="Skip this many EpisodeService rows before applying --max-episodes.",
    )
    parser.add_argument("--after-episode-id", type=int, default=0)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--replay-only",
        action="store_true",
        help="Skip extracting per-seat observation logs from replay JSON.",
    )
    parser.add_argument(
        "--zip",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Create one battle-log ZIP after fetching (default: enabled).",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    data_dir = args.data_dir.resolve()
    submission_name = submission_storage_name(args.submission_id, args.version)
    submission_dir = data_dir / "submissions" / submission_name
    replay_dir = data_dir / "replays" / submission_name
    log_dir = data_dir / "logs" / submission_name
    submission_dir.mkdir(parents=True, exist_ok=True)
    replay_dir.mkdir(parents=True, exist_ok=True)
    if not args.replay_only:
        log_dir.mkdir(parents=True, exist_ok=True)

    print(f"Submission ID: {args.submission_id}")
    print(f"Submission metadata: {submission_dir}")
    print("Discovering Episodes from Kaggle...")
    episodes, raw_response = list_submission_episodes(args.submission_id)
    discovered_count = len(episodes)
    _write_json(submission_dir / "episode_service_response.json", raw_response)

    if args.after_episode_id > 0:
        episodes = [episode for episode in episodes if episode.episode_id > args.after_episode_id]
    if args.skip_episodes > 0:
        episodes = episodes[args.skip_episodes :]
    if args.max_episodes > 0:
        episodes = episodes[: args.max_episodes]

    _write_csv(
        submission_dir / "episodes.csv",
        episodes,
        list(EpisodeRecord.__dataclass_fields__),
    )
    if not episodes:
        print(
            "No Episodes were returned. The submission may not have played yet, or the Episode is not publicly visible."
        )
        return 2

    print(f"Episodes selected: {len(episodes)} (discovered: {discovered_count})")
    manifest: list[DownloadRecord] = []

    for number, episode in enumerate(episodes, start=1):
        print(f"[{number}/{len(episodes)}] Episode {episode.episode_id} (state={episode.state or 'unknown'})")
        replay_path = replay_dir / f"episode_{episode.episode_id}.json"
        episode_log_dir = log_dir / f"episode_{episode.episode_id}"
        replay_status = "not_attempted"
        log_statuses = ["not_attempted", "not_attempted"]
        errors: list[str] = []
        replay: dict[str, Any] = {}

        try:
            replay_status, replay = download_replay(
                episode.episode_id,
                replay_path,
                overwrite=args.overwrite,
            )
            print(f"  replay: {replay_status}")
        except Exception as exc:  # Continue so one unavailable episode is visible.
            replay_status = "failed"
            errors.append(f"replay: {type(exc).__name__}: {exc}")
            print(f"  replay: FAILED: {exc}")

        seat = detect_submission_seat(episode, replay, args.submission_id)
        summary = summarize_replay(replay, seat)
        if args.replay_only:
            log_statuses = ["skipped_replay_only", "skipped_replay_only"]
        elif replay:
            for agent_index in (0, 1):
                path = episode_log_dir / f"agent_{agent_index}_observation_logs.json"
                try:
                    log_statuses[agent_index] = save_observation_logs(
                        episode.episode_id,
                        replay,
                        agent_index,
                        path,
                        overwrite=args.overwrite,
                    )
                    print(f"  agent {agent_index} logs: {log_statuses[agent_index]}")
                except Exception as exc:  # Keep the other seat and later episodes.
                    log_statuses[agent_index] = "failed"
                    errors.append(f"agent_{agent_index}: {type(exc).__name__}: {exc}")
        else:
            log_statuses = ["failed_no_replay", "failed_no_replay"]

        own_log_path = ""
        if seat in (0, 1) and not args.replay_only:
            own_log_path = _relative(episode_log_dir / f"agent_{seat}_observation_logs.json", data_dir)
        manifest.append(
            DownloadRecord(
                submission_id=args.submission_id,
                episode_id=episode.episode_id,
                episode_state=episode.state,
                submission_seat="" if seat is None else str(seat),
                opponent_submission_id=_text(summary["opponent_submission_id"]),
                team_name=_text(summary["team_name"]),
                opponent_team_name=_text(summary["opponent_team_name"]),
                result=_text(summary["result"]),
                own_reward=_text(summary["own_reward"]),
                opponent_reward=_text(summary["opponent_reward"]),
                step_count=int(summary["step_count"]),
                replay_status=replay_status,
                agent_0_log_status=log_statuses[0],
                agent_1_log_status=log_statuses[1],
                replay_path=_relative(replay_path, data_dir) if replay else "",
                log_path=own_log_path,
                error=" | ".join(errors),
            )
        )
        _write_csv(
            submission_dir / "manifest.csv",
            manifest,
            list(DownloadRecord.__dataclass_fields__),
        )
        if number < len(episodes) and args.sleep > 0:
            time.sleep(args.sleep)

    result_counts = {
        result: sum(row.result == result for row in manifest) for result in ("win", "loss", "draw", "unknown")
    }
    failure_count = sum(bool(row.error) for row in manifest)
    metadata = {
        "competition": "kaggriculture",
        "submission_id": args.submission_id,
        "agent_version": args.version,
        "reported_rating": args.rating,
        "reported_rating_source": "user-provided" if args.rating is not None else "",
        "fetched_at_utc": datetime.now(UTC).isoformat(),
        "episode_source": LIST_EPISODES_URL,
        "replay_source_template": REPLAY_URL,
        "episodes_discovered": discovered_count,
        "episodes_selected": len(episodes),
        "replays_available": sum(row.replay_status in {"downloaded", "skipped_existing"} for row in manifest),
        "episodes_with_errors": failure_count,
        "results": result_counts,
        "paths": {
            "episodes": _relative(submission_dir / "episodes.csv", data_dir),
            "manifest": _relative(submission_dir / "manifest.csv", data_dir),
            "replays": _relative(replay_dir, data_dir),
            "logs": "" if args.replay_only else _relative(log_dir, data_dir),
            "archive": (
                _relative(
                    submission_dir / f"{submission_name}_battle_logs.zip",
                    data_dir,
                )
                if args.zip
                else ""
            ),
        },
    }
    _write_json(submission_dir / "metadata.json", metadata)

    archive_path: Path | None = None
    archived_file_count = 0
    if args.zip:
        archive_path, archived_file_count = create_battle_log_archive(
            data_dir=data_dir,
            submission_name=submission_name,
            submission_dir=submission_dir,
            replay_dir=replay_dir,
            log_dir=log_dir,
            episode_ids=(row.episode_id for row in manifest),
            include_logs=not args.replay_only,
        )

    print("\n=== Summary ===")
    print(f"Replays: {metadata['replays_available']}/{len(manifest)}")
    print(
        "Results: "
        f"{result_counts['win']}W-{result_counts['loss']}L-"
        f"{result_counts['draw']}D ({result_counts['unknown']} unknown)"
    )
    print(f"Episodes with errors: {failure_count}")
    print(f"Manifest: {submission_dir / 'manifest.csv'}")
    if archive_path is not None:
        print(f"Battle-log ZIP: {archive_path} ({archived_file_count} files, {archive_path.stat().st_size} bytes)")
    return 1 if failure_count else 0


def main() -> None:
    raise SystemExit(run(build_parser().parse_args()))


if __name__ == "__main__":
    main()
