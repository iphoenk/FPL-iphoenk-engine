from __future__ import annotations

import json
from collections import Counter
from time import perf_counter

from src.engines import framework_health_audit as audit
from src.engines.fpl_legality import plan_legality_checks
from src.release import RELEASE_VERSION
from src.utils import DATA, atomic_json, read_json

CAPABILITY_STATES = {"ACTIVE", "ACTIVE_ADVISORY", "DEGRADED", "PARTIAL", "STALE", "WARMUP", "UNAVAILABLE", "BLOCKED"}


def _prediction_fixtures(predictions: dict) -> list[dict]:
    return [
        fixture
        for player in (predictions.get("players") or [])
        for fixture in (player.get("fixtures") or [])[:3]
    ]


def _postflight_audit_single_prediction_parse(predictions: dict | None = None) -> tuple[dict, dict, float]:
    """Run postflight health over one immutable prediction snapshot."""
    started = perf_counter()
    predictions = predictions if predictions is not None else read_json(DATA / "predictions_v4.json", {})
    if not (predictions.get("players") or []):
        raise RuntimeError("postflight truth requires current predictions")
    audit._PREDICTION_CACHE = predictions
    audit._PROBE_CACHE = {}
    try:
        health = audit._audit_with_cache("postflight", strict=False, started=started)
    finally:
        audit._PREDICTION_CACHE = None
        audit._PROBE_CACHE = None
    return health, predictions, round((perf_counter() - started) * 1000.0, 2)


