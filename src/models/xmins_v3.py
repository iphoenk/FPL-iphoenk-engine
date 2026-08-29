from __future__ import annotations

from typing import Any

from src.engines.p0_decision_quality import enrich_xmins_contract
from src.models.xmins_v2 import estimate_xmins as estimate_xmins_v2
from src.utils import ROOT, read_json

POLICY_PATH = ROOT / "config" / "intelligence" / "historical_priors.json"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def estimate_xmins(player: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = dict(context or {})
    out = estimate_xmins_v2(player, context)
    policy = read_json(POLICY_PATH, {}) or {}
    conf = policy.get("confidence") or {}
    prior_probability = context.get("prior_start_probability")
    prior_minutes = max(0.0, _f(context.get("prior_evidence_minutes")))
    current_starts = max(0.0, _f(player.get("starts")))

    confidence = str(out.get("confidence") or "LOW")
    medium_prior = max(0.0, _f(conf.get("medium_prior_minutes"), 900.0))
    high_prior = max(medium_prior, _f(conf.get("high_prior_minutes"), 1800.0))
    if prior_probability is not None and prior_minutes >= medium_prior:
        confidence = "MEDIUM" if confidence == "LOW" else confidence
    if (
        prior_probability is not None
        and prior_minutes >= high_prior
        and current_starts >= (1.0 if conf.get("high_requires_current_start", True) else 0.0)
        and current_starts >= 2.0
    ):
        confidence = "HIGH"

    out["model"] = "xmins_v3_hierarchical_prior"
    out["confidence"] = confidence
    out["historical_prior"] = {
        "available": prior_probability is not None,
        "start_probability": round(_f(prior_probability), 4) if prior_probability is not None else None,
        "evidence_minutes": round(prior_minutes, 1),
        "source": context.get("prior_source"),
        "identity_match": context.get("prior_identity_match"),
        "starter_minutes_prior": context.get("starter_minutes_prior"),
    }
    out.setdefault("governance", {}).update({
        "current_official_availability_is_authority": True,
        "historical_prior_is_shrinkage_evidence": True,
        "missing_historical_prior_is_not_fabricated": True,
    })
    return enrich_xmins_contract(out)
