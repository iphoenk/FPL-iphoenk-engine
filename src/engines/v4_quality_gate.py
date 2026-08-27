from __future__ import annotations

import json
import statistics
from pathlib import Path

from src.engines.reliability import validate_snapshot
from src.services.contracts import file_digest
from src.utils import DATA


LEGAL_FORMATIONS = {"3-4-3", "3-5-2", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"}


def _load(name: str) -> dict:
    path = DATA / name
    if not path.exists():
        raise AssertionError(f"missing required quality-gate input: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _assert_version(obj: dict, label: str, minimum: int, prefix: str, field: str = "engine") -> None:
    actual_schema = int(obj.get("schema_version", 0))
    actual_version = str(obj.get(field, ""))
    if actual_schema < minimum or not actual_version.startswith(prefix):
        raise AssertionError(
            f"stale or incompatible {label}: schema={actual_schema}, {field}={actual_version!r}; "
            f"expected schema>={minimum} and {field} prefix {prefix!r}. "
            "Run `python -m src.services.orchestrator daily --stats --deep-stats` "
            "before invoking the quality gate."
        )


def _assert_framework_health() -> tuple[dict, dict]:
    pre = _load("framework_health_preflight_v4.json")
    post = _load("framework_health_v4.json")
    for obj, phase in ((pre, "preflight"), (post, "postflight")):
        _assert_version(obj, phase, 492, "v4.9.2-truthful-health")
        assert obj.get("phase") == phase
        assert obj.get("registry_integrity") is True
        assert obj.get("overall") == obj.get("pipeline_health")
        assert obj.get("pipeline_health") in {"GREEN", "AMBER"}
        assert obj.get("prediction_health") in {"GREEN", "AMBER"}
        assert obj.get("capability_health") in {"GREEN", "AMBER"}
        assert obj.get("gate0", {}).get("pass") is True
        assert obj.get("gate0", {}).get("counts", {}).get("FAIL", 0) == 0
        assert obj.get("dss_core", {}).get("declared") == 50
        assert obj.get("dss_extensions", {}).get("declared") == 16
        assert obj.get("enhancements", {}).get("declared") == 8
        assert not obj.get("critical_failed")
        governance = obj.get("governance") or {}
        assert governance.get("file_exists_is_not_sufficient_for_active") is True
        assert governance.get("critical_warmup_blocks_unqualified_go") is True
        assert governance.get("pipeline_health_separate_from_prediction_health") is True
        assert obj.get("checkpoint_context", {}).get("policy_id")
    assert pre["gate0"]["counts"].get("PASS", 0) + pre["gate0"]["counts"].get("DEFERRED", 0) == 16
    assert post["gate0"]["counts"].get("PASS", 0) == 16
    assert post.get("pipeline_health") == "GREEN"
    assert post.get("capability_coverage", {}).get("declared") == 74
    critical_warmup = list(post.get("critical_warmup") or [])
    if critical_warmup:
        assert post.get("prediction_health") == "AMBER"
        assert post.get("decision_engine") == "PROVISIONAL"
        assert post.get("go_allowed") is False
    else:
        assert post.get("prediction_health") == "GREEN"
        assert post.get("decision_engine") == "HEALTHY"
    return pre, post


def _assert_orchestration(latest: dict) -> tuple[dict, list[dict]]:
    orchestration = _load("service_orchestration_v4.json")
    _assert_version(orchestration, "orchestration", 492, "v4.9.3-service-orchestrator")
    assert orchestration.get("status") == "PASS"
    assert orchestration.get("stats_enabled") is True
    assert orchestration.get("deep_stats_enabled") is True
    services = orchestration.get("services") or []
    ids = [row.get("id") for row in services]
    assert len(services) == 11 and all(row.get("status") == "PASS" for row in services), services
    assert ids[:4] == ["raw_snapshot", "enrichment", "prediction", "validation_lifecycle"]
    assert ids.index("optimization") < ids.index("user_decision_overlay") < ids.index("personal_gw_scorecard")
    assert ids[-1] == "report_governance"
    assert all(row.get("boundary_state") == "INDEPENDENT" for row in services)
    assert all(all(contract.get("valid") for contract in row.get("contracts") or []) for row in services)
    assert orchestration.get("snapshot_identity", {}).get("sha256") == file_digest(DATA / "runtime/snapshot.v1.json")
    assert latest.get("lineage", {}).get("snapshot_sha256") == file_digest(DATA / "runtime/snapshot.v1.json")
    assert latest.get("lineage", {}).get("enrichment_sha256") == file_digest(DATA / "runtime/enrichment.v1.json")
    guardrails = orchestration.get("guardrails") or {}
    for key in (
        "validation_lifecycle_no_official_refetch",
        "deadline_snapshot_immutable",
        "retroactive_snapshot_rejected",
        "reconciliation_archive_immutable",
        "reconciliation_idempotent",
        "health_view_current_model_only",
        "personal_gw_scorecard_no_official_refetch",
        "finished_gw_archive_immutable",
        "scorecard_simulation_never_mutates_archive",
        "scorecard_projection_from_effective_plan_contract",
        "user_decision_overlay_process_isolated",
        "engine_is_advisory",
        "user_decision_is_final_authority",
        "engine_never_auto_overwrites_valid_user_override",
        "projection_default_baseline_previous_submitted_gw",
        "planning_override_requires_target_gw",
        "stale_planning_override_rejected",
        "optimizer_search_width_unchanged",
    ):
        assert guardrails.get(key) is True, (key, guardrails.get(key))
    assert guardrails.get("official_fpl_api_authority") == "raw_snapshot_only"
    assert guardrails.get("gate0_checks_unchanged") == 16
    return orchestration, services


def _assert_prediction_and_validation(health: dict) -> tuple[dict, dict]:
    lifecycle = _load("validation/lifecycle_v4.json")
    predictions = _load("predictions_v4.json")
    _assert_version(lifecycle, "validation lifecycle", 493, "v4.9.3-validation-lifecycle")
    _assert_version(predictions, "predictions", 492, "v4.9.2-truthful-health", field="model_version")
    assert lifecycle.get("status") == "PASS"
    assert predictions.get("point_in_time") is True
    players = predictions.get("players") or []
    assert len(players) >= 500
    assert lifecycle.get("eligibility", {}).get("model_version") == predictions.get("model_version")
    eligible = lifecycle.get("eligibility", {}).get("eligible_samples")
    if eligible is not None:
        core = {row["id"]: row for row in health["dss_core"]["items"]}
        extensions = {row["id"]: row for row in health["dss_extensions"]["items"]}
        if int(eligible) == 0:
            assert core["DSS-44"]["status"] == "WARMUP"
            assert extensions["DSS-X12"]["status"] == "WARMUP"
        else:
            assert core["DSS-44"]["status"] == "ACTIVE"
            assert extensions["DSS-X12"]["status"] == "ACTIVE"
    coverage = predictions.get("input_coverage") or {}
    assert coverage.get("advanced_matched", 0) > 0
    assert coverage.get("last_season_matched", 0) > 0
    assert coverage.get("advanced_decision_used_ratio", 0) >= 0.25
    evidence = predictions.get("capability_evidence") or {}
    assert evidence.get("dynamic_opponent_fixtures", 0) > 0
    assert 0 < evidence.get("role_competition_adjustments", 0) < len(players)
    assert evidence.get("role_competition_factor_variants", 0) > 1
    all_x = [fx["xpts"] for row in players for fx in row.get("fixtures", [])]
    assert all_x and statistics.median(all_x) < 8
    assert sum(x > 15 for x in all_x) / len(all_x) < 0.03
    return lifecycle, predictions


def _assert_engine_advisory(latest: dict) -> tuple[dict, dict, dict, dict]:
    wc = _load("wc_decision_v4.json")
    packages = _load("wc_package_audit_v4.json")
    lineup = _load("lineup_decision_v4.json")
    pipeline = _load("decision_pipeline_v4.json")
    assert len(wc.get("optimized_elements") or []) == 15
    assert wc.get("classification") in {"KEEP_15", "OPTIONAL_IMPROVEMENT", "MATERIAL_UPGRADE"}
    assert (wc.get("affordability") or {}).get("price_basis") == "owned_sell_cost_unowned_now_cost"
    assert packages.get("overall_verdict") in {"KEEP_15", "OPTIONAL_IMPROVEMENT", "MATERIAL_UPGRADE"}
    assert set(packages.get("best_by_replacement_count") or {}) == {"1", "2", "3", "4"}
    assert len(lineup.get("starting_xi") or []) == 11
    assert lineup.get("formation") in LEGAL_FORMATIONS
    assert (lineup.get("governance") or {}).get("decision") == "OPTIMIZER_ONLY"
    assert pipeline.get("checkpoint_context") == latest.get("checkpoint_context")
    assert pipeline.get("decision_authority") == "ENGINE_ADVISORY_ONLY"
    pg = pipeline.get("performance_guardrails") or {}
    assert pg.get("search_quality_reduction") is False
    assert pg.get("planning_squad_from_team_contract") is True
    assert pg.get("stale_lock_players_not_direct_optimizer_input") is True
    assert pg.get("engine_lineup_is_advisory_only") is True
    assert pg.get("manual_override_applied_in_separate_microservice") is True
    planning_squad = pipeline.get("planning_squad") or {}
    baseline = latest.get("projection_baseline") or {}
    assert planning_squad.get("planning_gw") == baseline.get("planning_gw")
    assert planning_squad.get("baseline_gw") == baseline.get("baseline_gw")
    assert planning_squad.get("override_active") == baseline.get("override_applied")
    return wc, packages, lineup, pipeline


def _assert_human_overlay(latest: dict, engine_lineup: dict) -> tuple[dict, dict]:
    overlay = _load("effective_plan_v4.json")
    _assert_version(overlay, "user decision overlay", 4941, "v4.9.4.1-user-decision-overlay")
    assert overlay.get("status") == "PASS"
    effective = overlay.get("effective_plan") or {}
    assert len(effective.get("starting_xi") or []) == 11
    assert effective.get("formation") in LEGAL_FORMATIONS
    xi_ids = {int(row["element"]) for row in effective["starting_xi"]}
    assert int(effective["captain"]["element"]) in xi_ids
    assert int(effective["vice_captain"]["element"]) in xi_ids
    assert effective["captain"]["element"] != effective["vice_captain"]["element"]
    guardrails = overlay.get("guardrails") or {}
    assert guardrails.get("process_isolated_microservice") is True
    assert guardrails.get("official_api_refetch") is False
    assert guardrails.get("engine_is_advisory") is True
    assert guardrails.get("user_decision_is_final_authority") is True
    assert guardrails.get("engine_never_auto_overwrites_valid_user_override") is True
    assert guardrails.get("target_gw_override_required") is True
    assert guardrails.get("stale_override_ignored") is True
    assert guardrails.get("fpl_legality_still_enforced") is True
    assert (overlay.get("comparison") or {}).get("engine_can_warn_but_not_overwrite") is True
    engine = overlay.get("engine_recommendation") or {}
    assert engine.get("formation") == engine_lineup.get("formation")
    assert {r["element"] for r in engine.get("starting_xi") or []} == {r["element"] for r in engine_lineup.get("starting_xi") or []}
    if (overlay.get("user_override") or {}).get("active"):
        assert effective.get("authority") == "USER_OVERRIDE"
        assert effective.get("decision_authority") == "USER"
    else:
        assert effective.get("authority") == "ENGINE_RECOMMENDATION"
    assert overlay.get("planning_gw") == (latest.get("phase") or {}).get("planning_gw")
    return overlay, effective


def _assert_scorecard_and_governance(latest: dict, health: dict, overlay: dict, effective: dict) -> tuple[dict, dict]:
    scorecard = _load("gw_scorecard_v4.json")
    checkpoint = _load("checkpoint_decision_v4.json")
    _assert_version(scorecard, "scorecard", 494, "v4.9.4-personal-gw-scorecard")
    _assert_version(checkpoint, "checkpoint", 492, "v4.9.2-checkpoint-governance")
    assert scorecard.get("status") == "PASS"
    assert scorecard.get("snapshot_sha256") == file_digest(DATA / "runtime/snapshot.v1.json")
    assert scorecard.get("effective_plan_sha256") == file_digest(DATA / "effective_plan_v4.json")
    planning = scorecard.get("planning_gw") or {}
    planning_gw = (latest.get("phase") or {}).get("planning_gw")
    if planning_gw:
        assert planning.get("status") == "PROJECTION"
        assert planning.get("gw") == planning_gw
        assert planning.get("formation") == effective.get("formation")
        assert (planning.get("captain") or {}).get("element") == (effective.get("captain") or {}).get("element")
        assert planning.get("active_chip") == (effective.get("chip_context") or {}).get("active_chip")
        assert planning.get("human_override_active") == bool((overlay.get("user_override") or {}).get("active"))
        basis = planning.get("squad_basis") or {}
        latest_basis = latest.get("projection_baseline") or {}
        for key in ("planning_gw", "baseline_gw", "override_applied", "effective_authority", "authority_source"):
            assert basis.get(key) == latest_basis.get(key), (key, basis, latest_basis)
    last_finished = (latest.get("phase") or {}).get("last_finished_gw")
    if last_finished and not latest.get("checkpoint_context", {}).get("is_simulation"):
        previous = scorecard.get("previous_gw") or {}
        assert previous.get("status") == "FINAL"
        assert int(previous.get("gw") or 0) == int(last_finished)
        assert previous.get("net_points") is not None
        assert previous.get("chip") is not None
    assert checkpoint.get("checkpoint_context") == latest.get("checkpoint_context")
    assert (checkpoint.get("squad") or {}).get("authority_ok") is True
    decision = checkpoint.get("decision") or {}
    assert decision.get("engine_is_advisory") is True
    assert decision.get("user_decision_is_final_authority") is True
    action = checkpoint.get("action_state")
    assert action in {"HOLD", "REVIEW_REQUIRED", "GO", "EMERGENCY_UPDATE_ONLY", "REFRESH_REQUIRED", "BLOCKED", "SIMULATION_ONLY"}
    explicit_final_lock = str(effective.get("status") or "").upper() == "FINAL_LOCKED"
    expected_execution = action == "GO" and explicit_final_lock and not latest.get("checkpoint_context", {}).get("is_simulation")
    assert decision.get("execution_authorized") is expected_execution
    if action == "GO" and not explicit_final_lock:
        assert "USER_FINAL_LOCK_REQUIRED" in (checkpoint.get("readiness") or {}).get("reasons", [])
    if health.get("prediction_health") == "AMBER" and not latest.get("checkpoint_context", {}).get("is_simulation"):
        assert action == "HOLD"
    return scorecard, checkpoint


def run() -> dict:
    pre, health = _assert_framework_health()
    latest = _load("latest.json")
    assert validate_snapshot(latest)["ok"]
    _assert_version(latest, "latest", 492, "4.9.2-independent-services", field="engine_version")
    assert latest.get("files", {}).get("effective_plan") == "data/effective_plan_v4.json"
    assert latest.get("files", {}).get("gw_scorecard") == "data/gw_scorecard_v4.json"
    basis = latest.get("projection_baseline") or {}
    assert basis.get("default_rule") == "PLANNING_GW_FROM_PREVIOUS_OFFICIAL_SUBMITTED_SQUAD"
    assert basis.get("baseline_gw") == (latest.get("phase") or {}).get("submitted_gw")
    orchestration, services = _assert_orchestration(latest)
    lifecycle, predictions = _assert_prediction_and_validation(health)
    compliance = _load("compliance_audit.json")
    assert compliance.get("overall") == "PASS"
    wc, packages, engine_lineup, pipeline = _assert_engine_advisory(latest)
    overlay, effective = _assert_human_overlay(latest, engine_lineup)
    scorecard, checkpoint = _assert_scorecard_and_governance(latest, health, overlay, effective)
    sanity = _load("recommendation_sanity_v4.json")
    assert sanity.get("final_verdict") in {"KEEP_15", "OPTIONAL_IMPROVEMENT", "MATERIAL_UPGRADE"}
    out = {
        "health": health["overall"],
        "gate0": health["gate0"]["counts"],
        "recommendation": sanity["final_verdict"],
        "engine_formation": engine_lineup["formation"],
        "effective_authority": effective.get("authority"),
        "effective_formation": effective.get("formation"),
        "effective_captain": (effective.get("captain") or {}).get("name"),
        "human_override_active": (overlay.get("user_override") or {}).get("active"),
        "user_minus_engine_xpts": (overlay.get("comparison") or {}).get("user_minus_engine_xpts"),
        "previous_gw": (scorecard.get("headline") or {}).get("previous"),
        "planning_gw": (scorecard.get("headline") or {}).get("planning"),
        "projection_baseline_gw": basis.get("baseline_gw"),
        "projection_override_applied": basis.get("override_applied"),
        "action": checkpoint.get("action_state"),
        "execution_authorized": (checkpoint.get("decision") or {}).get("execution_authorized"),
        "services": len(services),
        "eligible_calibration_samples": lifecycle.get("eligibility", {}).get("eligible_samples"),
        "orchestration_ms": orchestration.get("duration_ms"),
        "pipeline_ms": (pipeline.get("timings") or {}).get("total_pipeline_ms"),
    }
    print("V4.9.4.1 HUMAN-IN-THE-LOOP MICROservice GATE PASS", json.dumps(out, ensure_ascii=False))
    return out


if __name__ == "__main__":
    run()
