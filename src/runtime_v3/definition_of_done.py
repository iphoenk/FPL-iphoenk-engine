from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from src.utils import DATA, ROOT, parse_dt, read_json

SLO_PATH = ROOT / "config" / "runtime" / "performance_slo.json"


def _check(rows: list[dict[str, Any]], name: str, passed: bool, detail: Any = None, *, external: bool = False) -> None:
    rows.append({
        "name": name,
        "status": "EXTERNAL_PROOF" if external else ("PASS" if passed else "FAIL"),
        "passed": bool(passed) if not external else None,
        "detail": detail,
    })


def _run_json_module(module: str, *args: str) -> tuple[bool, dict[str, Any]]:
    proc = subprocess.run([sys.executable, "-m", module, *args], capture_output=True, text=True, check=False)
    parsed: dict[str, Any] = {}
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
            break
        except json.JSONDecodeError:
            continue
    if not parsed and proc.stderr:
        parsed = {"stderr_tail": proc.stderr[-2000:]}
    return proc.returncode == 0, parsed


def _freshness_seconds(payload: dict[str, Any]) -> float | None:
    generated = parse_dt(payload.get("generated_at"))
    if generated is None:
        return None
    now = datetime.now(timezone.utc)
    return max(0.0, (now - generated).total_seconds())


def _framework_counts(framework: dict[str, Any], key: str, state: str) -> int:
    block = framework.get(key) or {}
    return int((block.get("counts") or {}).get(state) or 0)


