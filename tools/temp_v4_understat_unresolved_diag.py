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
    mapped, unresolved = normalize_player_evidence(raw, identity_universe)
    official_by_id = {int(row["element"]): row for row in identity_universe}

    accepted_source_ids = {
        str(row.get("understat_player_id"))
        for row in mapped.values()
        if (row.get("mapping") or {}).get("state") == "RESOLVED"
        and row.get("understat_player_id") is not None
    }
    unmatched_source = [
        row for row in candidates
        if str(row.get("understat_player_id")) not in accepted_source_ids
    ]
    unmatched_ids = {str(row.get("understat_player_id")) for row in unmatched_source}

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

        team_unmatched = [row for row in unmatched_source if team in (row.get("normalized_teams") or [])]
        exact_unmatched = [row for row in unmatched_source if row.get("normalized_name") in names]
        top_team = sorted(team_unmatched, key=score, reverse=True)[:5]
        top_global = sorted(unmatched_source, key=score, reverse=True)[:5]
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
            "pre_collision_proposal": proposal,
            "proposal_claimers": claimers.get(source_id, []) if source_id else [],
            "proposed_source_is_currently_unmatched": bool(source_id and source_id in unmatched_ids),
            "exact_unmatched": [_source_view(row) for row in exact_unmatched],
            "top_unmatched_team": [_source_view(row, score(row)) for row in top_team],
            "top_unmatched_global": [_source_view(row, score(row)) for row in top_global],
        })

    output = {
        "generated_at": now,
        "summary": {
            "official_count": len(identity_universe),
            "understat_source_player_count": len(candidates),
            "direct_resolved_unique_source_ids": len(accepted_source_ids),
            "unmatched_understat_source_count": len(unmatched_source),
            "identity_unresolved_count": len(unresolved),
        },
        "unmatched_source_players": [_source_view(row) for row in unmatched_source],
        "unresolved_official_players": report,
        "guardrails": {
            "diagnostic_only": True,
            "official_fpl_identity_authority": True,
            "player_specific_aliases": False,
            "candidate_set_is_only_unclaimed_understat_rows": True,
            "do_not_force_direct_match": True,
        },
    }
    path = Path("verification/v4_understat_unresolved_candidates.json")
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
