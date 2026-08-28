from __future__ import annotations

import json
from collections import Counter
from typing import Any

from src.utils import DATA, atomic_json, iso_now, read_json

TEAM_OUT = DATA / "tactical_team_profiles.json"
ROLE_OUT = DATA / "player_role_profiles.json"
RECENT_OUT = DATA / "recent_tactical_form.json"


def _team_names(official: dict[str, Any]) -> dict[int, str]:
    bootstrap = official.get("bootstrap") or {}
    out: dict[int, str] = {}
    for row in bootstrap.get("teams") or []:
        try:
            team_id = int(row.get("id") or -1)
        except (TypeError, ValueError):
            continue
        if team_id > 0:
            out[team_id] = str(row.get("name") or row.get("short_name") or team_id)
    return out


def _formation_variants(system: dict[str, Any]) -> list[str]:
    shapes = [
        str(row.get("fpl_position_shape"))
        for row in system.get("matches") or []
        if row.get("valid") and row.get("fpl_position_shape")
    ]
    return [shape for shape, _ in Counter(shapes).most_common()]


def build() -> dict[str, dict[str, Any]]:
    official = read_json(DATA / "official_snapshot.json", {})
    features = read_json(DATA / "player_features.json", {})
    if features.get("contract") != "PLAYER_FEATURE_CONTRACT_V1":
        raise RuntimeError("tactical context requires canonical PLAYER_FEATURE_CONTRACT_V1")
    names = _team_names(official)
    systems = features.get("team_system_context") or {}
    players = features.get("players") or {}
    generated_at = iso_now()

    team_rows: dict[str, Any] = {}
    for team_id, name in sorted(names.items()):
        system = systems.get(str(team_id)) or {}
        team_rows[str(team_id)] = {
            "team_id": team_id,
            "team_name": name,
            "coach": None,
            "base_formation": system.get("dominant_shape"),
            "formation_variants": _formation_variants(system),
            "build_up": None,
            "pressing": None,
            "defensive_line": None,
            "width": None,
            "transition": None,
            "set_piece_profile": None,
            "vulnerabilities": [],
            "strengths": [],
            "evidence": {
                "class": "OBSERVED_FPL_POSITION_SHAPE",
                "confidence": system.get("confidence") or "NONE",
                "valid_matches": int(system.get("valid_matches") or 0),
                "observed_matches": int(system.get("observed_matches") or 0),
                "shape_consistency": float(system.get("shape_consistency") or 0.0),
                "not_true_tactical_formation": True,
                "source": "PLAYER_FEATURE_CONTRACT_V1.team_system_context",
            },
        }

    role_rows: dict[str, Any] = {}
    assessed = 0
    for key, player in players.items():
        role = player.get("tactical_role") or {}
        profile = role.get("profile")
        if profile and profile != "UNASSESSED":
            assessed += 1
        role_rows[str(key)] = {
            "element": int(player.get("element") or key),
            "name": player.get("name"),
            "team_id": int(player.get("team_id") or -1),
            "position": player.get("position"),
            "role": profile if profile and profile != "UNASSESSED" else None,
            "zones": [],
            "set_pieces": None,
            "penalties": None,
            "progression_route": None,
            "return_routes": [],
            "confidence": role.get("confidence") or "NONE",
            "sample_quality": role.get("sample_quality"),
            "evidence_minutes": role.get("evidence_minutes"),
            "metrics": role.get("metrics") or {},
            "reason": role.get("reason"),
            "evidence": {
                "class": "OBSERVED_ADVANCED_ROLE_PROFILE" if profile and profile != "UNASSESSED" else "NO_ADVANCED_ROLE_EVIDENCE",
                "decision_influence": "ADVISORY_ONLY",
                "source": ((player.get("provenance") or {}).get("tactical_role")),
            },
        }

    teams = len(team_rows)
    team_profiles = {
        "schema_version": 1,
        "contract": "TACTICAL_TEAM_PROFILES_V1",
        "generated_at": generated_at,
        "status": "PARTIAL_INTERNAL_EVIDENCE",
        "teams": team_rows,
        "governance": {
            "coach_style_not_inferred": True,
            "fpl_position_shape_not_claimed_as_true_tactical_formation": True,
            "missing_tactical_fields_are_explicit_null_or_empty": True,
            "external_verified_tactical_enrichment_may_extend_but_not_overwrite_canonical_identity": True,
        },
    }
    player_roles = {
        "schema_version": 1,
        "contract": "TACTICAL_PLAYER_ROLE_PROFILES_V1",
        "generated_at": generated_at,
        "status": "PARTIAL_INTERNAL_EVIDENCE",
        "players": role_rows,
        "assessed_players": assessed,
        "total_players": len(role_rows),
        "governance": {
            "role_profiles_are_observed_evidence_not_manager_declared_roles": True,
            "missing_routes_zones_setpieces_are_not_inferred": True,
            "advisory_only": True,
        },
    }
    recent_form = {
        "schema_version": 1,
        "contract": "RECENT_TACTICAL_FORM_V1",
        "generated_at": generated_at,
        "status": "NO_VERIFIED_RECENT_TACTICAL_PATTERN_ARTIFACT",
        "teams": {str(team_id): [] for team_id in sorted(names)},
        "governance": {
            "empty_is_valid_when_verified_recent_tactical_pattern_is_unavailable": True,
            "match_ids_are_not_guessed_into_gameweeks": True,
            "missing_pressing_or_chance_zone_evidence_is_never_fabricated": True,
        },
    }
    return {
        "team_profiles": team_profiles,
        "player_roles": player_roles,
        "recent_form": recent_form,
        "summary": {
            "generated_at": generated_at,
            "team_profiles": teams,
            "player_profiles": len(role_rows),
            "assessed_player_roles": assessed,
            "verified_recent_tactical_teams": 0,
            "status": "PARTIAL_INTERNAL_EVIDENCE",
        },
    }


def run() -> dict[str, Any]:
    out = build()
    atomic_json(TEAM_OUT, out["team_profiles"])
    atomic_json(ROLE_OUT, out["player_roles"])
    atomic_json(RECENT_OUT, out["recent_form"])
    latest = read_json(DATA / "latest.json", {})
    latest.setdefault("files", {}).update({
        "tactical_team_profiles": "data/tactical_team_profiles.json",
        "player_role_profiles": "data/player_role_profiles.json",
        "recent_tactical_form": "data/recent_tactical_form.json",
    })
    latest["tactical_context_summary"] = out["summary"]
    atomic_json(DATA / "latest.json", latest)
    print(json.dumps(out["summary"], ensure_ascii=False))
    return out["summary"]


if __name__ == "__main__":
    run()
