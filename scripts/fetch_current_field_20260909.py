"""Read-only public Kaggriculture acquisition; preserves prior artifacts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/current_field_20260909"
BASE = "https://www.kaggle.com"


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def session():
    sess = requests.Session()
    sess.headers.update({"User-Agent": "Mozilla/5.0 Kaggriculture-Research/1.0"})
    r = sess.get(BASE + "/competitions/kaggriculture/leaderboard", timeout=60)
    xsrf = sess.cookies.get("XSRF-TOKEN") or sess.cookies.get("CSRF-TOKEN")
    if xsrf:
        sess.headers["X-XSRF-TOKEN"] = xsrf
    return sess, r


def post(sess, endpoint, payload):
    r = sess.post(BASE + "/api/i/" + endpoint, json=payload, timeout=60)
    try:
        data = r.json()
    except ValueError:
        data = {"non_json_preview": r.text[:200]}
    return r.status_code, data


def probe():
    sess, page = session()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "leaderboard_page.html").write_text(page.text, encoding="utf-8")
    ids = sorted(set(re.findall(r'competitionId["\s:=]+(\d+)', page.text)))
    markers = [
        m.group(0) for m in re.finditer(r".{0,60}(?:competitionId|competition_id|leaderboard).{0,100}", page.text, re.I)
    ][:30]
    print(
        json.dumps(
            {"status": page.status_code, "bytes": len(page.content), "competition_ids": ids, "markers": markers},
            ensure_ascii=False,
        )
    )
    results = []
    payloads = [{"competitionName": "kaggriculture", "pageSize": 200}]
    payloads += [{"competitionId": int(i), "pageSize": 200} for i in ids]
    for endpoint in [
        "competitions.LeaderboardService/GetLeaderboard",
        "competitions.CompetitionService/GetCompetition",
        "competitions.CompetitionApiService/GetLeaderboard",
    ]:
        for payload in payloads:
            status, data = post(sess, endpoint, payload)
            row = {"endpoint": endpoint, "payload": payload, "status": status, "data": data}
            results.append(row)
            print(
                json.dumps(
                    {k: v for k, v in row.items() if k != "data"}
                    | {
                        "keys": list(data) if isinstance(data, dict) else type(data).__name__,
                        "preview": str(data)[:500],
                    },
                    ensure_ascii=False,
                )
            )
    save(OUT / "api_probe.json", results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["probe"])
    args = parser.parse_args()
    probe()
