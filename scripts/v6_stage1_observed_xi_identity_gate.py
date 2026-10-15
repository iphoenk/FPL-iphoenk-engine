#!/usr/bin/env python3
"""Fail-closed retrospective GW1-6 FotMob -> Official FPL observed XI gate.

Uses only V6 published snapshots/Official partitions. No HTTP or numeric model
effect. Historical postmatch identity PASS is not historical predeadline as-of.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_VERIFIED = {"EXACT", "VERIFIED_MANUAL"}


def _id(raw: Any) -> int | None:
    try:
        number = int(raw)
        return number if number > 0 and str(number) == str(raw) else None
    except (TypeError, ValueError):
        return None


def verify_observed_xi_identity(
    official: Mapping[str, Any],
    fotmob: Mapping[str, Any],
    partitions: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    if (official.get("source_id") != "official_fpl"
            or official.get("health") != "GREEN"
            or fotmob.get("source_id") != "fotmob"
            or fotmob.get("normalization_status") != "NORMALIZED"):
        raise ValueError("SOURCE_AUTHORITY_OR_NORMALIZATION_NOT_VERIFIED")
    original_fixtures = (official.get("official") or {}).get("fixtures") or []
    official_index = {}
    for fixture in original_fixtures:
        fid = _id(fixture.get("id"))
        if fid is None or fid in official_index:
            raise ValueError("OFFICIAL_FIXTURE_ID_CONFLICT")
        official_index[fid] = fixture
    expected_fixtures = {
        fid for fid, fixture in official_index.items()
        if _id(fixture.get("event")) in range(1, 7) and fixture.get("finished") is True
    }
    if len(expected_fixtures) != 60:
        raise ValueError("OFFICIAL_HISTORICAL_60_FIXTURES_NOT_FINAL")

    official_xi: dict[tuple[int, int], set[int]] = defaultdict(set)
    for gw in range(1, 7):
        partition = partitions.get(gw)
        if (not isinstance(partition, Mapping) or _id(partition.get("gw")) != gw
                or partition.get("authority") != "OFFICIAL_FPL"
                or (partition.get("coverage") or {}).get("status") != "PASS"
                or (partition.get("coverage") or {}).get("gw_official_finalized") is not True):
            raise ValueError(f"OFFICIAL_GW{gw}_PARTITION_NOT_VERIFIED")
        for pid_str, player in (partition.get("players") or {}).items():
            pid = _id(pid_str)
            if pid is None or _id(player.get("element_id")) != pid:
                raise ValueError("OFFICIAL_PLAYER_PARTITION_ID_INVALID")
            for observation in player.get("fixtures") or []:
                fid = _id(observation.get("fixture"))
                if fid is None or fid not in expected_fixtures:
                    continue
                if _id(official_index[fid].get("event")) != gw:
                    raise ValueError("OFFICIAL_GW_FIXTURE_INCONSISTENT")
                if observation.get("starts") != 1:
                    continue
                if observation.get("was_home") not in (True, False):
                    raise ValueError("OFFICIAL_STARTER_HOME_AWAY_MISSING")
                team_key = "team_h" if observation["was_home"] else "team_a"
                team_id = _id(official_index[fid].get(team_key))
                if team_id is None or pid in official_xi[(fid, team_id)]:
                    raise ValueError("OFFICIAL_STARTER_DUPLICATE")
                official_xi[(fid, team_id)].add(pid)

    tactics = ((fotmob.get("record_groups") or {}).get("match_tactics") or [])
    if len(tactics) != 60:
        raise ValueError("FOTMOB_NATIVE_MATCH_DETAILS_NOT_60")
    source_fixtures: set[int] = set()
    native_to_official: dict[int, int] = {}
    official_to_native: dict[int, int] = {}
    source_snapshots: set[str] = set()
    starters = 0
    for match in tactics:
        fid = _id(match.get("official_fixture_id"))
        digest = str(match.get("source_snapshot_sha256") or "")
        if (fid not in expected_fixtures or fid in source_fixtures
                or match.get("fixture_join") != "VERIFIED_NATIVE_TO_OFFICIAL"
                or not _DIGEST.fullmatch(digest)):
            raise ValueError("FOTMOB_ORIGINAL_FIXTURE_OR_SHA_NOT_VERIFIED")
        source_fixtures.add(fid)
        source_snapshots.add(digest)
        fixture = official_index[fid]
        sides = match.get("sides") or []
        if not isinstance(sides, list) or len(sides) != 2:
            raise ValueError("FOTMOB_MATCH_SIDES_NOT_TWO")
        seen_teams: set[int] = set()
        for side in sides:
            tid = _id(side.get("official_team_id"))
            coach = side.get("coach") or {}
            formation = side.get("formation")
            if (tid not in {_id(fixture.get("team_h")), _id(fixture.get("team_a"))}
                    or tid in seen_teams or not isinstance(coach.get("name"), str)
                    or not coach["name"].strip() or not _id(coach.get("source_native_id"))
                    or not isinstance(formation, str)
                    or not re.fullmatch(r"[1-9](?:-[1-9]){2,4}", formation)
                    or sum(int(x) for x in formation.split("-")) != 10):
                raise ValueError("FOTMOB_COACH_FORMATION_TEAM_NOT_VERIFIED")
            seen_teams.add(tid)
            rows = side.get("verified_official_starters") or []
            if (side.get("starting_xi_complete") is not True or len(rows) != 11
                    or side.get("unverified_provider_starter_ids")
                    or side.get("provider_starter_count") != 11):
                raise ValueError("FOTMOB_ELEVEN_VERIFIED_STARTERS_REQUIRED")
            observed = set()
            for row in rows:
                nid, eid = _id(row.get("source_native_player_id")), _id(row.get("official_element_id"))
                if (not nid or not eid or row.get("identity_status") not in _VERIFIED
                        or eid in observed):
                    raise ValueError("FOTMOB_PLAYER_ID_NOT_CERTIFIED")
                if (nid in native_to_official and native_to_official[nid] != eid
                        or eid in official_to_native and official_to_native[eid] != nid):
                    raise ValueError("FOTMOB_OFFICIAL_PLAYER_ID_COLLISION")
                native_to_official[nid] = eid
                official_to_native[eid] = nid
                observed.add(eid)
                starters += 1
            if observed != official_xi.get((fid, tid), set()):
                raise ValueError("OFFICIAL_FOTMOB_STARTING_XI_DISAGREEMENT")
    if source_fixtures != expected_fixtures or starters != 1320 or len(official_xi) != 120:
        raise ValueError("HISTORICAL_XI_SCOPE_NOT_FULL")
    return {
        "contract": "V12_STAGE1_OBSERVED_NATIVE_IDENTITY_ACCEPTANCE_V1",
        "status": "PASS",
        "fixture_count": 60,
        "team_fixture_count": 120,
        "official_starter_observations": 1320,
        "source_verified_starter_observations": starters,
        "unique_source_native_starter_players": len(native_to_official),
        "source_snapshot_sha256_count": len(source_snapshots),
        "identity_conflicts": 0,
        "official_lineup_conflicts": 0,
        "proof_scope": "POSTMATCH_GW1_GW6_OBSERVED_PLAYERS_ONLY",
        "unobserved_canonical_players_not_asserted_absent": True,
        "historical_predeadline_source_asof": "NOT_ESTABLISHED",
        "semantic_role_and_manager_probability_calibration": "NOT_ESTABLISHED",
        "numeric_pstart_effect": "NONE",
        "canonical_identity_mutated": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--fotmob", type=Path, required=True)
    parser.add_argument("--history-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    opts = parser.parse_args()
    load = lambda p: json.loads(p.read_text(encoding="utf-8"))
    proof = verify_observed_xi_identity(
        load(opts.official), load(opts.fotmob),
        {gw: load(opts.history_dir / f"official_gw_{gw}.json") for gw in range(1, 7)},
    )
    opts.out.parent.mkdir(parents=True, exist_ok=True)
    opts.out.write_text(json.dumps(proof, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, sort_keys=True))


if __name__ == "__main__":
    main()
