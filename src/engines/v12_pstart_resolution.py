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
    invalid_identity, duplicate_identity, invalid_quantitative = [], [], []
    seen_ids: set[int] = set()
    conditioned = contextual = quantified = 0

    def valid_int(value: Any) -> bool:
        return type(value) is int and value >= 0

    def valid_prob(value: Any) -> bool:
        return (type(value) in (float, int)
                and isfinite(value) and 0 <= value <= 1)
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            missing.append(index)
            continue
        element_id = row.get("element_id")
        if element_id is None:
            element_id = row.get("element")
        if type(element_id) is not int or element_id <= 0:
            invalid_identity.append(index)
        elif element_id in seen_ids:
            duplicate_identity.append(element_id)
        else:
            seen_ids.add(element_id)
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
            and valid_int(selection.get("observed_matches"))
            and selection["observed_matches"] > 0
            and valid_int(selection.get("starts"))
            and 0 <= selection["starts"] <= selection["observed_matches"]
            and valid_int(selection.get("recent_starts"))
            and selection["recent_starts"] <= selection["observed_matches"]
            and valid_prob(selection.get("selection_posterior"))
        )
        conditioned += int(is_conditioned)
        contextual += int(bool(signals & CONTEXT_SIGNALS))
        raw_values = evidence.get("signal_values") or []
        vector_rows = [
            (str(value.get("signal")), value.get("probability"), value.get("weight"))
            for value in raw_values if isinstance(value, Mapping)
        ] if isinstance(raw_values, (list, tuple)) else []
        # Stable sort key avoids comparing malformed numeric types.
        quantitative_vector = tuple(sorted(vector_rows, key=lambda item: item[0]))
        signal_names = [item[0] for item in quantitative_vector]
        has_quantified = bool(
            quantitative_vector
            and len(quantitative_vector) == len(signals) == len(raw_values)
            and len(signal_names) == len(set(signal_names))
            and set(signal_names) == signals
            and all(valid_prob(probability)
                    and type(weight) in (float, int)
                    and isfinite(weight) and weight > 0
                    for _, probability, weight in quantitative_vector)
        )
        if not has_quantified:
            invalid_quantitative.append(element_id if type(element_id) is int else index)
        quantified += int(has_quantified)
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
    complete = bool(
        len(rows) == 15 and not missing and not mismatches
        and not invalid_identity and not duplicate_identity
    )
    individual_pass = bool(complete and conditioned == len(rows))
    calibrated = calibration_status == "PASS"
    full = bool(individual_pass and contextual == len(rows)
                and quantified == len(rows) and calibrated and different == 0)
    blockers = []
    if not complete:
        blockers.append("CANONICAL_EVIDENCE_BINDING_INCOMPLETE")
    if invalid_identity or duplicate_identity:
        blockers.append("CANONICAL_PLAYER_IDENTITY_INVALID_OR_DUPLICATED")
    if not individual_pass:
        blockers.append("INDIVIDUAL_SELECTION_INCOMPLETE")
    if contextual != len(rows):
        blockers.append("ADDITIONAL_ROLE_MANAGER_AVAILABILITY_CONTEXT_INCOMPLETE")
    if quantified != len(rows):
        blockers.append("QUANTIFIED_SIGNAL_INPUTS_INCOMPLETE")
    if not calibrated:
        blockers.append("PREDEADLINE_CALIBRATION_NOT_PASS")
    if different:
        blockers.append("EQUAL_OUTPUT_WITH_DIFFERENT_INPUT_REQUIRES_REVIEW")
    return {
        "contract": "V12_PSTART_RESOLUTION_AUDIT_V1",
        "status": "FULL_RESOLUTION" if full else "LIMITED_RESOLUTION",
        "evidence_conditioned_status": "PASS" if individual_pass else "PARTIAL",
        "expected_current15": 15, "actual_rows": len(rows),
        "individual_evidence_rows": conditioned,
        "contextual_evidence_rows": contextual,
        "quantified_input_rows": quantified,
        "missing_rows": missing, "binding_mismatch_elements": mismatches,
        "invalid_identity_rows": invalid_identity,
        "duplicate_player_elements": duplicate_identity,
        "invalid_quantitative_input_elements": invalid_quantitative,
        "independent_identity_check": True,
        "quantitative_signal_domain_checked": True,
        "modal_probability_count": max((len(v) for v in by_probability.values()), default=0),
        "unique_rounded_probabilities": len(by_probability),
        "equal_probability_pairs_with_identical_evidence": identical,
        "equal_probability_pairs_with_different_evidence": different,
        "calibration_status": calibration_status, "reasons": blockers,
        "equality_alone_is_not_failure": True,
        "mathematical_owner": "V12_PLAYER_MINUTES",
        "probability_recomputed": False,
    }
