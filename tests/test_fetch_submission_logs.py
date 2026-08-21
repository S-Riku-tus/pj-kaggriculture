from __future__ import annotations

import zipfile

from scripts.fetch_submission_logs import (
    EpisodeRecord,
    create_battle_log_archive,
    detect_submission_seat,
    extract_observation_logs,
    parse_submission_episodes,
    submission_storage_name,
    summarize_replay,
)


def test_parse_submission_episodes_preserves_seats_scores_and_deduplicates() -> None:
    response = {
        "episodes": [
            {
                "id": 123,
                "state": "DONE",
                "agents": [
                    {
                        "index": 1,
                        "submissionId": 22,
                        "initialScore": {"value": 510.5},
                    },
                    {
                        "index": 0,
                        "submissionId": 11,
                        "updatedScore": 521.9,
                    },
                ],
            },
            {"id": "123"},
            {"id": "not-an-id"},
        ]
    }

    records = parse_submission_episodes(response)

    assert len(records) == 1
    assert records[0].agent_0_submission_id == "11"
    assert records[0].agent_1_submission_id == "22"
    assert records[0].agent_0_updated_score == "521.9"
    assert records[0].agent_1_initial_score == "510.5"


def test_extract_logs_keeps_only_steps_with_observation_logs() -> None:
    replay = {
        "steps": [
            [
                {"observation": {"logs": []}},
                {"observation": {"logs": ["opponent setup"]}},
            ],
            [
                {"observation": {"logs": ["our turn"]}},
                {"observation": {}},
            ],
        ]
    }

    assert extract_observation_logs(replay, 0) == [{"step": 1, "logs": ["our turn"]}]
    assert extract_observation_logs(replay, 1) == [{"step": 0, "logs": ["opponent setup"]}]


def test_detect_seat_prefers_episode_service_and_summarizes_result() -> None:
    episode = EpisodeRecord(
        episode_id=123,
        agent_0_submission_id="55649709",
        agent_1_submission_id="99",
    )
    replay = {
        "info": {
            "SubmissionIds": [55649709, 99],
            "TeamNames": ["v1", "other"],
        },
        "rewards": [1, -1],
        "steps": [[], [], []],
    }

    seat = detect_submission_seat(episode, replay, 55649709)
    summary = summarize_replay(replay, seat)

    assert seat == 0
    assert summary == {
        "opponent_submission_id": 99,
        "team_name": "v1",
        "opponent_team_name": "other",
        "result": "win",
        "own_reward": 1,
        "opponent_reward": -1,
        "step_count": 3,
    }


def test_submission_storage_name_includes_agent_version() -> None:
    assert submission_storage_name(55649709, "v1") == "v1_submission_55649709"
    assert submission_storage_name(55649709, "economic core/v2") == "economic_core_v2_submission_55649709"
    assert submission_storage_name(55649709, "") == "submission_55649709"


def test_create_battle_log_archive_preserves_data_layout(tmp_path) -> None:
    data_dir = tmp_path / "data"
    name = "v1_submission_55649709"
    submission_dir = data_dir / "submissions" / name
    replay_dir = data_dir / "replays" / name
    log_dir = data_dir / "logs" / name
    submission_dir.mkdir(parents=True)
    replay_dir.mkdir(parents=True)
    (log_dir / "episode_123").mkdir(parents=True)
    (submission_dir / "metadata.json").write_text("{}", encoding="utf-8")
    (submission_dir / "manifest.csv").write_text("episode_id\n123\n", encoding="utf-8")
    (replay_dir / "episode_123.json").write_text("{}", encoding="utf-8")
    (log_dir / "episode_123" / "agent_0_observation_logs.json").write_text("{}", encoding="utf-8")

    archive_path, file_count = create_battle_log_archive(
        data_dir=data_dir,
        submission_name=name,
        submission_dir=submission_dir,
        replay_dir=replay_dir,
        log_dir=log_dir,
        episode_ids=[123],
        include_logs=True,
    )

    assert file_count == 4
    with zipfile.ZipFile(archive_path) as archive:
        assert set(archive.namelist()) == {
            f"{name}/data/submissions/{name}/metadata.json",
            f"{name}/data/submissions/{name}/manifest.csv",
            f"{name}/data/replays/{name}/episode_123.json",
            f"{name}/data/logs/{name}/episode_123/agent_0_observation_logs.json",
        }
