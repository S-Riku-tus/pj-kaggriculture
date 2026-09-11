"""Timestamped public metadata acquisition; no authenticated mutations."""

from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/current_field_20260910"
BASE = "https://www.kaggle.com"


def fetch(name, endpoint, payload):
    prior = OUT / f"{name}.json"
    if prior.is_file():
        saved = json.loads(prior.read_text(encoding="utf-8"))
        if saved.get("status") == 200:
            return saved
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
    session.get(BASE + "/competitions/kaggriculture/leaderboard", timeout=30)
    token = session.cookies.get("XSRF-TOKEN")
    if token:
        session.headers["X-XSRF-TOKEN"] = token
    response = session.post(BASE + "/api/i/" + endpoint, json=payload, timeout=45)
    try:
        data = response.json()
    except ValueError:
        data = {"non_json": response.text[:400]}
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    record = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "url": response.url,
        "payload": payload,
        "status": response.status_code,
        "data": data,
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"name": name, "status": response.status_code, "keys": list(data), "preview": str(data)[:350]},
            ensure_ascii=False,
        ),
        flush=True,
    )
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=["metadata", "notebooks", "top", "corpus", "sources", "readmes", "leaderboard_refresh"],
        default="metadata",
    )
    args = parser.parse_args()
    if args.mode == "leaderboard_refresh":
        fetch(
            "leaderboard_refresh_" + datetime.now(UTC).strftime("%Y%m%d"),
            "competitions.LeaderboardService/GetLeaderboard",
            {"competitionId": 147734},
        )
        return
    if args.mode == "readmes":
        repos = json.loads((OUT / "github_search.json").read_text(encoding="utf-8"))["items"][:28]
        directory = OUT / "public_readmes"
        directory.mkdir(exist_ok=True)

        def readme(repo):
            if repo["full_name"] == "S-Riku-tus/pj-kaggriculture":
                return
            url = f"https://raw.githubusercontent.com/{repo['full_name']}/{repo['default_branch']}/README.md"
            response = requests.get(url, timeout=30)
            (directory / (repo["full_name"].replace("/", "__") + ".md")).write_text(response.text, encoding="utf-8")
            print(repo["full_name"], response.status_code, len(response.content), flush=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(readme, repos))
        return
    if args.mode == "corpus":
        acquire_corpus()
        return
    if args.mode == "sources":
        for name, url in [
            (
                "github_search.json",
                "https://api.github.com/search/repositories?q=kaggriculture&sort=updated&per_page=50",
            ),
            (
                "official_engine.py",
                "https://raw.githubusercontent.com/Kaggle/kaggle-environments/master/kaggle_environments/envs/kaggriculture/kaggriculture.py",
            ),
        ]:
            response = requests.get(url, timeout=45)
            (OUT / name).write_bytes(response.content)
            print(
                name,
                response.status_code,
                len(response.content),
                hashlib.sha256(response.content).hexdigest(),
                flush=True,
            )
        return
    if args.mode == "top":
        board = json.loads((OUT / "leaderboard.json").read_text(encoding="utf-8"))["data"]
        jobs = [
            (
                f"episodes_{row['submissionId']}",
                "competitions.EpisodeService/ListEpisodes",
                {"submissionId": row["submissionId"]},
            )
            for row in board["publicLeaderboard"][:30]
        ]
        jobs += [
            (
                f"team_{row['teamId']}",
                "competitions.SubmissionService/ListTeamPublicSubmissions",
                {"teamId": row["teamId"]},
            )
            for row in board["publicLeaderboard"][:30]
        ]
        jobs += [("our_team", "competitions.SubmissionService/ListTeamPublicSubmissions", {"teamId": 16749257})]
        jobs += [
            (f"episodes_{sid}", "competitions.EpisodeService/ListEpisodes", {"submissionId": sid})
            for sid in [56089444, 55941525]
        ]
    else:
        jobs = (
            [
                ("leaderboard", "competitions.LeaderboardService/GetLeaderboard", {"competitionId": 147734}),
                ("competition", "competitions.CompetitionService/GetCompetition", {"competitionName": "kaggriculture"}),
                *[
                    (f"episodes_{sid}", "competitions.EpisodeService/ListEpisodes", {"submissionId": sid})
                    for sid in [55909167, 55912910, 55933145]
                ],
            ]
            if args.mode == "metadata"
            else [
                (
                    "kernel_adaptive",
                    "kernels.KernelsService/GetKernel",
                    {"userName": "reyhanksatria", "kernelSlug": "adaptive-route-agent-v2"},
                ),
                (
                    "output_adaptive",
                    "kernels.KernelsService/ListKernelSessionOutput",
                    {"userName": "reyhanksatria", "kernelSlug": "adaptive-route-agent-v2"},
                ),
                (
                    "kernel_tetsutani",
                    "kernels.KernelsService/GetKernel",
                    {"userName": "tetsutani", "kernelSlug": "read-the-town-build-the-farm-kaggriculture"},
                ),
            ]
        )
    if args.mode == "top":
        for job in jobs:
            try:
                prior = OUT / f"{job[0]}.json"
                if not prior.is_file() or json.loads(prior.read_text(encoding="utf-8")).get("status") != 200:
                    fetch(*job)
                    time.sleep(3)
            except Exception as exc:
                print(f"{job[0]} ERROR {exc}", flush=True)
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch, *job): job[0] for job in jobs}
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                print(f"{futures[future]} ERROR {type(exc).__name__}: {exc}", flush=True)


