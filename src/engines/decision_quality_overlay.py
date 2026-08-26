from __future__ import annotations

import json
from datetime import datetime, timezone

from src.engines.p0_framework_health_overlay import _recount, _set_probe_status
from src.utils import DATA, atomic_json, read_json


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run():
    health = read_json(DATA / "framework_health.json", {})
    quality = read_json(DATA / "prediction_quality.json", {})
    prior = read_json(DATA / "prior_season.json", {})
    if not health or not quality:
        raise RuntimeError("framework health and prediction quality are required")

    quality_ok = quality.get("status") == "HEALTHY"
    coverage = (prior.get("coverage") or {}).get("coverage_ratio", 0)
    prior_ok = bool(prior.get("players")) and float(coverage or 0) > 0
    prior_detail = {
        "historical_prior_operational_probe": True,
        "model": prior.get("model"), "season": prior.get("season"), "fetch_mode": prior.get("fetch_mode"),
        "coverage": prior.get("coverage")
    }
    _set_probe_status(health, {"last_season_prior"}, "ACTIVE" if prior_ok else "FAILED", prior_detail)

    quality_detail = {
        "prediction_quality_operational_probe": True,
        "status": quality.get("status"), "failed_checks": quality.get("failed_checks"), "checks": quality.get("checks"),
        "mechanical_validity_is_not_prediction_quality": True
    }
    if not quality_ok:
        _set_probe_status(health, {"xmins", "xmins_distribution", "captaincy", "uncertainty_robustness", "final_governance"}, "PARTIAL", quality_detail)
    if "p0_capabilities" in health and "P0-2_xmins_role_v2" in health["p0_capabilities"]:
        health["p0_capabilities"]["P0-2_xmins_role_v2"] = {
            "status": "ACTIVE" if quality_ok else "PARTIAL",
            "detail": quality_detail
        }

    health["prediction_quality"] = {
        "status": quality.get("status"),
        "failed_checks": quality.get("failed_checks"),
        "checks": quality.get("checks"),
        "historical_prior": prior_detail
    }
    health.setdefault("governance", {}).update({
        "mechanical_gate0_pass_does_not_imply_prediction_quality": True,
        "prediction_quality_can_downgrade_final_governance": True,
        "historical_prior_missing_evidence_is_never_fabricated": True
    })
    health["decision_quality_overlay_generated_at"] = _now()
    _recount(health)
    atomic_json(DATA / "framework_health.json", health)
    print(json.dumps({
        "overall": health.get("overall"), "prediction_quality": quality.get("status"),
        "p0_xmins": (health.get("p0_capabilities") or {}).get("P0-2_xmins_role_v2", {}).get("status"),
        "dss_core": (health.get("dss_core") or {}).get("counts"),
        "enhancements": (health.get("enhancements") or {}).get("counts"), "go_allowed": health.get("go_allowed")
    }, ensure_ascii=False))
    return health


if __name__ == "__main__":
    run()
