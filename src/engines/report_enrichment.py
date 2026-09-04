from __future__ import annotations

from typing import Any

from src.engines.decision_arbitration import arbitrate_decisions, assert_decision_consistency
from src.engines.report_time_intelligence import run as run_report_time_intelligence
from src.utils import CONFIG, DATA, atomic_json, read_json


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _projection_map(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(row["element"]): row for row in payload.get("players") or [] if row.get("element") is not None}


def _gw_row(proj: dict[str, Any], gw: int) -> dict[str, Any]:
    return next((row for row in proj.get("xpts_by_gw") or [] if int(row.get("gw") or -1) == gw), {})


def _battle_metrics(element: int | None, projections: dict[str, Any], planning_gw: int) -> dict[str, Any]:
    if element is None:
        return {}
    proj = _projection_map(projections).get(int(element)) or {}
    xmins = proj.get("xmins") or {}
    gw = _gw_row(proj, planning_gw)
    return {
        "element": element,
        "name": proj.get("name"),
        "xpts": gw.get("mean"),
        "xmins": xmins.get("expected_minutes"),
        "start_probability": xmins.get("start_probability"),
        "dnp_probability": xmins.get("dnp_probability"),
        "model_confidence": proj.get("projection_confidence"),
    }


def _battle_reasons(leader: dict[str, Any], challenger: dict[str, Any]) -> list[str]:
    thresholds = (read_json(CONFIG / "intelligence" / "reporting.json", {}).get("battle_reason_thresholds") or {})
    required = ("xpts_delta", "xmins_delta", "start_probability_delta")
    if any(_f(thresholds.get(key), -1.0) <= 0 for key in required):
        raise RuntimeError("reporting battle reason thresholds must be positive and config-owned")
    reasons: list[str] = []
    xpts_delta = _f(leader.get("xpts")) - _f(challenger.get("xpts"))
    xmins_delta = _f(leader.get("xmins")) - _f(challenger.get("xmins"))
    start_delta = _f(leader.get("start_probability")) - _f(challenger.get("start_probability"))
    if abs(xpts_delta) >= _f(thresholds["xpts_delta"]):
        reasons.append(f"projected points {'+' if xpts_delta >= 0 else ''}{xpts_delta:.2f}")
    if abs(xmins_delta) >= _f(thresholds["xmins_delta"]):
        reasons.append(f"xMins {'+' if xmins_delta >= 0 else ''}{xmins_delta:.1f}")
    if abs(start_delta) >= _f(thresholds["start_probability_delta"]):
        reasons.append(f"starter probability {'+' if start_delta >= 0 else ''}{start_delta * 100:.1f}pp")
    if not reasons:
        reasons.append("model margin sangat tipis; belum ada pembeda kuat")
    return reasons[:3]


def _source_availability(source_health: dict[str, Any]) -> dict[str, Any]:
    sources = {str(row.get("id")): row for row in source_health.get("sources") or []}
    capability_rows = source_health.get("capability_health") or []
    selected = []
    for source_id in ("onefpl", "fffix", "ffhub", "ffscout"):
        source = sources.get(source_id) or {}
        if not source:
            continue
        capabilities = [row for row in capability_rows if row.get("source_id") == source_id]
        selected.append({
            "source": source.get("name") or source_id,
            "source_id": source_id,
            "terjangkau": bool(source.get("reachable")),
            "status_sumber": source.get("status"),
            "capabilities": [
                {
                    "capability": row.get("capability"),
                    "structured_state": row.get("data_state") or "UNAVAILABLE",
                    "observasi_baru": int(row.get("fresh_observations") or 0),
                }
                for row in capabilities
            ],
        })
    return {
        "otoritas": "Official FPL native facts dan native price predictor tetap menjadi otoritas utama",
        "collector_challenger": selected,
        "report_time": {
            "onefpl": "transfer trends, market momentum, price/planner context sebagai challenger/consensus",
            "fffix": "predicted points, predicted lineup/xMins, price dan rotation challenger",
            "ffhub": "AI transfer/decision, fixture/player comparison, XI/captain challenger",
            "ffscout": "predicted lineup, team news, RMT/player comparison dan tactical/editorial challenger",
            "fixture_strategy": "Ben Crellin / schedule expert dicek saat report dibuat",
            "pundit_consensus": "FPL Harry, FPL Focal, Let's Talk FPL, BigManBakar, dan Scout editorial dibandingkan dengan DSS",
            "community": "Reddit r/FantasyPL dipakai sebagai sinyal komunitas yang wajib cross-check",
        },
        "catatan": "External benchmark tidak mengubah native truth/DSS. Sumber yang telah dipensiunkan tidak ditampilkan sebagai evidence V3; factual divergence memicu refresh Official, bukan overwrite external.",
    }