def _promote_official_first_capabilities(
    health: dict,
    *,
    latest: dict | None = None,
    predictions: dict | None = None,
    universe: dict | None = None,
) -> dict:
    latest = latest if latest is not None else read_json(DATA / "latest.json", {})
    predictions = predictions if predictions is not None else read_json(DATA / "predictions_v4.json", {})
    universe = universe if universe is not None else read_json(DATA / "universe.json", {})
    official = latest.get("official_context") or {}
    fixtures = _prediction_fixtures(predictions)
    players = list(universe.get("players") or [])
    fixture_count = len(fixtures)
    player_count = len(players)

    bonus_ok = bool(fixtures) and all(
        "bonus" in (row.get("components") or {})
        and (row.get("provenance") or {}).get("bonus_regression") is True
        for row in fixtures
    )
    defensive_risk_ok = bool(fixtures) and all(
        (row.get("calibration") or {}).get("clean_sheet_probability") is not None
        and (row.get("calibration") or {}).get("opponent_defence_resistance") is not None
        for row in fixtures
    )
    team_strength_source_ok = (
        official.get("official_fpl_first") is True
        and int(official.get("teams") or 0) > 0
        and int(official.get("team_strength_rows_complete") or 0) == int(official.get("teams") or 0)
    )
    team_attack_ok = team_strength_source_ok and bool(fixtures) and all(
        (row.get("calibration") or {}).get("fixture_adjustment") is not None for row in fixtures
    )
    team_defence_ok = team_strength_source_ok and defensive_risk_ok
    fixture_context_ok = (
        official.get("official_fpl_first") is True
        and int(official.get("upcoming_fixture_rows") or 0) > 0
        and int(official.get("fixture_context_rows_complete") or 0) == int(official.get("upcoming_fixture_rows") or 0)
        and bool(fixtures)
        and all((row.get("provenance") or {}).get("fixture_source") == "official_fpl" for row in fixtures)
    )
    regression_ok = bool(fixtures) and all(
        (row.get("provenance") or {}).get("attacking_rate_shrinkage") is True
        and (row.get("rates") or {}).get("current_season_weight") is not None
        for row in fixtures
    ) and any(0 < float((row.get("rates") or {}).get("current_season_weight") or 0) < 1 for row in fixtures)

    promotions = {
        "DSS-18": (bonus_ok, {"source": "Official FPL bootstrap-static elements.bps + model bonus regression", "fixtures_checked": fixture_count, "decision_component": "components.bonus"}),
        "DSS-20": (defensive_risk_ok, {"source": "Official FPL team/fixture defensive context", "fixtures_checked": fixture_count, "decision_evidence": "clean_sheet_probability + opponent_defence_resistance"}),
        "DSS-21": (team_attack_ok, {"source": "Official FPL bootstrap team/player attacking evidence", "teams": official.get("teams"), "team_strength_rows_complete": official.get("team_strength_rows_complete"), "decision_evidence": "fixture_adjustment"}),
        "DSS-22": (team_defence_ok, {"source": "Official FPL bootstrap strength_defence_home/away + finished results", "teams": official.get("teams"), "decision_evidence": "clean_sheet_probability + opponent resistance"}),
        "DSS-23": (fixture_context_ok, {"source": "Official FPL fixtures", "upcoming_fixtures": official.get("upcoming_fixture_rows"), "context_rows_complete": official.get("fixture_context_rows_complete"), "decision_evidence": "home/away + official FDR consumed by fixture adjustment"}),
        "DSS-38": (regression_ok, {"source": "Official FPL current xG/xA with prior shrinkage", "fixtures_checked": fixture_count, "decision_evidence": "current_season_weight + attacking_rate_shrinkage"}),
    }

    core = health.get("dss_core") or {}
    items = list(core.get("items") or [])
    promoted = []
    for row in items:
        module_id = row.get("id")
        if module_id in promotions:
            ok, detail = promotions[module_id]
            if ok:
                row["status"] = "ACTIVE"
                row["detail"] = detail
                promoted.append(module_id)
        elif module_id == "DSS-41":
            coverage = (official.get("player_field_coverage") or {}).get("ownership")
            row["detail"] = {"source": "Official FPL bootstrap-static elements.selected_by_percent", "ownership_rows": coverage, "players": player_count, "effective_ownership_available_from_official_fpl": False, "reason": "Official FPL provides ownership percentage but not effective ownership; module remains PARTIAL."}
        elif module_id in {"DSS-30", "DSS-31", "DSS-32", "DSS-33"}:
            row["detail"] = {"official_fpl_scope": official.get("external_schedule_scope", "premier_league_only"), "reason": "Official FPL fixtures cover Premier League matches only; complete congestion/travel/rest evidence needs external competition schedules, so this remains PARTIAL."}

    core_counts = Counter(row.get("status") for row in items)
    core["counts"] = dict(core_counts)
    health["dss_core"] = core
    extension_counts = Counter(row.get("status") for row in (health.get("dss_extensions") or {}).get("items") or [])
    enhancement_counts = Counter(row.get("status") for row in (health.get("enhancements") or {}).get("items") or [])
    active = core_counts.get("ACTIVE", 0) + extension_counts.get("ACTIVE", 0) + enhancement_counts.get("ACTIVE", 0)
    partial = core_counts.get("PARTIAL", 0) + extension_counts.get("PARTIAL", 0) + enhancement_counts.get("PARTIAL", 0)
    warmup = core_counts.get("WARMUP", 0) + extension_counts.get("WARMUP", 0) + enhancement_counts.get("WARMUP", 0)
    failed = core_counts.get("FAILED", 0) + extension_counts.get("FAILED", 0) + enhancement_counts.get("FAILED", 0)
    declared = active + partial + warmup + failed
    health["capability_coverage"] = {"active": active, "warmup": warmup, "partial": partial, "failed": failed, "declared": declared, "active_ratio": round(active / max(1, active + partial + warmup), 4)}
    health["official_fpl_first"] = {"status": "PASS" if official.get("official_fpl_first") else "FAIL", "source": official.get("source"), "promoted_modules": promoted, "promoted_count": len(promoted), "ownership_eo_limitation_disclosed": True, "external_schedule_limitation_disclosed": True}
    return health


def _module_status(health: dict, module_id: str) -> str | None:
    for section in ("dss_core", "dss_extensions", "enhancements"):
        for row in (health.get(section) or {}).get("items") or []:
            if row.get("id") == module_id:
                return str(row.get("status") or "") or None
    return None


