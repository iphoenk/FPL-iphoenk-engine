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
from src.v5.mini_league import build_tracking
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
    gw = int(context.planning_gw or context.current_gw or 1)
    ledger = build_chip_ledger(used, current_gw=gw)
    raw_active = None
    source = None
    target_raw = lock.get("target_gw")
    target_gw = int(target_raw) if target_raw is not None else None
    lock_target_matches = target_gw == gw
    if context.phase.value == "PRE_DEADLINE":
        if bool(lock.get("wildcard_active")) and lock_target_matches:
            raw_active = "wildcard"
            source = "user_lock"
        elif bool(lock.get("free_hit_active")) and lock_target_matches:
            raw_active = "free_hit"
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
    if active_chip == "free_hit" and gw == 1 and not bool(CHIP_RULES.get("free_hit_gw1_allowed", False)):
        special_legal = False
    legal = known and available_now and special_legal
    return {
        "active_chip": active_chip,
        "raw_active_chip": raw_active,
        "source": source,
        "planning_gw": gw,
        "submitted_gw": context.submitted_gw,
        "override_target_gw": target_gw,
        "lock_target_matches_planning_gw": lock_target_matches,
        "current_half": int(current_half),
        "available_this_half": sorted(available),
        "one_chip_per_gameweek": bool(CHIP_RULES.get("one_chip_per_gameweek", True)),
        "active_chip_count": 1 if active_chip else 0,
        "known_chip": known,
        "available_now": available_now,
        "special_rule_legal": special_legal,
        "legal": legal,
        "ledger": ledger,
        "governance": {
            "pre_deadline_user_chip_requires_exact_target_gw": True,
            "post_deadline_submitted_chip_is_authoritative": True,
        },
    }


def _capabilities(
    team: dict[str, Any],
    chip_state: dict[str, Any],
    historical_entry: dict[str, Any] | None = None,
    mini_league_tracking: dict[str, Any] | None = None,
) -> list[str]:
    capabilities = {
        "universe_identity",
        "universe_price_position",
        "universe_registration",
        "availability",
        "manual_authority",
        "defcon_rules",
        "mini_league_tracking_state",
    }
    if bool((team.get("validation") or {}).get("passed")):
        capabilities.add("structural_fit")
    if bool((team.get("finance") or {}).get("sell_value_complete")):
        capabilities.add("sell_cost_affordability")
    if bool(chip_state.get("legal")):
        capabilities.add("chip_context")
    coverage = (historical_entry or {}).get("coverage") if isinstance((historical_entry or {}).get("coverage"), dict) else {}
    if int(coverage.get("available") or 0) > 0:
        capabilities.add("historical_submitted_team")
    if (mini_league_tracking or {}).get("status") == "TRACKING":
        capabilities.add("mini_league_rank_gap_trend")
    return sorted(capabilities)


def _enrich_mini_leagues(payload: dict[str, Any]) -> dict[str, Any]:
    truth = payload.get("truth") if isinstance(payload.get("truth"), dict) else {}
    if not truth:
        raise ValueError("mini league truth enrichment requires existing truth")
    entry = payload.get("entry") if isinstance(payload.get("entry"), dict) else {}
    collection = payload.get("mini_league_collection") if isinstance(payload.get("mini_league_collection"), dict) else {}
    previous = payload.get("previous_mini_league") if isinstance(payload.get("previous_mini_league"), dict) else {}
    team_id = int(payload.get("team_id") or entry.get("id") or 0)
    tracking = build_tracking(
        team_id=team_id,
        entry=entry,
        collection=collection,
        previous_state=previous,
    )
    enriched = dict(truth)
    team = dict(enriched.get("team") or {})
    team["mini_league_tracking"] = tracking
    enriched["team"] = team
    enriched["mini_league_tracking"] = tracking
    enriched["capabilities"] = _capabilities(
        team,
        enriched.get("chip_state") if isinstance(enriched.get("chip_state"), dict) else {},
        enriched.get("historical_entry") if isinstance(enriched.get("historical_entry"), dict) else {},
        tracking,
    )
    return enriched


def handle(operation: str, payload: dict[str, Any]) -> Any:
    bootstrap = payload.get("bootstrap")
    if not isinstance(bootstrap, dict):
        raise ValueError("truth service requires bootstrap")
    if operation == "context":
        return context_dict(build_event_context(bootstrap, now=parse_datetime(payload.get("now"))))
    if operation == "rules":
        return _rules_view()
    if operation == "enrich_mini_leagues":
        return _enrich_mini_leagues(payload)
    identity = build_index(bootstrap)
    if operation == "resolve":
        return list(resolve_many(payload.get("element_ids") or (), identity))
    if operation != "assemble":
        raise KeyError(f"unsupported truth operation: {operation}")
    context = build_event_context(bootstrap, now=parse_datetime(payload.get("now")))
    auth_runtime = payload.get("auth_runtime") if isinstance(payload.get("auth_runtime"), dict) else {}
    dynamic = payload.get("dynamic") if isinstance(payload.get("dynamic"), dict) else {}
    base = payload.get("base") if isinstance(payload.get("base"), dict) else {}
    historical_entry = payload.get("historical_entry") if isinstance(payload.get("historical_entry"), dict) else None
    if historical_entry is None:
        historical_entry = dynamic.get("historical_entry") if isinstance(dynamic.get("historical_entry"), dict) else {}
    submitted = dynamic.get("submitted_picks") if isinstance(dynamic.get("submitted_picks"), dict) else None
    lock = payload.get("locked_squad") if isinstance(payload.get("locked_squad"), dict) else locked_squad()
    team = build_team_state(
        phase=context.phase,
        planning_gw=context.planning_gw or context.current_gw,
        submitted_gw=context.submitted_gw,
        bootstrap=bootstrap,
        identity=identity,
        locked_squad=lock,
        authenticated_my_team=auth_runtime.get("my_team") if isinstance(auth_runtime.get("my_team"), dict) else None,
        submitted_picks=submitted,
        transfers=base.get("entry_transfers") if isinstance(base.get("entry_transfers"), list) else [],
        entry=base.get("entry") if isinstance(base.get("entry"), dict) else None,
    )
    team["historical_entry"] = historical_entry
    mini_league_collection = payload.get("mini_league_collection") if isinstance(payload.get("mini_league_collection"), dict) else {}
    previous_mini_league = payload.get("previous_mini_league") if isinstance(payload.get("previous_mini_league"), dict) else {}
    entry = base.get("entry") if isinstance(base.get("entry"), dict) else {}
    team_id = int(payload.get("team_id") or entry.get("id") or 0)
    mini_league_tracking = build_tracking(
        team_id=team_id,
        entry=entry,
        collection=mini_league_collection,
        previous_state=previous_mini_league,
    )
    team["mini_league_tracking"] = mini_league_tracking
    live = personalized_live_score(
        picks=submitted,
        event_live=dynamic.get("event_live") if isinstance(dynamic.get("event_live"), dict) else None,
        identity=identity,
        scoring_gw=context.scoring_gw,
        is_live_event=context.is_live_event,
    )
    chip_state = _chip_state(context, lock, submitted, base.get("entry_history") if isinstance(base.get("entry_history"), dict) else None)
    return {
        "context": context_dict(context),
        "team": team,
        "live": live,
        "rules": _rules_view(),
        "chip_state": chip_state,
        "historical_entry": historical_entry,
        "mini_league_tracking": mini_league_tracking,
        "capabilities": _capabilities(team, chip_state, historical_entry, mini_league_tracking),
    }
