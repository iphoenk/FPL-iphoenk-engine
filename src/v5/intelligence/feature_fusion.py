from __future__ import annotations

from typing import Any


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def validate_feature_fusion_config(config: dict[str, Any] | None) -> None:
    cfg = config if isinstance(config, dict) else {}
    advanced = cfg.get("advanced_attacking") if isinstance(cfg.get("advanced_attacking"), dict) else {}
    if not advanced:
        raise RuntimeError("authoritative feature fusion requires advanced_attacking registry section")
    minimum_minutes = _f(advanced.get("minimum_evidence_minutes"), -1.0)
    shrink_minutes = _f(advanced.get("evidence_shrinkage_minutes"), 0.0)
    maximum_weight = _f(advanced.get("maximum_weight"), -1.0)
    lower = _f(advanced.get("candidate_lower_multiplier"), -1.0)
    upper = _f(advanced.get("candidate_upper_multiplier"), -1.0)
    absolute_upper = _f(advanced.get("absolute_upper_rate90"), 0.0)
    if minimum_minutes < 0:
        raise RuntimeError("advanced attacking minimum_evidence_minutes must be >= 0")
    if shrink_minutes <= 0:
        raise RuntimeError("advanced attacking evidence_shrinkage_minutes must be > 0")
    if not 0.0 <= maximum_weight <= 1.0:
        raise RuntimeError("advanced attacking maximum_weight must be within [0, 1]")
    if lower < 0 or upper < 0 or lower > upper:
        raise RuntimeError("advanced attacking candidate multipliers require 0 <= lower <= upper")
    if absolute_upper <= 0:
        raise RuntimeError("advanced attacking absolute_upper_rate90 must be > 0")
    if not bool(advanced.get("current_native_rate_remains_primary", True)):
        raise RuntimeError("authoritative advanced attack fusion must keep current native rate primary")


def _fuse_rate(
    native_rate: float,
    candidate_rate: float,
    prior_rate: float,
    weight: float,
    *,
    lower_multiplier: float,
    upper_multiplier: float,
    absolute_upper_rate90: float,
) -> dict[str, float]:
    native = max(0.0, float(native_rate))
    prior = max(0.0, float(prior_rate))
    anchor = max(native, prior, 0.01)
    lower = max(0.0, anchor * lower_multiplier)
    upper = max(lower, min(absolute_upper_rate90, anchor * upper_multiplier))
    bounded = _clamp(max(0.0, candidate_rate), lower, upper)
    final = native * (1.0 - weight) + bounded * weight
    return {
        "native": native,
        "candidate_raw": max(0.0, candidate_rate),
        "candidate_bounded": bounded,
        "final": max(0.0, final),
        "delta": final - native,
        "anchor": anchor,
        "lower_bound": lower,
        "upper_bound": upper,
    }


