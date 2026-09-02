from __future__ import annotations

import json
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import requests

from src.intelligence.understat_tactical import _norm, _understat_players, normalize_player_evidence
from src.services.enrichment_service import _official_player_row
from src.sources import understat


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    bootstrap_response = session.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=20)
    bootstrap_response.raise_for_status()
    bootstrap = bootstrap_response.json()
    teams = {int(row["id"]): row["name"] for row in bootstrap.get("teams", [])}
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    meta = {
        "source": "bootstrap-static.elements",
        "source_snapshot_id": f"diag:{now}",
        "fetched_at": now,
        "observed_at": now,
        "freshness": "FRESH",
    }
    universe = [_official_player_row(player, teams, positions, meta) for player in bootstrap.get("elements", [])]
    identity_universe = [{**row, "name": row.get("full_name") or row.get("name")} for row in universe]
    raw = understat.sync(force=True, session=session)
    candidates = _understat_players(raw)
    _, unresolved = normalize_player_evidence(raw, identity_universe)
    official_by_id = {int(row["element"]): row for row in identity_universe}

    report = []
    for item in unresolved:
        official = official_by_id[int(item["element"])]
        team = _norm(official.get("team"))
        names = []
        for value in [official.get("name"), official.get("full_name"), official.get("web_name"), official.get("second_name"), *(official.get("name_variants") or [])]:
            normalized = _norm(value)
            if normalized and normalized not in names:
                names.append(normalized)
        def score(row: dict) -> float:
            candidate = row.get("normalized_name") or ""
            return max((SequenceMatcher(None, name, candidate).ratio() for name in names), default=0.0)
        team_rows = [row for row in candidates if team in (row.get("normalized_teams") or [])]
        top_team = sorted(team_rows, key=score, reverse=True)[:8]
        top_global = sorted(candidates, key=score, reverse=True)[:8]
        report.append({
            "element": item["element"],
            "official_name": official.get("name"),
            "web_name": official.get("web_name"),
            "second_name": official.get("second_name"),
            "team": official.get("team"),
            "normalized_names": names,
            "top_team": [
                {"name": row.get("name"), "teams": row.get("teams"), "normalized_name": row.get("normalized_name"), "score": round(score(row), 6)}
                for row in top_team
            ],
            "top_global": [
                {"name": row.get("name"), "teams": row.get("teams"), "normalized_name": row.get("normalized_name"), "score": round(score(row), 6)}
                for row in top_global
            ],
        })
    Path("verification/v4_understat_unresolved_candidates.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
