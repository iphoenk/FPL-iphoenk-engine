from __future__ import annotations

import json

from src.runtime_v3 import registry_compiler
from src.runtime_v3.domain_orchestrator import _load_domains
from src.runtime_v3.orchestrator import _load_registry
from src.utils import ROOT

POLICY_PATH = ROOT / "config" / "runtime" / "fast_lane_policy.json"
CANONICAL_SLO_PATH = "config/runtime/performance_slo.json"
CANONICAL_DOMAIN_PATH = "config/runtime/execution_domains.json"
CANONICAL_CAPABILITY_PATH = "config/v3_service_registry.json"


def run() -> dict:
    errors: list[str] = []
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if policy.get("registry") != "V3_FAST_LANE_POLICY_V1":
        errors.append("unexpected fast-lane policy registry")

    profile = str(policy.get("performance_slo_profile") or "")
    if policy.get("performance_slo_registry") != CANONICAL_SLO_PATH:
        errors.append("fast-lane performance SLO registry pointer drift")
    if profile != "fast_decision" or policy.get("profiles") != ["fast_decision"]:
        errors.append("fast-lane profile must resolve to canonical fast_decision")
    if policy.get("execution_domain_registry") != CANONICAL_DOMAIN_PATH:
        errors.append("fast-lane execution-domain registry pointer drift")
    if policy.get("capability_registry") != CANONICAL_CAPABILITY_PATH:
        errors.append("fast-lane capability registry pointer drift")

    duplicate_numeric_keys = {
        "hard_wall_ms",
        "warning_wall_ms",
        "required_execution_domains",
        "required_capability_owners",
    }
    duplicated = sorted(duplicate_numeric_keys & set(policy))
    if duplicated:
        errors.append(f"fast-lane policy duplicates canonical numeric truth: {duplicated}")

    slo = json.loads((ROOT / CANONICAL_SLO_PATH).read_text(encoding="utf-8"))
    if slo.get("registry") != "RUNTIME_PERFORMANCE_SLO_V1":
        errors.append("unexpected canonical performance SLO registry")
    fast_slo = (slo.get("profiles") or {}).get(profile) if profile else None
    if not isinstance(fast_slo, dict):
        errors.append(f"missing canonical performance SLO profile: {profile!r}")
        fast_slo = {}
    target = float(fast_slo.get("target_wall_ms") or 0)
    warning = float(fast_slo.get("warning_wall_ms") or 0)
    ceiling = float(fast_slo.get("legacy_ceiling_ms") or 0)
    if target <= 0 or warning <= 0 or ceiling <= 0:
        errors.append("canonical fast-decision SLO contains non-positive limits")
    if ceiling != target:
        errors.append("canonical fast-decision hard ceiling must equal target")
    if warning > ceiling:
        errors.append("canonical fast-decision warning may not exceed hard ceiling")
    if fast_slo.get("enforcement") != "HARD_CEILING":
        errors.append("fast-decision contract must use HARD_CEILING")

    plan = registry_compiler.compile_runtime_plan(
        domain_registry=_load_domains(),
        service_registry=_load_registry(),
    )
    if int(plan.get("domain_count") or 0) <= 0:
        errors.append("compiled fast-lane execution plan has no domains")
    if int(plan.get("capability_count") or 0) <= 0:
        errors.append("compiled fast-lane execution plan has no capability owners")

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
    if int(policy.get("consecutive_candidate_runs") or 0) < 3:
        errors.append("fast-lane consistency proof requires at least three fresh-process runs")

    result = {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "registry": policy.get("registry"),
        "plan_sha256": plan.get("plan_sha256"),
        "execution_domains": plan.get("domain_count"),
        "capability_owners": plan.get("capability_count"),
        "slo_profile": profile,
        "target_wall_ms": target,
        "warning_wall_ms": warning,
        "hard_wall_ms": ceiling,
        "single_numeric_authority": not duplicated,
        "consecutive_candidate_runs": policy.get("consecutive_candidate_runs"),
        "fallback_to_multi_process_allowed": policy.get("fallback_to_multi_process_allowed"),
    }
    print(json.dumps(result, ensure_ascii=False))
    if errors:
        raise SystemExit(2)
    return result


if __name__ == "__main__":
    run()
