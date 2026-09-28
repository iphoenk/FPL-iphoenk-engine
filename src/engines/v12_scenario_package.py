from __future__ import annotations

"""Fail-closed private P4 scenario-package orchestration for Canonical V12."""

from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
from typing import Any

REQUIRED_DECISION_SURFACES = ("S06", "S08", "S09", "S14", "S19")
REQUIRED_BASE_DEPENDENCIES = (
    "model_version", "our15_fingerprint", "fixture_gw_fingerprint",
    "projection_lineage_fingerprint", "cache_schema_version", "mc_authority",
    "owner_context_fingerprint",
)

class ScenarioPackageError(RuntimeError):
    pass

def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str).encode("utf-8")

def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()

def _decision_surfaces(payload: Mapping[str, Any]) -> dict[str, Any]:
    surfaces = dict(payload.get("decision_surfaces") or {})
    if not surfaces:
        surfaces = {key: payload.get(key) for key in REQUIRED_DECISION_SURFACES if key in payload}
    missing = [key for key in REQUIRED_DECISION_SURFACES if key not in surfaces]
    if missing:
        raise ScenarioPackageError(f"canonical evaluator missing required decision surfaces: {missing}")
    return {key: surfaces[key] for key in REQUIRED_DECISION_SURFACES}

def _normalize_owned(owned_elements: Sequence[int]) -> list[int]:
    out = [int(x) for x in owned_elements]
    if len(out) != 15 or len(set(out)) != 15 or any(x <= 0 for x in out):
        raise ScenarioPackageError("P4 requires exactly 15 unique positive OUR15 element ids")
    return out

def _normalize_dependencies(dependencies: Mapping[str, Any]) -> dict[str, str]:
    out = {str(k): str(v or "").strip() for k, v in dependencies.items()}
    missing = [k for k in REQUIRED_BASE_DEPENDENCIES if not out.get(k)]
    if missing:
        raise ScenarioPackageError(f"missing P4 base dependencies: {missing}")
    return {k: out[k] for k in REQUIRED_BASE_DEPENDENCIES}

def base_fingerprint(dependencies: Mapping[str, Any]) -> str:
    return _fingerprint(_normalize_dependencies(dependencies))

def _specs(owned: Sequence[int], captain: int | None, vice: int | None) -> list[dict[str, Any]]:
    owned = _normalize_owned(owned); owned_set=set(owned)
    specs=[{"scenario_id":"BASE_CURRENT15","override_type":"BASE","element_id":None,"p_available":None}]
    specs += [{"scenario_id":f"UNAVAILABLE_{e}","override_type":"OWNED_UNAVAILABLE","element_id":e,"p_available":0.0} for e in owned]
    for sid, typ, raw in (("CAPTAIN_UNAVAILABLE","CAPTAIN_UNAVAILABLE",captain),("VICE_UNAVAILABLE","VICE_UNAVAILABLE",vice)):
        if raw is not None:
            e=int(raw)
            if e not in owned_set: raise ScenarioPackageError(f"{typ} element must belong to OUR15: {e}")
            specs.append({"scenario_id":sid,"override_type":typ,"element_id":e,"p_available":0.0})
    return specs

def build_scenario_package(*, dependencies: Mapping[str, Any], base_result: Mapping[str, Any],
    owned_elements: Sequence[int], evaluate: Callable[[Mapping[str, Mapping[str, Any]]], Mapping[str, Any]],
    generated_at: str, captain_element: int | None=None, vice_element: int | None=None) -> dict[str, Any]:
    deps=_normalize_dependencies(dependencies); bf=base_fingerprint(deps); base=_decision_surfaces(base_result)
    scenarios=[]
    for spec in _specs(owned_elements,captain_element,vice_element):
        override={}
        if spec["element_id"] is not None:
            override={str(spec["element_id"]):{"override_type":spec["override_type"],"p_available":spec["p_available"]}}
        evaluated=base_result if spec["override_type"]=="BASE" else evaluate(override)
        surfaces=_decision_surfaces(evaluated)
        scenarios.append({
            "scenario_id":spec["scenario_id"],"base_fingerprint":bf,"override_type":spec["override_type"],
            "override_input": None if spec["element_id"] is None else {"element_id":spec["element_id"],"p_available":spec["p_available"]},
            "decision_surfaces":surfaces,
            "delta_vs_base":{k:{"changed":base[k]!=surfaces[k],"base":base[k],"scenario":surfaces[k]} for k in REQUIRED_DECISION_SURFACES},
            "output_fingerprint":_fingerprint({"base_fingerprint":bf,"scenario_id":spec["scenario_id"],"override":override,"decision_surfaces":surfaces}),
        })
    return {
        "schema_version":2,"authority":"CANONICAL_V12_P4_SCENARIO_PACKAGE","private_only":True,
        "second_model_created":False,"generated_at":generated_at,"base_dependencies":deps,
        "current_base_fingerprint":bf,"scenario_count":len(scenarios),"scenarios":scenarios,
        "package_fingerprint":_fingerprint({"base_fingerprint":bf,"scenario_fingerprints":[x["output_fingerprint"] for x in scenarios]}),
        "governance":{"same_canonical_v12_evaluator_required":True,"p1_1_scenario_override_required":True,
          "posthoc_xpts_mutation_forbidden":True,"public_persistent_personal_cache_forbidden":True,
          "wrong_base_reuse_fails_closed":True,"stale_scenario_is_cache_miss":True}
    }

def validate_package_for_dependencies(package: Mapping[str, Any], *, dependencies: Mapping[str, Any]) -> dict[str, Any]:
    expected=base_fingerprint(dependencies); observed=str(package.get("current_base_fingerprint") or "")
    current=bool(expected and observed and expected==observed)
    return {"status":"HIT" if current else "MISS_RECOMPUTE","current":current,
      "expected_base_fingerprint":expected,"package_base_fingerprint":observed}

def resolve_scenario(package: Mapping[str, Any], *, scenario_id: str, dependencies: Mapping[str, Any]) -> Mapping[str, Any]:
    validation=validate_package_for_dependencies(package,dependencies=dependencies)
    if not validation["current"]: raise ScenarioPackageError("stale or wrong-base P4 package: fail closed")
    rows=[x for x in package.get("scenarios") or [] if x.get("scenario_id")==scenario_id]
    if len(rows)!=1: raise ScenarioPackageError(f"scenario not uniquely available: {scenario_id}")
    return rows[0]