def _canonical_capability_telemetry(health: dict, latest: dict, predictions: dict, universe: dict) -> dict:
    team = read_json(DATA / "team.json", {})
    tactical = read_json(DATA / "tactical_serving_v4.json", {})
    packages = read_json(DATA / "wc_package_audit_v4.json", {})
    lineup = read_json(DATA / "lineup_decision_v4.json", {})
    arbitration = read_json(DATA / "decision_arbitration_v4.json", {})
    lifecycle = read_json(DATA / "validation/lifecycle_v4.json", {})
    compliance = read_json(DATA / "compliance_audit.json", {})
    effective = read_json(DATA / "effective_plan_v4.json", {})

    fixtures = _prediction_fixtures(predictions)
    xmins_rows = [row.get("xmins") or {} for row in fixtures]
    xmins_complete = bool(xmins_rows) and all(row.get("start_probability") is not None and row.get("dnp_probability") is not None for row in xmins_rows)
    opponent_active = all(_module_status(health, module_id) == "ACTIVE" for module_id in ("DSS-20", "DSS-21", "DSS-22", "DSS-23"))
    competitive_states = [_module_status(health, module_id) for module_id in ("DSS-30", "DSS-31", "DSS-32", "DSS-33")]
    competitive_state = "ACTIVE" if competitive_states and all(state == "ACTIVE" for state in competitive_states) else "PARTIAL"
    prediction_health = str(health.get("prediction_health") or "").upper()
    prediction_state = {"GREEN": "ACTIVE", "AMBER": "DEGRADED", "RED": "BLOCKED"}.get(prediction_health, "UNAVAILABLE")
    freshness = str((latest.get("freshness_state") or (latest.get("freshness") or {}).get("freshness_state") or "")).upper()
    official_state = "ACTIVE" if (health.get("official_fpl_first") or {}).get("status") == "PASS" else "BLOCKED"
    personal_state = "ACTIVE" if len(team.get("squad") or []) == 15 and team.get("squad_authority") else "BLOCKED"
    phase_state = "ACTIVE" if (latest.get("phase") or {}).get("planning_gw") and (latest.get("checkpoint_context") or {}).get("policy_id") else "BLOCKED"
    tactical_state = "ACTIVE" if len(tactical.get("owned") or []) == 15 and len(tactical.get("watchlist") or []) == 20 else "PARTIAL"
    finance_state = "ACTIVE" if len(team.get("team_value_ledger") or []) == 15 and (packages.get("affordability") or {}).get("price_basis") else "PARTIAL"
    package_search = packages.get("search") or {}
    package_proven = (
        package_search.get("status") == "FULL_UNIVERSE_PROVEN"
        and package_search.get("authoritative_for_recommendation") is True
        and packages.get("decision_authority") == "ENGINE_ADVISORY_ONLY_FULL_UNIVERSE_PROVEN"
    )
    package_state = (
        "ACTIVE" if package_proven and packages.get("best_by_replacement_count") is not None and packages.get("overall_verdict")
        else "BLOCKED" if package_search.get("status") == "FULL_UNIVERSE_HEURISTIC"
        else "UNAVAILABLE"
    )
    lineup_state = "ACTIVE" if len(lineup.get("starting_xi") or []) == 11 else "BLOCKED"
    captain_state = "ACTIVE" if (lineup.get("captain") or {}).get("element") and (lineup.get("vice_captain") or {}).get("element") else "BLOCKED"
    comparator_state = "ACTIVE" if tactical_state == "ACTIVE" and arbitration.get("resolution_id") else "PARTIAL"
    validation_state = "ACTIVE" if lifecycle.get("status") == "PASS" and compliance.get("overall") == "PASS" and (health.get("gate0") or {}).get("pass") is True else "DEGRADED"
    reporting_state = "ACTIVE" if arbitration.get("resolution_id") and (effective.get("effective_plan") or {}).get("starting_xi") else "BLOCKED"
    set_piece_status = _module_status(health, "DSS-17") or _module_status(health, "DSS-19")
    set_piece_state = "ACTIVE" if set_piece_status == "ACTIVE" else "PARTIAL" if set_piece_status else "UNAVAILABLE"
    external_rows = ((latest.get("source_sweep_status") or {}).get("statuses") or [])
    external_state = "ACTIVE_ADVISORY" if external_rows else "UNAVAILABLE"

    rows = {
        "Official Truth": (official_state, {"official_fpl_first": (health.get("official_fpl_first") or {}).get("status"), "freshness": freshness or None}),
        "Personal State": (personal_state, {"owned": len(team.get("squad") or []), "authority": team.get("squad_authority")}),
        "Phase Authority": (phase_state, {"planning_gw": (latest.get("phase") or {}).get("planning_gw"), "policy_id": (latest.get("checkpoint_context") or {}).get("policy_id")}),
        "Prediction": (prediction_state, {"prediction_health": health.get("prediction_health"), "players": len(predictions.get("players") or [])}),
        "xMins": ("ACTIVE" if xmins_complete else "PARTIAL", {"fixture_rows": len(xmins_rows), "complete": xmins_complete}),
        "Opponent Model": ("ACTIVE" if opponent_active else "PARTIAL", {"dss_20_23": {module_id: _module_status(health, module_id) for module_id in ("DSS-20", "DSS-21", "DSS-22", "DSS-23")}}),
        "Tactical Matchup": (tactical_state, {"owned": len(tactical.get("owned") or []), "watchlist": len(tactical.get("watchlist") or [])}),
        "Competitive Load": (competitive_state, {"dss_30_33": competitive_states}),
        "Set Pieces": (set_piece_state, {"health_status": set_piece_status}),
        "Price/Finance": (finance_state, {"ledger": len(team.get("team_value_ledger") or []), "price_basis": (packages.get("affordability") or {}).get("price_basis")}),
        "Comparator": (comparator_state, {"canonical_resolution": arbitration.get("resolution_id"), "watchlist": len(tactical.get("watchlist") or [])}),
        "Package Optimizer": (package_state, {
            "verdict": packages.get("overall_verdict"),
            "search_status": package_search.get("status"),
            "authoritative_for_recommendation": package_search.get("authoritative_for_recommendation"),
            "decision_authority": packages.get("decision_authority"),
            "false_green_forbidden": True,
        }),
        "XI/Bench": (lineup_state, {"xi": len(lineup.get("starting_xi") or []), "formation": lineup.get("formation")}),
        "Captaincy": (captain_state, {"captain": (lineup.get("captain") or {}).get("element"), "vice": (lineup.get("vice_captain") or {}).get("element")}),
        "External Consensus": (external_state, {"source_rows": len(external_rows), "advisory_only": True}),
        "Validation/Calibration": (validation_state, {"lifecycle": lifecycle.get("status"), "compliance": compliance.get("overall"), "gate0": (health.get("gate0") or {}).get("pass")}),
        "Reporting/Serving": (reporting_state, {"canonical_resolution": arbitration.get("resolution_id"), "effective_xi": len((effective.get("effective_plan") or {}).get("starting_xi") or []), "composition_only": True}),
    }
    telemetry = {name: {"state": state, "evidence": evidence} for name, (state, evidence) in rows.items()}
    invalid = {name: row["state"] for name, row in telemetry.items() if row["state"] not in CAPABILITY_STATES}
    if invalid:
        raise RuntimeError(f"invalid capability telemetry states: {invalid}")
    return {
        "schema_version": 1,
        "states_allowed": sorted(CAPABILITY_STATES),
        "capabilities": telemetry,
        "summary": dict(Counter(row["state"] for row in telemetry.values())),
        "false_green_forbidden": True,
    }


