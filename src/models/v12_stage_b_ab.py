from __future__ import annotations

"""Controlled Stage B A/B diagnostics over existing canonical owners.

The harness never becomes a decision owner. It re-runs existing P1.1 and P1.7
on frozen A/B inputs, and compares already-produced comparator surfaces.
"""

from copy import deepcopy
from typing import Any, Mapping, Sequence

from src.engines.v12_lineup_optimizer import optimize_lineup
from src.engines.v12_player_minutes import estimate_player_minutes


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def run_stage_b_controlled_ab(
    *,
    player: Mapping[str, Any],
    baseline_context: Mapping[str, Any],
    role_duty_evidence: Mapping[str, Any],
    availability_evidence: Mapping[str, Any],
    baseline_components: Mapping[str, Any] | None = None,
    candidate_defcon_ev: float | None = None,
) -> dict[str, Any]:
    """Re-run the existing P1.1 owner with candidate evidence only."""
    baseline_context = dict(baseline_context)
    baseline = estimate_player_minutes(dict(player), baseline_context)

    candidate_context = dict(baseline_context)
    role_context = dict(role_duty_evidence.get("candidate_p1_1_context") or {})
    role_start_probability = role_context.get("role_start_probability")
    causal_fields: list[str] = []
    if role_start_probability is not None:
        candidate_context["role_start_probability"] = role_start_probability
        causal_fields.append("context.role_start_probability")

    availability_context = dict(availability_evidence.get("xmins_context") or {})
    if availability_context.get("automatic_numeric_congestion_factor") is not None:
        candidate_context["congestion_factor"] = availability_context[
            "automatic_numeric_congestion_factor"
        ]
        causal_fields.append("context.congestion_factor")
    if availability_context.get("automatic_numeric_rotation_risk") is not None:
        candidate_context["rotation_risk"] = availability_context[
            "automatic_numeric_rotation_risk"
        ]
        causal_fields.append("context.rotation_risk")

    candidate = estimate_player_minutes(dict(player), candidate_context)
    components = dict(baseline_components or {})
    replacement = shadow_component_replacement(
        baseline_total=_f(components.get("TOTAL_EV")),
        baseline_components=components,
        enriched_defcon_ev=candidate_defcon_ev,
    ) if components.get("TOTAL_EV") is not None else {
        "status": "UNAVAILABLE_BASELINE_TOTAL_NOT_SUPPLIED"
    }

    return {
        "contract": "V12_STAGE_B_CONTROLLED_AB_V2",
        "baseline": {
            "xmins": baseline.get("expected_minutes"),
            "p_start": baseline.get("start_probability"),
            "components": components,
        },
        "candidate_evidence": {
            "xmins": candidate.get("expected_minutes"),
            "p_start": candidate.get("start_probability"),
            "candidate_context": candidate_context,
            "DEFCON_EV": candidate_defcon_ev,
            "component_replacement": replacement,
        },
        "delta": {
            "xmins": round(
                _f(candidate.get("expected_minutes"))
                - _f(baseline.get("expected_minutes")),
                6,
            ),
            "p_start": round(
                _f(candidate.get("start_probability"))
                - _f(baseline.get("start_probability")),
                6,
            ),
            "causal_fields": causal_fields,
        },
        "availability_numeric_effect": (
            "NOT_APPLIED_NO_CALIBRATED_NUMERIC_MAPPING"
            if not any(field in {
                "context.congestion_factor",
                "context.rotation_risk",
            } for field in causal_fields)
            else "APPLIED_THROUGH_EXISTING_P1_1_CONTEXT"
        ),
        "governance": {
            "frozen_snapshot_required": True,
            "p1_1_owner_reused": True,
            "new_xmins_owner_created": False,
            "canonical_xpts_not_mutated": True,
            "p1_7_not_modified": True,
            "p1_2b_not_modified": True,
            "monte_carlo_not_modified": True,
        },
    }


def shadow_component_replacement(
    *,
    baseline_total: float,
    baseline_components: Mapping[str, Any],
    enriched_defcon_ev: float | None,
) -> dict[str, Any]:
    """Replace the DEFCON component in shadow arithmetic, never add it."""
    baseline_defcon = _f(
        baseline_components.get("DEFCON_EV")
        if baseline_components.get("DEFCON_EV") is not None
        else baseline_components.get("defensive_contribution")
        if baseline_components.get("defensive_contribution") is not None
        else baseline_components.get("defcon"),
        0.0,
    )
    if enriched_defcon_ev is None:
        return {
            "status": "UNAVAILABLE",
            "baseline_total": round(float(baseline_total), 6),
            "shadow_total": None,
            "causal_field": None,
        }
    shadow_total = (
        float(baseline_total) - baseline_defcon + float(enriched_defcon_ev)
    )
    return {
        "status": "AVAILABLE",
        "baseline_total": round(float(baseline_total), 6),
        "baseline_DEFCON_EV": round(baseline_defcon, 6),
        "enriched_DEFCON_EV": round(float(enriched_defcon_ev), 6),
        "shadow_total": round(shadow_total, 6),
        "delta": round(shadow_total - float(baseline_total), 6),
        "causal_field": "DEFCON_EV_REPLACEMENT",
        "double_count_guard": True,
        "CS_EV_unchanged": baseline_components.get("CS_EV"),
        "ATTACK_EV_unchanged": baseline_components.get("ATTACK_EV"),
        "BONUS_EV_unchanged": baseline_components.get("BONUS_EV"),
    }


