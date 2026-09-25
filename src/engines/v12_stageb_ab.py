from __future__ import annotations

"""Controlled Stage B A/B diagnostics.

This module does not alter P1.7 or comparator semantics. It invokes existing
owners on two frozen input surfaces and reports exact deltas.
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


def apply_existing_p11_availability_overlay(
    *,
    player: Mapping[str, Any],
    baseline_context: Mapping[str, Any],
    availability_state: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Re-run the existing P1.1 owner with only its governed congestion input."""
    baseline = estimate_player_minutes(dict(player), dict(baseline_context))
    overlay = dict(
        ((availability_state or {}).get("xmins_context_overlay") or {})
    )
    enriched_context = dict(baseline_context)
    if overlay.get("application") == "EXISTING_P1_1_CONGESTION_FACTOR":
        existing = _f(enriched_context.get("congestion_factor"), 1.0)
        enriched_context["congestion_factor"] = min(
            existing,
            _f(overlay.get("congestion_factor"), 1.0),
        )
    enriched = estimate_player_minutes(dict(player), enriched_context)
    return {
        "contract": "V12_STAGEB_P11_AB_V1",
        "owner": "V12_PLAYER_MINUTES",
        "baseline": baseline,
        "enriched": enriched,
        "delta": {
            "Pstart": round(
                _f(enriched.get("start_probability"))
                - _f(baseline.get("start_probability")),
                6,
            ),
            "xMins": round(
                _f(enriched.get("expected_minutes"))
                - _f(baseline.get("expected_minutes")),
                6,
            ),
        },
        "causal_field": (
            "context.congestion_factor"
            if enriched_context != dict(baseline_context)
            else None
        ),
        "new_minutes_owner_created": False,
    }


def shadow_component_replacement(
    *,
    baseline_total: float,
    baseline_components: Mapping[str, Any],
    enriched_defcon_ev: float | None,
) -> dict[str, Any]:
    """Replace, never add, the baseline DEFCON component in shadow xPts."""
    baseline_defcon = _f(
        baseline_components.get("defensive_contribution")
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
    }


def _decision_surface(decision: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "XI": [int(row.get("element") or 0) for row in decision.get("starting_xi") or []],
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
    """Run exact canonical P1.7 twice on frozen A/B projection surfaces."""
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
        "contract": "V12_STAGEB_EXACT_P17_AB_V1",
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
    }


def compare_transfer_comparator_outputs(
    baseline: Mapping[str, Any] | None,
    enriched: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Compare existing comparator output; this function owns no ranking."""
    def gains(payload: Mapping[str, Any] | None) -> dict[str, Any]:
        if not payload:
            return {}
        rows = payload.get("comparisons") or []
        out = {}
        for row in rows:
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
    component: Mapping[str, Any] | None = None,
    ordering: Mapping[str, Any] | None = None,
    p17: Mapping[str, Any] | None = None,
    comparator: Mapping[str, Any] | None = None,
    causal_fields: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "contract": "V12_STAGEB_CONTROLLED_AB_REPORT_V1",
        "P1_1": deepcopy(dict(p11 or {})),
        "projected_points_components": deepcopy(dict(component or {})),
        "player_ordering": deepcopy(dict(ordering or {})),
        "P1_7": deepcopy(dict(p17 or {})),
        "transfer_comparator": deepcopy(dict(comparator or {})),
        "exact_causal_fields": list(dict.fromkeys(str(x) for x in causal_fields if x)),
        "governance": {
            "same_frozen_snapshot_required": True,
            "defcon_replacement_not_addition": True,
            "p17_semantics_unchanged": True,
            "p12b_semantics_unchanged": True,
            "monte_carlo_architecture_unchanged": True,
            "diagnostic_only": True,
        },
    }
