from __future__ import annotations

"""Bounded Stage-B analytics evidence orchestration."""

from collections import defaultdict
from typing import Any, Mapping, Sequence

from src.models.v12_availability_evidence import build_availability_state
from src.models.v12_defcon_probability import (
    build_defcon_context,
    project_defcon_hit_probability,
)
from src.models.v12_role_duty_evidence import build_role_duty_evidence


def _player_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("player_id")
    if value is None:
        value = row.get("element")
    if value is None:
        value = row.get("official_element_id")
    if value is None:
        return None
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return None


def _position(player: Mapping[str, Any]) -> str:
    mapping = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
    try:
        return mapping.get(int(player.get("element_type") or 0), "UNKNOWN")
    except (TypeError, ValueError):
        return "UNKNOWN"


def build_stage_b_evidence_snapshot(
    *,
    bootstrap: Mapping[str, Any],
    player_match_rows: Sequence[Mapping[str, Any]],
    supplemental_players: Mapping[str, Mapping[str, Any]] | None = None,
    xmins_by_player: Mapping[str, Mapping[str, Any]] | None = None,
    upcoming_by_player: Mapping[str, Mapping[str, Any]] | None = None,
    availability_events_by_player: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    external_role_claims_by_player: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    snapshot_timestamp: str | None = None,
    now_iso: str | None = None,
) -> dict[str, Any]:
    supplemental_players = supplemental_players or {}
    xmins_by_player = xmins_by_player or {}
    upcoming_by_player = upcoming_by_player or {}
    availability_events_by_player = availability_events_by_player or {}
    external_role_claims_by_player = external_role_claims_by_player or {}

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in player_match_rows:
        if not isinstance(raw, Mapping):
            continue
        key = _player_id(raw)
        if key:
            grouped[key].append(dict(raw))

    defcon_context = build_defcon_context(player_match_rows)
    players: dict[str, Any] = {}
    for player in bootstrap.get("elements") or []:
        if not isinstance(player, Mapping) or player.get("id") is None:
            continue
        try:
            element = str(int(player["id"]))
        except (TypeError, ValueError):
            continue
        rows = grouped.get(element, [])
        supplemental = dict(supplemental_players.get(element) or {})
        xmins = dict(xmins_by_player.get(element) or {})
        upcoming = dict(upcoming_by_player.get(element) or {})
        role = build_role_duty_evidence(
            player,
            match_rows=rows,
            observed_role=supplemental.get("tactical_role"),
            xmins=xmins,
            external_claims=external_role_claims_by_player.get(element) or (),
        )
        availability = build_availability_state(
            player,
            events=availability_events_by_player.get(element) or (),
            snapshot_timestamp=snapshot_timestamp,
            now_iso=now_iso,
        )
        home = upcoming.get("home")
        home_value = home if isinstance(home, bool) else None
        try:
            opponent = (
                None
                if upcoming.get("opponent_team_id") is None
                else int(upcoming.get("opponent_team_id"))
            )
        except (TypeError, ValueError):
            opponent = None

        defcon = project_defcon_hit_probability(
            rows,
            position=_position(player),
            xmins=xmins,
            home=home_value,
            opponent_team_id=opponent,
            context=defcon_context,
            role_evidence={
                "actual_tactical_role": (
                    role.get("derived", {})
                    .get("actual_tactical_role", {})
                    .get("value")
                ),
                "actual_tactical_role_class": "DERIVED",
            },
        )
        players[element] = {
            "element": int(element),
            "availability": availability,
            "role_duty": role,
            "defcon": defcon,
        }

    return {
        "contract": "V12_STAGE_B_EVIDENCE_SNAPSHOT_V1",
        "players": players,
        "player_count": len(players),
        "defcon_context": defcon_context,
        "governance": {
            "analytical_evidence_only": True,
            "p1_7_semantics_changed": False,
            "p1_2b_semantics_changed": False,
            "monte_carlo_architecture_changed": False,
            "identity_source_authority_changed": False,
            "scheduler_changed": False,
            "canonical_defcon_owner_replaced": False,
            "canonical_xmins_owner_replaced": False,
        },
    }
