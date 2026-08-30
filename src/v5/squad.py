from __future__ import annotations

from typing import Any, Iterable

from src.rules import ELEMENT_TYPE_TO_POSITION, SQUAD_RULES
from src.v5.config_cache import load_json_config
from src.v5.state import authority_chain as phase_authority_chain

REGISTRY_CONFIG = "config/v5_squad_registry.json"


def _cfg() -> dict[str, Any]:
    return load_json_config(REGISTRY_CONFIG)


def bootstrap_maps(bootstrap: dict):
    players = {int(p["id"]): p for p in bootstrap.get("elements", []) if p.get("id") is not None}
    teams = {int(t["id"]): str(t.get("name")) for t in bootstrap.get("teams", []) if t.get("id") is not None}
    return players, teams


def _row(player: dict, teams: dict[int, str], source: str, purchase_cost=None) -> dict:
    return {
        "element": int(player["id"]),
        "name": player.get("web_name"),
        "team_id": int(player["team"]),
        "team": teams.get(int(player["team"])),
        "position": ELEMENT_TYPE_TO_POSITION[int(player["element_type"])],
        "purchase_cost": int(purchase_cost) if purchase_cost is not None else None,
        "source": source,
    }


def resolve_locked_squad(lock: dict, bootstrap: dict) -> tuple[dict, ...]:
    players, teams = bootstrap_maps(bootstrap)
    out = []
    seen = set()
    for source_row in lock.get("players", []) or []:
        eid = int(source_row["element"])
        player = players.get(eid)
        if player is None or eid in seen:
            raise RuntimeError(f"invalid locked element: {eid}")
        seen.add(eid)
        position = ELEMENT_TYPE_TO_POSITION[int(player["element_type"])]
        team = teams.get(int(player["team"]))
        if source_row.get("position") and source_row["position"] != position:
            raise RuntimeError(f"locked position mismatch: {eid}")
        if source_row.get("expected_web_name") and source_row["expected_web_name"] != player.get("web_name"):
            raise RuntimeError(f"locked name mismatch: {eid}")
        if source_row.get("expected_team") and source_row["expected_team"] != team:
            raise RuntimeError(f"locked team mismatch: {eid}")
        out.append(_row(player, teams, "user_capture", source_row.get("purchase_cost")))
    return tuple(out)


def resolve_submitted_squad(picks: dict, bootstrap: dict) -> tuple[dict, ...]:
    players, teams = bootstrap_maps(bootstrap)
    out = []
    for pick in picks.get("picks", []) or []:
        player = players.get(int(pick["element"]))
        if player is not None:
            out.append(_row(player, teams, "official_submitted"))
    return tuple(out)


def resolve_authenticated_draft(my_team: dict, bootstrap: dict) -> tuple[dict, ...]:
    """Parse private draft diagnostics only. Authenticated Official is never squad authority."""
    players, teams = bootstrap_maps(bootstrap)
    out = []
    for pick in my_team.get("picks", []) or []:
        player = players.get(int(pick["element"]))
        if player is not None:
            out.append(_row(player, teams, "official_authenticated_enrichment", pick.get("purchase_price")))
    return tuple(out)


def validate_squad(squad: Iterable[dict]) -> dict[str, Any]:
    rows = tuple(squad)
    expected_counts = {str(k): int(v) for k, v in SQUAD_RULES["position_counts"].items()}
    ids = [int(row["element"]) for row in rows]
    counts = {pos: sum(row.get("position") == pos for row in rows) for pos in expected_counts}
    clubs = {}
    for row in rows:
        team = int(row["team_id"])
        clubs[team] = clubs.get(team, 0) + 1
    checks = {
        "squad_size": len(rows) == int(SQUAD_RULES["squad_size"]),
        "unique_elements": len(ids) == len(set(ids)),
        "position_counts": counts == expected_counts,
        "club_limit": max(clubs.values(), default=0) <= int(SQUAD_RULES["max_players_per_club"]),
    }
    result = {"passed": all(checks.values()), "checks": checks, "position_counts": counts, "club_counts": clubs}
    if not result["passed"] and bool(_cfg()["validation"].get("fail_closed", True)):
        raise RuntimeError(f"V5 squad validation failed: {result}")
    return result


