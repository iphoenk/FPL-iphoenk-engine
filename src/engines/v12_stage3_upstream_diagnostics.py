"""Read-only diagnostic summary for Stage3 blocked by incomplete upstream analytics."""
from __future__ import annotations

from typing import Any, Mapping


def blocked_stage3_payload(proof: Mapping[str, Any] | None, runner_status: str) -> dict[str, Any]:
    """Do not claim Stage3 PASS if analytics never completed."""
    if runner_status == "PASS":
        raise ValueError("Stage3 validator must execute when runner passes")
    source = dict(proof or {})
    allowed = {
        "MC_CANONICAL_PASS", "MC_CONVERGENCE_PASS", "MC_PATHS_500K",
        "MC_EXECUTED", "MC_MATCH_STATE_INVARIANTS_PASS",
        "STAGE3_DECISION_PRESENT", "PACKAGE_WITH_STAGE3_PRESENT",
        "MINI_OVERLAY_PRESENT", "PACKAGE_SEARCH_PRESENT",
        "PACKAGE_UTILITY_PRESENT", "MATERIAL_MC_ROUTES_PRESENT",
    }
    guard_failures = list(dict.fromkeys(
        token for token in source.get("stage3_guard_failures") or []
        if isinstance(token, str) and token in allowed
    ))
    mc = dict(source.get("monte_carlo") or {})
    convergence = dict(mc.get("convergence") or {})
    flags = dict(convergence.get("acceptance") or {})
    status = str(convergence.get("status") or "UNAVAILABLE")
    if status not in {"PASS", "INSUFFICIENT_STABILITY", "INSUFFICIENT_CHECKPOINTS"}:
        status = "UNAVAILABLE"
    return {
        "contract": "V12_STAGE3_INTEGRATED_ACCEPTANCE_V1",
        "status": "DEGRADED",
        "reason": "BLOCKED_UPSTREAM",
        "integrated_runner": runner_status,
        "stage3_executed": False,
        "stage3_pass_claimed": False,
        "mc_pass_claimed": False,
        "engineering_closure_blocks_report": False,
        "upstream_guard_failures": guard_failures,
        "upstream_monte_carlo": {
            "actual_paths": mc.get("actual_paths") if type(mc.get("actual_paths")) is int else None,
            "canonical_pass": mc.get("canonical_pass") if type(mc.get("canonical_pass")) is bool else None,
            "convergence_status": status,
            "mean_delta_stable": flags.get("mean_delta_stable") if type(flags.get("mean_delta_stable")) is bool else None,
            "outperform_probability_stable": flags.get("outperform_probability_stable") if type(flags.get("outperform_probability_stable")) is bool else None,
            "median_delta_stable": flags.get("median_delta_stable") if type(flags.get("median_delta_stable")) is bool else None,
        },
        "governance": {
            "qa_relaxed": False,
            "new_scheduler_created": False,
            "second_model_authority_created": False,
            "upstream_guard_diagnostics_only": True,
        },
    }
