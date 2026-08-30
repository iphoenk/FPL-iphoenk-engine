from __future__ import annotations

import json

from src.runtime_v3 import registry_compiler
from src.runtime_v3.domain_orchestrator import _load_domains
from src.runtime_v3.orchestrator import _load_registry
from src.utils import ROOT

POLICY_PATH = ROOT / "config" / "runtime" / "fast_lane_policy.json"
SLO_PATH = ROOT / "config" / "runtime" / "performance_slo.json"


def run() -> dict:
    errors: list[str] = []
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    slo = json.loads(SLO_PATH.read_text(encoding="utf-8"))
    if policy.get("registry") != "V3_FAST_LANE_POLICY_V1":
        errors.append("unexpected fast-lane policy registry")
    plan = registry_compiler.compile_runtime_plan(
        domain_registry=_load_domains(),
        service_registry=_load_registry(),
    )
    if int(plan.get("domain_count") or 0) != int(policy.get("required_execution_domains") or 0):
        errors.append("fast-lane execution-domain contract drift")
    if int(plan.get("capability_count") or 0) != int(policy.get("required_capability_owners") or 0):
        errors.append("fast-lane capability-owner contract drift")
    if policy.get("execution_boundary") != "IN_PROCESS_COALESCED":
        errors.append("fast-lane execution boundary must be IN_PROCESS_COALESCED")
    if not policy.get("fail_closed_after_partial_execution"):
        errors.append("fast lane must fail closed after partial execution")
    if policy.get("fallback_to_multi_process_allowed"):
        errors.append("fast lane may not silently fall back to multi-process execution")
    for key in (
        "preserve_capability_order",
        "preserve_artifact_validation",
        "preserve_material_decision_semantics",
        "preserve_full_deep_live_paths",
    ):
        if not policy.get(key):
            errors.append(f"required fast-lane invariant disabled: {key}")
    fast_slo = (slo.get("profiles") or {}).get("fast_decision") or {}
    if float(fast_slo.get("target_wall_ms") or 0) != float(policy.get("hard_wall_ms") or -1):
        errors.append("fast-decision target SLO and fast-lane hard wall must match")
    if float(fast_slo.get("legacy_ceiling_ms") or 0) != float(policy.get("hard_wall_ms") or -1):
        errors.append("legacy ceiling must not weaken the sub-3s hard wall")
    if fast_slo.get("enforcement") != "HARD_CEILING":
        errors.append("fast-decision sub-3s contract must use HARD_CEILING")
    if int(policy.get("consecutive_candidate_runs") or 0) < 3:
        errors.append("fast-lane consistency proof requires at least three fresh-process runs")
    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "registry": policy.get("registry"),
        "plan_sha256": plan.get("plan_sha256"),
        "execution_domains": plan.get("domain_count"),
        "capability_owners": plan.get("capability_count"),
        "hard_wall_ms": policy.get("hard_wall_ms"),
        "consecutive_candidate_runs": policy.get("consecutive_candidate_runs"),
        "fallback_to_multi_process_allowed": policy.get("fallback_to_multi_process_allowed"),
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
