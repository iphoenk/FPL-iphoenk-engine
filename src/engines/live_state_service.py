from __future__ import annotations

import json

from src.engines.base_state import bootstrap_maps, expanded_live
from src.utils import DATA, atomic_json, iso_now, read_json

OFFICIAL = DATA / "official_snapshot.json"
OUT = DATA / "live.json"


def run() -> dict:
    official = read_json(OFFICIAL, {})
    bootstrap = official.get("bootstrap") or {}
    if not bootstrap:
        raise RuntimeError("official_snapshot missing bootstrap")
    phase = official.get("phase") or {}
    picks = official.get("picks") or {}
    event_live = official.get("event_live") or {}
    teams, positions, by_id = bootstrap_maps(bootstrap)
    scoring_gw = phase.get("scoring_gw")
    payload = {"generated_at": iso_now(), "status": "IDLE", "scoring_gw": scoring_gw, "players": []}

    if picks and event_live:
        live_by = {int(row["id"]): row for row in event_live.get("elements") or []}
        detail = []
        gross = 0
        for pick in picks.get("picks") or []:
            element = int(pick["element"])
            player = by_id.get(element) or {}
            stats = expanded_live(live_by.get(element) or {})
            raw_points = int(stats.get("total_points") or 0)
            multiplier = int(pick.get("multiplier") or 0)
            if multiplier > 0:
                gross += raw_points * multiplier
            detail.append({
                "element": element,
                "name": player.get("web_name"),
                "team": teams.get(player.get("team")),
                "position": positions.get(player.get("element_type")),
                "pick_position": pick.get("position"),
                "multiplier": multiplier,
                "captain": pick.get("is_captain"),
                "vice": pick.get("is_vice_captain"),
                **stats,
            })
        hit = int((picks.get("entry_history") or {}).get("event_transfers_cost") or 0)
        payload = {
            "generated_at": iso_now(),
            "status": "PROVISIONAL" if phase.get("is_live_event") else "RECONCILED_OR_IDLE",
            "scoring_gw": scoring_gw,
            "gross_points": gross,
            "hit": hit,
            "net_points": gross - hit,
            "players": detail,
        }
    atomic_json(OUT, payload)
    return payload


if __name__ == "__main__":
    out = run()
    print(json.dumps({
        "status": out.get("status"),
        "scoring_gw": out.get("scoring_gw"),
        "net_points": out.get("net_points"),
    }, ensure_ascii=False))
