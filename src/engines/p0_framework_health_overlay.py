from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from src.utils import DATA, ROOT, atomic_json, read_json

XMINS_CONTRACT_VALIDATION = read_json(ROOT / "config" / "intelligence" / "xmins_v2.json", {}).get("contract_validation") or {}
PROJECTION_VALIDATION = read_json(ROOT / "config" / "intelligence" / "projection.json", {}).get("validation") or {}
XMINS_PROBABILITY_SUM_TOLERANCE = float(XMINS_CONTRACT_VALIDATION["probability_sum_tolerance"])
MINIMUM_PLAYER_COVERAGE_RATIO = float(PROJECTION_VALIDATION["minimum_player_coverage_ratio"])

HEALTH_PATH = DATA / "framework_health.json"
PREFLIGHT_PATH = DATA / "framework_health_preflight.json"
CHALLENGER_REGISTRY_PATH = ROOT / "config" / "intelligence" / "challenger_registry.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _projection_probe() -> tuple[bool, dict[str, Any]]:
    projections = read_json(DATA / "projections.json", {})
    universe = read_json(DATA / "universe.json", {})
    players = list(projections.get("players") or [])
    expected = len(universe.get("players") or [])
    valid = 0
    uncertainty = 0
    small_sample = 0
    horizon15 = 0
    for p in players:
        x = p.get("xmins") or {}
        probs = sum(float(x.get(k) or 0) for k in ("start_probability", "bench_probability", "dnp_probability"))
        interval = x.get("expected_minutes_interval") or []
        rows = p.get("xpts_by_gw") or []
        if abs(probs - 1.0) < XMINS_PROBABILITY_SUM_TOLERANCE and 0 <= float(x.get("expected_minutes") or 0) <= 90:
            valid += 1
        if len(interval) == 2 and all(r.get("std") is not None for r in rows):
            uncertainty += 1
        if x.get("small_sample_guard") is not None:
            small_sample += 1
        if len(rows) >= 15:
            horizon15 += 1
    coverage = valid / max(1, expected)
    ok = expected > 0 and len(players) == expected and coverage >= MINIMUM_PLAYER_COVERAGE_RATIO and uncertainty == len(players) and horizon15 == len(players)
    return ok, {
        "players": len(players),
        "expected": expected,
        "valid_xmins": valid,
        "uncertainty_coverage": uncertainty,
        "small_sample_guard_coverage": small_sample,
        "horizon15_coverage": horizon15,
        "coverage": round(coverage, 4),
        "model": projections.get("model"),
    }


def _team_strength_probe() -> tuple[bool, dict[str, Any]]:
    strength = read_json(DATA / "team_strength.json", {})
    universe = read_json(DATA / "universe.json", {})
    expected_teams = len({int(p.get("team_id")) for p in universe.get("players") or [] if p.get("team_id") is not None})
    teams = list(strength.get("teams") or [])
    matchups = list(strength.get("matchups") or [])
    valid = sum(1 for t in teams if all(t.get(k) is not None for k in ("attack_home_index", "attack_away_index", "defence_home_index", "defence_away_index")))
    ok = expected_teams > 0 and len(teams) == expected_teams and valid == len(teams) and bool(matchups)
    return ok, {
        "model": strength.get("model"),
        "teams": len(teams),
        "expected_teams": expected_teams,
        "valid_teams": valid,
        "upcoming_matchups": len(matchups),
        "baseline": strength.get("baseline"),
    }


def _package_probe() -> tuple[bool, dict[str, Any]]:
    package = read_json(DATA / "package_optimizer.json", {})
    pools = package.get("candidate_pool") or {}
    positions = {"GK", "DEF", "MID", "FWD"}
    hold = package.get("hold") or {}
    packages = list(package.get("packages") or [])
    ok = (
        package.get("status") == "READY"
        and package.get("gate0_prevalidated") is True
        and positions.issubset(set(pools))
        and hold.get("legal") is True
        and (hold.get("score") or {}).get("valid") is True
        and bool(packages)
        and all(p.get("legal") is True and (p.get("score") or {}).get("valid") is True for p in packages)
    )
    return ok, {
        "model": package.get("model"),
        "status": package.get("status"),
        "package_count": package.get("package_count"),
        "published_top_packages": len(packages),
        "candidate_positions": sorted(pools),
        "gate0_prevalidated": package.get("gate0_prevalidated"),
        "simulation_assumption": package.get("simulation_assumption"),
    }


