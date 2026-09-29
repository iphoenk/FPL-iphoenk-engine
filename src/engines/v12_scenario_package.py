from __future__ import annotations

"""Fail-closed private P4 scenario-package orchestration for Canonical V12."""

from collections.abc import Callable, Mapping, Sequence
import gzip
import hashlib
import json
from pathlib import Path
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
        surfaces = {
            key: payload.get(key)
            for key in REQUIRED_DECISION_SURFACES
            if key in payload
        }
    missing = [key for key in REQUIRED_DECISION_SURFACES if key not in surfaces]
    if missing:
        raise ScenarioPackageError(
            f"canonical evaluator missing required decision surfaces: {missing}"
        )
    # Keep every canonical section supplied by the evaluator.  The P4 builder
    # will persist the mandatory decision core plus any section whose payload
    # actually changes versus BASE_CURRENT15.  This preserves cold semantics
    # without bloating every shard with unchanged report sections.
    return surfaces

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

def build_scenario_package(
    *,
    dependencies: Mapping[str, Any],
    base_result: Mapping[str, Any],
    owned_elements: Sequence[int],
    evaluate: Callable[
        [Mapping[str, Mapping[str, Any]]],
        Mapping[str, Any],
    ],
    generated_at: str,
    captain_element: int | None = None,
    vice_element: int | None = None,
) -> dict[str, Any]:
    deps = _normalize_dependencies(dependencies)
    bf = base_fingerprint(deps)
    base_all = _decision_surfaces(base_result)
    base_stage3_action = str(base_result.get("stage3_action") or "")
    scenarios = []
    for spec in _specs(
        owned_elements,
        captain_element,
        vice_element,
    ):
        override: dict[str, dict[str, Any]] = {}
        if spec["element_id"] is not None:
            override = {
                str(spec["element_id"]): {
                    "override_type": spec["override_type"],
                    "p_available": spec["p_available"],
                }
            }
        evaluated = (
            base_result
            if spec["override_type"] == "BASE"
            else evaluate(override)
        )
        surfaces_all = _decision_surfaces(evaluated)
        if set(surfaces_all) != set(base_all):
            raise ScenarioPackageError(
                "canonical scenario section set differs from BASE_CURRENT15"
            )
        changed_surface_ids = [
            key
            for key in sorted(base_all)
            if base_all[key] != surfaces_all[key]
        ]
        selected_surface_ids = sorted(
            set(REQUIRED_DECISION_SURFACES)
            | set(changed_surface_ids)
        )
        surfaces = {
            key: surfaces_all[key]
            for key in selected_surface_ids
        }
        stage3_action = str(evaluated.get("stage3_action") or "")
        raw_rebind_inputs = evaluated.get("p1_8_rebind_inputs")
        rebind_inputs = (
            dict(raw_rebind_inputs)
            if isinstance(raw_rebind_inputs, Mapping)
            else None
        )
        scenarios.append(
            {
                "scenario_id": spec["scenario_id"],
                "base_fingerprint": bf,
                "override_type": spec["override_type"],
                "override_input": (
                    None
                    if spec["element_id"] is None
                    else {
                        "element_id": spec["element_id"],
                        "p_available": spec["p_available"],
                    }
                ),
                "changed_surface_ids": changed_surface_ids,
                "decision_surfaces": surfaces,
                "stage3_action": stage3_action,
                "stage3_action_changed": (
                    stage3_action != base_stage3_action
                ),
                **(
                    {"p1_8_rebind_inputs": rebind_inputs}
                    if rebind_inputs is not None
                    else {}
                ),
                "delta_vs_base": {
                    key: {
                        "changed": base_all[key] != surfaces_all[key],
                        "base": base_all[key],
                        "scenario": surfaces_all[key],
                    }
                    for key in selected_surface_ids
                },
                "output_fingerprint": _fingerprint(
                    {
                        "base_fingerprint": bf,
                        "scenario_id": spec["scenario_id"],
                        "override": override,
                        "decision_surfaces": surfaces,
                        "stage3_action": stage3_action,
                        **(
                            {"p1_8_rebind_inputs": rebind_inputs}
                            if rebind_inputs is not None
                            else {}
                        ),
                    }
                ),
            }
        )
    return {
        "schema_version": 4,
        "authority": "CANONICAL_V12_P4_SCENARIO_PACKAGE",
        "private_only": True,
        "second_model_created": False,
        "generated_at": generated_at,
        "base_dependencies": deps,
        "current_base_fingerprint": bf,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "package_fingerprint": _fingerprint(
            {
                "base_fingerprint": bf,
                "scenario_fingerprints": [
                    row["output_fingerprint"]
                    for row in scenarios
                ],
            }
        ),
        "governance": {
            "same_canonical_v12_evaluator_required": True,
            "p1_1_scenario_override_required": True,
            "posthoc_xpts_mutation_forbidden": True,
            "public_persistent_personal_cache_forbidden": True,
            "wrong_base_reuse_fails_closed": True,
            "stale_scenario_is_cache_miss": True,
            "changed_surface_capture_required": True,
            "p1_8_overlay_rebind_inputs_persisted": all(
                isinstance(row.get("p1_8_rebind_inputs"), Mapping)
                for row in scenarios
            ),
        },
    }

def validate_package_for_dependencies(package: Mapping[str, Any], *, dependencies: Mapping[str, Any]) -> dict[str, Any]:
    expected=base_fingerprint(dependencies); observed=str(package.get("current_base_fingerprint") or "")
    current=bool(expected and observed and expected==observed)
    return {"status":"HIT" if current else "MISS_RECOMPUTE","current":current,
      "expected_base_fingerprint":expected,"package_base_fingerprint":observed}

def _load_sharded_scenario(package: Mapping[str, Any], row: Mapping[str, Any]) -> Mapping[str, Any]:
    root_raw = str(package.get("_storage_root") or "").strip()
    relative_raw = str(row.get("storage_path") or "").strip()
    encoding = str(row.get("storage_encoding") or "").strip()
    if not root_raw or not relative_raw or encoding != "gzip-json-v1":
        raise ScenarioPackageError("sharded P4 scenario storage metadata is incomplete")
    relative = Path(relative_raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise ScenarioPackageError("unsafe P4 scenario storage path")
    root = Path(root_raw).resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ScenarioPackageError("P4 scenario shard escaped private storage root")
    if not candidate.is_file():
        raise ScenarioPackageError(f"P4 scenario shard unavailable: {relative_raw}")
    with gzip.open(candidate, "rt", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, Mapping):
        raise ScenarioPackageError("P4 scenario shard is not an object")
    for key in ("scenario_id", "base_fingerprint", "output_fingerprint"):
        if str(payload.get(key) or "") != str(row.get(key) or ""):
            raise ScenarioPackageError(f"P4 scenario shard metadata mismatch: {key}")
    _decision_surfaces(payload)
    return dict(payload)


def resolve_scenario(package: Mapping[str, Any], *, scenario_id: str, dependencies: Mapping[str, Any]) -> Mapping[str, Any]:
    validation=validate_package_for_dependencies(package,dependencies=dependencies)
    if not validation["current"]: raise ScenarioPackageError("stale or wrong-base P4 package: fail closed")
    rows=[x for x in package.get("scenarios") or [] if x.get("scenario_id")==scenario_id]
    if len(rows)!=1: raise ScenarioPackageError(f"scenario not uniquely available: {scenario_id}")
    row=rows[0]
    if isinstance(row.get("decision_surfaces"), Mapping):
        return row
    return _load_sharded_scenario(package, row)
