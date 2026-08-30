from __future__ import annotations

import json
import statistics

from src.engines import v4_quality_gate_legacy as legacy
from src.services.contracts import file_digest
from src.utils import CONFIG, DATA


def _assert_framework_health() -> tuple[dict, dict]:
    """Preserve health checks while matching the engine's FAILED>PARTIAL>WARMUP precedence."""
    pre = legacy._load("framework_health_preflight_v4.json")
    post = legacy._load("framework_health_v4.json")
    for obj, phase in ((pre, "preflight"), (post, "postflight")):
        legacy._assert_version(obj, phase, 492, f"v{legacy.RELEASE_VERSION}-truthful-health")
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
    plan_truth = post.get("gate0", {}).get("plan_authority_validation") or {}
    assert (plan_truth.get("engine_plan") or {}).get("legal") is True
    assert (plan_truth.get("effective_plan") or {}).get("legal") is True
    assert plan_truth.get("both_required") is True
    assert (post.get("governance") or {}).get("effective_plan_legality_enforced") is True
    assert (post.get("governance") or {}).get("engine_and_effective_plan_legality_reported_separately") is True
    assert (post.get("governance") or {}).get("official_fpl_first_when_available") is True

    official_first = post.get("official_fpl_first") or {}
    assert official_first.get("status") == "PASS"
    assert official_first.get("promoted_count", 0) >= 6
    assert set(official_first.get("promoted_modules") or []) >= {"DSS-18", "DSS-20", "DSS-21", "DSS-22", "DSS-23", "DSS-38"}
    assert official_first.get("ownership_eo_limitation_disclosed") is True
    assert official_first.get("external_schedule_limitation_disclosed") is True

    core = {row["id"]: row for row in post["dss_core"]["items"]}
    for module_id in ("DSS-18", "DSS-20", "DSS-21", "DSS-22", "DSS-23", "DSS-38"):
        assert core[module_id]["status"] == "ACTIVE", (module_id, core[module_id])
    # Official ownership percentage is a complete production capability even though
    # effective ownership is not supplied by Official FPL. If the maturity reconciler
    # proves full Official coverage, DSS-41 may be ACTIVE while EO remains explicitly
    # unavailable; otherwise the legacy PARTIAL state is still valid.
    assert core["DSS-41"]["status"] in {"ACTIVE", "PARTIAL"}
    ownership_detail = core["DSS-41"].get("detail") or {}
    eo_available = ownership_detail.get("effective_ownership_available_from_official_fpl")
    assert eo_available is False
    if core["DSS-41"]["status"] == "ACTIVE":
        assert ownership_detail.get("implementation_state") == "ACTIVE"
        assert int(ownership_detail.get("ownership_rows") or 0) == int(ownership_detail.get("players") or 0) > 0

    critical_partial = list(post.get("critical_partial") or [])
    critical_warmup = list(post.get("critical_warmup") or [])
    if critical_partial:
        assert post.get("prediction_health") == "AMBER"
        assert post.get("decision_engine") == "DEGRADED"
        assert post.get("go_allowed") is False
    elif critical_warmup:
        assert post.get("prediction_health") == "AMBER"
        assert post.get("decision_engine") == "PROVISIONAL"
        assert post.get("go_allowed") is False
    else:
        assert post.get("prediction_health") == "GREEN"
        assert post.get("decision_engine") == "HEALTHY"
    return pre, post


def _assert_competition_evidence(players: list[dict], evidence: dict) -> None:
    """Validate competition evidence without requiring an artificial mixed population.

    Every player must expose the competition inputs. Zero adjustments are valid only
    when the current data contains no governed competition/squad-depth pressure.
    Conversely, if pressure exists, at least one adjustment must be applied. It is
    legitimate for every player to receive a bounded adjustment when every team has
    non-zero squad-depth pressure, so the gate must not require an unadjusted player.
    """
    assert players
    priors = [row.get("priors") or {} for row in players]
    assert all("competition_factor" in row for row in priors)
    assert all("competition_pressure" in row for row in priors)
    assert all("squad_depth_pressure" in row for row in priors)
    assert all(0.72 <= float(row.get("competition_factor") or 0) <= 1.0 for row in priors)
    assert all(0.0 <= float(row.get("competition_pressure") or 0) <= 1.0 for row in priors)
    assert all(0.0 <= float(row.get("squad_depth_pressure") or 0) <= 0.3 for row in priors)

    adjustments = int(evidence.get("role_competition_adjustments", 0) or 0)
    variants = int(evidence.get("role_competition_factor_variants", 0) or 0)
    pressure_rows = sum(
        float(row.get("competition_pressure") or 0) > 0
        or float(row.get("squad_depth_pressure") or 0) > 0
        for row in priors
    )
    assert 0 <= adjustments <= len(players)
    assert variants >= 1
    if pressure_rows:
        assert adjustments > 0
    else:
        assert adjustments == 0
        assert variants == 1


def _assert_prediction_and_validation(health: dict) -> tuple[dict, dict]:
    return legacy._assert_prediction_and_validation(health)


def _assert_decision_artifacts() -> tuple[dict, dict, dict, dict]:
    return legacy._assert_decision_artifacts()


def _assert_advanced_ablation() -> dict:
    return legacy._assert_advanced_ablation()


def _assert_service_orchestration() -> dict:
    return legacy._assert_service_orchestration()


def _assert_release_and_architecture() -> tuple[dict, dict]:
    return legacy._assert_release_and_architecture()


def _assert_serving_contract() -> tuple[dict, dict]:
    return legacy._assert_serving_contract()


def _assert_performance() -> tuple[dict, dict]:
    return legacy._assert_performance()


def run() -> dict:
    pre, health = _assert_framework_health()
    predictions, validation = _assert_prediction_and_validation(health)
    evidence = predictions.get("evidence") or {}
    _assert_competition_evidence(list(predictions.get("players") or []), evidence)
    wc, package, lineup, sanity = _assert_decision_artifacts()
    ablation = _assert_advanced_ablation()
    orchestration = _assert_service_orchestration()
    release, architecture = _assert_release_and_architecture()
    serving, serving_benchmark = _assert_serving_contract()
    performance, perf_benchmark = _assert_performance()

    result = {
        "status": "PASS",
        "framework": {
            "preflight": pre.get("overall"),
            "postflight": health.get("overall"),
            "prediction_health": health.get("prediction_health"),
            "capability_health": health.get("capability_health"),
            "coverage": health.get("capability_coverage"),
        },
        "validation": validation.get("status"),
        "decision": {
            "wc": wc.get("overall_verdict"),
            "package": package.get("overall_verdict"),
            "formation": lineup.get("formation"),
            "sanity": sanity.get("status"),
        },
        "ablation": ablation.get("status"),
        "orchestration": orchestration.get("status"),
        "release": release.get("release"),
        "architecture": architecture.get("status"),
        "serving": serving.get("contract"),
        "performance": {
            "pipeline": performance,
            "benchmark": perf_benchmark,
            "serving_benchmark": serving_benchmark,
        },
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == "__main__":
    run()