def _calibration_probe() -> tuple[bool, dict[str, Any]]:
    accuracy = read_json(DATA / "prediction_accuracy.json", {})
    ledger = read_json(DATA / "prediction_ledger.json", {})
    records = ledger.get("records") or {}
    collecting = list(accuracy.get("collecting_gameweeks") or [])
    settled = list(accuracy.get("settled_gameweeks") or [])
    ok = bool(records) and accuracy.get("freeze_policy") == "last_pre_deadline_snapshot"
    return ok, {
        "records": len(records),
        "collecting_gameweeks": collecting,
        "settled_gameweeks": settled,
        "sample_size": (accuracy.get("overall") or {}).get("sample_size", 0),
        "confidence": accuracy.get("confidence"),
        "dynamic_weight_eligible": accuracy.get("dynamic_weight_eligible"),
    }


def _challenger_probe() -> tuple[str, dict[str, Any]]:
    score = read_json(DATA / "challenger_scorecard.json", {})
    registry = read_json(CHALLENGER_REGISTRY_PATH, {})
    expected = {
        str(p.get("id"))
        for p in registry.get("providers") or []
        if p.get("enabled", True) and p.get("id")
    }
    providers = list(score.get("providers") or [])
    provider_ids = {str(p.get("id")) for p in providers if p.get("id")}
    if not expected or provider_ids != expected:
        return "FAILED", {
            "providers": sorted(provider_ids),
            "required": sorted(expected),
            "missing": sorted(expected - provider_ids),
            "unexpected": sorted(provider_ids - expected),
        }

    states = {str(p.get("id")): str(p.get("state") or "") for p in providers}
    internal_state = states.get("internal")
    if internal_state != "ACTIVE":
        return "FAILED", {
            "status": score.get("status"),
            "providers": states,
            "reason": "internal challenger baseline is not active",
        }

    external_active = sorted(
        provider_id
        for provider_id, state in states.items()
        if provider_id != "internal" and (state == "ACTIVE" or state.startswith("ACTIVE_"))
    )
    status = "ACTIVE" if external_active else "PARTIAL"
    return status, {
        "status": score.get("status"),
        "providers": states,
        "external_active": external_active,
        "current_comparisons": len(score.get("current_comparisons") or []),
        "structured_fresh_count": int(score.get("structured_fresh_count") or 0),
        "auto_scrape": score.get("auto_scrape"),
        "reason": None if external_active else "external advisory evidence currently absent; no fabrication allowed",
    }


def _set_probe_status(health: dict[str, Any], probe_names: set[str], status: str, detail: dict[str, Any]) -> None:
    for group in ("dss_core", "dss_extensions", "enhancements"):
        block = health.get(group) or {}
        for item in block.get("items") or []:
            if item.get("probe") in probe_names and item.get("status") != "FAILED":
                item["status"] = status
                item["detail"] = {"p0_operational_probe": True, **detail}


def _recount(health: dict[str, Any]) -> None:
    critical_failed = []
    critical_partial = []
    any_partial = False
    for group in ("dss_core", "dss_extensions", "enhancements"):
        block = health.get(group) or {}
        counts = Counter(item.get("status") for item in block.get("items") or [])
        block["counts"] = dict(counts)
        any_partial = any_partial or counts.get("PARTIAL", 0) > 0
        for item in block.get("items") or []:
            if item.get("critical") and item.get("status") == "FAILED":
                critical_failed.append(item.get("id"))
            elif item.get("critical") and item.get("status") == "PARTIAL":
                critical_partial.append(item.get("id"))
    health["critical_failed"] = critical_failed
    health["critical_partial"] = critical_partial

    rules_status = ((health.get("rules_registry") or {}).get("status") or "MISSING")
    source_status = ((health.get("source_health") or {}).get("status") or "FAIL")
    data_status = ((health.get("data_freshness") or {}).get("status") or "PARTIAL")
    gate = health.get("gate0") or {}
    gate_fail = int((gate.get("counts") or {}).get("FAIL", 0)) > 0 or gate.get("pass") is False
    registry_ok = health.get("registry_integrity") is True
    rules_failed = rules_status not in {"PASS", "REVIEW_REQUIRED"}
    rules_review = rules_status == "REVIEW_REQUIRED"
    if not registry_ok or gate_fail or critical_failed or rules_failed or source_status == "FAIL":
        overall = "RED"
    elif rules_review or critical_partial or data_status != "PASS" or any_partial:
        overall = "AMBER"
    else:
        overall = "GREEN"
    health["overall"] = overall
    health["decision_engine"] = "HEALTHY" if overall == "GREEN" else "DEGRADED" if overall == "AMBER" else "BLOCKED"
    health["recommendation_allowed"] = overall != "RED" and not gate_fail
    health["go_allowed"] = overall == "GREEN" and not gate_fail and not rules_review


