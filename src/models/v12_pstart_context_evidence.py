from __future__ import annotations

"""Read-only provenance of context offered to the canonical P(start) audit.

Observed FPL position/status and external role profiles are not calibrated
manager-, tactical-role-, or medical-start probabilities. This module does
not feed an optional numeric signal into V12_PLAYER_MINUTES.
"""
from typing import Any, Mapping


def build_pstart_context_observability(
    projection: Mapping[str, Any],
    xmins: Mapping[str, Any],
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    signals = frozenset(str(x) for x in (evidence or {}).get("signals") or [])
    tactical = projection.get("tactical_role") or {}
    if not isinstance(tactical, Mapping):
        tactical = {}
    profile = str(tactical.get("profile") or "").strip()
    advisory_profile = profile not in {"", "UNASSESSED", "UNKNOWN"}
    official_status = str(projection.get("status") or "").strip().lower()
    source_observation = xmins.get("availability_observation") or {}
    if not isinstance(source_observation, Mapping):
        source_observation = {}
    normalized = str(source_observation.get("gw_availability") or "UNKNOWN").upper()
    manager = projection.get("manager_start_context") or {}
    if not isinstance(manager, Mapping):
        manager = {}
    # A coach name in a report is not sufficient to prove a player-specific
    # manager-effect posterior, its source cutoff, or its calibration.
    manager_source = str(manager.get("source") or "")
    manager_id = str(manager.get("manager_id") or "")
    manager_observed = bool(manager_source and manager_id)
    active_manager = "manager_start_probability" in signals
    active_role = "role_start_probability" in signals
    normalized_adjusted = "normalized_availability_start_signal" in signals
    status_valid = official_status in {"a", "d", "i", "s", "u"}
    # The unflagged official status is a real observation of FPL status,
    # not a medical clearance or 100% chance of starting.
    normal_status_no_adjustment = bool(
        status_valid and official_status == "a"
        and normalized in {"UNKNOWN", "AVAILABLE", "LIKELY_AVAILABLE"}
        and not normalized_adjusted
    )
    return {
        "contract": "V12_PSTART_CONTEXT_OBSERVABILITY_V1",
        "role": {
            "profile": profile if advisory_profile else None,
            "source": tactical.get("source") if advisory_profile else None,
            "status": "PROFILE_ADVISORY_UNCALIBRATED" if advisory_profile else "UNAVAILABLE",
            "calibrated_start_signal_applied": active_role,
        },
        "manager": {
            "manager_id": manager_id if manager_observed else None,
            "source": manager_source if manager_observed else None,
            "status": "OBSERVED_NOT_CALIBRATED" if manager_observed else "NO_VERIFIED_MANAGER_TIMELINE",
            "calibrated_start_signal_applied": active_manager,
        },
        "availability": {
            "fpl_status": official_status if status_valid else None,
            "official_status_observed": status_valid,
            "authority": "OFFICIAL_FPL_BOOTSTRAP" if status_valid else "UNVERIFIED",
            "normalized_gw_state": normalized,
            "normalized_start_signal_applied": normalized_adjusted,
            "normal_status_no_numeric_adjustment": normal_status_no_adjustment,
            "official_status_is_not_start_probability": True,
            "normal_status_is_not_medical_clearance": True,
        },
        "readiness": {
            "role_manager_calibration": "NOT_ESTABLISHED",
            "asof_feature_lineage": "NOT_ESTABLISHED",
            "shadow_only": True,
            "changes_to_canonical_pstart": False,
        },
    }
