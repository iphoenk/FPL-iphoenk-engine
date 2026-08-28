from __future__ import annotations

from typing import Any

from src.rules import (
    ASSIST_POINTS,
    CHIP_API_NAMES,
    CHIP_DISPLAY_NAMES,
    CHIP_RULES,
    CLEAN_SHEET_POINTS,
    DC_RULES,
    GOAL_POINTS,
    LINEUP_RULES,
    RULESET_ID,
    RULESET_SEASON,
    SQUAD_RULES,
    build_chip_ledger,
)
from src.v5.event_context import build_event_context
from src.v5.identity import build_index, resolve_many
from src.v5.live_scoring import personalized_live_score
from src.v5.team_service import build_team_state
from src.v5.services.common import context_dict, locked_squad, parse_datetime


def _rules_view() -> dict[str, Any]:
    return {
        "ruleset_id": RULESET_ID,
        "season": RULESET_SEASON,
        "goal_points": {str(k): int(v) for k, v in GOAL_POINTS.items()},
        "assist_points": int(ASSIST_POINTS),
        "clean_sheet_points": {str(k): int(v) for k, v in CLEAN_SHEET_POINTS.items()},
        "defensive_contributions": {str(k): dict(v) for k, v in DC_RULES.items()},
        "squad": SQUAD_RULES,
        "lineup": LINEUP_RULES,
        "chips": CHIP_RULES,
        "authority": "truth-service",
    }


def _chip_state(context, lock: dict[str, Any], submitted: dict[str, Any] | None, entry_history: dict[str, Any] | None) -> dict[str, Any]:
    used = (entry_history or {}).get("chips") if isinstance((entry_history or {}).get("chips"), list) else []
    ledger = build_chip_ledger(used, current_gw=context.planning_gw or context.current_gw or 1)
    raw_active = None
    source = None
    if context.phase.value == "PRE_DEADLINE":
        if bool(lock.get("wildcard_active")):
            raw_active = "wildcard"
            source = "user_lock"
    elif isinstance(submitted, dict):
        raw_active = submitted.get("active_chip")
        source = "submitted_picks" if raw_active else None
    active_chip = CHIP_API_NAMES.get(str(raw_active), str(raw_active)) if raw_active else None
    current_half = str(ledger.get("current_half") or 1)
    available = set(((ledger.get("halves") or {}).get(current_half) or {}).get("available") or [])
    known = active_chip is None or active_chip in CHIP_DISPLAY_NAMES
    available_now = active_chip is None or active_chip in available
    special_legal = True
    gw = int(context.planning_gw or context.current_gw or 1)
    if active_chip == "free_hit" and gw == 1 and not bool(CHIP_RULES.get("free_hit_gw1_allowed", False)):
        special_legal = False
    legal = known and available_now and special_legal
    return {
        "active_chip": active_chip,
        "raw_active_chip": raw_active,
        "source": source,
        "planning_gw": gw,
        "submitted_gw": context.submitted_gw,
        "current_half": int(current_half),
        "available_this_half": sorted(available),
        "one_chip_per_gameweek": bool(CHIP_RULES.get("one_chip_per_gameweek", True)),
        "active_chip_count": 1 if active_chip else 0,
        "known_chip": known,
        "available_now": available_now,
        "special_rule_legal": special_legal,
        "legal": legal,
        "ledger": ledger,
    }


def _capabilities(team: dict[str, Any], chip_state: dict[str, Any]) -> list[str]:
    capabilities = {
        "universe_identity",
        "universe_price_position",
        "universe_registration",
        "availability",
        "manual_authority",
        "defcon_rules",
    }
    if bool((team.get("validation") or {}).get("passed")):
        capabilities.add("structural_fit")
    if bool((team.get("finance") or {}).get("sell_value_complete")):
        capabilities.add("sell_cost_affordability")
    if bool(chip_state.get("legal")):
        capabilities.add("chip_context")
    return sorted(capabilities)


def _match_state(fixtures: list[dict[str, Any]], scoring_gw: int | None) -> dict[str, Any]:
    if scoring_gw is None:
        return {
            "authority": "OFFICIAL_FPL_FIXTURES",
            "scoring_gw": None,
            "live_match_active": False,
            "live_fixture_count": 0,
            "live_fixtures": [],
        }
    live_rows = []
    for row in fixtures or []:
        if not isinstance(row, dict) or int(row.get("event") or -1) != int(scoring_gw):
            continue
        if row.get("started") is not True or row.get("finished") is True:
            continue
        live_rows.append(
            {
                "id": row.get("id"),
                "event": row.get("event"),
                "kickoff_time": row.get("kickoff_time"),
                "team_h": row.get("team_h"),
                "team_a": row.get("team_a"),
                "started": True,
                "finished": False,
            }
        )
    return {
        "authority": "OFFICIAL_FPL_FIXTURES",
        "scoring_gw": scoring_gw,
        "live_match_active": bool(live_rows),
        "live_fixture_count": len(live_rows),
        "live_fixtures": live_rows,
    }


def handle(operation: str, payload: dict[str, Any]) -> Any:
    bootstrap = payload.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise ValueError("truth service requires bootstrap")
    if operation == "context":
        return context_dict(build_event_context(bootstrap, now=parse_datetime(payload.get("now"))))
    if operation == "rules":
        return _rules_view()
    identity = build_index(bootstrap)
    if operation == "resolve":
        return list(resolve_many(payload.get("element_ids") or (), identity))
    if operation != "assemble":
        raise KeyError(f"unsupported truth operation: {operation}")
    context = build_event_context(bootstrap, now=parse_datetime(payload.get("now")))
    auth_runtime = payload.get("auth_runtime") if isinstance(payload.get("auth_runtime"), dict) else {}
    dynamic = payload.get("dynamic") if isinstance(payload.get("dynamic"), dict) else {}
    base = payload.get("base") if isinstance(payload.get("base"), dict) else {}
    submitted = dynamic.get("submitted_picks") if isinstance(dynamic.get("submitted_picks"), dict) else None
    lock = payload.get("locked_squad") if isinstance(payload.get("locked_squad"), dict) else locked_squad()
    team = build_team_state(
        phase=context.phase,
        bootstrap=bootstrap,
        identity=identity,
        locked_squad=lock,
        authenticated_my_team=auth_runtime.get("my_team") if isinstance(auth_runtime.get("my_team"), dict) else None,
        submitted_picks=submitted,
        transfers=base.get("entry_transfers") if isinstance(base.get("entry_transfers"), list) else [],
        entry=base.get("entry") if isinstance(base.get("entry"), dict) else None,
    )
    match_state = _match_state(base.get("fixtures") if isinstance(base.get("fixtures"), list) else [], context.scoring_gw)
    live = personalized_live_score(
        picks=submitted,
        event_live=dynamic.get("event_live") if isinstance(dynamic.get("event_live"), dict) else None,
        identity=identity,
        scoring_gw=context.scoring_gw,
        is_live_event=context.is_live_event,
    )
    live = {**live, "match_state": match_state}
    chip_state = _chip_state(context, lock, submitted, base.get("entry_history") if isinstance(base.get("entry_history"), dict) else None)
    return {
        "context": context_dict(context),
        "team": team,
        "live": live,
        "match_state": match_state,
        "rules": _rules_view(),
        "chip_state": chip_state,
        "capabilities": _capabilities(team, chip_state),
    }