def acquire_corpus():
    board = json.loads((OUT / "leaderboard.json").read_text(encoding="utf-8"))["data"]["publicLeaderboard"]
    ranks = {row["submissionId"]: row["rank"] for row in board[:30]}
    selected, reserved = {}, {}
    for path in sorted(OUT.glob("episodes_*.json")):
        sid = int(path.stem.split("_")[1])
        episodes = json.loads(path.read_text(encoding="utf-8"))["data"].get("episodes", [])
        count = 8 if ranks.get(sid, 100) <= 3 else 4 if ranks.get(sid, 100) <= 10 else 1
        if sid in (55909167, 55912910):
            count = 1000
        if sid == 55933145:
            count = 30
        obtained = 0
        for episode in sorted(episodes, key=lambda row: row["id"], reverse=True):
            if episode.get("state") != "COMPLETED":
                continue
            eid = episode["id"]
            if sid in ranks and eid % 7 == 0:
                reserved[eid] = {
                    "episode_id": eid,
                    "episode_metadata": episode,
                    "dataset_role": "Fresh Holdout metadata only; NOT DOWNLOADED",
                }
                continue
            if obtained >= count:
                break
            selected[eid] = {
                "episode_id": eid,
                "episode_metadata": episode,
                "dataset_role": "Discovery",
                "selection_submission": sid,
            }
            obtained += 1
    reserved = {eid: row for eid, row in reserved.items() if eid not in selected}
    (OUT / "fresh_episode_reservations.json").write_text(
        json.dumps(list(reserved.values()), indent=2), encoding="utf-8"
    )
    cached = {int(path.stem.split("_")[-1]): path for path in (ROOT / "data/replays").glob("*/episode_*.json")}
    replay_dir = OUT / "replays"
    replay_dir.mkdir(exist_ok=True)

    def download(row):
        eid = row["episode_id"]
        path = cached.get(eid) or replay_dir / f"episode_{eid}.json.gz"
        if not path.exists():
            response = requests.get(f"https://www.kaggleusercontent.com/episodes/{eid}.json", timeout=60)
            response.raise_for_status()
            json.loads(response.content)
            with gzip.open(path, "wb", compresslevel=3) as handle:
                handle.write(response.content)
        row.update(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        print(f"episode {eid} stored", flush=True)
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(download, row): eid for eid, row in selected.items()}
        manifest = []
        for future in concurrent.futures.as_completed(futures):
            try:
                manifest.append(future.result())
            except Exception as exc:
                print(f"episode {futures[future]} ERROR {exc}", flush=True)
            (OUT / "discovery_manifest.jsonl").write_text(
                "".join(
                    json.dumps(row, ensure_ascii=False) + "\n"
                    for row in sorted(manifest, key=lambda row: row["episode_id"])
                ),
                encoding="utf-8",
            )


if __name__ == "__main__":
    main()
