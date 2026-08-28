from __future__ import annotations

import json
from collections import Counter

from src.engines import framework_health_audit as audit
from src.utils import DATA, atomic_json, read_json

LEGAL_FORMS = {"3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"}


def _plan_checks(plan: dict, compliance: dict | None = None) -> dict[str, tuple[bool, str]]:
    xi = list(plan.get("starting_xi") or [])
    xi_ids = {int(row.get("element")) for row in xi if row.get("element") is not None}
    captain = int((plan.get("captain") or {}).get("element") or -1)
    vice = int((plan.get("vice_captain") or {}).get("element") or -1)
    bench = plan.get("bench") or {}
    chip = plan.get("chip_context") or {}
    checks = {
        "G0-10": (len(xi) == 11 and plan.get("formation") in LEGAL_FORMS, f"formation={plan.get('formation')},xi={len(xi)}"),
        "G0-11": (sum(row.get("position") == "GK" for row in xi) == 1, "starting GK"),
        "G0-12": (captain in xi_ids and vice in xi_ids and captain != vice, f"captain={captain},vice={vice}"),
        "G0-13": (bool(bench.get("gk")) and len(bench.get("order") or []) == 3, "bench structure"),
        "G0-14": (chip.get("single_chip_rule_respected") is True and (not compliance or compliance.get("overall") == "PASS"), f"single_chip={chip.get('single_chip_rule_respected')},rules={(compliance or {}).get('overall')}"),
    }
    return checks


def _prediction_fixtures(predictions: dict) -> list[dict]:
    return [
        fixture
        for player in (predictions.get("players") or [])
        for fixture in (player.get("fixtures") or [])[:3]
    ]


def _promote_official_first_capabilities(health: dict) -> dict:
    latest = read_json(DATA / "latest.json", {})
    predictions = read_json(DATA / "predictions_v4.json", {})
    universe = read_json(DATA / "universe.json", {})
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
        "DSS-18": (bonus_ok, {
            "source": "Official FPL bootstrap-static elements.bps + model bonus regression",
            "fixtures_checked": fixture_count,
            "decision_component": "components.bonus",
        }),
        "DSS-20": (defensive_risk_ok, {
            "source": "Official FPL team/fixture defensive context",
            "fixtures_checked": fixture_count,
            "decision_evidence": "clean_sheet_probability + opponent_defence_resistance",
        }),
        "DSS-21": (team_attack_ok, {
            "source": "Official FPL bootstrap team/player attacking evidence",
            "teams": official.get("teams"),
            "team_strength_rows_complete": official.get("team_strength_rows_complete"),
            "decision_evidence": "fixture_adjustment",
        }),
        "DSS-22": (team_defence_ok, {
            "source": "Official FPL bootstrap strength_defence_home/away + finished results",
            "teams": official.get("teams"),
            "decision_evidence": "clean_sheet_probability + opponent resistance",
        }),
        "DSS-23": (fixture_context_ok, {
            "source": "Official FPL fixtures",
            "upcoming_fixtures": official.get("upcoming_fixture_rows"),
            "context_rows_complete": official.get("fixture_context_rows_complete"),
            "decision_evidence": "home/away + official FDR consumed by fixture adjustment",
        }),
        "DSS-38": (regression_ok, {
            "source": "Official FPL current xG/xA with prior shrinkage",
            "fixtures_checked": fixture_count,
            "decision_evidence": "current_season_weight + attacking_rate_shrinkage",
        }),
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
            row["detail"] = {
                "source": "Official FPL bootstrap-static elements.selected_by_percent",
                "ownership_rows": coverage,
                "players": player_count,
                "effective_ownership_available_from_official_fpl": False,
                "reason": "Official FPL provides ownership percentage but not effective ownership; module remains PARTIAL.",
            }
        elif module_id in {"DSS-30", "DSS-31", "DSS-32", "DSS-33"}:
            row["detail"] = {
                "official_fpl_scope": official.get("external_schedule_scope", "premier_league_only"),
                "reason": "Official FPL fixtures cover Premier League matches only; complete congestion/travel/rest evidence needs external competition schedules, so this remains PARTIAL.",
            }

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
    health["capability_coverage"] = {
        "active": active,
        "warmup": warmup,
        "partial": partial,
        "failed": failed,
        "declared": declared,
        "active_ratio": round(active / max(1, active + partial + warmup), 4),
    }
    health["official_fpl_first"] = {
        "status": "PASS" if official.get("official_fpl_first") else "FAIL",
        "source": official.get("source"),
        "promoted_modules": promoted,
        "promoted_count": len(promoted),
        "ownership_eo_limitation_disclosed": True,
        "external_schedule_limitation_disclosed": True,
    }
    return health


def run() -> dict:
    health = audit.audit("postflight", strict=False)
    health = _promote_official_first_capabilities(health)
    engine_plan = read_json(DATA / "lineup_decision_v4.json", {})
    overlay = read_json(DATA / "effective_plan_v4.json", {})
    effective_plan = overlay.get("effective_plan") or {}
    compliance = read_json(DATA / "compliance_audit.json", {})
    if not engine_plan or not effective_plan:
        raise RuntimeError("postflight truth service requires engine and effective plans")

    engine_checks = _plan_checks(engine_plan, compliance)
    effective_checks = _plan_checks(effective_plan, compliance)
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
        "engine_plan": {
            "authority": "ENGINE_RECOMMENDATION",
            "formation": engine_plan.get("formation"),
            "legal": all(value[0] for value in engine_checks.values()),
        },
        "effective_plan": {
            "authority": effective_plan.get("authority") or overlay.get("decision_authority") or "UNKNOWN",
            "formation": effective_plan.get("formation"),
            "legal": all(value[0] for value in effective_checks.values()),
        },
        "both_required": True,
    }
    health.setdefault("governance", {})["effective_plan_legality_enforced"] = True
    health["governance"]["engine_and_effective_plan_legality_reported_separately"] = True
    health["governance"]["official_fpl_first_when_available"] = True
    health["release"] = "4.9.5"

    if not gate0_pass:
        health["overall"] = "RED"
        health["pipeline_health"] = "RED"
        health["recommendation_allowed"] = False
        health["go_allowed"] = False

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
    }, ensure_ascii=False))
    if health.get("overall") == "RED":
        raise SystemExit(2)
    return health


if __name__ == "__main__":
    run()