def _decision_surface(decision: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "XI": [
            int(row.get("element") or 0)
            for row in decision.get("starting_xi") or []
        ],
        "bench": [
            int(row.get("element") or 0)
            for row in ((decision.get("bench") or {}).get("order") or [])
        ],
        "captain": int((decision.get("captain") or {}).get("element") or 0),
        "vice": int((decision.get("vice_captain") or {}).get("element") or 0),
        "formation": decision.get("formation"),
        "lineup_score": (decision.get("lineup_score") or {}).get("robust"),
    }


def run_exact_p17_ab(
    *,
    baseline_projections: Mapping[str, Any],
    enriched_projections: Mapping[str, Any],
    squad_ids: Sequence[int],
    planning_gw: int,
    generated_at: str,
) -> dict[str, Any]:
    """Invoke the exact existing P1.7 owner twice on frozen A/B surfaces."""
    baseline = optimize_lineup(
        baseline_projections,
        squad_ids,
        planning_gw=planning_gw,
        generated_at=generated_at,
    )
    enriched = optimize_lineup(
        enriched_projections,
        squad_ids,
        planning_gw=planning_gw,
        generated_at=generated_at,
    )
    base_surface = _decision_surface(baseline)
    enriched_surface = _decision_surface(enriched)
    return {
        "contract": "V12_STAGE_B_EXACT_P17_AB_V1",
        "baseline": base_surface,
        "enriched": enriched_surface,
        "changed": {
            "XI": base_surface["XI"] != enriched_surface["XI"],
            "bench": base_surface["bench"] != enriched_surface["bench"],
            "captain": base_surface["captain"] != enriched_surface["captain"],
            "vice": base_surface["vice"] != enriched_surface["vice"],
            "formation": base_surface["formation"] != enriched_surface["formation"],
        },
        "p17_owner": "V12_LINEUP_OPTIMIZER",
        "p17_semantics_changed": False,
    }


def compare_player_ordering(
    baseline_rows: Sequence[Mapping[str, Any]],
    enriched_rows: Sequence[Mapping[str, Any]],
    *,
    score_field: str = "score",
) -> dict[str, Any]:
    def ordered(rows: Sequence[Mapping[str, Any]]) -> list[int]:
        return [
            int(row.get("element") or 0)
            for row in sorted(
                rows,
                key=lambda row: (
                    _f(row.get(score_field)),
                    -int(row.get("element") or 0),
                ),
                reverse=True,
            )
        ]

    baseline = ordered(baseline_rows)
    enriched = ordered(enriched_rows)
    return {
        "baseline": baseline,
        "enriched": enriched,
        "changed": baseline != enriched,
        "score_field": score_field,
        "ranking_authority_created": False,
    }


def compare_transfer_comparator_outputs(
    baseline: Mapping[str, Any] | None,
    enriched: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare existing comparator outputs without creating a comparator owner."""
    def gains(payload: Mapping[str, Any] | None) -> dict[str, Any]:
        if not payload:
            return {}
        out = {}
        for row in payload.get("comparisons") or []:
            if not isinstance(row, Mapping):
                continue
            candidate = (
                row.get("player_in")
                or row.get("candidate")
                or row.get("challenger")
                or {}
            )
            element = (
                candidate.get("element_id")
                or candidate.get("element")
                or row.get("element_id")
            )
            if element is None:
                continue
            out[str(element)] = (
                row.get("raw_gains")
                or row.get("horizon_raw_gains")
                or row.get("horizons")
            )
        return out

    base = gains(baseline)
    enrich = gains(enriched)
    return {
        "baseline": base,
        "enriched": enrich,
        "changed": base != enrich,
        "comparator_semantics_changed": False,
        "ranking_authority_created": False,
    }


def build_ab_report(
    *,
    p11: Mapping[str, Any] | None = None,
    components: Mapping[str, Any] | None = None,
    ordering: Mapping[str, Any] | None = None,
    p17: Mapping[str, Any] | None = None,
    comparator: Mapping[str, Any] | None = None,
    causal_fields: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "contract": "V12_STAGE_B_CONTROLLED_AB_REPORT_V1",
        "P1_1": deepcopy(dict(p11 or {})),
        "projected_points_components": deepcopy(dict(components or {})),
        "player_ordering": deepcopy(dict(ordering or {})),
        "P1_7": deepcopy(dict(p17 or {})),
        "transfer_comparator": deepcopy(dict(comparator or {})),
        "exact_causal_fields": list(
            dict.fromkeys(str(value) for value in causal_fields if value)
        ),
        "governance": {
            "same_frozen_snapshot_required": True,
            "defcon_replacement_not_addition": True,
            "p1_7_semantics_unchanged": True,
            "p1_2b_semantics_unchanged": True,
            "monte_carlo_architecture_unchanged": True,
            "diagnostic_only": True,
        },
    }
