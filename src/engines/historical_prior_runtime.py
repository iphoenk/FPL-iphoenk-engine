from __future__ import annotations

import json

from src.engines.historical_prior_service import _fetch_previous_season, build_prior_index
from src.utils import DATA, atomic_json, read_json

OFFICIAL = DATA / "official_snapshot.json"
PRIOR_OUT = DATA / "prior_season.json"


def run() -> dict:
    official = read_json(OFFICIAL, {})
    bootstrap = official.get("bootstrap") or {}
    if not bootstrap:
        raise RuntimeError("official_snapshot missing bootstrap for historical prior runtime")
    payload, fetch_mode = _fetch_previous_season()
    prior = build_prior_index(list(bootstrap.get("elements") or []), payload)
    prior["fetch_mode"] = fetch_mode
    prior["source_health"] = ((official.get("endpoint_health") or {}).get("bootstrap") or {}).get("status")
    prior.setdefault("governance", {})["official_snapshot_reused"] = True
    atomic_json(PRIOR_OUT, prior)

    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {}).update({
        "prior_season": "data/prior_season.json",
        "vaastav_previous_season": "data/stats/vaastav_previous_season.json",
    })
    latest["historical_prior_summary"] = {
        "model": prior.get("model"),
        "season": prior.get("season"),
        "fetch_mode": fetch_mode,
        "coverage": prior.get("coverage"),
    }
    atomic_json(DATA / "latest.json", latest)
    return prior


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "model": out.get("model"),
        "season": out.get("season"),
        "fetch_mode": out.get("fetch_mode"),
        "coverage": out.get("coverage"),
    }, ensure_ascii=False))
