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
        out.append(_row(player, teams, "user_lock", source_row.get("purchase_cost")))
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
    players, teams = bootstrap_maps(bootstrap)
    out = []
    for pick in my_team.get("picks", []) or []:
        player = players.get(int(pick["element"]))
        if player is not None:
            out.append(_row(player, teams, "official_authenticated", pick.get("purchase_price")))
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


def projection_baseline_authority(
    lock: dict | None,
    *,
    planning_gw: int | None,
    submitted_gw: int | None,
) -> dict[str, Any]:
    lock = lock if isinstance(lock, dict) else {}
    policy = _cfg().get("planning_override") or {}
    wildcard = bool(lock.get("wildcard_active"))
    free_hit = bool(lock.get("free_hit_active"))
    manual = bool(lock.get("planning_override_active"))
    override_requested = bool(policy.get("enabled", True)) and (wildcard or free_hit or manual)
    target_raw = lock.get("target_gw")
    if override_requested and bool(policy.get("target_gw_required", True)) and target_raw is None:
        raise RuntimeError("V5 squad FAIL CLOSED: active planning override requires target_gw")
    target_gw = int(target_raw) if target_raw is not None else None
    planning = int(planning_gw) if planning_gw is not None else None
    submitted = int(submitted_gw) if submitted_gw is not None else None
    target_matches = bool(override_requested and planning is not None and target_gw == planning)
    post_deadline_reclaimed = bool(target_matches and submitted is not None and planning == submitted)
    override_applied = bool(target_matches and not post_deadline_reclaimed)
    if wildcard:
        override_kind = "WILDCARD"
    elif free_hit:
        override_kind = "FREE_HIT"
    elif manual:
        override_kind = "USER_LOCK"
    else:
        override_kind = "NONE"
    return {
        "planning_gw": planning,
        "submitted_gw": submitted,
        "override_requested": override_requested,
        "override_kind": override_kind,
        "override_target_gw": target_gw,
        "override_applied": override_applied,
        "stale_override_rejected": bool(override_requested and planning is not None and target_gw != planning),
        "post_deadline_official_reclaims_authority": post_deadline_reclaimed,
        "authority_source": (lock.get("authority_source") or "USER_PLANNING_OVERRIDE") if override_applied else None,
        "governance": {
            "target_gw_required": bool(policy.get("target_gw_required", True)),
            "stale_target_behavior": policy.get("stale_target_behavior"),
            "post_deadline_official_submission_reclaims_authority": bool(
                policy.get("post_deadline_official_submission_reclaims_authority", True)
            ),
        },
    }


def select_squad(
    *,
    phase,
    bootstrap: dict,
    planning_gw: int | None = None,
    submitted_gw: int | None = None,
    locked_squad=None,
    authenticated_my_team=None,
    submitted_picks=None,
):
    baseline = projection_baseline_authority(
        locked_squad,
        planning_gw=planning_gw,
        submitted_gw=submitted_gw,
    )
    for authority in phase_authority_chain(phase, "squad"):
        if authority == "user_lock" and locked_squad and baseline.get("override_applied"):
            squad = resolve_locked_squad(locked_squad, bootstrap)
        elif authority == "official_authenticated" and authenticated_my_team:
            squad = resolve_authenticated_draft(authenticated_my_team, bootstrap)
        elif authority == "official_public" and submitted_picks:
            squad = resolve_submitted_squad(submitted_picks, bootstrap)
        else:
            continue
        if squad:
            return {
                "authority": authority,
                "squad": squad,
                "validation": validate_squad(squad),
                "projection_baseline": {
                    **baseline,
                    "effective_authority": authority,
                },
            }
    raise RuntimeError(f"no usable V5 squad authority for phase {phase}")


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
