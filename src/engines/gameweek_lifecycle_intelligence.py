from __future__ import annotations

from collections import Counter
from typing import Any

from src.engines.official_snapshot_primitives import snapshot_event_live_for_gw

LEGAL_FORMATIONS = {
    (3, 4, 3), (3, 5, 2),
    (4, 3, 3), (4, 4, 2), (4, 5, 1),
    (5, 2, 3), (5, 3, 2), (5, 4, 1),
}


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _latest_final(history: list[dict[str, Any]], before_gw: int) -> dict[str, Any] | None:
    rows = [row for row in history if row.get("status") == "FINAL" and _i(row.get("gw")) < before_gw]
    return max(rows, key=lambda row: _i(row.get("gw")), default=None)


def _transition(previous: dict[str, Any] | None, team: dict[str, Any], current_gw: int) -> dict[str, Any]:
    previous_players = list((previous or {}).get("submitted_squad") or [])
    current_players = list(team.get("team_value_ledger") or [])
    pmap = {_i(row.get("element")): row for row in previous_players if _i(row.get("element")) > 0}
    cmap = {_i(row.get("element")): row for row in current_players if _i(row.get("element")) > 0}
    previous_ids, current_ids = set(pmap), set(cmap)

    def compact(row: dict[str, Any], element: int) -> dict[str, Any]:
        return {
            "element": element,
            "name": row.get("name"),
            "position": row.get("position"),
        }

    return {
        "from_gw": _i((previous or {}).get("gw")) or None,
        "to_gw": current_gw,
        "kept": [compact(cmap[e], e) for e in sorted(previous_ids & current_ids)],
        "ins": [compact(cmap[e], e) for e in sorted(current_ids - previous_ids)],
        "outs": [compact(pmap[e], e) for e in sorted(previous_ids - current_ids)],
        "governance": {
            "comparison_is_squad_identity_not_previous_gw_points": True,
            "previous_gw_points_never_count_as_transfer_or_wildcard_loss": True,
        },
    }


