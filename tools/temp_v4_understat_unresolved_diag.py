from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import requests

from src.intelligence.understat_tactical import _map_player, _norm, _understat_players, normalize_player_evidence
from src.services.enrichment_service import _official_player_row
from src.sources import understat


def _source_view(row: dict, score: float | None = None) -> dict:
    season = row.get("season_to_date") or {}
    out = {
        "understat_player_id": str(row.get("understat_player_id") or ""),
        "name": row.get("name"),
        "normalized_name": row.get("normalized_name"),
        "teams": row.get("teams"),
        "position": row.get("position"),
        "minutes": season.get("minutes"),
        "matches": season.get("matches"),
    }
    if score is not None:
        out["score"] = round(score, 6)
    return out


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

    proposals: dict[int, dict] = {}
    claimers: dict[str, list[dict]] = defaultdict(list)
    for official in identity_universe:
        element = int(official.get("element") or official.get("element_id") or 0)
        row, confidence, method = _map_player(official, candidates, {})
        proposal = {
            "element": element,
            "official_name": official.get("name"),
            "web_name": official.get("web_name"),
            "team": official.get("team"),
            "position": official.get("position"),
            "official_minutes": official.get("minutes"),
            "confidence": round(float(confidence or 0.0), 6),
            "method": method,
            "source": _source_view(row) if row else None,
        }
        proposals[element] = proposal
        if row and row.get("understat_player_id") is not None:
            claimers[str(row.get("understat_player_id"))].append(proposal)

    report = []
    for item in unresolved:
        official = official_by_id[int(item["element"])]
        team = _norm(official.get("team"))
        names = []
        for value in [
            official.get("name"), official.get("full_name"), official.get("web_name"),
            official.get("first_name"), official.get("second_name"), *(official.get("name_variants") or [])
        ]:
            normalized = _norm(value)
            if normalized and normalized not in names:
                names.append(normalized)

        def score(row: dict) -> float:
            candidate = row.get("normalized_name") or ""
            return max((SequenceMatcher(None, name, candidate).ratio() for name in names), default=0.0)

        team_rows = [row for row in candidates if team in (row.get("normalized_teams") or [])]
        top_team = sorted(team_rows, key=score, reverse=True)[:10]
        top_global = sorted(candidates, key=score, reverse=True)[:10]
        exact_global = [row for row in candidates if row.get("normalized_name") in names]
        proposal = proposals.get(int(item["element"])) or {}
        source_id = str(((proposal.get("source") or {}).get("understat_player_id")) or "")
        report.append({
            "element": item["element"],
            "unresolved_method": item.get("method"),
            "official_name": official.get("name"),
            "web_name": official.get("web_name"),
            "first_name": official.get("first_name"),
            "second_name": official.get("second_name"),
            "team": official.get("team"),
            "position": official.get("position"),
            "official_minutes": official.get("minutes"),
            "normalized_names": names,
            "pre_collision_proposal": proposal,
            "proposal_claimers": claimers.get(source_id, []) if source_id else [],
            "exact_global": [_source_view(row) for row in exact_global],
            "top_team": [_source_view(row, score(row)) for row in top_team],
            "top_global": [_source_view(row, score(row)) for row in top_global],
        })
    path = Path("verification/v4_understat_unresolved_candidates.json")
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