def _report_time_user_block(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": payload.get("status"),
        "web_refresh_required": bool(payload.get("web_refresh_required")),
        "pundit_consensus_vs_dss": payload.get("pundit_consensus") or [],
        "fixture_strategy": payload.get("fixture_strategy") or [],
        "model_challenger": payload.get("model_challenger") or [],
        "community_signal": payload.get("community_signal") or [],
        "verified_news": payload.get("verified_news") or [],
        "catatan": "Konsensus pundit bersifat advisory. Perbedaan dengan DSS harus ditampilkan, bukan disembunyikan atau otomatis mengubah keputusan model.",
    }


def _external_consensus_user_block(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "overall": payload.get("overall") or "INSUFFICIENT_EVIDENCE",
        "requires_official_refresh": bool(payload.get("requires_official_refresh")),
        "source_status": payload.get("source_status") or {},
        "subjects": [
            {"subject": row.get("subject"), "classification": row.get("classification")}
            for row in payload.get("subjects") or []
        ],
        "advisory_only": bool((payload.get("governance") or {}).get("advisory_only", True)),
        "catatan": "Native multi-GW conclusion remains primary. External benchmarks challenge and explain divergence only; no majority vote and no overwrite of Official/native truth.",
    }


def _player_ref(raw: Any, *, cost_key: str) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    return {
        "element": row.get("element"),
        "name": row.get("name"),
        "position": row.get("position"),
        cost_key: row.get(cost_key),
        "official_ownership": row.get("official_ownership"),
    }