def _event_actual_map(event_live: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in (event_live or {}).get("elements") or []:
        element = _i(row.get("id"), -1)
        if element <= 0:
            continue
        stats = row.get("stats") or {}
        out[element] = {
            "element": element,
            "points": _f(stats.get("total_points")),
            "minutes": _f(stats.get("minutes")),
            "started": _i(stats.get("starts")) > 0 if stats.get("starts") is not None else None,
        }
    return out


def _live_scorecard(live: dict[str, Any], prediction_accuracy: dict[str, Any]) -> list[dict[str, Any]]:
    learning_rows: dict[int, dict[str, Any]] = {}
    for record in (prediction_accuracy.get("records") or {}).values() if isinstance(prediction_accuracy.get("records"), dict) else []:
        if record.get("status") != "SETTLED":
            continue
        for pair in record.get("pairs") or []:
            forecast = pair.get("forecast") or {}
            actual = pair.get("actual") or {}
            element = _i(forecast.get("element") or actual.get("element"), -1)
            if element > 0:
                learning_rows[element] = {
                    "forecast_xpts": forecast.get("xpts"),
                    "forecast_xmins": forecast.get("xmins"),
                    "actual_points": actual.get("points"),
                    "actual_minutes": actual.get("minutes"),
                }

    rows = []
    for row in live.get("players") or []:
        minutes = _f(row.get("minutes"))
        points = _f(row.get("total_points"))
        match_state = "PLAYED" if minutes > 0 else "PENDING_OR_DNP"
        if str(live.get("status") or "").upper() == "FINAL" and minutes <= 0:
            match_state = "DNP"
        item = {
            "element": row.get("element"),
            "name": row.get("name"),
            "position": row.get("position"),
            "pick_position": row.get("pick_position"),
            "captain": bool(row.get("captain")),
            "vice": bool(row.get("vice")),
            "multiplier": row.get("multiplier"),
            "minutes": row.get("minutes"),
            "raw_points": row.get("total_points"),
            "counted_points_so_far": round(points * _f(row.get("multiplier"), 0.0), 2),
            "match_state": match_state,
        }
        learning = learning_rows.get(_i(row.get("element")))
        if learning:
            item["actual_vs_predicted"] = learning
        rows.append(item)
    return rows


def _legal_xi(players: list[dict[str, Any]]) -> bool:
    counts = Counter(str(row.get("position")) for row in players)
    if counts.get("GK", 0) != 1:
        return False
    return (counts.get("DEF", 0), counts.get("MID", 0), counts.get("FWD", 0)) in LEGAL_FORMATIONS


def _carry_forward_score(previous: dict[str, Any], actual_map: dict[int, dict[str, Any]], *, final: bool) -> dict[str, Any]:
    squad = list(previous.get("submitted_squad") or [])
    if len(squad) != 15 or not actual_map:
        return {
            "status": "UNAVAILABLE",
            "reason": "previous_submitted_squad_or_current_event_live_missing",
            "points": None,
        }
    by_id = {_i(row.get("element")): dict(row) for row in squad if _i(row.get("element")) > 0}
    starters = [row for row in squad if _i(row.get("pick_position"), 99) <= 11]
    bench = sorted([row for row in squad if _i(row.get("pick_position"), 0) > 11], key=lambda row: _i(row.get("pick_position")))
    if len(starters) != 11 or len(bench) != 4:
        return {"status": "UNAVAILABLE", "reason": "previous_plan_shape_invalid", "points": None}

    selected = [dict(row) for row in starters]
    used_bench: set[int] = set()
    autosubs: list[dict[str, Any]] = []

    if final:
        starter_gk = next((row for row in selected if row.get("position") == "GK"), None)
        bench_gk = next((row for row in bench if row.get("position") == "GK"), None)
        if starter_gk and bench_gk and _f((actual_map.get(_i(starter_gk.get("element"))) or {}).get("minutes")) <= 0 and _f((actual_map.get(_i(bench_gk.get("element"))) or {}).get("minutes")) > 0:
            idx = selected.index(starter_gk)
            selected[idx] = dict(bench_gk)
            used_bench.add(_i(bench_gk.get("element")))
            autosubs.append({"out": _i(starter_gk.get("element")), "in": _i(bench_gk.get("element"))})

        for starter in list(selected):
            if starter.get("position") == "GK":
                continue
            sid = _i(starter.get("element"))
            if _f((actual_map.get(sid) or {}).get("minutes")) > 0:
                continue
            for candidate in bench:
                cid = _i(candidate.get("element"))
                if candidate.get("position") == "GK" or cid in used_bench:
                    continue
                if _f((actual_map.get(cid) or {}).get("minutes")) <= 0:
                    continue
                trial = [dict(x) for x in selected]
                idx = next((n for n, x in enumerate(trial) if _i(x.get("element")) == sid), None)
                if idx is None:
                    continue
                trial[idx] = dict(candidate)
                if not _legal_xi(trial):
                    continue
                selected = trial
                used_bench.add(cid)
                autosubs.append({"out": sid, "in": cid})
                break

    selected_ids = {_i(row.get("element")) for row in selected}
    points = sum(_f((actual_map.get(element) or {}).get("points")) for element in selected_ids)
    captain = next((row for row in squad if row.get("captain")), None)
    vice = next((row for row in squad if row.get("vice_captain")), None)
    captain_id = _i((captain or {}).get("element"), -1)
    vice_id = _i((vice or {}).get("element"), -1)
    captain_played = _f((actual_map.get(captain_id) or {}).get("minutes")) > 0
    vice_played = _f((actual_map.get(vice_id) or {}).get("minutes")) > 0
    effective_captain = captain_id if captain_played else (vice_id if final and vice_played else None)
    if effective_captain in selected_ids:
        points += _f((actual_map.get(effective_captain) or {}).get("points"))

    return {
        "status": "SETTLED" if final else "PROVISIONAL_NO_AUTOSUB_FINALIZATION",
        "policy": "CARRY_FORWARD_LAST_OFFICIAL_SUBMITTED_PLAN",
        "points": round(points, 2),
        "hit": 0,
        "net_points": round(points, 2),
        "captain": captain_id if captain_id > 0 else None,
        "vice_captain": vice_id if vice_id > 0 else None,
        "effective_captain": effective_captain,
        "autosubs": autosubs,
        "selected_after_autosub": sorted(selected_ids),
        "governance": {
            "same_gameweek_actuals_only": True,
            "no_previous_gameweek_points_used": True,
            "active_chip_not_carried_forward": True,
            "autosubs_finalized_only_when_current_gw_final": True,
        },
    }


def _counterfactual(previous: dict[str, Any] | None, live: dict[str, Any], official_snapshot: dict[str, Any]) -> dict[str, Any]:
    current_gw = _i(live.get("scoring_gw"))
    if not previous or current_gw <= 0:
        return {"status": "UNAVAILABLE", "reason": "previous_final_or_current_gw_missing"}
    event_live, health = snapshot_event_live_for_gw(official_snapshot, current_gw)
    actual_map = _event_actual_map(event_live)
    final = str(live.get("status") or "").upper() == "FINAL"
    old = _carry_forward_score(previous, actual_map, final=final)
    current_net = live.get("net_points")
    pnl = None
    if old.get("net_points") is not None and current_net is not None:
        pnl = round(_f(current_net) - _f(old.get("net_points")), 2)
    return {
        "status": "SETTLED" if final and pnl is not None else ("PROVISIONAL" if pnl is not None else "UNAVAILABLE"),
        "policy": "CURRENT_SUBMITTED_VS_CARRY_FORWARD_LAST_OFFICIAL_SUBMITTED_PLAN",
        "current_squad": {
            "gw": current_gw,
            "status": live.get("status"),
            "gross_points": live.get("gross_points"),
            "hit": live.get("hit"),
            "net_points": current_net,
        },
        "old_squad_counterfactual": old,
        "realized_or_live_pnl": pnl,
        "endpoint_health": health,
        "verdict": (
            "POSITIVE" if final and pnl is not None and pnl > 0 else
            "NEGATIVE" if final and pnl is not None and pnl < 0 else
            "NEUTRAL" if final and pnl == 0 else
            "PROVISIONAL"
        ),
        "governance": {
            "never_finalize_before_current_gw_final": True,
            "counterfactual_policy_is_explicit": True,
            "no_hindsight_optimized_old_xi": True,
        },
    }


def _auth_readiness(auth: dict[str, Any]) -> dict[str, Any]:
    state = str(auth.get("state") or "DISABLED").upper()
    if state == "VALID":
        health = "GREEN"
    elif state.startswith("PARTIAL") or state in {"UNAVAILABLE"}:
        health = "AMBER"
    else:
        health = "RED"
    finance = auth.get("safe_finance") or {}
    return {
        "health": health,
        "state": state,
        "verified_entry": auth.get("verified_entry"),
        "chip_state_available": bool((auth.get("chip_state") or {}).get("available")),
        "transfers_latest_available": bool((auth.get("transfers_latest") or {}).get("available")),
        "exact_finance_coverage_complete": bool((finance.get("coverage") or {}).get("complete")),
        "raw_authenticated_payload_persisted": bool(auth.get("raw_authenticated_payload_persisted")),
        "authority_upgrade_allowed": state == "VALID" and auth.get("verified_entry") == auth.get("expected_entry"),
        "governance": {
            "disabled_without_credentials_is_explicit": True,
            "raw_authenticated_payload_must_not_be_persisted": True,
            "public_official_remains_authority_when_auth_not_valid": True,
        },
    }


def _price_readiness(price_model_health: dict[str, Any]) -> dict[str, Any]:
    state = str(price_model_health.get("status") or "NO_DATA").upper()
    calibrated = state == "HEALTHY"
    return {
        "status": state,
        "actionability": "CALIBRATED_ADVISORY" if calibrated else "ADVISORY_ONLY",
        "direction_samples": price_model_health.get("direction_samples"),
        "direction_accuracy": price_model_health.get("direction_accuracy"),
        "timing_samples": price_model_health.get("timing_samples"),
        "mean_timing_error_hours_observation_bound": price_model_health.get("mean_timing_error_hours_observation_bound"),
        "missed_prediction_windows": price_model_health.get("missed_prediction_windows"),
        "price_alone_can_trigger_transfer": False,
        "governance": {
            "warmup_or_degraded_state_is_advisory_only": True,
            "price_signal_requires_decision_quality_support": True,
        },
    }


def _learning(prediction_accuracy: dict[str, Any]) -> dict[str, Any]:
    aggregate = prediction_accuracy.get("aggregate") or prediction_accuracy.get("metrics") or {}
    decision = prediction_accuracy.get("decision_validation") or prediction_accuracy.get("decision_metrics") or {}
    return {
        "status": prediction_accuracy.get("status") or aggregate.get("status") or "WAIT_FOR_DATA",
        "sample_size": aggregate.get("sample_size"),
        "points_mae": aggregate.get("points_mae"),
        "points_rmse": aggregate.get("points_rmse"),
        "xmins_mae": aggregate.get("xmins_mae"),
        "starter_brier": aggregate.get("starter_brier"),
        "dnp_brier": aggregate.get("dnp_brier"),
        "decision_validation": decision,
        "governance": {
            "genuine_predeadline_samples_only": True,
            "retrospective_forecast_fabrication_forbidden": True,
            "wait_for_data_is_valid_state": True,
        },
    }


def build_gameweek_lifecycle(
    *,
    gameweek_context: dict[str, Any],
    team: dict[str, Any],
    live: dict[str, Any],
    official_snapshot: dict[str, Any],
    prediction_accuracy: dict[str, Any],
    auth: dict[str, Any],
    price_model_health: dict[str, Any],
) -> dict[str, Any]:
    current_gw = _i(live.get("scoring_gw"))
    previous = _latest_final(list(gameweek_context.get("historical") or []), current_gw)
    counterfactual = _counterfactual(previous, live, official_snapshot)
    return {
        "schema": "gameweek_lifecycle.v1",
        "status": "FINAL" if str(live.get("status") or "").upper() == "FINAL" else "PROVISIONAL",
        "previous_gw": previous or {"status": "UNAVAILABLE", "reason": "no_previous_final_gameweek"},
        "transition": _transition(previous, team, current_gw),
        "current_gw": {
            "gw": current_gw or None,
            "status": live.get("status"),
            "gross_points": live.get("gross_points"),
            "hit": live.get("hit"),
            "net_points": live.get("net_points"),
            "player_scorecard": _live_scorecard(live, prediction_accuracy),
        },
        "counterfactual_pnl": counterfactual,
        "learning": _learning(prediction_accuracy),
        "authenticated_official": _auth_readiness(auth),
        "price_calibration": _price_readiness(price_model_health),
        "next_gw": gameweek_context.get("planning") or {},
        "governance": {
            "previous_final_to_current_to_next_sequence": True,
            "no_hindsight_rewrite": True,
            "no_fabricated_evidence": True,
            "counterfactual_never_uses_previous_gw_points": True,
            "provisional_pnl_never_presented_as_final": True,
        },
    }
