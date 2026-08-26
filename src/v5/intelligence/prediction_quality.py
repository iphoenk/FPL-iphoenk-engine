from __future__ import annotations

from statistics import pstdev
from typing import Any, Iterable

from src.v5.config_cache import load_json_config

CONFIG = "config/intelligence/historical_priors.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def evaluate_prediction_quality(
    projections: dict[str, Any],
    prior: dict[str, Any],
    *,
    owned_ids: Iterable[int] = (),
) -> dict[str, Any]:
    cfg = load_json_config(CONFIG).get("quality") or {}
    players = [row for row in projections.get("players") or [] if isinstance(row, dict)]
    pmap = {int(player["element"]): player for player in players if player.get("element") is not None}
    starters = [
        player
        for player in players
        if int((player.get("current_season") or {}).get("starts") or 0) > 0
        and str(player.get("status")) in {"a", "d"}
    ]
    start_probs = [_f((player.get("xmins") or {}).get("start_probability")) for player in starters]
    dispersion = pstdev(start_probs) if len(start_probs) >= 2 else 0.0

    owned = [pmap[int(element)] for element in owned_ids if int(element) in pmap]
    owned_prior = sum(bool(player.get("historical_prior")) for player in owned)
    owned_low = sum(str(player.get("projection_confidence")) == "LOW" for player in owned)
    owned_prior_ratio = owned_prior / max(1, len(owned)) if owned else 0.0
    owned_low_ratio = owned_low / max(1, len(owned)) if owned else 1.0
    universe_ratio = _f((prior.get("coverage") or {}).get("coverage_ratio"))

    checks: dict[str, dict[str, Any]] = {
        "universe_prior_coverage": {
            "value": round(universe_ratio, 4),
            "threshold": _f(cfg.get("universe_prior_coverage_min"), 0.45),
        },
        "owned_prior_coverage": {
            "value": round(owned_prior_ratio, 4),
            "threshold": _f(cfg.get("owned_prior_coverage_min"), 0.50),
            "sample": len(owned),
        },
        "starter_xmins_dispersion": {
            "value": round(dispersion, 4),
            "threshold": _f(cfg.get("starter_start_probability_std_min"), 0.035),
            "sample": len(starters),
            "minimum_sample": int(cfg.get("minimum_starter_sample") or 40),
        },
        "owned_low_confidence_share": {
            "value": round(owned_low_ratio, 4),
            "maximum": _f(cfg.get("owned_low_confidence_share_max"), 0.60),
            "sample": len(owned),
        },
    }
    checks["universe_prior_coverage"]["pass"] = universe_ratio >= checks["universe_prior_coverage"]["threshold"]
    checks["owned_prior_coverage"]["pass"] = bool(owned) and owned_prior_ratio >= checks["owned_prior_coverage"]["threshold"]
    checks["starter_xmins_dispersion"]["pass"] = (
        len(starters) >= checks["starter_xmins_dispersion"]["minimum_sample"]
        and dispersion >= checks["starter_xmins_dispersion"]["threshold"]
    )
    checks["owned_low_confidence_share"]["pass"] = bool(owned) and owned_low_ratio <= checks["owned_low_confidence_share"]["maximum"]
    failed = [name for name, row in checks.items() if not bool(row.get("pass"))]

    return {
        "model": "v5_prediction_quality_guard_v1",
        "status": "HEALTHY" if not failed else "DEGRADED",
        "failed_checks": failed,
        "checks": checks,
        "prior": {
            "model": prior.get("model"),
            "season": prior.get("season"),
            "status": prior.get("status"),
            "fetch_mode": prior.get("fetch_mode"),
            "coverage": prior.get("coverage"),
        },
        "owned_squad": {
            "players": len(owned),
            "historical_prior_players": owned_prior,
            "low_confidence_players": owned_low,
        },
        "governance": {
            "mechanical_validity_is_not_prediction_quality": True,
            "low_sample_collapse_is_detected": True,
            "quality_guard_may_downgrade_final_governance": True,
            "failed_quality_never_fabricates_replacement_evidence": True,
        },
    }
