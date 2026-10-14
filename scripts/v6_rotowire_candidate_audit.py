#!/usr/bin/env python3
"""Read-only RotoWire -> Official FPL identity CANDIDATE audit.

Never creates a joinable crosswalk. The only route to verified mapping remains
config/v6/verified_crosswalks.json with independent provider-native evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TEAM_ALIASES = {
    "Manchester City": "Man City",
    "Manchester United": "Man Utd",
    "Newcastle United": "Newcastle",
    "Tottenham Hotspur": "Spurs",
    "Nottingham Forest": "Nott'm Forest",
    "Brighton & Hove Albion": "Brighton",
    "AFC Bournemouth": "Bournemouth",
    "Leeds United": "Leeds",
}
JOINABLE = False
_CONTRACT = "ROTOWIRE_OFFICIAL_CANDIDATE_AUDIT_V1"


def _key(value: Any) -> str:
    stripped = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^a-z0-9]", "", "".join(
        ch for ch in stripped if not unicodedata.combining(ch)
    ).casefold())


def _source_time(text: Any) -> datetime | None:
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _kickoff_utc(text: Any, anchor_year: int) -> datetime | None:
    if not isinstance(text, str) or " ET" not in text:
        return None
    try:
        parsed = datetime.strptime(f"{text} {anchor_year}", "%B %d %I:%M %p ET %Y")
        return parsed.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def build_rotowire_candidate_audit(
    official_snapshot: dict[str, Any],
    rotowire: dict[str, Any],
    *,
    target_gw: int,
) -> dict[str, Any]:
    """Audit observed native IDs without promoting guessed player links."""
    official = official_snapshot.get("official") or official_snapshot
    bootstrap = official.get("bootstrap") or {}
    elements = bootstrap.get("elements") or []
    official_teams = bootstrap.get("teams") or []
    official_fixtures = official.get("fixtures") or []
    groups = rotowire.get("record_groups") or {}

    official_by_name: dict[str, dict[str, Any]] = {}
    for team in official_teams:
        key = _key(team.get("name"))
        if key and key not in official_by_name:
            official_by_name[key] = team
    for source_name, official_name in TEAM_ALIASES.items():
        target = official_by_name.get(_key(official_name))
        if target is not None:
            official_by_name[_key(source_name)] = target

    # The name-and-club bridge is only a REVIEW CANDIDATE, never EXACT or
    # VERIFIED_MANUAL. It is not written back to V6's identity map.
    candidates: dict[tuple[int, str], dict[int, tuple[str, dict[str, Any]]]] = defaultdict(dict)
    for player in elements:
        try:
            team_id = int(player["team"])
            official_id = int(player["id"])
        except (KeyError, TypeError, ValueError):
            continue
        full = f"{player.get('first_name') or ''} {player.get('second_name') or ''}"
        alt = f"{player.get('first_name') or ''} {player.get('web_name') or ''}"
        names = [
            ("FULL_NAME_AND_CLUB", full),
            ("FIRST_AND_WEB_NAME_AND_CLUB", alt),
            ("OFFICIAL_SECOND_NAME_AND_CLUB", player.get("second_name")),
            ("WEB_NAME_AND_CLUB", player.get("web_name")),
        ]
        for method, name in names:
            key = _key(name)
            if key and official_id not in candidates[(team_id, key)]:
                candidates[(team_id, key)][official_id] = (method, player)

    source_asof = _source_time(rotowire.get("effective_at"))
    deadline_raw = next((x.get("deadline_time") for x in bootstrap.get("events") or []
                         if x.get("id") == target_gw), None)
    deadline = _source_time(deadline_raw)
    source_before_deadline = bool(source_asof and deadline and source_asof <= deadline)
    year = source_asof.year if source_asof else (deadline.year if deadline else 2026)

    fixtures: list[dict[str, Any]] = []
    fixture_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in groups.get("fixtures") or []:
        if not isinstance(raw, dict):
            continue
        home = official_by_name.get(_key((raw.get("home") or {}).get("name")))
        away = official_by_name.get(_key((raw.get("away") or {}).get("name")))
        kickoff = _kickoff_utc(raw.get("time_text"), year)
        matched = []
        if home and away and kickoff:
            for official_row in official_fixtures:
                ts = _source_time(official_row.get("kickoff_time"))
                if (official_row.get("team_h") == home.get("id")
                        and official_row.get("team_a") == away.get("id")
                        and ts == kickoff):
                    matched.append(official_row)
        if len(matched) == 1:
            official_row = matched[0]
            status = "GW_TARGET_FIXTURE_VERIFIED" if official_row.get("event") == target_gw else "OUT_OF_TARGET_GW"
        elif len(matched) > 1:
            official_row = None
            status = "AMBIGUOUS_FIXTURE"
        else:
            official_row = None
            status = "UNVERIFIED_FIXTURE"
        item = {
            "source_fixture_key": raw.get("fixture_key"),
            "source_native_fixture_id": raw.get("source_native_id"),
            "source_kickoff_text": raw.get("time_text"),
            "computed_utc_kickoff": kickoff.isoformat() if kickoff else None,
            "home_official_team_id": home.get("id") if home else None,
            "away_official_team_id": away.get("id") if away else None,
            "candidate_official_fixture_id": official_row.get("id") if official_row else None,
            "candidate_official_gw": official_row.get("event") if official_row else None,
            "fixture_status": status,
            "fixture_identity_verification": "TEAM_PAIR_AND_UTC_KICKOFF" if official_row else None,
            "gw_target_eligible": status == "GW_TARGET_FIXTURE_VERIFIED",
        }
        fixtures.append(item)
        fixture_by_key[str(raw.get("fixture_key") or "")].append(item)

    rows: list[dict[str, Any]] = []
    reverse: dict[str, set[int]] = defaultdict(set)
    for group in ("lineups", "availability"):
        for raw in groups.get(group) or []:
            if not isinstance(raw, dict):
                continue
            native = str(raw.get("source_native_id") or "").strip()
            source_fixture = str(raw.get("fixture_key") or "")
            observed_fixture = fixture_by_key.get(source_fixture) or []
            match = observed_fixture[0] if len(observed_fixture) == 1 else {}
            team = official_by_name.get(_key(raw.get("team_name")))
            found = candidates.get((int(team["id"]), _key(raw.get("player_name"))), {}) if team else {}
            candidate_id = next(iter(found)) if len(found) == 1 else None
            candidate = found.get(candidate_id) if candidate_id is not None else None
            if candidate_id is not None and native:
                reverse[native].add(candidate_id)
            if not native:
                status = "MISSING_NATIVE_PLAYER_ID"
            elif not team:
                status = "UNKNOWN_OFFICIAL_TEAM"
            elif len(found) > 1:
                status = "AMBIGUOUS_NAME_TEAM_CANDIDATE"
            elif candidate_id is None:
                status = "NO_EXACT_NAME_TEAM_CANDIDATE"
            else:
                status = "CANDIDATE_ONLY_NOT_VERIFIED"
            rows.append({
                "group": group,
                "rotowire_native_player_id": native or None,
                "rotowire_player_name": raw.get("player_name"),
                "rotowire_team_name": raw.get("team_name"),
                "rotowire_role": raw.get("position"),
                "rotowire_lineup_status": raw.get("lineup_status"),
                "rotowire_availability_status": raw.get("availability_status"),
                "source_fixture_key": source_fixture,
                "fixture_status": match.get("fixture_status", "UNVERIFIED_FIXTURE"),
                "candidate_official_fixture_id": match.get("candidate_official_fixture_id"),
                "candidate_official_element_id": candidate_id,
                "candidate_official_code": candidate[1].get("code") if candidate else None,
                "candidate_official_name": (f"{candidate[1].get('first_name') or ''} "
                                             f"{candidate[1].get('second_name') or ''}".strip()) if candidate else None,
                "candidate_method": candidate[0] if candidate else None,
                "candidate_status": status,
                "identity_status": "UNMAPPED",
                "joinable": JOINABLE,
                "model_admission": "FORBIDDEN_UNVERIFIED_PLAYER_IDENTITY",
                "predeadline_source": source_before_deadline,
            })

    conflicted_native = {k for k, ids in reverse.items() if len(ids) > 1}
    for row in rows:
        if row["rotowire_native_player_id"] in conflicted_native:
            row["candidate_status"] = "CONFLICTING_NATIVE_PLAYER_ID"
            row["candidate_official_element_id"] = None
            row["candidate_official_code"] = None
            row["candidate_official_name"] = None
            row["candidate_method"] = None

    per_native: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["rotowire_native_player_id"]:
            per_native[row["rotowire_native_player_id"]].append(row)
    unique_candidates = sum(
        1 for entries in per_native.values()
        if len({e["candidate_official_element_id"] for e in entries}) == 1
        and all(e["candidate_status"] == "CANDIDATE_ONLY_NOT_VERIFIED" for e in entries)
    )
    return {
        "contract": _CONTRACT,
        "canonical_authority": "official_fpl",
        "provider": "rotowire",
        "target_gw": target_gw,
        "official_deadline": deadline_raw,
        "rotowire_effective_at": rotowire.get("effective_at"),
        "rotowire_snapshot_ids": list(rotowire.get("source_snapshot_ids") or []),
        "official_checked_at": official_snapshot.get("checked_at"),
        "source_before_deadline": source_before_deadline,
        "identity_promotion": "NOT_AUTHORIZED",
        "calibrated_pstart_signal": False,
        "governance": {
            "read_only": True,
            "name_team_candidates_are_never_verified_links": True,
            "no_fuzzy_matching": True,
            "no_mutation_to_verified_crosswalk": True,
            "no_canonical_model_change": True,
            "fixture_admission_requires_team_pair_and_exact_utc_kickoff": True,
            "official_bootstrap_identity": "CANONICAL",
            "provider_lineup_predictions": "ADVISORY_UNCALIBRATED",
        },
        "summary": {
            "official_player_count": len(elements),
            "fixture_count": len(fixtures),
            "fixture_statuses": dict(Counter(e["fixture_status"] for e in fixtures)),
            "lineup_rows": len(groups.get("lineups") or []),
            "availability_rows": len(groups.get("availability") or []),
            "distinct_rotowire_player_ids": len(per_native),
            "distinct_name_team_candidates": unique_candidates,
            "candidate_statuses": dict(Counter(e["candidate_status"] for e in rows)),
            "verified_player_crosswalks_created": 0,
            "numeric_model_signals_applied": 0,
        },
        "fixtures": fixtures,
        "player_rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-data-root", type=Path, required=True)
    parser.add_argument("--target-gw", type=int, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    source = args.runtime_data_root / "data/v6"
    official = json.loads((source / "current/official_fpl.json").read_text(encoding="utf-8"))
    rotowire = json.loads((source / "normalized/sources/rotowire.json").read_text(encoding="utf-8"))
    result = build_rotowire_candidate_audit(official, rotowire, target_gw=args.target_gw)
    content = json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