def run() -> dict[str, Any]:
    health = read_json(HEALTH_PATH, {})
    if not health:
        raise RuntimeError("framework_health.json missing before P0 overlay")

    projection_ok, projection_detail = _projection_probe()
    strength_ok, strength_detail = _team_strength_probe()
    package_ok, package_detail = _package_probe()
    calibration_ok, calibration_detail = _calibration_probe()
    challenger_status, challenger_detail = _challenger_probe()

    _set_probe_status(health, {"xmins", "xmins_distribution", "projection_uncertainty", "small_sample_guard", "uncertainty_robustness"}, "ACTIVE" if projection_ok else "FAILED", projection_detail)
    _set_probe_status(health, {"clean_sheet_probability", "team_defensive_risk", "team_attacking_strength", "team_defensive_strength", "fixture_context", "fixture_difficulty", "fixture_swing"}, "ACTIVE" if strength_ok else "FAILED", strength_detail)
    _set_probe_status(health, {"horizon_3", "horizon_5", "horizon_10", "horizon_15", "multi_horizon"}, "ACTIVE" if projection_ok and package_ok else "FAILED", {**projection_detail, **package_detail})
    _set_probe_status(health, {"budget_opportunity_cost", "direct_challenger", "governed_optimizer", "package_churn_penalty", "package_structural"}, "ACTIVE" if package_ok else "FAILED", package_detail)
    _set_probe_status(health, {"calibration_store"}, "ACTIVE" if calibration_ok else "FAILED", calibration_detail)
    learning_status = "ACTIVE" if calibration_ok and int(calibration_detail.get("sample_size") or 0) > 0 else "PARTIAL"
    _set_probe_status(health, {"learning_loop"}, learning_status, {**calibration_detail, "reason": "awaiting settled GW sample" if learning_status == "PARTIAL" else "settled sample available"})

    health["framework_schema"] = max(3, int(health.get("framework_schema") or 0))
    health["auditor"] = "framework-health-auditor-v3+p0-intelligence-overlay"
    health["p0_capabilities"] = {
        "P0-1_prediction_calibration_backtest": {"status": "ACTIVE" if calibration_ok else "FAILED", "detail": calibration_detail},
        "P0-2_xmins_role_v2": {"status": "ACTIVE" if projection_ok else "FAILED", "detail": projection_detail},
        "P0-3_team_strength_fixture_probability": {"status": "ACTIVE" if strength_ok else "FAILED", "detail": strength_detail},
        "P0-4_multi_horizon_package_optimizer": {"status": "ACTIVE" if package_ok else "FAILED", "detail": package_detail},
        "P0-5_external_challenger_scorecard": {"status": challenger_status, "detail": challenger_detail},
    }
    health.setdefault("governance", {}).update({
        "p0_models_are_candidate_generators_not_final_go": True,
        "external_challenger_missing_data_is_never_fabricated": True,
        "provider_dynamic_weight_requires_observed_accuracy": True,
        "p0_operational_probes_can_upgrade_partial_only_with_runtime_evidence": True,
        "external_challenger_provider_set_is_registry_owned": True,
        "external_challenger_absence_is_partial_not_failed_when_internal_baseline_is_active": True,
    })
    health["p0_overlay_generated_at"] = _now()
    _recount(health)
    atomic_json(HEALTH_PATH, health)
    if PREFLIGHT_PATH.exists() and health.get("phase") == "preflight":
        atomic_json(PREFLIGHT_PATH, health)
    print(json.dumps({
        "overall": health.get("overall"),
        "p0": {k: v.get("status") for k, v in health["p0_capabilities"].items()},
        "dss_core": (health.get("dss_core") or {}).get("counts"),
        "extensions": (health.get("dss_extensions") or {}).get("counts"),
        "enhancements": (health.get("enhancements") or {}).get("counts"),
        "go_allowed": health.get("go_allowed"),
    }, ensure_ascii=False))
    return health


if __name__ == "__main__":
    run()
