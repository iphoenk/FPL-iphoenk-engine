from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.time_utils import parse_iso_datetime

CONFIG = "config/v5_mini_league_registry.json"


def _cfg() -> dict[str, Any]:
    return load_json_config(CONFIG)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def discovered_private_league_ids(kind: str, entry: dict[str, Any] | None) -> list[str]:
    if kind not in {"classic", "h2h"}:
        raise ValueError("kind must be classic or h2h")
    cfg = _cfg()
    auto = cfg.get("auto_discovery") if isinstance(cfg.get("auto_discovery"), dict) else {}
    if not bool(auto.get("enabled", True)) or not isinstance(entry, dict):
        return []
    leagues = entry.get("leagues") if isinstance(entry.get("leagues"), dict) else {}
    rows = leagues.get(kind) if isinstance(leagues.get(kind), list) else []
    signals = tuple(auto.get("private_signals") or ["entry_can_leave", "entry_can_admin", "entry_can_invite"])
    private_only = bool(auto.get("private_only", True))
    limit = max(0, _int(auto.get("max_per_kind"), 5))
    result: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if private_only and not any(row.get(signal) is True for signal in signals):
            continue
        league_id = str(row.get("id") or "").strip()
        if league_id and league_id not in result:
            result.append(league_id)
        if limit and len(result) >= limit:
            break
    return result


def configured_league_ids(kind: str, entry: dict[str, Any] | None = None) -> list[str]:
    if kind not in {"classic", "h2h"}:
        raise ValueError("kind must be classic or h2h")
    cfg = _cfg()
    configured = [str(value).strip() for value in cfg.get(f"{kind}_league_ids", []) if str(value).strip()]
    env_map = cfg.get("environment_override") if isinstance(cfg.get("environment_override"), dict) else {}
    env_name = str(env_map.get(kind) or ("FPL_CLASSIC_LEAGUE_IDS" if kind == "classic" else "FPL_H2H_LEAGUE_IDS"))
    env_ids = [value.strip() for value in os.getenv(env_name, "").split(",") if value.strip()]
    discovered = discovered_private_league_ids(kind, entry)
    result: list[str] = []
    for league_id in configured + env_ids + discovered:
        if league_id not in result:
            result.append(league_id)
    return result


def collection_plan(entry: dict[str, Any] | None) -> dict[str, Any]:
    configured = {
        "classic": configured_league_ids("classic", entry),
        "h2h": configured_league_ids("h2h", entry),
    }
    discovered = {
        "classic": discovered_private_league_ids("classic", entry),
        "h2h": discovered_private_league_ids("h2h", entry),
    }
    requests: list[dict[str, str]] = []
    for kind in ("classic", "h2h"):
        route = "classic_league_standings" if kind == "classic" else "h2h_league_standings"
        for league_id in configured[kind]:
            requests.append(
                {
                    "key": f"{kind}:{league_id}",
                    "kind": kind,
                    "league_id": league_id,
                    "route": route,
                }
            )
    return {"configured": configured, "auto_discovered": discovered, "requests": requests}


