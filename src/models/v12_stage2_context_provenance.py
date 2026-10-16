"""Stage 2: independent, retrospective context provenance audit (advisory only).

Consumes the already-verified V6->V12 manager/formation/provider-slot ledger.
No provider slot may become a tactical role, current coach, or P(start) prior.
No hidden inference from missing observations. Only aggregates leave this audit.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from typing import Any

HEX_SHA = re.compile(r"^[0-9a-f]{64}$")
STATUS = frozenset({"a", "d", "i", "s", "u"})
REQUIRED_SCOPE = "GW1_GW6_POST_MATCH_RETROSPECTIVE_ONLY"


def audit_stage2_context_provenance(
    bootstrap: Mapping[str, Any],
    longitudinal: Mapping[str, Any],
    *,
    expected_players: int = 667,
    expected_clubs: int = 20,
) -> dict[str, Any]:
    """Verify player-specific observed sources without changing the model.

    Only exact Official IDs, original hashed V6 match observations and
    matching club identity are admitted. The output deliberately contains no
    per-player medical assumptions or numerical coach/role effect.
    """
    bootstrap_rows = bootstrap.get("elements") or []
    official: dict[int, Mapping[str, Any]] = {}
    reasons: Counter[str] = Counter()
    for row in bootstrap_rows:
        if not isinstance(row, Mapping):
            reasons["INVALID_OFFICIAL_ROW"] += 1
            continue
        pid, tid = row.get("id"), row.get("team")
        if type(pid) is not int or pid <= 0 or pid in official or type(tid) is not int or tid <= 0:
            reasons["OFFICIAL_PLAYER_IDENTITY_INVALID"] += 1
            continue
        official[pid] = row
    clubs = bootstrap.get("teams") or []
    club_ids = set()
    for row in clubs:
        tid = row.get("id") if isinstance(row, Mapping) else None
        if type(tid) is not int or tid <= 0 or tid in club_ids:
            reasons["OFFICIAL_CLUB_IDENTITY_INVALID"] += 1
        else:
            club_ids.add(tid)
    if len(official) != expected_players:
        reasons["OFFICIAL_UNIVERSE_INCOMPLETE"] += 1
    if len(club_ids) != expected_clubs:
        reasons["OFFICIAL_CLUB_UNIVERSE_INCOMPLETE"] += 1
    if any(row["team"] not in club_ids for row in official.values()):
        reasons["OFFICIAL_PLAYER_CLUB_UNKNOWN"] += 1

    observed = longitudinal.get("players") or []
    scope_ok = (
        longitudinal.get("contract") == "V12_ALLCLUB_MANAGER_ROLE_LONGITUDINAL_V1"
        and longitudinal.get("observation_scope") == REQUIRED_SCOPE
        and longitudinal.get("numeric_pstart_effect") == "NONE"
        and longitudinal.get("source_asof_before_historical_deadline_verified") is False
        and longitudinal.get("manager_start_effect_calibrated") is False
        and longitudinal.get("semantic_tactical_role_calibrated") is False
    )
    if not scope_ok:
        reasons["LONGITUDINAL_SOURCE_AUTHORITY_INVALID"] += 1
    verified_ids: set[int] = set()
    source_verified_players: set[int] = set()
    manager_players: set[int] = set()
    formation_players: set[int] = set()
    slot_players: set[int] = set()
    fixture_observations = 0
    for row in observed:
        if not isinstance(row, Mapping):
            reasons["LONGITUDINAL_PLAYER_ROW_INVALID"] += 1
            continue
        pid = row.get("element_id")
        if type(pid) is not int or pid not in official or pid in verified_ids:
            reasons["LONGITUDINAL_IDENTITY_DUPLICATE_OR_UNKNOWN"] += 1
            continue
        verified_ids.add(pid)
        if row.get("team_id") != official[pid]["team"]:
            reasons["LONGITUDINAL_CLUB_DRIFT"] += 1
            continue
        if (
            row.get("provider_position_id_semantics") != "SOURCE_NATIVE_OPAQUE_ONLY"
            or row.get("semantic_role") is not None
            or row.get("target_gw_manager_fit_probability") is not None
            or row.get("target_gw_role_start_probability") is not None
            or row.get("numeric_pstart_effect") != "NONE"
        ):
            reasons["UNVERIFIED_TACTICAL_OR_NUMERIC_PROMOTION"] += 1
            continue
        games = row.get("history")
        if not isinstance(games, list):
            reasons["MATCH_HISTORY_MISSING"] += 1
            continue
        seen_fixtures: set[int] = set()
        valid_games: list[Mapping[str, Any]] = []
        bad = False
        for game in games:
            if not isinstance(game, Mapping):
                bad = True
                break
            fid, gw, tid = game.get("fixture_id"), game.get("gw"), game.get("team_id")
            if (
                type(fid) is not int or fid <= 0 or fid in seen_fixtures
                or type(gw) is not int or not 1 <= gw <= 6
                or tid != official[pid]["team"]
                or not HEX_SHA.fullmatch(str(game.get("source_snapshot_sha256") or ""))
                or not str(game.get("formation") or "").strip()
            ):
                bad = True
                break
            seen_fixtures.add(fid)
            valid_games.append(game)
        if bad:
            reasons["SOURCE_MATCH_FIXTURE_SHA_INVALID"] += 1
            continue
        if valid_games:
            source_verified_players.add(pid)
            fixture_observations += len(valid_games)
            formation_players.add(pid)
            if any(type(game.get("manager_native_id")) is int and game["manager_native_id"] > 0 for game in valid_games):
                manager_players.add(pid)
            if any(type(game.get("provider_position_id")) is int and game["provider_position_id"] > 0 for game in valid_games):
                slot_players.add(pid)
    # A missing player row is not a missing Official player; it does mean this
    # retrospective ledger cannot be declared fully integrity-admitted.
    if verified_ids != set(official):
        reasons["LONGITUDINAL_PLAYER_UNIVERSE_INCOMPLETE"] += 1
    observed_status = sum(
        str(row.get("status") or "").strip().lower() in STATUS
        for row in official.values()
    )
    if observed_status != len(official):
        reasons["OFFICIAL_STATUS_PARTIAL"] += 1
    admission_ok = not reasons and scope_ok
    return {
        "contract": "V12_STAGE2_CONTEXT_SOURCE_PROVENANCE_V1",
        "mode": "SHADOW_ONLY",
        "source_integrity_state": "PASS" if admission_ok else "PARTIAL",
        "official_universe_count": len(official),
        "official_club_count": len(club_ids),
        "observed_official_status_players": observed_status,
        "status_is_not_medical_clearance": True,
        "historical_source_players": len(source_verified_players),
        "historical_match_player_observations": fixture_observations,
        "verified_manager_history_players": len(manager_players),
        "verified_formation_history_players": len(formation_players),
        "verified_opaque_provider_slot_players": len(slot_players),
        "verified_semantic_tactical_role_players": 0,
        "verified_target_gw_manager_effect_players": 0,
        "verified_medical_predeadline_players": 0,
        "source_rejections": dict(sorted(reasons.items())),
        "source_cutoff_authority": "RETROSPECTIVE_MATCH_ONLY",
        "historical_predeadline_model_witness": "NOT_ESTABLISHED",
        "oos_calibration": "PENDING_SETTLED_GW7",
        "numeric_pstart_effect": "NONE",
        "numeric_xmins_effect": "NONE",
        "production_activation_allowed": False,
        "new_scheduler": False,
    }