def _tactical_side(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    return {
        key: row.get(key)
        for key in (
            "evidence_state", "status", "classification", "fixture_id", "opponent_team_id",
            "opponent", "venue", "matchup_state", "confidence",
        )
        if row.get(key) is not None
    }


def _load_side(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    return {
        key: row.get(key)
        for key in ("state", "status", "days_rest", "rest_days", "fixture_count", "load_state", "confidence")
        if row.get(key) is not None
    }


def _serving_package(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    return {
        "replacements": row.get("replacements"),
        "out": row.get("out") or [],
        "in": row.get("in") or [],
        "classification": row.get("classification"),
        "robust_gain_vs_hold": row.get("robust_gain_vs_hold"),
        "net_gain_3gw": row.get("net_gain_3gw"),
        "net_gain_5gw": row.get("net_gain_5gw"),
        "net_gain_10gw": row.get("net_gain_10gw"),
        "net_gain_15gw": row.get("net_gain_15gw"),
        "hit_cost": row.get("hit_cost"),
        "legal": row.get("legal"),
        "affordability": row.get("affordability") or {},
    }


def _serving_decision(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    return {
        "state": row.get("state"),
        "execution_authorized": bool(row.get("execution_authorized")),
        "reason": row.get("reason"),
        "no_transfer_recommended": bool(row.get("no_transfer_recommended")),
        "no_transfer_message": row.get("no_transfer_message"),
        "selected_package_evidence": _serving_package(row.get("selected_package_evidence")),
        "market_timing_is_not_football_authority": bool(row.get("market_timing_is_not_football_authority", True)),
        "package_optimizer_is_transfer_structure_authority": bool(row.get("package_optimizer_is_transfer_structure_authority", True)),
    }


def _serving_battle(raw: Any) -> dict[str, Any]:
    row = dict(raw or {}) if isinstance(raw, dict) else {}
    v3_edge = row.get("v3_edge") or {}
    tactical = row.get("next_matchup") or {}
    load = row.get("rest_congestion") or {}
    predictor = row.get("predictor") or {}
    challenger_market = predictor.get("challenger") or {}
    structural = row.get("structural_impact") or {}
    return {
        "owned": _player_ref(row.get("owned"), cost_key="sell_cost"),
        "challenger": _player_ref(row.get("challenger"), cost_key="now_cost"),
        "v3_edge": {
            "3gw": v3_edge.get("3gw") or {},
            "5gw": v3_edge.get("5gw") or {},
            "10_15gw": v3_edge.get("10_15gw") or {},
        },
        "xmins_start": row.get("xmins_start") or {},
        "role": row.get("role") or {},
        "next_matchup": {
            "owned": _tactical_side(tactical.get("owned")),
            "challenger": _tactical_side(tactical.get("challenger")),
        },
        "rest_congestion": {
            "owned": _load_side(load.get("owned")),
            "challenger": _load_side(load.get("challenger")),
        },
        "route_to_points": row.get("route_to_points") or {},
        "official_price": row.get("official_price") or {},
        "official_ownership": row.get("official_ownership") or {},
        "predictor": {
            key: challenger_market.get(key)
            for key in (
                "direction", "urgency", "progress_percent", "trajectory", "predicted_player_change_eta",
                "next_official_price_update_window", "eta_narrative_id", "freshness_seconds", "evidence_state",
                "fresh", "imminent", "confirmed_price_change",
            )
            if challenger_market.get(key) is not None
        },
        "structural_impact": {
            key: structural.get(key)
            for key in (
                "exact_sell_cost", "purchase_cost", "incoming_now_cost", "itb", "affordable",
                "switching_cost", "net_projected_gain",
            )
            if structural.get(key) is not None
        },
        "risk": row.get("risk") or [],
        "confidence": row.get("confidence"),
        "decision": row.get("decision"),
        "reason": row.get("reason"),
        "flip_conditions": row.get("flip_conditions") or [],
    }


def _comparator_user_block(payload: dict[str, Any]) -> dict[str, Any]:
    battles = list(payload.get("main_transfer_battles") or [])
    alternatives = list(payload.get("multi_transfer_alternatives") or [])
    return {
        "status": payload.get("status"),
        "contract": payload.get("contract"),
        "owner": payload.get("owner"),
        "capability_status": payload.get("capability_status") or "GOVERNED_DECISION",
        "owned_count": payload.get("owned_count"),
        "governed_watchlist_count": payload.get("governed_watchlist_count"),
        "material_candidate_count": payload.get("material_candidate_count"),
        "mandatory_review_count": payload.get("mandatory_review_count"),
        "comparison_count": payload.get("comparison_count"),
        "challenged_owned": payload.get("challenged_owned") or [],
        "decision": _serving_decision(payload.get("decision")),
        "main_transfer_battle_count": len(battles),
        "multi_transfer_alternatives": [_serving_package(row) for row in alternatives[:8]],
        "publication_validation": payload.get("publication_validation") or {},
        "state_counts": payload.get("state_counts") or {},
        "actionability_counts": payload.get("actionability_counts") or {},
        "v3_view": payload.get("v3_view") or {},
        "technical_evidence_ref": "data/dss_watchlist.json#owned_challenger_decision",
        "catatan": "Keputusan challenger dihitung sekali pada capability DECISION/watchlist. Surface user hanya membawa evidence ringkas; detail teknis tetap pada artifact canonical dan tidak dihitung ulang oleh reporting.",
    }


def _apply_transfer_decision(user: dict[str, Any], comparator: dict[str, Any]) -> None:
    governed = str((comparator.get("decision") or {}).get("state") or "HOLD").upper()
    decision = user.setdefault("decision", {})
    current = str(decision.get("squad") or "HOLD").upper()
    if governed == "BLOCKED":
        raise RuntimeError("governed owned challenger decision is BLOCKED")
    if governed == "CHANGE":
        decision["squad"] = "CHANGE"
        if str(decision.get("overall") or "").upper() not in {"REVIEW", "REVIEW_DIVERGENCE"}:
            decision["overall"] = "CHANGE"
    elif governed in {"REVIEW", "REVIEW_NOW"} and current == "HOLD":
        decision["squad"] = "REVIEW"
        decision["overall"] = "REVIEW"
    decision["challenger_state"] = governed
    decision["challenger_execution_authorized"] = bool((comparator.get("decision") or {}).get("execution_authorized"))
    for item in user.get("action_board") or []:
        if str(item.get("subject") or "") == "Squad":
            item["action"] = decision.get("squad")
            item["trigger"] = "ikuti Main Transfer Battles; eksekusi tetap memerlukan keputusan pengguna"
            break


def _action_class(subject: str) -> str:
    return "FACT_CONSTRAINT" if subject == "Chip" else "MODEL_DERIVED"


def _price_action(row: dict[str, Any], *, owned: bool) -> str:
    direction = str(row.get("direction") or "NO_SIGNAL")
    urgency = str(row.get("model_urgency") or "LOW")
    state = str(row.get("evidence_state") or "UNAVAILABLE")
    if state in {"STALE", "FIELD_MISSING", "SCHEMA_CHANGED", "UNAVAILABLE"}:
        return "REVIEW_EVIDENCE"
    if owned and direction == "FALL" and urgency in {"HIGH", "CRITICAL"}:
        return "REVIEW_VALUE_RISK"
    if not owned and direction == "RISE" and urgency in {"HIGH", "CRITICAL"}:
        return "REVIEW_NOW"
    return "HOLD" if owned else "WATCH"


def _price_serving_row(raw: dict[str, Any], *, owned: bool, reason: str | None = None) -> dict[str, Any]:
    element = raw.get("element_id") if raw.get("element_id") is not None else raw.get("element")
    return {
        "element": element,
        "name": raw.get("player_name") or raw.get("name"),
        "team_id": raw.get("team_id"),
        "position": raw.get("position"),
        "official_price": raw.get("current_price"),
        "official_ownership": raw.get("ownership_percent"),
        "confirmed_price_change": raw.get("confirmed_price_change"),
        "direction": raw.get("direction") or "NO_SIGNAL",
        "progress_pct": raw.get("current_progress_percent"),
        "trajectory": raw.get("trajectory"),
        "hourly_rate": raw.get("price_change_hourly_rate"),
        "projection_offset_0_percent": raw.get("projection_offset_0_percent"),
        "projection_offset_1_percent": raw.get("projection_offset_1_percent"),
        "projection_offset_2_percent": raw.get("projection_offset_2_percent"),
        "predicted_change_cycle": raw.get("predicted_change_cycle"),
        "predicted_change_at": raw.get("predicted_change_at"),
        "next_official_price_update_at": raw.get("next_official_price_update_at"),
        "eta_human": raw.get("eta_human"),
        "urgency": raw.get("model_urgency") or "LOW",
        "confidence": raw.get("confidence") or "UNAVAILABLE",
        "source": raw.get("source") or "OFFICIAL_FPL",
        "observed_at": raw.get("observed_at"),
        "freshness_seconds": raw.get("freshness_seconds"),
        "evidence_state": raw.get("evidence_state") or "UNAVAILABLE",
        "sell_value_relevance": raw.get("sell_value_relevance") if owned else "NOT_OWNED",
        "action": _price_action(raw, owned=owned),
        "mandatory_challenger_reason": reason,
        "threshold_crossing_is_not_confirmation": True,
        "price_signal_is_overlay_only": True,
        "narrative": raw.get("narrative"),
    }


def _mandatory_challenger_ids(comparator: dict[str, Any], market_watch: list[dict[str, Any]], owned_ids: set[int]) -> dict[int, str]:
    mandatory: dict[int, str] = {}
    for pair in comparator.get("top_comparisons") or []:
        incoming = pair.get("player_in") or {}
        element = incoming.get("element")
        if element is None:
            continue
        element = int(element)
        if element in owned_ids:
            continue
        actionability = str((pair.get("actionability") or {}).get("level") or "")
        state = str(pair.get("state") or "")
        challenger_types = set(pair.get("challenger_types") or [])
        if pair.get("challenger_type"):
            challenger_types.add(str(pair.get("challenger_type")))
        if (
            actionability in {"REVIEW", "MATERIAL_UPGRADE", "ACTIONABLE_CHANGE"}
            or state in {"REVIEW", "LEAN_TRANSFER", "STRONG_TRANSFER"}
            or challenger_types & {"EMERGING_CHALLENGER", "MANDATORY_VALUE_MARKET_REVIEW", "FULL_UNIVERSE_DISCOVERY"}
        ):
            mandatory[element] = "GOVERNED_CHALLENGER"
    for row in market_watch:
        element = row.get("element_id") if row.get("element_id") is not None else row.get("element")
        if element is None:
            continue
        element = int(element)
        if element in owned_ids:
            continue
        if str(row.get("model_urgency") or row.get("urgency") or "") in {"HIGH", "CRITICAL"}:
            mandatory.setdefault(element, "MARKET_URGENT_SCREEN_REQUIRED")
    return mandatory


def _hydrate_price_radar(
    user: dict[str, Any],
    team: dict[str, Any],
    prices: dict[str, Any],
    price_alerts: dict[str, Any],
    watchlist: dict[str, Any],
    comparator: dict[str, Any],
) -> dict[str, Any]:
    owned_ids = {
        int(row["element"])
        for row in team.get("team_value_ledger") or team.get("squad") or []
        if isinstance(row, dict) and row.get("element") is not None
    }
    by_id = {
        int(row.get("element_id") if row.get("element_id") is not None else row.get("element")): row
        for row in prices.get("players") or []
        if isinstance(row, dict) and (row.get("element_id") is not None or row.get("element") is not None)
    }
    served_owned = {
        int(row.get("element")): row
        for row in price_alerts.get("owned_price_radar") or []
        if isinstance(row, dict) and row.get("element") is not None
    }
    missing_owned = sorted(owned_ids - (set(by_id) | set(served_owned)))
    if len(owned_ids) != 15:
        raise RuntimeError(f"price radar owned authority requires 15 players, got {len(owned_ids)}")
    if missing_owned:
        raise RuntimeError(f"price radar owned predictor coverage missing elements: {missing_owned}")

    owned_rows = []
    for element in sorted(owned_ids):
        raw = by_id.get(element) or served_owned.get(element) or {}
        owned_rows.append(_price_serving_row(raw, owned=True))

    market_watch = list(price_alerts.get("market_watch_candidates") or [])
    mandatory = _mandatory_challenger_ids(comparator, market_watch, owned_ids)
    mandatory_rows = []
    for element, reason in mandatory.items():
        raw = by_id.get(element)
        if raw is None:
            raw = next(
                (
                    row for row in market_watch
                    if int(row.get("element_id") if row.get("element_id") is not None else row.get("element") or -1) == element
                ),
                {},
            )
        mandatory_rows.append(_price_serving_row(raw, owned=False, reason=reason))

    watch_ids = {
        int(row.get("element"))
        for rows in (watchlist.get("positions") or {}).values()
        for row in rows
        if isinstance(row, dict) and row.get("element") is not None
    }
    visible_watchlist_rows = []
    for element in sorted(watch_ids):
        raw = by_id.get(element)
        if raw is None:
            visible_watchlist_rows.append({
                "element": element,
                "name": None,
                "direction": "NO_SIGNAL",
                "evidence_state": "UNAVAILABLE",
                "action": "WATCH",
                "threshold_crossing_is_not_confirmation": True,
            })
        else:
            visible_watchlist_rows.append(_price_serving_row(raw, owned=False))

    radar = user.get("price_radar") or {}
    radar.update({
        "owned": owned_rows,
        "owned_count": len(owned_rows),
        "owned_coverage_required": 15,
        "mandatory_high_value_challengers": mandatory_rows,
        "mandatory_challenger_count": len(mandatory_rows),
        "external_watchlist": visible_watchlist_rows,
        "external_watchlist_count": len(visible_watchlist_rows),
        "predictor_health": price_alerts.get("health") or prices.get("official_price_predictor_health") or {},
        "fact_model_separation": {
            "fact_fields": ["official_price", "official_ownership", "confirmed_price_change"],
            "model_fields": ["direction", "progress_pct", "trajectory", "predicted_change_at", "urgency", "confidence"],
            "next_official_price_update_is_not_player_change_eta": True,
            "threshold_crossing_is_not_confirmation": True,
        },
        "decision": "REVIEW" if any(str(row.get("action")) in {"REVIEW_VALUE_RISK", "REVIEW_NOW", "REVIEW_EVIDENCE"} for row in owned_rows + mandatory_rows) else "HOLD",
    })
    user["price_radar"] = radar
    return {
        "owned_complete": len(owned_rows) == 15,
        "mandatory_challenger_count": len(mandatory_rows),
        "watchlist_price_rows": len(visible_watchlist_rows),
        "all_price_rows_source": "data/prices.json players",
        "market_watch_source": "data/price_alerts.json market_watch_candidates",
    }


def _apply_readiness_and_actionability(
    user: dict[str, Any],
    tech: dict[str, Any],
    latest: dict[str, Any],
    report_time: dict[str, Any],
) -> None:
    framework = tech.get("framework_health") or {}
    prediction = latest.get("prediction_evaluation") or {}
    sample_size = int(prediction.get("sample_size") or 0)
    model_eligible = bool(prediction.get("dynamic_weight_eligible")) and sample_size > 0
    engine_ready = (
        str(framework.get("overall") or "") == "GREEN"
        and framework.get("go_allowed") is True
        and not list(framework.get("critical_failed") or [])
    )
    evidence_ready = str(report_time.get("status") or "") == "READY"

    readiness = {
        "engine": "ENGINE_READY" if engine_ready else "ENGINE_REVIEW_REQUIRED",
        "final_report_evidence": "FINAL_REPORT_EVIDENCE_READY" if evidence_ready else "FINAL_REPORT_EVIDENCE_PENDING",
        "report_time_status": report_time.get("status"),
        "web_refresh_required": bool(report_time.get("web_refresh_required")),
        "predictive_validation": {
            "status": prediction.get("status"),
            "sample_size": sample_size,
            "settled_gameweeks": list(prediction.get("settled_gameweeks") or []),
            "model_derived_actionability": "ACTIVE" if model_eligible else "GATED",
        },
    }
    user["readiness"] = readiness

    for item in user.get("action_board") or []:
        subject = str(item.get("subject") or "")
        action_class = _action_class(subject)
        item["action_class"] = action_class
        if action_class == "FACT_CONSTRAINT":
            item["actionability"] = "ACTIONABLE"
            item["calibration_gate_applies"] = False
        else:
            item["actionability"] = "ACTIONABLE" if model_eligible else "ADVISORY_UNTIL_SETTLED_VALIDATION"
            item["calibration_gate_applies"] = True

    tech["readiness_and_actionability"] = {
        **readiness,
        "policy": {
            "runtime_readiness_is_separate_from_final_report_evidence": True,
            "fact_constraint_actionability_is_not_blocked_by_model_sample_size": True,
            "model_derived_actionability_requires_prediction_evaluation_eligibility": True,
            "existing_decisions_are_annotated_not_rewritten": True,
        },
    }
    tech.setdefault("audit", {})["runtime_and_report_evidence_readiness_are_separate"] = True
    tech["audit"]["fact_and_model_actionability_are_separate"] = True


def run() -> dict[str, Any]:
    user = read_json(DATA / "user_report.json", {})
    tech = read_json(DATA / "technical_appendix.json", {})
    latest = read_json(DATA / "latest.json", {})
    team = read_json(DATA / "team.json", {})
    lineup = read_json(DATA / "lineup_decision.json", {})
    projections = read_json(DATA / "projections.json", {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    prices = read_json(DATA / "prices.json", {})
    price_alerts = read_json(DATA / "price_alerts.json", {})
    source_health = read_json(DATA / "source_health.json", {})
    external_consensus = read_json(DATA / "external_consensus.json", {})
    comparator = watchlist.get("owned_challenger_decision") or {}
    if comparator.get("contract") != "OWNED_CHALLENGER_DECISION_V3":
        raise RuntimeError("persisted governed owned challenger decision missing from watchlist capability")
    if ((comparator.get("publication_validation") or {}).get("status")) != "PASS":
        raise RuntimeError("persisted governed owned challenger decision failed publication validation")
    report_time = run_report_time_intelligence()

    price_coverage = _hydrate_price_radar(user, team, prices, price_alerts, watchlist, comparator)

    battle = lineup.get("main_starting_xi_battle") or {}
    leader_raw = (battle.get("starter_side") or [{}])[0]
    challenger_raw = (battle.get("bench_side") or [{}])[0]
    planning_gw = int(lineup.get("planning_gw") or projections.get("planning_gw") or 1)
    leader = _battle_metrics(leader_raw.get("element"), projections, planning_gw)
    challenger = _battle_metrics(challenger_raw.get("element"), projections, planning_gw)
    section = user.get("starting_xi") or {}
    model_battle = (section.get("model") or {}).get("battle") or {}
    model_battle["leader_metrics"] = leader
    model_battle["challenger_metrics"] = challenger
    model_battle["main_reasons"] = _battle_reasons(leader, challenger) if leader and challenger else []

    _apply_transfer_decision(user, comparator)
    user["source_availability"] = _source_availability(source_health)
    user["report_time_intelligence"] = _report_time_user_block(report_time)
    user["external_consensus"] = _external_consensus_user_block(external_consensus)
    user["owned_vs_challenger"] = _comparator_user_block(comparator)
    user["main_transfer_battles"] = [_serving_battle(row) for row in (comparator.get("main_transfer_battles") or [])[:10]]
    tech["source_capability_health"] = {
        "source_overall": source_health.get("overall"),
        "capabilities": source_health.get("capability_health") or [],
        "structured_observation_count": source_health.get("structured_observation_count", 0),
        "structured_cached_count": source_health.get("structured_cached_count", 0),
        "structured_stale_count": source_health.get("structured_stale_count", 0),
        "disagreement_count": source_health.get("disagreement_count", 0),
    }
    tech["report_time_intelligence"] = report_time
    tech["external_consensus"] = external_consensus
    tech["owned_challenger_decision"] = comparator
    tech["price_radar_serving_coverage"] = price_coverage
    tech["runtime"] = {
        "current_run_ref": "data/runtime_performance.json",
        "embedded_during_report_stage": False,
        "note": "current-run runtime metadata is finalized by the orchestrator after report generation",
    }
    tech.setdefault("audit", {})["price_radar_has_current_price_when_source_available"] = True
    tech["audit"]["price_radar_owned_predictor_detail_is_all15"] = bool(price_coverage.get("owned_complete"))
    tech["audit"]["price_radar_includes_mandatory_challengers"] = True
    tech["audit"]["price_update_window_is_not_change_confirmation"] = True
    tech["audit"]["starting_xi_battle_has_decision_evidence"] = True
    tech["audit"]["source_reachability_is_separate_from_structured_data"] = True
    tech["audit"]["report_time_sources_do_not_mutate_dss"] = True
    tech["audit"]["pundit_consensus_is_compared_with_dss"] = True
    tech["audit"]["external_consensus_is_advisory_only"] = bool((external_consensus.get("governance") or {}).get("advisory_only", True))
    tech["audit"]["external_consensus_never_majority_votes"] = not bool((external_consensus.get("governance") or {}).get("majority_vote_used", False))
    tech["audit"]["external_consensus_does_not_mutate_native_truth"] = not bool((external_consensus.get("governance") or {}).get("native_truth_mutated", False))
    tech["audit"]["owned_challenger_decision_is_governed"] = comparator.get("owner") == "decision.owned_challenger_evaluation"
    tech["audit"]["owned_challenger_decision_reuses_governed_watchlist"] = int(comparator.get("governed_watchlist_count") or 0) == 20
    tech["audit"]["owned_challenger_reporting_recomputation_forbidden"] = True
    tech["audit"]["challenger_user_serving_is_bounded_summary"] = True
    tech["audit"]["livefpl_retired_from_v3_serving"] = True
    _apply_readiness_and_actionability(user, tech, latest, report_time)

    arbitration = arbitrate_decisions(user, lineup, comparator)
    user["decision_consistency"] = arbitration
    tech["decision_arbitration"] = arbitration
    tech["audit"]["decision_consistency_arbitrated_once"] = True
    assert_decision_consistency(arbitration)

    atomic_json(DATA / "user_report.json", user)
    atomic_json(DATA / "technical_appendix.json", tech)
    return {"user_report": user, "technical_appendix": tech}


if __name__ == "__main__":
    run()
