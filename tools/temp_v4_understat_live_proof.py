from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from src.engines.v4_official_fact_integrity import fact_defects
from src.intelligence.understat_tactical import normalize_player_evidence, normalize_team_evidence
from src.services.enrichment_service import _official_player_row
from src.sources import understat


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    session = requests.Session()
    response = session.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=20)
    response.raise_for_status()
    bootstrap = response.json()
    teams = {int(row["id"]): row["name"] for row in bootstrap.get("teams", [])}
    positions = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    meta = {
        "source": "bootstrap-static.elements",
        "source_snapshot_id": f"live-proof:{now}",
        "fetched_at": now,
        "observed_at": now,
        "freshness": "FRESH",
    }
    universe = [_official_player_row(player, teams, positions, meta) for player in bootstrap.get("elements", [])]
    identity_universe = [{**row, "name": row.get("full_name") or row.get("name")} for row in universe]

    raw = understat.sync(force=True, session=session)
    team_evidence = normalize_team_evidence(raw)
    mapped, unresolved = normalize_player_evidence(raw, identity_universe)

    official_count = len(universe)
    element_ids = [int(row.get("element_id") or 0) for row in universe]
    official_valid = sum(
        not fact_defects(row, expected_element=int(row.get("element_id") or 0))
        for row in universe
    )
    official_unique = len(set(element_ids))
    states: dict[str, int] = {}
    direct_ids: list[str] = []
    for row in mapped.values():
        state = (row.get("mapping") or {}).get("state") or "UNKNOWN"
        states[state] = states.get(state, 0) + 1
        if state == "RESOLVED":
            source_id = str(row.get("understat_player_id") or "")
            if source_id:
                direct_ids.append(source_id)

    direct_resolved = states.get("RESOLVED", 0)
    source_absent = states.get("SOURCE_ABSENT_CURRENT_SEASON", 0)
    source_present = direct_resolved + len(unresolved)
    id_counts = Counter(direct_ids)
    duplicate_direct_ids = sorted(source_id for source_id, count in id_counts.items() if count > 1)
    direct_ids_complete_unique = (
        len(direct_ids) == direct_resolved
        and len(set(direct_ids)) == direct_resolved
        and not duplicate_direct_ids
    )
    proof = {
        "generated_at": now,
        "official": {
            "count": official_count,
            "valid": official_valid,
            "unique_element_ids": official_unique,
            "valid_coverage": round(official_valid / max(1, official_count), 6),
            "unique_coverage": round(official_unique / max(1, official_count), 6),
            "team_count": len(teams),
        },
        "understat": {
            "source_availability": raw.get("source_availability"),
            "freshness": raw.get("freshness"),
            "schema_valid": raw.get("schema_valid"),
            "transport_revision": raw.get("transport_revision"),
            "team_mapping_count": len(team_evidence),
            "crosswalk_classified_count": len(mapped),
            "crosswalk_coverage": round(len(mapped) / max(1, official_count), 6),
            "direct_resolved_count": direct_resolved,
            "direct_understat_id_count": len(direct_ids),
            "direct_understat_unique_id_count": len(set(direct_ids)),
            "duplicate_direct_understat_ids": duplicate_direct_ids,
            "source_absent_current_season_count": source_absent,
            "source_present_official_count": source_present,
            "source_present_resolved_coverage": round(direct_resolved / max(1, source_present), 6),
            "identity_unresolved_count": len(unresolved),
            "state_counts": states,
            "identity_unresolved": unresolved,
        },
    }
    proof["acceptance"] = {
        "official_100_percent_valid": official_valid == official_count,
        "official_100_percent_unique": official_unique == official_count,
        "understat_available_fresh": (
            raw.get("source_availability") == "AVAILABLE"
            and raw.get("freshness") == "FRESH"
            and bool(raw.get("schema_valid"))
        ),
        "team_mapping_100_percent": len(team_evidence) == len(teams),
        "crosswalk_classified_100_percent": len(mapped) == official_count,
        "source_present_mapping_100_percent": len(unresolved) == 0,
        "direct_understat_ids_one_to_one": direct_ids_complete_unique,
        "no_fake_source_absent_mapping": direct_resolved + source_absent == official_count,
    }
    proof["acceptance"]["all_green"] = all(proof["acceptance"].values())

    path = Path("verification/v4_official_understat_identity_live_proof.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(proof, sort_keys=True))


if __name__ == "__main__":
    main()
