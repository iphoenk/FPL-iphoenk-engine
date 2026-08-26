from __future__ import annotations

from datetime import datetime, timezone
from statistics import pstdev
from typing import Any

from src.utils import CONFIG, ROOT, read_json

POLICY = ROOT / "config" / "intelligence" / "historical_priors.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def evaluate(projections: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    cfg = (read_json(POLICY, {}) or {}).get("quality") or {}
    players = list(projections.get("players") or [])
    pmap = {int(p["element"]): p for p in players}
    starters = [p for p in players if int((p.get("current_season") or {}).get("starts") or 0) > 0 and p.get("status") in {"a", "d"}]
    start_probs = [_f((p.get("xmins") or {}).get("start_probability")) for p in starters]
    dispersion = pstdev(start_probs) if len(start_probs) >= 2 else 0.0

    lock = read_json(CONFIG / "locked_squad.json", {}) or {}
    locked = [pmap[int(x.get("element") or -1)] for x in lock.get("players") or [] if int(x.get("element") or -1) in pmap]
    locked_prior = sum(bool(p.get("historical_prior")) for p in locked)
    locked_low = sum(p.get("projection_confidence") == "LOW" for p in locked)
    locked_prior_ratio = locked_prior / max(1, len(locked))
    locked_low_ratio = locked_low / max(1, len(locked))
    universe_ratio = _f((prior.get("coverage") or {}).get("coverage_ratio"))

    checks = {
        "universe_prior_coverage": {"value": round(universe_ratio, 4), "threshold": _f(cfg.get("universe_prior_coverage_min"), 0.45)},
        "locked_prior_coverage": {"value": round(locked_prior_ratio, 4), "threshold": _f(cfg.get("locked_prior_coverage_min"), 0.50)},
        "starter_xmins_dispersion": {"value": round(dispersion, 4), "threshold": _f(cfg.get("starter_start_probability_std_min"), 0.035), "sample": len(starters), "minimum_sample": int(cfg.get("minimum_starter_sample") or 40)},
        "locked_low_confidence_share": {"value": round(locked_low_ratio, 4), "maximum": _f(cfg.get("locked_low_confidence_share_max"), 0.60)},
    }
    checks["universe_prior_coverage"]["pass"] = universe_ratio >= checks["universe_prior_coverage"]["threshold"]
    checks["locked_prior_coverage"]["pass"] = locked_prior_ratio >= checks["locked_prior_coverage"]["threshold"]
    checks["starter_xmins_dispersion"]["pass"] = len(starters) >= checks["starter_xmins_dispersion"]["minimum_sample"] and dispersion >= checks["starter_xmins_dispersion"]["threshold"]
    checks["locked_low_confidence_share"]["pass"] = locked_low_ratio <= checks["locked_low_confidence_share"]["maximum"]
    failed = [name for name, row in checks.items() if not row["pass"]]
    return {
        "generated_at": _now(),
        "model": "prediction_quality_guard_v1",
        "status": "HEALTHY" if not failed else "DEGRADED",
        "failed_checks": failed,
        "checks": checks,
        "prior": {"model": prior.get("model"), "season": prior.get("season"), "coverage": prior.get("coverage")},
        "locked_squad": {"players": len(locked), "historical_prior_players": locked_prior, "low_confidence_players": locked_low},
        "governance": {
            "mechanical_validity_is_not_prediction_quality": True,
            "low_sample_collapse_is_detected": True,
            "quality_guard_may_downgrade_final_governance": True,
            "failed_quality_never_fabricates_replacement_evidence": True
        }
    }
