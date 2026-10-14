from __future__ import annotations

"""Audits canonical P(start) evidence without changing V12_PLAYER_MINUTES maths.

Probability diversity is not a success criterion. Identical probabilities can
be supported by identical individual input evidence, but context and as-of
calibration remain independent requirements for full resolution.
"""
from collections import Counter, defaultdict
from math import isfinite
from typing import Any, Mapping, Sequence

CONTEXT_SIGNALS = frozenset((
    "prior_start_probability", "role_start_probability",
    "manager_start_probability", "normalized_availability_start_signal",
))


def assess_pstart_resolution(
    rows: Sequence[Mapping[str, Any]],
    *,
    calibration_status: str = "UNVERIFIED",
) -> dict[str, Any]:
    by_probability: dict[float, list[tuple[Any, ...]]] = defaultdict(list)
    missing, mismatches = [], []
    conditioned = contextual = quantified = model_agreed = 0
    official_availability = no_numeric_adjustment = advisory_role = missing_manager = 0
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            missing.append(index)
            continue
        evidence = row.get("p_start_evidence") or {}
        if not isinstance(evidence, Mapping):
            missing.append(index)
            continue
        try:
            p = float(row.get("p_start"))
        except (ValueError, TypeError):
            missing.append(index)
            continue
        if not isfinite(p) or not 0 <= p <= 1:
            missing.append(index)
            continue
        signals = frozenset(str(s) for s in evidence.get("signals") or [])
        selection = evidence.get("selection_evidence") or {}
        if not isinstance(selection, Mapping):
            selection = {}
        is_conditioned = (
            "player_selection_posterior" in signals
            and selection.get("status") == "AVAILABLE"
            and selection.get("observed_matches") is not None
            and selection.get("selection_posterior") is not None
        )
        conditioned += int(is_conditioned)
        context_evidence = row.get("pstart_context_evidence") or {}
        if not isinstance(context_evidence, Mapping):
            context_evidence = {}
        avail = context_evidence.get("availability") or {}
        role = context_evidence.get("role") or {}
        manager = context_evidence.get("manager") or {}
        if not isinstance(avail, Mapping):
            avail = {}
        if not isinstance(role, Mapping):
            role = {}
        if not isinstance(manager, Mapping):
            manager = {}
        observed_status = avail.get("official_status_observed") is True
        normal_without_numeric = (
            observed_status
            and avail.get("normal_status_no_numeric_adjustment") is True
            and avail.get("authority") == "OFFICIAL_FPL_BOOTSTRAP"
            and avail.get("fpl_status") == "a"
        )
        official_availability += int(observed_status)
        no_numeric_adjustment += int(normal_without_numeric)
        advisory_role += int(role.get("status") == "PROFILE_ADVISORY_UNCALIBRATED")
        missing_manager += int(manager.get("status") == "NO_VERIFIED_MANAGER_TIMELINE")
        # Normal official FPL status is an observation, not a numerical
        # medical/start probability. No DOUBT probability should be
        # invented solely to satisfy a mandatory signal count.
        required_nonavailability = CONTEXT_SIGNALS - {"normalized_availability_start_signal"}
        contextual += int(
            required_nonavailability.issubset(signals)
            and ("normalized_availability_start_signal" in signals
                 or normal_without_numeric)
        )
        raw_values = evidence.get("signal_values") or []
        quantitative_vector = tuple(
            sorted(
                (
                    (str(r.get("signal")), r.get("probability"), r.get("weight"))
                    for r in raw_values if isinstance(r, Mapping)
                ),
                key=lambda item: item[0],
            )
        )
        # Vectors must match signals one-for-one; duplicate/undeclared
        # signals, nonfinite values or out-of-range probabilities are invalid.
        has_quantified = bool(
            quantitative_vector
            and len(quantitative_vector) == len(signals)
            and {name for name, _, _ in quantitative_vector} == signals
            and all(
                isinstance(probability, (int, float))
                and not isinstance(probability, bool)
                and isfinite(probability)
                and 0.0 <= probability <= 1.0
                and isinstance(weight, (int, float))
                and not isinstance(weight, bool)
                and isfinite(weight)
                and weight >= 0.0
                for _, probability, weight in quantitative_vector
            )
        )
        quantified += int(has_quantified)
        agrees = evidence.get("model_probability_agrees") is True
        model_agreed += int(agrees)
        if evidence.get("model_probability_agrees") is False:
            mismatches.append(row.get("element_id") or row.get("element") or index)
        # Player identity/position are intentionally not used as evidence.
        signature = (
            selection.get("observed_matches"), selection.get("starts"),
            selection.get("recent_starts"), selection.get("selection_posterior"),
            tuple(sorted(signals)), quantitative_vector,
        )
        by_probability[round(p, 4)].append(signature)

    identical, different = 0, 0
    for vectors in by_probability.values():
        counts = Counter(vectors)
        n = len(vectors)
        same = sum(v * (v - 1) // 2 for v in counts.values())
        identical += same
        different += n * (n - 1) // 2 - same
    complete = len(rows) == 15 and not missing and not mismatches
    individual_pass = bool(complete and conditioned == len(rows))
    calibrated = calibration_status == "PASS"
    # Equal rounded output with different valid inputs is not by itself
    # a contradiction. Keep explicit model agreement and as-of calibration.
    full = bool(individual_pass and contextual == len(rows)
                and quantified == len(rows) and model_agreed == len(rows)
                and calibrated)
    blockers = []
    if not complete:
        blockers.append("CANONICAL_EVIDENCE_BINDING_INCOMPLETE")
    if not individual_pass:
        blockers.append("INDIVIDUAL_SELECTION_INCOMPLETE")
    if contextual != len(rows):
        blockers.append("ADDITIONAL_ROLE_MANAGER_AVAILABILITY_CONTEXT_INCOMPLETE")
    if quantified != len(rows):
        blockers.append("QUANTIFIED_SIGNAL_INPUTS_INCOMPLETE")
    if not calibrated:
        blockers.append("PREDEADLINE_CALIBRATION_NOT_PASS")
    if model_agreed != len(rows):
        blockers.append("MODEL_OUTPUT_AGREEMENT_UNVERIFIED")
    return {
        "contract": "V12_PSTART_RESOLUTION_AUDIT_V1",
        "status": "FULL_RESOLUTION" if full else "LIMITED_RESOLUTION",
        "evidence_conditioned_status": "PASS" if individual_pass else "PARTIAL",
        "expected_current15": 15, "actual_rows": len(rows),
        "individual_evidence_rows": conditioned,
        "contextual_evidence_rows": contextual,
        "quantified_input_rows": quantified,
        "model_agreement_rows": model_agreed,
        "official_availability_observation_rows": official_availability,
        "normal_status_numeric_adjustment_not_applicable_rows": no_numeric_adjustment,
        "advisory_role_profile_rows": advisory_role,
        "missing_verified_manager_timeline_rows": missing_manager,
        "normal_official_status_is_not_medical_probability": True,
        "availability_probability_signal_is_conditional": True,
        "complete_context_requires_all_signals": sorted(CONTEXT_SIGNALS),
        "normal_availability_exemption_requires_official_observation": True,
        "missing_rows": missing, "binding_mismatch_elements": mismatches,
        "modal_probability_count": max((len(v) for v in by_probability.values()), default=0),
        "unique_rounded_probabilities": len(by_probability),
        "equal_probability_pairs_with_identical_evidence": identical,
        "equal_probability_pairs_with_different_evidence": different,
        "rounded_collision_status": (
            "REVIEW_ONLY_NOT_A_FAIL_GATE" if different else "NO_DIFFERENT_INPUT_COLLISIONS"
        ),
        "calibration_status": calibration_status, "reasons": blockers,
        "equality_alone_is_not_failure": True,
        "mathematical_owner": "V12_PLAYER_MINUTES",
        "probability_recomputed": False,
    }