def planning_override_state(
    lock: dict | None,
    *,
    planning_gw: int | None,
    submitted_gw: int | None,
) -> dict[str, Any]:
    """Resolve exact-target user-capture eligibility without masking Official public truth."""
    lock = lock if isinstance(lock, dict) else {}
    wildcard = bool(lock.get("wildcard_active"))
    free_hit = bool(lock.get("free_hit_active"))
    manual = bool(lock.get("planning_override_active"))
    requested = wildcard or free_hit or manual
    has_players = bool(lock.get("players"))
    target_raw = lock.get("target_gw")
    target_gw = None
    rejection_reason = None

    if requested and not has_players:
        rejection_reason = "NO_CAPTURE_PLAYERS"
    elif requested and target_raw is None:
        rejection_reason = "MISSING_TARGET_GW"
    elif target_raw is not None:
        try:
            target_gw = int(target_raw)
        except (TypeError, ValueError):
            rejection_reason = "INVALID_TARGET_GW" if requested else None

    planning = int(planning_gw) if planning_gw is not None else None
    submitted = int(submitted_gw) if submitted_gw is not None else None
    if requested and rejection_reason is None:
        if planning is None:
            rejection_reason = "UNKNOWN_PLANNING_GW"
        elif target_gw != planning:
            rejection_reason = "TARGET_GW_MISMATCH"
        elif submitted is not None and planning == submitted:
            rejection_reason = "OFFICIAL_SUBMITTED_RECLAIMS_AUTHORITY"

    applied = bool(requested and has_players and rejection_reason is None and target_gw == planning)
    if wildcard:
        kind = "WILDCARD"
    elif free_hit:
        kind = "FREE_HIT"
    elif manual:
        kind = "PLANNING_OVERRIDE"
    else:
        kind = "NONE"
    return {
        "planning_gw": planning,
        "baseline_gw": submitted,
        "primary_authority_model": "PUBLIC_OFFICIAL_PLUS_USER_CAPTURE",
        "default_authority": "official_public",
        "conditional_override_authority": "user_capture",
        "override_requested": requested,
        "override_kind": kind,
        "override_target_gw": target_gw,
        "override_applied": applied,
        "override_rejection_reason": rejection_reason,
        "effective_authority": "user_capture" if applied else "official_public",
        "stale_override_rejected": bool(requested and not applied),
        "post_deadline_official_reclaims_authority": rejection_reason == "OFFICIAL_SUBMITTED_RECLAIMS_AUTHORITY",
        "authenticated_official_is_private_enrichment_only": True,
    }


def _capture_is_current(lock: dict | None, planning_gw: int | None, submitted_gw: int | None) -> bool:
    return bool(
        planning_override_state(lock, planning_gw=planning_gw, submitted_gw=submitted_gw).get("override_applied")
    )


def select_squad(
    *,
    phase,
    bootstrap: dict,
    locked_squad=None,
    authenticated_my_team=None,
    submitted_picks=None,
    planning_gw: int | None = None,
    submitted_gw: int | None = None,
):
    baseline = planning_override_state(
        locked_squad,
        planning_gw=planning_gw,
        submitted_gw=submitted_gw,
    )
    capture_error = None
    for authority in phase_authority_chain(phase, "squad"):
        validation = None
        if authority in {"user_capture", "user_lock"}:
            if not baseline.get("override_applied") or not locked_squad:
                continue
            try:
                squad = resolve_locked_squad(locked_squad, bootstrap)
                validation = validate_squad(squad)
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                capture_error = str(exc)
                baseline = {
                    **baseline,
                    "override_applied": False,
                    "effective_authority": "official_public",
                    "invalid_override_rejected": True,
                    "override_rejection_reason": "INVALID_USER_CAPTURE",
                    "override_validation_error": capture_error,
                }
                continue
            effective_authority = "user_capture"
        elif authority == "official_public" and submitted_picks:
            squad = resolve_submitted_squad(submitted_picks, bootstrap)
            validation = validate_squad(squad) if squad else None
            effective_authority = "official_public"
        elif authority == "official_authenticated":
            # Historical registry snapshots may still contain this label. It is never decision authority.
            continue
        else:
            continue
        if squad:
            return {
                "authority": effective_authority,
                "squad": squad,
                "validation": validation or validate_squad(squad),
                "projection_baseline": baseline,
                "authority_policy": {
                    "model": "PUBLIC_OFFICIAL_PLUS_USER_CAPTURE",
                    "public_official": "DEFAULT_SUBMITTED_PLANNING_BASELINE",
                    "user_capture": "EXACT_TARGET_PREDEADLINE_OVERRIDE",
                    "authenticated_official": "OPTIONAL_PRIVATE_ENRICHMENT",
                    "authenticated_official_production_blocking": False,
                    "authenticated_official_must_not_select_squad": True,
                    "capture_current": bool(baseline.get("override_applied")),
                },
            }
    detail = f"; rejected user capture: {capture_error}" if capture_error else ""
    raise RuntimeError(f"no usable V5 squad authority for phase {phase}{detail}")


def reconcile_baseline(pre_deadline_squad: Iterable[dict], submitted_squad: Iterable[dict]) -> dict[str, Any]:
    pre = {int(row["element"]) for row in pre_deadline_squad}
    submitted = {int(row["element"]) for row in submitted_squad}
    return {
        "changed": pre != submitted,
        "additions": sorted(submitted - pre),
        "removals": sorted(pre - submitted),
        "unchanged": sorted(pre & submitted),
        "submitted_becomes_baseline": bool(_cfg()["reconciliation"].get("submitted_becomes_baseline_after_deadline", True)),
    }
