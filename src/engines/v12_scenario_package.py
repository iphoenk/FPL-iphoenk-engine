from __future__ import annotations

"""Private P4 scenario-package orchestration for Canonical V12.

This module does not score players, project points, optimize routes, or select
captains.  It enumerates governed counterfactuals and calls an injected
canonical evaluator for each one.  The evaluator must run the existing V12
decision chain with the supplied P1.1 scenario override.
"""

from collections.abc import Callable, Mapping, Sequence
import hashlib
import json
from typing import Any


REQUIRED_DECISION_SURFACES = ("S06", "S08", "S09", "S14", "S19")
STABILITY_PLACEHOLDER = "NOT_YET_EVALUATED"


class ScenarioPackageError(RuntimeError):
    pass


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


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
    return {key: surfaces[key] for key in REQUIRED_DECISION_SURFACES}


def _delta(
    base: Mapping[str, Any],
    scenario: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        key: {
            "changed": base.get(key) != scenario.get(key),
            "base": base.get(key),
            "scenario": scenario.get(key),
        }
        for key in REQUIRED_DECISION_SURFACES
    }


def _normalize_owned(owned_elements: Sequence[int]) -> list[int]:
    out = [int(element) for element in owned_elements]
    if len(out) != 15 or len(set(out)) != 15 or any(element <= 0 for element in out):
        raise ScenarioPackageError(
            "P4 requires exactly 15 unique positive OUR15 element ids"
        )
    return out


def _scenario_specs(
    owned_elements: Sequence[int],
    *,
    captain_doubt_elements: Sequence[int] = (),
    vice_captain_doubt_elements: Sequence[int] = (),
) -> list[dict[str, Any]]:
    owned = _normalize_owned(owned_elements)
    owned_set = set(owned)
    specs: list[dict[str, Any]] = [
        {
            "scenario_id": f"OUR15_UNAVAILABLE_{element}",
            "override_type": "OWNED_UNAVAILABLE",
            "element_id": element,
            "p_available": 0.0,
        }
        for element in owned
    ]
    for label, values in (
        ("CAPTAIN_DOUBT", captain_doubt_elements),
        ("VICE_CAPTAIN_DOUBT", vice_captain_doubt_elements),
    ):
        for raw in values:
            element = int(raw)
            if element not in owned_set:
                raise ScenarioPackageError(
                    f"{label} element must belong to OUR15: {element}"
                )
            specs.append(
                {
                    "scenario_id": f"{label}_{element}",
                    "override_type": label,
                    "element_id": element,
                    "p_available": 0.5,
                }
            )
    ids = [row["scenario_id"] for row in specs]
    if len(ids) != len(set(ids)):
        raise ScenarioPackageError("duplicate P4 scenario id")
    return specs


def build_scenario_package(
    *,
    current_base_fingerprint: str,
    base_result: Mapping[str, Any],
    owned_elements: Sequence[int],
    evaluate: Callable[[Mapping[str, Mapping[str, Any]]], Mapping[str, Any]],
    captain_doubt_elements: Sequence[int] = (),
    vice_captain_doubt_elements: Sequence[int] = (),
) -> dict[str, Any]:
    base_fingerprint = str(current_base_fingerprint or "").strip()
    if not base_fingerprint:
        raise ScenarioPackageError("current_base_fingerprint is required")

    base_surfaces = _decision_surfaces(base_result)
    specs = _scenario_specs(
        owned_elements,
        captain_doubt_elements=captain_doubt_elements,
        vice_captain_doubt_elements=vice_captain_doubt_elements,
    )

    scenarios: list[dict[str, Any]] = []
    for spec in specs:
        element = int(spec["element_id"])
        override = {
            str(element): {
                "override_type": spec["override_type"],
                "p_available": float(spec["p_available"]),
            }
        }
        evaluated = evaluate(override)
        if not isinstance(evaluated, Mapping):
            raise ScenarioPackageError(
                f"canonical evaluator returned non-mapping for {spec['scenario_id']}"
            )
        scenario_surfaces = _decision_surfaces(evaluated)
        output_fingerprint = _fingerprint(
            {
                "base_fingerprint": base_fingerprint,
                "scenario_id": spec["scenario_id"],
                "override": override,
                "decision_surfaces": scenario_surfaces,
            }
        )
        scenarios.append(
            {
                "scenario_id": spec["scenario_id"],
                "base_fingerprint": base_fingerprint,
                "override_type": spec["override_type"],
                "override_input": {
                    "element_id": element,
                    "p_available": float(spec["p_available"]),
                },
                "decision_surfaces": scenario_surfaces,
                "delta_vs_base": _delta(base_surfaces, scenario_surfaces),
                "output_fingerprint": output_fingerprint,
                "route_survival": STABILITY_PLACEHOLDER,
                "reversal_probability": STABILITY_PLACEHOLDER,
                "expected_regret": STABILITY_PLACEHOLDER,
                "stability_state": STABILITY_PLACEHOLDER,
            }
        )

    package = {
        "schema_version": 1,
        "authority": "CANONICAL_V12_P4_SCENARIO_PACKAGE",
        "private_only": True,
        "second_model_created": False,
        "current_base_fingerprint": base_fingerprint,
        "base_decision_surfaces": base_surfaces,
        "scenario_count": len(scenarios),
        "owned_unavailable_scenario_count": 15,
        "captain_doubt_scenario_count": len(captain_doubt_elements),
        "vice_captain_doubt_scenario_count": len(vice_captain_doubt_elements),
        "scenarios": scenarios,
        "package_fingerprint": _fingerprint(
            {
                "base_fingerprint": base_fingerprint,
                "scenario_fingerprints": [
                    row["output_fingerprint"] for row in scenarios
                ],
            }
        ),
        "governance": {
            "same_canonical_v12_evaluator_required": True,
            "p1_1_scenario_override_required": True,
            "posthoc_xpts_mutation_forbidden": True,
            "public_persistent_personal_cache_forbidden": True,
            "stability_placeholders_are_not_evaluated_metrics": True,
        },
    }
    return package


def validate_package_for_base(
    package: Mapping[str, Any],
    *,
    current_base_fingerprint: str,
) -> dict[str, Any]:
    expected = str(current_base_fingerprint or "").strip()
    observed = str(package.get("current_base_fingerprint") or "").strip()
    valid = bool(expected and observed and expected == observed)
    return {
        "status": "CURRENT" if valid else "INVALIDATE_AND_REBUILD",
        "current": valid,
        "expected_base_fingerprint": expected,
        "package_base_fingerprint": observed,
    }