def fuse_advanced_attack(
    *,
    position: str,
    native_xg90: float,
    native_xa90: float,
    position_xg_prior: float,
    position_xa_prior: float,
    advanced: dict[str, Any] | None,
    config: dict[str, Any] | None,
) -> dict[str, Any]:
    cfg = config if isinstance(config, dict) else {}
    validate_feature_fusion_config(cfg)
    advanced_cfg = cfg["advanced_attacking"]
    enabled = bool(advanced_cfg.get("enabled", False))
    eligible = {str(value) for value in advanced_cfg.get("eligible_positions") or ("DEF", "MID", "FWD")}
    native_xg = max(0.0, _f(native_xg90))
    native_xa = max(0.0, _f(native_xa90))
    used_fields = [str(value) for value in advanced_cfg.get("used_fields") or ("minutes", "xg", "xa")]
    base = {
        "model": str(cfg.get("model") or "authoritative_feature_fusion_v1"),
        "feature": "advanced_attacking_stats",
        "authoritative_scope": "AUTHORITATIVE_XPTS",
        "used_fields": used_fields,
        "current_native_rate_remains_primary": True,
        "xg90_native": round(native_xg, 6),
        "xa90_native": round(native_xa, 6),
        "xg90_final": round(native_xg, 6),
        "xa90_final": round(native_xa, 6),
        "applied": False,
    }
    if not enabled:
        return {**base, "status": "DISABLED", "reason": "advanced attacking feature fusion disabled by registry"}
    if str(position) not in eligible:
        return {**base, "status": "POSITION_INELIGIBLE", "reason": f"position {position} is not configured for attacking fusion"}
    evidence = advanced if isinstance(advanced, dict) else {}
    if not evidence:
        return {**base, "status": "UNAVAILABLE", "reason": "advanced attacking evidence unavailable"}

    minutes = max(0.0, _f(evidence.get("minutes")))
    minimum_minutes = _f(advanced_cfg.get("minimum_evidence_minutes"), 45.0)
    if minutes < minimum_minutes:
        return {
            **base,
            "status": "AVAILABLE_NOT_APPLIED",
            "reason": "advanced attacking evidence below configured minimum minutes",
            "evidence_minutes": round(minutes, 1),
            "minimum_evidence_minutes": round(minimum_minutes, 1),
        }

    shrink_minutes = _f(advanced_cfg.get("evidence_shrinkage_minutes"), 540.0)
    maximum_weight = _f(advanced_cfg.get("maximum_weight"), 0.25)
    evidence_fraction = minutes / (minutes + shrink_minutes)
    weight = _clamp(maximum_weight * evidence_fraction, 0.0, maximum_weight)
    if weight <= 0.0:
        return {
            **base,
            "status": "AVAILABLE_NOT_APPLIED",
            "reason": "configured evidence weight is zero",
            "evidence_minutes": round(minutes, 1),
        }

    xg90_advanced = max(0.0, _f(evidence.get("xg"))) * 90.0 / minutes
    xa90_advanced = max(0.0, _f(evidence.get("xa"))) * 90.0 / minutes
    lower_multiplier = _f(advanced_cfg.get("candidate_lower_multiplier"), 0.70)
    upper_multiplier = _f(advanced_cfg.get("candidate_upper_multiplier"), 1.30)
    absolute_upper = _f(advanced_cfg.get("absolute_upper_rate90"), 1.50)
    xg = _fuse_rate(
        native_xg,
        xg90_advanced,
        max(0.0, _f(position_xg_prior)),
        weight,
        lower_multiplier=lower_multiplier,
        upper_multiplier=upper_multiplier,
        absolute_upper_rate90=absolute_upper,
    )
    xa = _fuse_rate(
        native_xa,
        xa90_advanced,
        max(0.0, _f(position_xa_prior)),
        weight,
        lower_multiplier=lower_multiplier,
        upper_multiplier=upper_multiplier,
        absolute_upper_rate90=absolute_upper,
    )
    return {
        **base,
        "status": "APPLIED",
        "applied": True,
        "evidence_minutes": round(minutes, 1),
        "minimum_evidence_minutes": round(minimum_minutes, 1),
        "evidence_shrinkage_minutes": round(shrink_minutes, 1),
        "maximum_weight": round(maximum_weight, 6),
        "weight": round(weight, 6),
        "xg90_advanced": round(xg90_advanced, 6),
        "xa90_advanced": round(xa90_advanced, 6),
        "xg90_final": round(xg["final"], 6),
        "xa90_final": round(xa["final"], 6),
        "xg": {key: round(value, 6) for key, value in xg.items()},
        "xa": {key: round(value, 6) for key, value in xa.items()},
        "governance": {
            "missing_evidence_is_unavailable_not_zero": True,
            "advanced_evidence_is_secondary_to_native_official_rate": True,
            "weight_is_evidence_minutes_shrunk_and_capped": True,
            "candidate_rate_is_registry_bounded": True,
            "rest_congestion_not_promoted_by_this_fusion": True,
            "preseason_not_promoted_by_this_fusion": True,
            "current_form_not_double_counted": True,
        },
    }
