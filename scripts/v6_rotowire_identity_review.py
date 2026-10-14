"""Read-only RotoWire -> Official FPL identity review, never a verified bridge.

Provider-native IDs are stable but neither shared with FPL elements nor proof
of identity. All name/club matches are quarantined CANDIDATES, not joinable.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any

# Only display-label aliases for fixture/candidate discovery. No ID authority.
TEAM_ALIASES = {
    "afc bournemouth": "bournemouth",
    "brighton hove albion": "brighton",
    "leeds united": "leeds",
    "manchester city": "man city",
    "manchester united": "man utd",
    "newcastle united": "newcastle",
    "nottingham forest": "nott m forest",
    "tottenham hotspur": "spurs",
    "wolverhampton wanderers": "wolves",
    "west ham united": "west ham",
}
JOINABLE_STATUSES = frozenset(("EXACT", "VERIFIED_MANUAL"))


def _label(value: Any) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    normalized = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", normalized)).strip()


def _observed_fixture_time(key: str, source_effective_at: str) -> datetime | None:
    """Interpret explicitly labelled ET using New York DST for source year."""
    stamp = str(key).split("|", 1)[0].strip()
    if not stamp.endswith(" ET"):
        return None
    try:
        year = datetime.fromisoformat(source_effective_at.replace("Z", "+00:00")).year
        dt = datetime.strptime(f"{year} {stamp[:-3]}", "%Y %B %d %I:%M %p")
        return dt.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def build_review(
    rotowire: dict[str, Any],
    canonical_players: dict[str, Any],
    canonical_teams: dict[str, Any],
    canonical_fixtures: dict[str, Any],
    *,
    target_gw: int | None = None,
) -> dict[str, Any]:
    if rotowire.get("source_id") != "rotowire":
        raise ValueError("expected RotoWire normalized V6 payload")
    if canonical_players.get("authority") != "official_fpl":
        raise ValueError("expected Official FPL canonical players")
    if canonical_teams.get("authority") != "official_fpl":
        raise ValueError("expected Official FPL canonical teams")
    if canonical_fixtures.get("authority") != "official_fpl":
        raise ValueError("expected Official FPL canonical fixtures")

    groups = rotowire.get("record_groups") or {}
    if not all(isinstance(groups.get(k), list) for k in ("fixtures", "lineups", "availability")):
        raise ValueError("malformed RotoWire record groups")
    effective_at = str(rotowire.get("effective_at") or "")
    try:
        asof = datetime.fromisoformat(effective_at.replace("Z", "+00:00"))
        if asof.tzinfo is None:
            raise ValueError("naive source timestamp")
        asof = asof.astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError("RotoWire source effective_at must be timezone aware") from exc

    team_ids = {
        _label(t["name"]): int(t["official_fpl_team_id"])
        for t in canonical_teams.get("teams") or []
    }
    def team_id(label: Any) -> int | None:
        value = _label(label)
        return team_ids.get(TEAM_ALIASES.get(value, value))

    official_fixtures = defaultdict(list)
    for row in canonical_fixtures.get("fixtures") or []:
        try:
            at = datetime.fromisoformat(row["kickoff_time"].replace("Z", "+00:00"))
            key = (int(row["team_h"]), int(row["team_a"]), at.astimezone(timezone.utc))
            official_fixtures[key].append(row)
        except (KeyError, TypeError, ValueError):
            continue

    fixture_proof = {}
    for row in groups["fixtures"]:
        key = str(row.get("fixture_key") or "")
        h = team_id((row.get("home") or {}).get("name"))
        a = team_id((row.get("away") or {}).get("name"))
        at = _observed_fixture_time(key, effective_at)
        matches = official_fixtures.get((h, a, at), []) if h and a and at else []
        valid = len(matches) == 1 and at is not None and asof < at
        same_gw = valid and (target_gw is None or matches[0].get("event") == target_gw)
        fixture_status = ("FIXTURE_CANDIDATE_MATCHED" if same_gw else
                          "MATCHED_OTHER_GW" if valid else "FIXTURE_UNVERIFIED")
        fixture_proof[key] = {
            "status": fixture_status,
            "official_fixture_id_candidate": int(matches[0]["official_fpl_fixture_id"]) if valid else None,
            "gw_candidate": matches[0].get("event") if valid else None,
            "target_gw_eligible": bool(same_gw),
            "kickoff_utc": at.isoformat() if at is not None else None,
            "official_team_pair_resolved": h is not None and a is not None,
            "fixture_identity_joinable": False,
        }

    official_players = defaultdict(list)
    official_web_names = defaultdict(list)
    for p in canonical_players.get("players") or []:
        key = (int(p["team_id"]), _label(f"{p.get('first_name', '')} {p.get('second_name', '')}"))
        official_players[key].append(p)
        official_web_names[(int(p["team_id"]), _label(p.get("web_name")))].append(p)

    records = defaultdict(list)
    for group in ("lineups", "availability"):
        for row in groups[group]:
            if not isinstance(row, dict) or row.get("source_native_id") is None:
                continue
            records[str(row["source_native_id"])].append((group, row))

    output = []
    for native, observations in sorted(records.items(), key=lambda item: (0, int(item[0])) if item[0].isdigit() else (1, item[0])):
        names = {_label(x.get("player_name")) for _, x in observations}
        clubs = {_label(x.get("team_name")) for _, x in observations}
        group_names = sorted({group for group, _ in observations})
        first = observations[0][1]
        team = team_id(first.get("team_name"))
        matches = (official_players.get((team, next(iter(names))), [])
                   if team is not None and len(names) == 1 else [])
        candidate_basis = "FULL_CANONICAL_NAME_AND_CLUB" if len(matches) == 1 else None
        if not matches and team is not None and len(names) == 1:
            matches = official_web_names.get((team, next(iter(names))), [])
            if len(matches) == 1:
                candidate_basis = "OFFICIAL_WEB_NAME_AND_CLUB"
        matched_fixtures = sorted({
            fixture_proof.get(str(x.get("fixture_key") or ""), {}).get("official_fixture_id_candidate")
            for _, x in observations
            if fixture_proof.get(str(x.get("fixture_key") or ""), {}).get("status") == "FIXTURE_CANDIDATE_MATCHED"
        })
        if len(names) != 1 or len(clubs) != 1:
            status = "PROVIDER_ID_COLLISION"
        elif team is None:
            status = "TEAM_UNRESOLVED"
        elif len(matches) != 1:
            status = "NAME_TEAM_UNRESOLVED" if not matches else "AMBIGUOUS_OFFICIAL_PLAYER"
        elif not matched_fixtures:
            has_other_gw = any(
                fixture_proof.get(str(x.get("fixture_key") or ""), {}).get("status") == "MATCHED_OTHER_GW"
                for _, x in observations
            )
            status = "MATCHED_OTHER_GW" if has_other_gw else "FIXTURE_UNVERIFIED"
        else:
            status = "IDENTITY_CANDIDATE_REVIEW"
        player = matches[0] if len(matches) == 1 else {}
        output.append({
            "rotowire_native_id": first["source_native_id"],
            "rotowire_name": first.get("player_name"),
            "rotowire_team": first.get("team_name"),
            "official_fpl_element_candidate": player.get("official_fpl_element_id"),
            "official_fpl_code_candidate": player.get("official_code"),
            "official_team_candidate": team,
            "official_fixture_candidates": matched_fixtures,
            "source_groups": group_names,
            "provider_role_observed": sorted({str(x.get("position")) for _, x in observations if x.get("position")}),
            "provider_lineup_status": sorted({str(x.get("lineup_status")) for _, x in observations if x.get("lineup_status")}),
            "provider_availability_status": sorted({str(x.get("availability_status")) for _, x in observations if x.get("availability_status")}),
            "review_status": status,
            "candidate_basis": candidate_basis,
            "verification_status": "UNMAPPED",
            "joinable": False,
            "numeric_pstart_authority": False,
        })

    counts = {status: sum(row["review_status"] == status for row in output)
              for status in sorted({row["review_status"] for row in output})}
    return {
        "contract": "V6_ROTOWIRE_IDENTITY_REVIEW_CANDIDATES_V1",
        "authority": "ADVISORY_DISCOVERY_ONLY",
        "source_effective_at": effective_at,
        "source_snapshot_ids": rotowire.get("source_snapshot_ids") or [],
        "official_fpl_player_universe": len(canonical_players.get("players") or []),
        "provider_unique_player_ids": len(output),
        "provider_input_rows": len(groups["lineups"]) + len(groups["availability"]),
        "target_gw": target_gw,
        "fixture_matched_other_gw": sum(x["status"] == "MATCHED_OTHER_GW" for x in fixture_proof.values()),
        "candidate_counts": counts,
        "fixture_candidate_matches": sum(x["status"] == "FIXTURE_CANDIDATE_MATCHED" for x in fixture_proof.values()),
        "fixture_count": len(groups["fixtures"]),
        "fixtures": fixture_proof,
        "players": output,
        "governance": {
            "name_matching_cannot_verify_identity": True,
            "crosswalk_catalog_not_mutated": True,
            "manual_or_independent_provider_bridge_required": True,
            "historical_asof_not_established": True,
            "no_canonical_pstart_or_xmins_mutation": True,
            "predicted_lineup_is_not_observed_starter": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rotowire", "canonical-players", "canonical-teams", "canonical-fixtures", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--target-gw", type=int, default=None)
    args = parser.parse_args()
    def load(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))
    review = build_review(
        load(args.rotowire),
        load(args.canonical_players),
        load(args.canonical_teams),
        load(args.canonical_fixtures),
        target_gw=args.target_gw,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(review, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate_counts": review["candidate_counts"],
                      "official_fixture_candidates": review["fixture_candidate_matches"],
                      "canonical_joinable": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
