from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.v5.config_cache import load_json_config
from src.v5.contracts import Confidence, DecisionTrace, EvidenceRef

CONFIG = "config/v5_decision_registry.json"


def _cfg() -> dict[str, Any]:
    data = load_json_config(CONFIG)
    if not isinstance(data.get("trace"), dict):
        raise RuntimeError("invalid V5 decision registry trace section")
    return data


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(default if value is None else value)
    except (TypeError, ValueError):
        return float(default)


def _confidence(score: float) -> Confidence:
    bands = _cfg()["confidence"]
    if score >= _f(bands.get("high_minimum"), 0.80):
        return Confidence.HIGH
    if score >= _f(bands.get("medium_high_minimum"), 0.70):
        return Confidence.MEDIUM_HIGH
    if score >= _f(bands.get("medium_minimum"), 0.58):
        return Confidence.MEDIUM
    if score >= _f(bands.get("medium_low_minimum"), 0.45):
        return Confidence.MEDIUM_LOW
    return Confidence.LOW


def _package_probability(package: dict[str, Any]) -> float:
    return _f((package.get("monte_carlo") or {}).get("p_outperform_hold_independent_baseline"), 0.5)


def build_trace(
    *,
    truth: dict[str, Any],
    prediction: dict[str, Any],
    price: dict[str, Any],
    packages: dict[str, Any],
    lineup: dict[str, Any],
    dss: dict[str, Any],
) -> dict[str, Any]:
    policy = _cfg()["package_selection"]
    ranked = packages.get("packages") or []
    hold = packages.get("hold") or next((item for item in ranked if item.get("id") == "HOLD"), {})
    best = ranked[0] if ranked else hold
    hold_robust = _f((hold.get("score") or {}).get("robust_score"))
    best_robust = _f((best.get("score") or {}).get("robust_score"), hold_robust)
    robust_gain = best_robust - hold_robust
    probability = _package_probability(best)
    minimum_gain = _f(policy.get("minimum_robust_gain_to_review"), 0.5)
    minimum_probability = _f(policy.get("minimum_outperform_hold_probability"), 0.55)
    strong_gain = _f(policy.get("strong_robust_gain"), 2.0)
    strong_probability = _f(policy.get("strong_outperform_hold_probability"), 0.65)

    if best.get("id") == "HOLD" or robust_gain < minimum_gain or probability < minimum_probability:
        decision_type = "HOLD"
        action = "HOLD current squad; no transfer package clears the configured review threshold"
        chosen = hold
    else:
        decision_type = "TRANSFER_PACKAGE_REVIEW"
        chosen = best
        outgoing = ", ".join(str(row.get("name") or row.get("element")) for row in chosen.get("outs") or [])
        incoming = ", ".join(str(row.get("name") or row.get("element")) for row in chosen.get("ins") or [])
        action = f"REVIEW transfer package: {outgoing} -> {incoming}"

    confidence_basis = probability
    if dss.get("critical_partial_count"):
        confidence_basis *= max(0.25, 1.0 - 0.03 * int(dss["critical_partial_count"]))
    confidence = _confidence(confidence_basis)

    reasons_for = [
        f"robust score delta vs HOLD = {robust_gain:.3f}",
        f"independent-baseline probability of outperforming HOLD = {probability:.3f}",
        f"lineup formation = {lineup.get('formation')}",
    ]
    if robust_gain >= strong_gain and probability >= strong_probability:
        reasons_for.append("package clears configured strong-review thresholds")

    reasons_against = []
    critical_partial = int(dss.get("critical_partial_count") or 0)
    if critical_partial:
        reasons_against.append(f"{critical_partial} critical DSS capabilities remain PARTIAL")
    price_alert_count = len(((price.get("alerts") or {}).get("alerts") or []))
    if price_alert_count:
        reasons_against.append(f"market timing context contains {price_alert_count} active price alerts")
    if not reasons_against:
        reasons_against.append("no additional decision-local blocker detected; final Gate0/governance still required")

    evidence = (
        EvidenceRef(
            source="truth-service",
            field="team+rules+chip_state",
            authority=str((truth.get("rules") or {}).get("authority") or "truth-service"),
            provenance={"squad_authority": (truth.get("team") or {}).get("authority")},
        ),
        EvidenceRef(
            source="prediction-service",
            field="xmins+xpts+horizons",
            authority="prediction-service",
            provenance={"model_version": prediction.get("model_version")},
        ),
        EvidenceRef(
            source="decision-service",
            field="package_optimizer+lineup_optimizer+dss",
            authority="decision-service",
            provenance={"package_model": packages.get("model"), "dss_model": dss.get("evaluation_model")},
        ),
    )
    subject_ids = tuple(
        int(row["element"])
        for row in [*(chosen.get("outs") or []), *(chosen.get("ins") or [])]
        if row.get("element") is not None
    )
    trace = DecisionTrace(
        decision_type=decision_type,
        action=action,
        subject_element_ids=subject_ids,
        score=round(robust_gain, 4),
        confidence=confidence,
        reasons_for=tuple(reasons_for),
        reasons_against=tuple(reasons_against),
        evidence=evidence,
        constraints_checked=(
            "squad_structure",
            "club_limit",
            "element_uniqueness",
            "sell_value_affordability",
            "legal_formation",
            "captain_vice_distinct",
            "bench_structure",
        ),
        projection_model=str(prediction.get("model_version") or "unknown"),
        ruleset_id=str((truth.get("rules") or {}).get("ruleset_id") or prediction.get("ruleset_id") or "unknown"),
    )
    trace.validate()
    raw = asdict(trace)
    raw["confidence"] = trace.confidence.value
    raw["evidence"] = [asdict(item) for item in trace.evidence]
    raw["selected_package_id"] = chosen.get("id")
    raw["robust_gain_vs_hold"] = round(robust_gain, 4)
    raw["p_outperform_hold_independent_baseline"] = round(probability, 4)
    raw["production_recommendation"] = None
    return raw
