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


def _f(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid numeric decision-trace configuration/value: {value!r}") from exc


def _confidence(score: float) -> Confidence:
    bands = _cfg()["confidence"]
    if score >= _f(bands["high_minimum"]):
        return Confidence.HIGH
    if score >= _f(bands["medium_high_minimum"]):
        return Confidence.MEDIUM_HIGH
    if score >= _f(bands["medium_minimum"]):
        return Confidence.MEDIUM
    if score >= _f(bands["medium_low_minimum"]):
        return Confidence.MEDIUM_LOW
    return Confidence.LOW


def _package_probability(package: dict[str, Any]) -> float:
    default = _f(_cfg()["package_selection"]["default_outperform_hold_probability"])
    value = (package.get("monte_carlo") or {}).get("p_outperform_hold_independent_baseline")
    return default if value is None else _f(value)


def _gate0_context(preflight: dict[str, Any]) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    trace_policy = _cfg()["trace"]
    required = bool(trace_policy.get("require_gate0_preflight", True))
    items = preflight.get("items") if isinstance(preflight.get("items"), list) else []
    checked = tuple(str(item.get("id")) for item in items if item.get("id"))
    pass_status = str(trace_policy["gate0_pass_status"])
    failed = tuple(
        str(item.get("id"))
        for item in items
        if item.get("id") and str(item.get("status")) != pass_status
    )
    passed = bool(preflight.get("pass")) if items else not required
    return passed, checked, failed


def _bind_execution_fingerprint(raw: dict[str, Any], execution_fingerprint: dict[str, Any] | None) -> None:
    policy = _cfg()["trace"]
    raw["trace_contract"] = str(policy.get("contract") or "V5_DECISION_TRACE_V1")
    fingerprint = execution_fingerprint if isinstance(execution_fingerprint, dict) else {}
    raw["runtime_release_fingerprint"] = fingerprint.get("runtime_release_fingerprint")
    raw["replay_fingerprint"] = fingerprint.get("replay_fingerprint")
    raw["execution_fingerprint"] = fingerprint.get("execution_fingerprint")
    raw["code_revision"] = fingerprint.get("code_revision")
    raw["promotion_fingerprint_complete"] = fingerprint.get("promotion_fingerprint_complete")
    raw["fingerprint_binding"] = {
        "bound": bool(fingerprint.get("replay_fingerprint") and fingerprint.get("execution_fingerprint")),
        "scoring_input": False,
        "provenance_only": True,
        "required_for_promotion": bool(policy.get("require_exact_execution_fingerprint_for_promotion", True)),
    }


def build_trace(
    *,
    truth: dict[str, Any],
    prediction: dict[str, Any],
    price: dict[str, Any],
    packages: dict[str, Any],
    package_governance: dict[str, Any],
    lineup: dict[str, Any],
    dss: dict[str, Any],
    gate0_preflight: dict[str, Any],
    execution_fingerprint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = _cfg()
    policy = cfg["package_selection"]
    trace_policy = cfg["trace"]
    ranked = packages.get("packages") or []
    hold = packages.get("hold") or next((item for item in ranked if item.get("id") == "HOLD"), {})
    governed_selected = (
        package_governance.get("selected_package")
        if isinstance(package_governance.get("selected_package"), dict)
        else hold
    )
    challenger = (
        package_governance.get("optimizer_best_challenger")
        if isinstance(package_governance.get("optimizer_best_challenger"), dict)
        else None
    )
    best = challenger or (ranked[0] if ranked else hold)
    hold_robust = _f((hold.get("score") or {}).get("robust_score") or 0.0)
    best_value = (best.get("score") or {}).get("robust_score")
    best_robust = hold_robust if best_value is None else _f(best_value)
    robust_gain = best_robust - hold_robust
    probability = _package_probability(best)
    minimum_gain = _f(policy["minimum_robust_gain_to_review"])
    minimum_probability = _f(policy["minimum_outperform_hold_probability"])
    strong_gain = _f(policy["strong_robust_gain"])
    strong_probability = _f(policy["strong_outperform_hold_probability"])
    preflight_passed, gate0_checked, gate0_failed = _gate0_context(gate0_preflight)
    manual_override = bool(package_governance.get("manual_authority_override"))

    if not preflight_passed:
        decision_type = "BLOCKED"
        action = "BLOCK decision output because Gate0 preflight did not pass"
        chosen = governed_selected or hold or best
    elif manual_override:
        decision_type = "HOLD"
        action = "HOLD authoritative manual LOCK; optimizer challenger is review evidence only"
        chosen = governed_selected or hold
    elif governed_selected.get("id") == "HOLD" or best.get("id") == "HOLD" or robust_gain < minimum_gain or probability < minimum_probability:
        decision_type = "HOLD"
        action = "HOLD current squad; no transfer package clears the configured review threshold"
        chosen = governed_selected or hold
    else:
        decision_type = "TRANSFER_PACKAGE_REVIEW"
        chosen = governed_selected if governed_selected.get("id") != "HOLD" else best
        outgoing = ", ".join(str(row.get("name") or row.get("element")) for row in chosen.get("outs") or [])
        incoming = ", ".join(str(row.get("name") or row.get("element")) for row in chosen.get("ins") or [])
        action = f"REVIEW transfer package: {outgoing} -> {incoming}"

    critical_partial = int(dss.get("critical_partial_count") or 0)
    confidence_basis = probability
    if critical_partial:
        per_module = _f(cfg["confidence"]["critical_partial_penalty_per_module"])
        floor = _f(cfg["confidence"]["critical_partial_floor_multiplier"])
        confidence_basis *= max(floor, 1.0 - per_module * critical_partial)
    confidence = Confidence.LOW if not preflight_passed else _confidence(confidence_basis)

    reasons_for = [
        f"best challenger robust score delta vs HOLD = {robust_gain:.3f}",
        f"best challenger independent-baseline probability of outperforming HOLD = {probability:.3f}",
        f"lineup formation = {lineup.get('formation')}",
    ]
    if manual_override:
        reasons_for.append("authoritative manual LOCK freezes squad composition while retaining optimizer challenger evidence")
    if robust_gain >= strong_gain and probability >= strong_probability:
        reasons_for.append("optimizer challenger clears configured strong-review thresholds")

    reasons_against = []
    if gate0_failed:
        reasons_against.append(f"Gate0 preflight failures: {', '.join(gate0_failed)}")
    if critical_partial:
        reasons_against.append(f"{critical_partial} critical DSS capabilities remain PARTIAL")
    price_alert_count = len(((price.get("alerts") or {}).get("alerts") or []))
    if price_alert_count:
        reasons_against.append(f"market timing context contains {price_alert_count} active price alerts")
    if not reasons_against:
        reasons_against.append("no additional decision-local blocker detected; final postflight governance still required")

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
            source="governance-service",
            field="gate0_preflight",
            authority="governance-service",
            provenance={
                "model": gate0_preflight.get("model"),
                "pass": preflight_passed,
                "checked_ids": list(gate0_checked),
                "failed_ids": list(gate0_failed),
            },
        ),
        EvidenceRef(
            source="decision-service",
            field="package_optimizer+package_governance+lineup_optimizer+dss",
            authority="decision-service",
            provenance={
                "package_model": packages.get("model"),
                "package_governance_model": package_governance.get("model"),
                "manual_authority_override": manual_override,
                "dss_model": dss.get("evaluation_model"),
            },
        ),
    )
    subject_ids = tuple(
        int(row["element"])
        for row in [*(chosen.get("outs") or []), *(chosen.get("ins") or [])]
        if row.get("element") is not None
    )
    local_labels = trace_policy.get("local_constraint_labels") or {}
    local_checked = []
    if packages.get("local_legality_prevalidated"):
        local_checked.append(str(local_labels["package_ready"]))
    if package_governance.get("status") == "READY":
        package_governance_label = local_labels.get("package_governance_ready")
        if package_governance_label:
            local_checked.append(str(package_governance_label))
    if lineup.get("status") == "READY":
        local_checked.append(str(local_labels["lineup_ready"]))
    constraints_checked = tuple([*gate0_checked, *local_checked])

    projection_model = prediction.get("model_version")
    ruleset_id = (truth.get("rules") or {}).get("ruleset_id") or prediction.get("ruleset_id")
    if trace_policy.get("require_projection_model", True) and not projection_model:
        raise RuntimeError("DecisionTrace requires prediction model version")
    if trace_policy.get("require_ruleset_id", True) and not ruleset_id:
        raise RuntimeError("DecisionTrace requires ruleset_id")
    if trace_policy.get("require_dss_coverage", True) and not isinstance(dss.get("core"), dict):
        raise RuntimeError("DecisionTrace requires DSS coverage evidence")

    trace = DecisionTrace(
        decision_type=decision_type,
        action=action,
        subject_element_ids=subject_ids,
        score=round(robust_gain, 4),
        confidence=confidence,
        reasons_for=tuple(reasons_for),
        reasons_against=tuple(reasons_against),
        evidence=evidence,
        constraints_checked=constraints_checked,
        projection_model=str(projection_model) if projection_model else None,
        ruleset_id=str(ruleset_id) if ruleset_id else None,
    )
    trace.validate()
    raw = asdict(trace)
    raw["confidence"] = trace.confidence.value
    raw["evidence"] = [asdict(item) for item in trace.evidence]
    raw["selected_package_id"] = chosen.get("id")
    raw["optimizer_best_challenger_id"] = best.get("id")
    raw["manual_authority_override"] = manual_override
    raw["robust_gain_vs_hold"] = round(robust_gain, 4)
    raw["p_outperform_hold_independent_baseline"] = round(probability, 4)
    raw["gate0_preflight_pass"] = preflight_passed
    raw["production_recommendation"] = None
    _bind_execution_fingerprint(raw, execution_fingerprint)
    return raw
