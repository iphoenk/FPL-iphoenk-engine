from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.v5.config_cache import load_json_config

CONFIG = "config/v5_evidence_guard_registry.json"


def _cfg() -> dict[str, Any]:
    return load_json_config(CONFIG)


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def evaluate(prediction: dict[str, Any], context: dict[str, Any], truth: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = _cfg()
    truth = truth or {}
    planning_gw = int(context.get("planning_gw") or prediction.get("planning_gw") or 0)
    horizon_gws = [int(x) for x in prediction.get("horizon_gws") or []]
    leakage_cfg = cfg.get("leakage") or {}
    leakage_ok = bool(planning_gw > 0)
    if leakage_cfg.get("require_prediction_gw_not_before_planning_gw", True):
        leakage_ok = leakage_ok and all(gw >= planning_gw for gw in horizon_gws)
    forbidden = set(str(x) for x in leakage_cfg.get("forbidden_same_gw_fields") or [])
    forbidden_hits: list[str] = []
    for player in prediction.get("players") or []:
        current = player.get("current_season") if isinstance(player.get("current_season"), dict) else {}
        forbidden_hits.extend(sorted(forbidden.intersection(current.keys())))
    leakage_ok = leakage_ok and not forbidden_hits

    freshness_cfg = cfg.get("freshness") or {}
    generated = _dt(prediction.get("generated_at"))
    now = datetime.now(timezone.utc)
    age_seconds = (now - generated).total_seconds() if generated else None
    freshness_ok = generated is not None and age_seconds is not None and age_seconds <= float(freshness_cfg.get("max_prediction_age_seconds", 1800))
    if freshness_cfg.get("require_deadline", True):
        freshness_ok = freshness_ok and bool(context.get("deadline_time"))

    quality = prediction.get("prediction_quality") if isinstance(prediction.get("prediction_quality"), dict) else {}
    ruleset_match = bool(prediction.get("ruleset_id")) and prediction.get("ruleset_id") == ((truth.get("rules") or {}).get("ruleset_id") if isinstance(truth.get("rules"), dict) else prediction.get("ruleset_id"))
    validation = (truth.get("team") or {}).get("validation") if isinstance(truth.get("team"), dict) else {}
    reliability_ok = bool(quality) and quality.get("status") == str((cfg.get("reliability") or {}).get("healthy_prediction_status", "HEALTHY")) and ruleset_match
    if (cfg.get("reliability") or {}).get("require_truth_validation", True) and truth:
        reliability_ok = reliability_ok and bool(validation.get("passed"))

    capabilities = []
    if leakage_ok:
        capabilities.append("leakage_guard")
    if freshness_ok:
        capabilities.extend(["data_freshness", "source_health"])
    if reliability_ok:
        capabilities.extend(["reliability_overlay", "data_reliability_triangulation"])

    return {
        "model": cfg.get("model_id"),
        "leakage": {"pass": leakage_ok, "forbidden_hits": sorted(set(forbidden_hits)), "planning_gw": planning_gw, "horizon_gws": horizon_gws},
        "freshness": {"pass": freshness_ok, "prediction_age_seconds": round(age_seconds, 3) if age_seconds is not None else None},
        "reliability": {"pass": reliability_ok, "ruleset_match": ruleset_match, "prediction_quality": quality.get("status")},
        "capabilities": sorted(set(capabilities)),
    }