def run(
    *,
    predictions: dict | None = None,
    latest: dict | None = None,
    universe: dict | None = None,
) -> dict:
    total = perf_counter()
    health, predictions, audit_ms = _postflight_audit_single_prediction_parse(predictions)
    latest = latest if latest is not None else read_json(DATA / "latest.json", {})
    universe = universe if universe is not None else read_json(DATA / "universe.json", {})

    started = perf_counter()
    health = _promote_official_first_capabilities(health, latest=latest, predictions=predictions, universe=universe)
    promotion_ms = round((perf_counter() - started) * 1000.0, 2)

    engine_plan = read_json(DATA / "lineup_decision_v4.json", {})
    overlay = read_json(DATA / "effective_plan_v4.json", {})
    effective_plan = overlay.get("effective_plan") or {}
    compliance = read_json(DATA / "compliance_audit.json", {})
    if not engine_plan or not effective_plan:
        raise RuntimeError("postflight truth service requires engine and effective plans")

    started = perf_counter()
    engine_checks = plan_legality_checks(engine_plan, compliance)
    effective_checks = plan_legality_checks(effective_plan, compliance)
    items = list((health.get("gate0") or {}).get("items") or [])
    by_id = {row.get("id"): row for row in items}
    for check_id in ("G0-10", "G0-11", "G0-12", "G0-13", "G0-14"):
        engine_ok, engine_detail = engine_checks[check_id]
        effective_ok, effective_detail = effective_checks[check_id]
        row = by_id.get(check_id)
        if row is None:
            raise RuntimeError(f"Gate-0 row missing: {check_id}")
        row["status"] = "PASS" if engine_ok and effective_ok else "FAIL"
        row["detail"] = f"engine[{engine_detail}];effective[{effective_detail}]"

    counts = Counter(row.get("status") for row in items)
    gate0_pass = counts.get("FAIL", 0) == 0
    health["gate0"]["counts"] = dict(counts)
    health["gate0"]["pass"] = gate0_pass
    health["gate0"]["plan_authority_validation"] = {
        "engine_plan": {"authority": "ENGINE_RECOMMENDATION", "formation": engine_plan.get("formation"), "legal": all(value[0] for value in engine_checks.values())},
        "effective_plan": {"authority": effective_plan.get("authority") or overlay.get("decision_authority") or "UNKNOWN", "formation": effective_plan.get("formation"), "legal": all(value[0] for value in effective_checks.values())},
        "both_required": True,
    }
    legality_ms = round((perf_counter() - started) * 1000.0, 2)

    health.setdefault("governance", {})["effective_plan_legality_enforced"] = True
    health["governance"]["engine_and_effective_plan_legality_reported_separately"] = True
    health["governance"]["official_fpl_first_when_available"] = True
    health["governance"]["postflight_prediction_snapshot_single_parse"] = True
    health["release"] = RELEASE_VERSION

    if not gate0_pass:
        health["overall"] = "RED"
        health["pipeline_health"] = "RED"
        health["recommendation_allowed"] = False
        health["go_allowed"] = False

    started = perf_counter()
    health["capability_telemetry"] = _canonical_capability_telemetry(health, latest, predictions, universe)
    telemetry_ms = round((perf_counter() - started) * 1000.0, 2)

    total_ms = round((perf_counter() - total) * 1000.0, 2)
    health["postflight_service_performance"] = {
        "audit_ms": audit_ms,
        "official_promotion_ms": promotion_ms,
        "plan_legality_ms": legality_ms,
        "capability_telemetry_ms": telemetry_ms,
        "prediction_snapshot_parse_count": 1,
        "total_ms": total_ms,
    }
    atomic_json(DATA / "framework_health_v4.json", health)
    print(json.dumps({
        "service": "framework_postflight",
        "pipeline_health": health.get("pipeline_health"),
        "gate0": health["gate0"]["counts"],
        "engine_formation": engine_plan.get("formation"),
        "effective_formation": effective_plan.get("formation"),
        "both_legal": gate0_pass,
        "official_promoted": (health.get("official_fpl_first") or {}).get("promoted_modules"),
        "capability_coverage": health.get("capability_coverage"),
        "canonical_capability_telemetry": (health.get("capability_telemetry") or {}).get("summary"),
        "performance_ms": total_ms,
        "prediction_snapshot_parse_count": 1,
    }, ensure_ascii=False))
    if health.get("overall") == "RED":
        raise SystemExit(2)
    return health


if __name__ == "__main__":
    run()