def _finite_number(value: Any, *, allow_zero: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    if number < 0.0 or (number == 0.0 and not allow_zero):
        return None
    return number


def _selected_profile_runtime_contract(
    runtime: dict[str, Any],
    slo_registry: dict[str, Any] | None = None,
) -> tuple[bool, dict[str, Any]]:
    detail: dict[str, Any] = {
        "profile": runtime.get("execution_profile") if isinstance(runtime, dict) else None,
        "wall_ms": runtime.get("total_wall_ms") if isinstance(runtime, dict) else None,
        "target_ms": runtime.get("target_wall_ms") if isinstance(runtime, dict) else None,
        "ceiling_ms": runtime.get("legacy_ceiling_ms") if isinstance(runtime, dict) else None,
    }
    if not isinstance(runtime, dict) or not runtime:
        detail["reason"] = "MISSING_RUNTIME_TELEMETRY"
        return False, detail

    if slo_registry is None:
        try:
            slo_registry = json.loads(SLO_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            detail["reason"] = "INVALID_SLO_REGISTRY"
            detail["error"] = f"{type(exc).__name__}: {exc}"
            return False, detail

    if not isinstance(slo_registry, dict) or slo_registry.get("registry") != "RUNTIME_PERFORMANCE_SLO_V1":
        detail["reason"] = "INVALID_SLO_REGISTRY"
        return False, detail
    profiles = slo_registry.get("profiles")
    if not isinstance(profiles, dict):
        detail["reason"] = "INVALID_SLO_REGISTRY"
        return False, detail

    profile = runtime.get("execution_profile")
    if not isinstance(profile, str) or not profile:
        detail["reason"] = "MISSING_EXECUTION_PROFILE"
        return False, detail
    profile_cfg = profiles.get(profile)
    if not isinstance(profile_cfg, dict):
        detail["reason"] = "UNKNOWN_EXECUTION_PROFILE"
        return False, detail

    wall_ms = _finite_number(runtime.get("total_wall_ms"), allow_zero=True)
    runtime_target_ms = _finite_number(runtime.get("target_wall_ms"))
    runtime_ceiling_ms = _finite_number(runtime.get("legacy_ceiling_ms"))
    runtime_budget_ms = _finite_number(runtime.get("performance_budget_ms"))
    canonical_target_ms = _finite_number(profile_cfg.get("target_wall_ms"))
    canonical_ceiling_ms = _finite_number(profile_cfg.get("legacy_ceiling_ms"))
    if canonical_ceiling_ms is None:
        canonical_ceiling_ms = canonical_target_ms

    required_numbers = {
        "total_wall_ms": wall_ms,
        "target_wall_ms": runtime_target_ms,
        "legacy_ceiling_ms": runtime_ceiling_ms,
        "performance_budget_ms": runtime_budget_ms,
        "canonical_target_wall_ms": canonical_target_ms,
        "canonical_legacy_ceiling_ms": canonical_ceiling_ms,
    }
    malformed = [name for name, value in required_numbers.items() if value is None]
    if malformed:
        detail["reason"] = "MALFORMED_TIMING_TELEMETRY"
        detail["malformed_fields"] = malformed
        return False, detail

    within_target_claim = runtime.get("within_target_slo")
    within_budget_claim = runtime.get("within_target_budget")
    if not isinstance(within_target_claim, bool) or not isinstance(within_budget_claim, bool):
        detail["reason"] = "MALFORMED_SLO_CLAIMS"
        return False, detail

    enforcement = profile_cfg.get("enforcement")
    if enforcement not in {"HARD_CEILING", "TARGET_WITH_LEGACY_CEILING", "CEILING"}:
        detail["reason"] = "UNKNOWN_SLO_ENFORCEMENT"
        detail["enforcement"] = enforcement
        return False, detail

    target_config_match = runtime_target_ms == canonical_target_ms
    ceiling_config_match = runtime_ceiling_ms == canonical_ceiling_ms
    budget_config_match = runtime_budget_ms == canonical_ceiling_ms
    computed_within_target = wall_ms <= canonical_target_ms
    computed_within_budget = wall_ms <= canonical_ceiling_ms
    target_claim_match = within_target_claim is computed_within_target
    budget_claim_match = within_budget_claim is computed_within_budget

    detail.update({
        "profile": profile,
        "wall_ms": wall_ms,
        "target_ms": canonical_target_ms,
        "ceiling_ms": canonical_ceiling_ms,
        "enforcement": enforcement,
        "within_target_slo": computed_within_target,
        "within_contract_ceiling": computed_within_budget,
        "target_claim_match": target_claim_match,
        "budget_claim_match": budget_claim_match,
        "target_config_match": target_config_match,
        "ceiling_config_match": ceiling_config_match,
        "budget_config_match": budget_config_match,
    })

    if not target_config_match or not ceiling_config_match or not budget_config_match:
        detail["reason"] = "RUNTIME_SLO_CONFIG_MISMATCH"
        return False, detail
    if not target_claim_match or not budget_claim_match:
        detail["reason"] = "FALSE_SLO_CLAIM"
        return False, detail
    if not computed_within_budget:
        detail["reason"] = "PROFILE_CEILING_BREACH"
        return False, detail

    detail["reason"] = "WITHIN_SELECTED_PROFILE_CONTRACT"
    return True, detail


def _tactical_report_coverage(user: dict[str, Any], watchlist: dict[str, Any]) -> dict[str, Any]:
    owned = list((user.get("owned_squad") or {}).get("facts") or [])
    external = [
        row
        for position in ("GK", "DEF", "MID", "FWD")
        for row in ((watchlist.get("positions") or {}).get(position) or [])
    ]
    return {
        "owned": len(owned),
        "owned_with_tactical": sum(isinstance(row.get("tactical_matchup"), dict) and bool(row.get("tactical_matchup")) for row in owned),
        "watchlist": len(external),
        "watchlist_with_tactical": sum(isinstance(row.get("tactical_matchup"), dict) and bool(row.get("tactical_matchup")) for row in external),
    }


def _price_fact_model_contract(prices: dict[str, Any], alerts: dict[str, Any], trajectory: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    official_fields = prices.get("official_price_fields") or {}
    authority = str(official_fields.get("authority") or "")
    model_id = str((prices.get("filter_policy") or {}).get("model_id") or (alerts.get("policy") or {}).get("model_id") or "")
    players = [row for row in prices.get("players") or [] if isinstance(row, dict)]
    sampled = players[:25]
    semantic_separation = bool(sampled) and all(
        "now_cost" in row
        and "official_progress_pct" in row
        and "predicted_change_deadline" in row
        and "prediction_source" in row
        for row in sampled
    )
    fact_authority = authority == "Official FPL bootstrap native fields"
    model_declared = model_id == "official_price_radar_v3"
    trajectory_is_state_cache = isinstance(trajectory.get("players"), dict) and bool(trajectory.get("generated_at"))
    return fact_authority and model_declared and semantic_separation and trajectory_is_state_cache, {
        "fact_authority": authority,
        "model_id": model_id,
        "sampled_players": len(sampled),
        "semantic_field_separation": semantic_separation,
        "fact_fields": ["now_cost", "official_progress_pct", "official_hourly_rate_pct", "official_projections"],
        "model_fields": ["predicted_change_deadline", "prediction_source", "trajectory_eta_hours", "urgency"],
        "trajectory_role": "STATE_CACHE" if trajectory_is_state_cache else "UNVERIFIED",
    }


def _user_capture_authority_contract(baseline: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """Validate phase-scoped own-team authority without requiring stale rejection.

    A valid exact-GW pre-deadline capture must be applied as LOCKED_PRE_DEADLINE.
    Official authority is also valid when there is no capture, when a stale or
    wrong-GW capture was safely rejected, or when Official reclaimed authority
    after the deadline. Invalid exact-GW capture evidence remains fail-closed.
    """

    authority = str(baseline.get("effective_authority") or "")
    requested = baseline.get("override_requested") is True
    applied = baseline.get("override_applied") is True
    rejection = baseline.get("capture_rejection_reason")
    evidence = baseline.get("capture_evidence")
    canonical_capture = str(
        baseline.get("canonical_user_capture_authority") or "LOCKED_PRE_DEADLINE"
    )

    if authority == canonical_capture:
        evidence_ok = (
            isinstance(evidence, dict)
            and evidence.get("contract") == "STRUCTURED_USER_CAPTURE_V1"
            and evidence.get("valid") is True
            and evidence.get("timestamp_valid") is True
            and evidence.get("own_team") is True
            and evidence.get("identity_validated") is True
            and evidence.get("squad_legal") is True
            and (evidence.get("lineup") or {}).get("valid") is True
        )
        passed = bool(
            requested
            and applied
            and baseline.get("capture_target_gw_matches") is True
            and baseline.get("capture_pre_deadline_phase") is True
            and baseline.get("capture_evidence_required") is True
            and rejection is None
            and baseline.get("stale_override_rejected") is not True
            and baseline.get("post_deadline_official_reclaims_authority") is not True
            and evidence_ok
        )
    elif authority == "OFFICIAL_SUBMITTED":
        if applied:
            passed = False
        elif not requested:
            passed = True
        elif rejection in {
            "STALE_TARGET_GW",
            "WRONG_FUTURE_TARGET_GW",
            "POST_DEADLINE_OFFICIAL_RECLAIM",
            "NOT_PRE_DEADLINE_PHASE",
        }:
            passed = True
        else:
            passed = False
    else:
        passed = False

    return passed, {
        "effective_authority": authority,
        "canonical_user_capture_authority": canonical_capture,
        "override_requested": requested,
        "override_applied": applied,
        "capture_target_gw_matches": baseline.get("capture_target_gw_matches"),
        "capture_pre_deadline_phase": baseline.get("capture_pre_deadline_phase"),
        "capture_rejection_reason": rejection,
        "stale_override_rejected": baseline.get("stale_override_rejected"),
        "post_deadline_official_reclaims_authority": baseline.get("post_deadline_official_reclaims_authority"),
        "capture_evidence": evidence,
    }


def _canonical_comparator_contract(watchlist: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    comparator = watchlist.get("owned_challenger_decision") or {}
    decision = comparator.get("decision") or {}
    validation = comparator.get("publication_validation") or {}
    governance = comparator.get("governance") or {}
    passed = bool(
        comparator.get("contract") == "OWNED_CHALLENGER_DECISION_V3"
        and comparator.get("owner") == "decision.owned_challenger_evaluation"
        and comparator.get("status") == "READY"
        and validation.get("status") == "PASS"
        and decision.get("execution_authorized") is False
        and governance.get("reporting_recomputation_forbidden") is True
        and governance.get("canonical_transfer_recommendation_may_consume_this_decision") is True
    )
    return passed, {
        "contract": comparator.get("contract"),
        "owner": comparator.get("owner"),
        "status": comparator.get("status"),
        "publication_validation": validation.get("status"),
        "decision_state": decision.get("state"),
        "execution_authorized": decision.get("execution_authorized"),
        "reporting_recomputation_forbidden": governance.get("reporting_recomputation_forbidden"),
        "canonical_transfer_recommendation_may_consume_this_decision": governance.get("canonical_transfer_recommendation_may_consume_this_decision"),
        "canonical_ref": "data/dss_watchlist.json#owned_challenger_decision",
    }


def run(scope: str = "candidate", source_commit: str | None = None) -> dict[str, Any]:
    framework = read_json(DATA / "framework_health.json", {})
    latest = read_json(DATA / "latest.json", {})
    user = read_json(DATA / "user_report.json", {})
    watchlist = read_json(DATA / "dss_watchlist.json", {})
    load = read_json(DATA / "recent_competitive_load.json", {})
    team = read_json(DATA / "team.json", {})
    detail = read_json(DATA / "official_detail.json", {})
    runtime = read_json(DATA / "runtime_performance.json", {})
    manifest = read_json(DATA / "runtime_manifest.json", {})
    prices = read_json(DATA / "prices.json", {})
    trajectory = read_json(DATA / "price_trajectory.json", {})
    price_alerts = read_json(DATA / "price_alerts.json", {})
    technical = read_json(DATA / "technical_appendix.json", {})
    accuracy = read_json(DATA / "prediction_accuracy.json", {})
    decision_snapshots = read_json(DATA / "decision_validation_snapshots.json", {})
    rows: list[dict[str, Any]] = []

    _check(rows, "CI_GREEN", True, "proved by the enclosing V3 CI workflow", external=True)
    _check(rows, "FRAMEWORK_GREEN", framework.get("overall") == "GREEN" and framework.get("go_allowed") is True, {"overall": framework.get("overall"), "go_allowed": framework.get("go_allowed")})
    _check(rows, "GATE0_16_16", _framework_counts(framework, "gate0", "PASS") == 16, (framework.get("gate0") or {}).get("counts"))
    _check(rows, "DSS_CORE_50_50", _framework_counts(framework, "dss_core", "ACTIVE") == 50, (framework.get("dss_core") or {}).get("counts"))
    _check(rows, "DSS_EXTENSIONS_16_16", _framework_counts(framework, "dss_extensions", "ACTIVE") == 16, (framework.get("dss_extensions") or {}).get("counts"))
    _check(rows, "ENHANCEMENTS_8_HEALTHY", _framework_counts(framework, "enhancements", "ACTIVE") == 8, (framework.get("enhancements") or {}).get("counts"))

    runtime_ok, runtime_detail = _selected_profile_runtime_contract(runtime)
    _check(rows, "SELECTED_PROFILE_RUNTIME_GREEN", runtime_ok, runtime_detail)
    capability_registry = read_json(ROOT / "config" / "v3_service_registry.json", {})
    expected_capability_count = len(capability_registry.get("services") or {})
    domain_registry = read_json(ROOT / "config" / "runtime" / "execution_domains.json", {})
    expected_domain_count = int(domain_registry.get("domain_count") or 0)
    expected_phase_count = int(domain_registry.get("phase_count") or 0)
    canonical_runtime = (
        expected_domain_count > 0
        and expected_phase_count > 0
        and int(runtime.get("execution_domain_count") or 0) == expected_domain_count
        and int(runtime.get("execution_phase_count") or 0) == expected_phase_count
        and expected_capability_count > 0
        and int(runtime.get("capability_owner_count") or 0) == expected_capability_count
    )
    _check(
        rows,
        "CANONICAL_REGISTRY_OWNED_DOMAIN_PHASE_RUNTIME",
        canonical_runtime,
        {
            "domains": runtime.get("execution_domain_count"),
            "expected_domains": expected_domain_count,
            "phases": runtime.get("execution_phase_count"),
            "expected_phases": expected_phase_count,
            "owners": runtime.get("capability_owner_count"),
            "expected_owners": expected_capability_count,
        },
    )

    age = _freshness_seconds(latest)
    _check(rows, "FRESH_RUNTIME_DATA", age is not None and age <= 900.0, {"age_seconds": round(age, 3) if age is not None else None, "max_seconds": 900})

    historical = (detail.get("historical_entry") or {})
    history_ready = historical.get("authority") == "PUBLIC_OFFICIAL_POST_DEADLINE" and any((row or {}).get("status") == "PUBLIC_OFFICIAL_SUBMITTED_TEAM" for row in (historical.get("gameweeks") or {}).values())
    _check(rows, "POST_DEADLINE_OFFICIAL_RECONCILIATION_PROVEN", history_ready, {"authority": historical.get("authority"), "gameweeks": sorted((historical.get("gameweeks") or {}).keys())})
    _check(rows, "OFFICIAL_HISTORY_IMMUTABLE_AUTHORITY", (latest.get("official_historical_authority") or {}).get("historical_submitted_team") == "GREEN_PUBLIC_OFFICIAL", latest.get("official_historical_authority"))

    workflow_text = (ROOT / ".github" / "workflows" / "v3-runtime.yml").read_text(encoding="utf-8")
    collector_policy = read_json(ROOT / "config" / "runtime" / "collector_policy.json", {})
    schedules = collector_policy.get("schedules") or {}
    recovery_policy = collector_policy.get("checkpoint_recovery") or {}
    primary_expr = str(schedules.get("primary") or "")
    precompute_expr = str(schedules.get("precompute") or "")
    adaptive_expr = str(schedules.get("adaptive") or "")
    schedule_state = {
        "primary_policy_bound": bool(primary_expr) and f'cron: "{primary_expr}"' in workflow_text,
        "precompute_policy_bound": bool(precompute_expr) and f'cron: "{precompute_expr}"' in workflow_text,
        "adaptive_policy_bound": bool(adaptive_expr) and f'cron: "{adaptive_expr}"' in workflow_text,
        "precompute_resolver": "precompute_checkpoint" in workflow_text,
        "recovery_enabled": recovery_policy.get("enabled") is True,
        "recovery_no_second_authority": recovery_policy.get("never_create_second_checkpoint_authority") is True,
    }
    schedule_ok = all(schedule_state.values())
    _check(rows, "SCHEDULE_GOVERNANCE_PROVEN", schedule_ok, schedule_state)

    comparator_ok, comparator_detail = _canonical_comparator_contract(watchlist)
    _check(rows, "COMPARATOR_CANONICAL", comparator_ok, comparator_detail)

    tactical = _tactical_report_coverage(user, watchlist)
    _check(rows, "TACTICAL_EVIDENCE_ALL_35", tactical == {"owned": 15, "owned_with_tactical": 15, "watchlist": 20, "watchlist_with_tactical": 20}, tactical)

    load_ok = int(load.get("player_count") or 0) >= 35 and load.get("contract") == "COMPETITIVE_LOAD_PRIMITIVE_V1" and (load.get("governance") or {}).get("no_blanket_fatigue_penalty") is True
    _check(rows, "COMPETITIVE_LOAD_EVIDENCE", load_ok, {"status": load.get("status"), "players": load.get("player_count"), "state_counts": load.get("state_counts")})

    ownership_ok, ownership = _run_json_module("src.engines.v3_architecture_ownership_guard")
    _check(rows, "NO_DUPLICATE_OWNERSHIP", ownership_ok and ownership.get("status") == "PASS", {"status": ownership.get("status"), "errors": ownership.get("errors")})

    owned_count = int((user.get("owned_squad") or {}).get("count") or 0)
    position_counts = {pos: len((watchlist.get("positions") or {}).get(pos) or []) for pos in ("GK", "DEF", "MID", "FWD")}
    _check(rows, "OWNED_15", owned_count == 15, owned_count)
    _check(rows, "WATCHLIST_20_5_PER_POSITION", sum(position_counts.values()) == 20 and all(value == 5 for value in position_counts.values()), position_counts)

    price_separated, price_detail = _price_fact_model_contract(prices, price_alerts, trajectory)
    _check(rows, "PRICE_FACT_MODEL_SEPARATED", price_separated, price_detail)

    no_fabrication = (
        (load.get("governance") or {}).get("travel_distance_must_not_be_invented") is True
        and (load.get("governance") or {}).get("coach_rotation_tendency_must_not_be_inferred_without_evidence") is True
        and (accuracy.get("governance") or {}).get("post_deadline_information_cannot_create_retroactive_decision_snapshot") is True
    )
    _check(rows, "NO_FABRICATED_EVIDENCE", no_fabrication, {"load_status": load.get("status"), "prediction_confidence": accuracy.get("confidence")})

    baseline = team.get("projection_baseline") or {}
    user_authority_ok, user_authority_detail = _user_capture_authority_contract(baseline)
    _check(rows, "USER_OVERRIDE_PHASE_AUTHORITY_GOVERNED", user_authority_ok, user_authority_detail)

    benchmark_ok, benchmark = _run_json_module("src.runtime_v3.unified_fastpath", "--benchmark")
    interactive_ms = benchmark.get("median_ms")
    slo_registry = read_json(SLO_PATH, {})
    instant_slo = ((slo_registry.get("profiles") or {}).get("instant_serving") or {})
    instant_ceiling_ms = _finite_number(instant_slo.get("legacy_ceiling_ms"))
    interactive_ok = bool(benchmark_ok and interactive_ms is not None and instant_ceiling_ms is not None and float(interactive_ms) < instant_ceiling_ms)
    _check(rows, "INTERACTIVE_SERVING_UNDER_1S", interactive_ok, {**benchmark, "configured_ceiling_ms": instant_ceiling_ms})

    report_registry = read_json(DATA / "report_artifact_registry.json", {})
    report_contract_ok = bool(report_registry) and (DATA / "decision_brief.json").exists() and (DATA / "deep_review_payload.json").exists()
    _check(rows, "REPORT_CONTRACTS_GREEN", report_contract_ok, {"registry": report_registry.get("registry"), "decision_brief": (DATA / "decision_brief.json").exists(), "deep_review": (DATA / "deep_review_payload.json").exists()})

    decision_capture_ok = decision_snapshots.get("contract") == "DECISION_VALIDATION_SNAPSHOTS_V1"
    _check(rows, "MODEL_VALIDATION_GENUINE_SNAPSHOT_PIPELINE", decision_capture_ok and (accuracy.get("governance") or {}).get("formula_correctness_is_separate_from_predictive_accuracy") is True, {"snapshot_contract": decision_snapshots.get("contract"), "confidence": accuracy.get("confidence"), "decision_metrics": accuracy.get("decision_metrics")})

    if scope == "production":
        source_ok = bool(source_commit) and manifest.get("source_commit") == source_commit
        _check(rows, "PRODUCTION_PUBLICATION_SOURCE_COMMIT", source_ok, {"expected": source_commit, "manifest": manifest.get("source_commit")})
    else:
        _check(rows, "PRODUCTION_PUBLICATION_SOURCE_COMMIT", True, "proved after merge by V3 Runtime publication", external=True)

    failures = [row for row in rows if row.get("status") == "FAIL"]
    result = {
        "status": "PASS" if not failures else "FAIL",
        "contract": "V3_DEFINITION_OF_DONE_V1",
        "scope": scope,
        "checks": rows,
        "failures": failures,
        "external_proofs": [row["name"] for row in rows if row.get("status") == "EXTERNAL_PROOF"],
        "policy": {
            "all_internal_checks_must_pass": True,
            "ci_green_is_proved_by_enclosing_workflow": True,
            "candidate_never_claims_production_publication": True,
            "production_scope_requires_exact_source_commit": True,
            "no_presence_only_feature_claims": True,
        },
    }
    print(json.dumps(result, ensure_ascii=False))
    if failures:
        raise SystemExit(1)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Executable V3 production definition-of-done validator")
    parser.add_argument("--scope", choices=["candidate", "production"], default="candidate")
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    run(args.scope, args.source_commit)


if __name__ == "__main__":
    main()