def _standing_rows(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    standings = (payload or {}).get("standings") if isinstance((payload or {}).get("standings"), dict) else {}
    rows = standings.get("results") if isinstance(standings.get("results"), list) else []
    return [row for row in rows if isinstance(row, dict)]


def _league_snapshot(
    *,
    kind: str,
    league_id: str,
    payload: dict[str, Any],
    team_id: int,
    previous: dict[str, Any] | None,
    current_gw_points: Any,
    generated_at: str,
) -> dict[str, Any]:
    rows = _standing_rows(payload)
    league = payload.get("league") if isinstance(payload.get("league"), dict) else {}
    user = next((row for row in rows if _int(row.get("entry"), -1) == int(team_id)), None)
    if user is None:
        return {
            "generated_at": generated_at,
            "kind": kind,
            "league_id": str(league_id),
            "league_name": league.get("name"),
            "status": "ENTRY_NOT_ON_FETCHED_PAGE",
            "entry_id": int(team_id),
        }

    ordered = sorted(rows, key=lambda row: _int(row.get("rank"), 10**9))
    index = next((idx for idx, row in enumerate(ordered) if _int(row.get("entry"), -1) == int(team_id)), -1)
    above = ordered[index - 1] if index > 0 else None
    below = ordered[index + 1] if 0 <= index < len(ordered) - 1 else None
    total = _int(user.get("total"))
    rank = _int(user.get("rank"))
    last_rank = _int(user.get("last_rank"), rank)
    current: dict[str, Any] = {
        "generated_at": generated_at,
        "kind": kind,
        "league_id": str(league_id),
        "league_name": league.get("name"),
        "status": "TRACKING",
        "entry_id": int(team_id),
        "rank": rank,
        "last_rank": last_rank,
        "rank_delta": last_rank - rank,
        "total_points": total,
        "current_gw_points": current_gw_points,
        "above": None,
        "below": None,
        "points_behind_above": None,
        "points_ahead_below": None,
    }
    if above is not None:
        current["above"] = {
            "entry": above.get("entry"),
            "entry_name": above.get("entry_name"),
            "player_name": above.get("player_name"),
            "rank": above.get("rank"),
            "total": above.get("total"),
        }
        current["points_behind_above"] = max(0, _int(above.get("total")) - total)
    if below is not None:
        current["below"] = {
            "entry": below.get("entry"),
            "entry_name": below.get("entry_name"),
            "player_name": below.get("player_name"),
            "rank": below.get("rank"),
            "total": below.get("total"),
        }
        current["points_ahead_below"] = max(0, total - _int(below.get("total")))

    prior_current = (previous or {}).get("current") if isinstance((previous or {}).get("current"), dict) else {}
    if prior_current:
        current["points_delta_since_last_refresh"] = total - _int(prior_current.get("total_points"), total)
        prior_gap = prior_current.get("points_behind_above")
        if prior_gap is not None and current["points_behind_above"] is not None:
            current["gap_to_above_delta"] = current["points_behind_above"] - _int(prior_gap)
    return current


def _history_row(current: dict[str, Any]) -> dict[str, Any]:
    return {
        key: current.get(key)
        for key in (
            "generated_at",
            "rank",
            "total_points",
            "points_behind_above",
            "points_ahead_below",
        )
    }


def _standing_signature(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("rank"),
        row.get("total_points"),
        row.get("points_behind_above"),
        row.get("points_ahead_below"),
    )


def _append_history(history: list[dict[str, Any]], current: dict[str, Any], generated_at: str) -> list[dict[str, Any]]:
    history_cfg = _cfg().get("history") if isinstance(_cfg().get("history"), dict) else {}
    limit = max(1, _int(history_cfg.get("limit"), 50))
    checkpoint_minutes = max(1, _int(history_cfg.get("unchanged_checkpoint_minutes"), 60))
    candidate = _history_row(current)
    if not history:
        return [candidate]
    prior = history[-1]
    changed = _standing_signature(prior) != _standing_signature(candidate)
    prior_at = parse_iso_datetime(prior.get("generated_at"))
    current_at = parse_iso_datetime(generated_at)
    checkpoint_due = True
    if prior_at is not None and current_at is not None:
        checkpoint_due = (current_at - prior_at).total_seconds() >= checkpoint_minutes * 60
    if changed or checkpoint_due:
        history.append(candidate)
    return history[-limit:]


def build_tracking(
    *,
    team_id: int,
    entry: dict[str, Any] | None,
    collection: dict[str, Any] | None,
    previous_state: dict[str, Any] | None,
) -> dict[str, Any]:
    cfg = _cfg()
    collection = collection if isinstance(collection, dict) else {}
    plan = collection.get("plan") if isinstance(collection.get("plan"), dict) else collection_plan(entry)
    configured = plan.get("configured") if isinstance(plan.get("configured"), dict) else {"classic": [], "h2h": []}
    discovered = plan.get("auto_discovered") if isinstance(plan.get("auto_discovered"), dict) else {"classic": [], "h2h": []}
    generated_at = str(collection.get("generated_at") or datetime.now(timezone.utc).isoformat())
    raw_leagues = collection.get("leagues") if isinstance(collection.get("leagues"), dict) else {}
    previous_leagues = (previous_state or {}).get("leagues") if isinstance((previous_state or {}).get("leagues"), dict) else {}

    if not configured.get("classic") and not configured.get("h2h"):
        return {
            "schema_version": 1,
            "contract": cfg.get("contract"),
            "model": cfg.get("model_id"),
            "generated_at": generated_at,
            "status": "NO_PRIVATE_LEAGUES_DISCOVERED",
            "configured": configured,
            "auto_discovered": discovered,
            "tracking_count": 0,
            "leagues": {},
            "note": "No explicit or auto-discovered private mini league is available from the Official entry payload.",
            "governance": cfg.get("governance") or {},
        }

    result: dict[str, Any] = {}
    gw_points = (entry or {}).get("summary_event_points") if isinstance(entry, dict) else None
    history_limit = max(1, _int((cfg.get("history") or {}).get("limit"), 50))
    for kind in ("classic", "h2h"):
        kind_payloads = raw_leagues.get(kind) if isinstance(raw_leagues.get(kind), dict) else {}
        for league_id in configured.get(kind) or []:
            key = f"{kind}:{league_id}"
            prior = previous_leagues.get(key) if isinstance(previous_leagues.get(key), dict) else {}
            payload = kind_payloads.get(str(league_id))
            if not isinstance(payload, dict):
                result[key] = {
                    "current": {"generated_at": generated_at, "kind": kind, "league_id": str(league_id), "status": "UNAVAILABLE"},
                    "history": list(prior.get("history") or [])[-history_limit:],
                }
                continue
            current = _league_snapshot(
                kind=kind,
                league_id=str(league_id),
                payload=payload,
                team_id=int(team_id),
                previous=prior,
                current_gw_points=gw_points,
                generated_at=generated_at,
            )
            history = list(prior.get("history") or [])
            if current.get("status") == "TRACKING":
                history = _append_history(history, current, generated_at)
            result[key] = {"current": current, "history": history[-history_limit:]}

    tracking_count = sum(1 for row in result.values() if (row.get("current") or {}).get("status") == "TRACKING")
    return {
        "schema_version": 1,
        "contract": cfg.get("contract"),
        "model": cfg.get("model_id"),
        "generated_at": generated_at,
        "status": "TRACKING" if tracking_count else "CONFIGURED_NO_LIVE_STANDINGS",
        "configured": configured,
        "auto_discovered": discovered,
        "tracking_count": tracking_count,
        "leagues": result,
        "health": collection.get("health") if isinstance(collection.get("health"), dict) else {},
        "governance": cfg.get("governance") or {},
    }
