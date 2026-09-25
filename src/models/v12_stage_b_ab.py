from __future__ import annotations

"""Controlled evidence-only Stage-B A/B harness."""

from copy import deepcopy
from typing import Any, Mapping

from src.engines.v12_player_minutes import estimate_player_minutes


def run_stage_b_controlled_ab(
    *,
    player: Mapping[str, Any],
    baseline_context: Mapping[str, Any],
    role_duty_evidence: Mapping[str, Any],
    availability_evidence: Mapping[str, Any],
    baseline_components: Mapping[str, Any] | None = None,
    candidate_defcon_ev: float | None = None,
    frozen_decision_surface: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare evidence surfaces without mutating canonical final xPts/decisions."""
    baseline_context = dict(baseline_context)
    baseline = estimate_player_minutes(dict(player), baseline_context)

    candidate_context = dict(baseline_context)
    role_context = dict(role_duty_evidence.get("candidate_p1_1_context") or {})
    role_start_probability = role_context.get("role_start_probability")
    causal_fields: list[str] = []
    if role_start_probability is not None:
        candidate_context["role_start_probability"] = role_start_probability
        causal_fields.append("role_start_probability")

    availability_context = dict(availability_evidence.get("xmins_context") or {})
    if availability_context.get("automatic_numeric_congestion_factor") is not None:
        candidate_context["congestion_factor"] = availability_context[
            "automatic_numeric_congestion_factor"
        ]
        causal_fields.append("congestion_factor")
    if availability_context.get("automatic_numeric_rotation_risk") is not None:
        candidate_context["rotation_risk"] = availability_context[
            "automatic_numeric_rotation_risk"
        ]
        causal_fields.append("rotation_risk")

    candidate = estimate_player_minutes(dict(player), candidate_context)

    components = dict(baseline_components or {})
    candidate_components = dict(components)
    evidence_preview = {
        "DEFCON_EV": candidate_defcon_ev,
        "CS_EV": components.get("CS_EV"),
        "ATTACK_EV": components.get("ATTACK_EV"),
        "BONUS_EV": components.get("BONUS_EV"),
    }

    decision = deepcopy(dict(frozen_decision_surface or {}))
    decision_fields = {
        key: {
            "baseline": deepcopy(decision.get(key)),
            "candidate": deepcopy(decision.get(key)),
            "changed": False,
        }
        for key in (
            "player_ordering",
            "xi",
            "bench",
            "captain",
            "vice",
            "transfer_comparator",
        )
    }

    return {
        "contract": "V12_STAGE_B_CONTROLLED_AB_V1",
        "baseline": {
            "xmins": baseline.get("expected_minutes"),
            "p_start": baseline.get("start_probability"),
            "components": components,
        },
        "candidate_evidence": {
            "xmins": candidate.get("expected_minutes"),
            "p_start": candidate.get("start_probability"),
            "component_preview": evidence_preview,
            "candidate_context": candidate_context,
        },
        "delta": {
            "xmins": round(
                float(candidate.get("expected_minutes") or 0.0)
                - float(baseline.get("expected_minutes") or 0.0),
                6,
            ),
            "p_start": round(
                float(candidate.get("start_probability") or 0.0)
                - float(baseline.get("start_probability") or 0.0),
                6,
            ),
            "causal_fields": causal_fields,
        },
        "decision_surface": decision_fields,
        "final_xpts_changed": False,
        "candidate_components_committed_to_xpts": False,
        "governance": {
            "frozen_snapshot_required": True,
            "p1_1_owner_reused": True,
            "new_xmins_owner_created": False,
            "canonical_xpts_not_mutated": True,
            "p1_7_not_called_or_modified": True,
            "p1_2b_not_called_or_modified": True,
            "monte_carlo_not_called_or_modified": True,
            "decision_outputs_unchanged_by_construction": True,
        },
    }
