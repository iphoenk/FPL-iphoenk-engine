"""Safe, read-only diagnostics for Stage3 blocked by upstream analytics."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


_SAFE_GUARDS = {
    "MC_CANONICAL_PASS",
    "MC_CONVERGENCE_PASS",
    "MC_PATHS_500K",
    "MC_EXECUTED",
    "MC_MATCH_STATE_INVARIANTS_PASS",
    "STAGE3_DECISION_PRESENT",
    "PACKAGE_WITH_STAGE3_PRESENT",
    "MINI_OVERLAY_PRESENT",
    "PACKAGE_SEARCH_PRESENT",
    "PACKAGE_UTILITY_PRESENT",
    "MATERIAL_MC_ROUTES_PRESENT",
}
_SAFE_RUNNER_STATUSES = {"PARTIAL", "FAIL", "FAILED", "DEGRADED", "UNKNOWN"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_bool(value: Any) -> bool | None:
    return value if type(value) is bool else None


def blocked_stage3_payload(
    proof: Mapping[str, Any] | None, runner_status: str
) -> dict[str, Any]:
    """Summarize only allowlisted aggregate evidence; never copy source payloads."""
    status = str(runner_status or "UNKNOWN").upper()
    if status == "PASS":
        raise ValueError("Stage3 must execute and validate when runner passes")
    if status not in _SAFE_RUNNER_STATUSES:
        status = "UNKNOWN"

    source = _mapping(proof)
    failures = source.get("stage3_guard_failures")
    guard_failures = list(dict.fromkeys(
        token for token in (failures if isinstance(failures, list) else [])
        if isinstance(token, str) and token in _SAFE_GUARDS
    ))

    mc = _mapping(source.get("monte_carlo"))
    convergence = _mapping(mc.get("convergence"))
    acceptance = _mapping(convergence.get("acceptance"))
    convergence_status = convergence.get("status")
    if convergence_status not in {
        "PASS", "INSUFFICIENT_STABILITY", "INSUFFICIENT_CHECKPOINTS"
    }:
        convergence_status = "UNAVAILABLE"
    paths = mc.get("actual_paths")

    return {
        "contract": "V12_STAGE3_INTEGRATED_ACCEPTANCE_V1",
        "status": "DEGRADED",
        "reason": "BLOCKED_UPSTREAM",
        "integrated_runner": status,
        "stage3_executed": False,
        "stage3_pass_claimed": False,
        "mc_pass_claimed": False,
        "engineering_closure_blocks_report": False,
        "upstream_guard_failures": guard_failures,
        "upstream_monte_carlo": {
            "actual_paths": paths if type(paths) is int and paths >= 0 else None,
            "canonical_pass": _safe_bool(mc.get("canonical_pass")),
            "convergence_status": convergence_status,
            "mean_delta_stable": _safe_bool(acceptance.get("mean_delta_stable")),
            "outperform_probability_stable": _safe_bool(
                acceptance.get("outperform_probability_stable")
            ),
            "median_delta_stable": _safe_bool(acceptance.get("median_delta_stable")),
        },
        "governance": {
            "qa_relaxed": False,
            "new_scheduler_created": False,
            "second_model_authority_created": False,
            "upstream_guard_diagnostics_only": True,
        },
    }
