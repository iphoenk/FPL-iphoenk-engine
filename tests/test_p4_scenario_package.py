from __future__ import annotations

from copy import deepcopy

import pytest

from src.engines.v12_scenario_package import (
    REQUIRED_DECISION_SURFACES,
    ScenarioPackageError,
    build_scenario_package,
    validate_package_for_base,
)


OWNED = list(range(1, 16))


def _base() -> dict:
    return {
        "decision_surfaces": {
            "S06": {"xi": list(range(1, 12)), "bench": [12, 13, 14, 15]},
            "S08": {"captain": 1, "vice": 2},
            "S09": {"chip": "NONE"},
            "S14": {"route": "HOLD"},
            "S19": {"action": "WAIT"},
        }
    }


def _evaluator(overrides):
    out = deepcopy(_base())
    element = int(next(iter(overrides)))
    override = overrides[str(element)]
    assert override["override_type"] in {
        "OWNED_UNAVAILABLE",
        "CAPTAIN_DOUBT",
        "VICE_CAPTAIN_DOUBT",
    }
    out["decision_surfaces"]["S06"] = {
        "xi": [value for value in range(1, 12) if value != element],
        "bench": [12, 13, 14, 15, element],
    }
    if element == 1:
        out["decision_surfaces"]["S08"] = {"captain": 2, "vice": 3}
    out["decision_surfaces"]["S19"] = {"action": "PREPARE"}
    return out


def test_p4_builds_exact_15_owned_unavailable_scenarios() -> None:
    package = build_scenario_package(
        current_base_fingerprint="base-a",
        base_result=_base(),
        owned_elements=OWNED,
        evaluate=_evaluator,
    )
    assert package["private_only"] is True
    assert package["second_model_created"] is False
    assert package["scenario_count"] == 15
    assert package["owned_unavailable_scenario_count"] == 15
    assert len(package["scenarios"]) == 15
    assert len({row["scenario_id"] for row in package["scenarios"]}) == 15
    assert all(row["base_fingerprint"] == "base-a" for row in package["scenarios"])
    assert all(
        row["override_type"] == "OWNED_UNAVAILABLE"
        for row in package["scenarios"]
    )
    assert all(row["route_survival"] == "NOT_YET_EVALUATED" for row in package["scenarios"])
    assert all(
        row["reversal_probability"] == "NOT_YET_EVALUATED"
        for row in package["scenarios"]
    )
    assert all(row["expected_regret"] == "NOT_YET_EVALUATED" for row in package["scenarios"])
    assert all(row["stability_state"] == "NOT_YET_EVALUATED" for row in package["scenarios"])


def test_p4_package_is_deterministic_for_same_base_and_evaluator() -> None:
    kwargs = {
        "current_base_fingerprint": "base-a",
        "base_result": _base(),
        "owned_elements": OWNED,
        "evaluate": _evaluator,
    }
    a = build_scenario_package(**kwargs)
    b = build_scenario_package(**kwargs)
    assert a == b
    assert a["package_fingerprint"] == b["package_fingerprint"]


def test_p4_supports_material_captain_and_vice_doubt_scenarios() -> None:
    package = build_scenario_package(
        current_base_fingerprint="base-a",
        base_result=_base(),
        owned_elements=OWNED,
        evaluate=_evaluator,
        captain_doubt_elements=[1],
        vice_captain_doubt_elements=[2],
    )
    assert package["scenario_count"] == 17
    assert package["captain_doubt_scenario_count"] == 1
    assert package["vice_captain_doubt_scenario_count"] == 1
    ids = {row["scenario_id"] for row in package["scenarios"]}
    assert "CAPTAIN_DOUBT_1" in ids
    assert "VICE_CAPTAIN_DOUBT_2" in ids


def test_p4_invalidates_when_current_base_changes() -> None:
    package = build_scenario_package(
        current_base_fingerprint="base-a",
        base_result=_base(),
        owned_elements=OWNED,
        evaluate=_evaluator,
    )
    assert validate_package_for_base(
        package, current_base_fingerprint="base-a"
    )["status"] == "CURRENT"
    result = validate_package_for_base(
        package, current_base_fingerprint="base-b"
    )
    assert result["status"] == "INVALIDATE_AND_REBUILD"
    assert result["current"] is False


def test_p4_requires_exact_our15_and_required_decision_surfaces() -> None:
    with pytest.raises(ScenarioPackageError, match="exactly 15"):
        build_scenario_package(
            current_base_fingerprint="base-a",
            base_result=_base(),
            owned_elements=OWNED[:14],
            evaluate=_evaluator,
        )

    bad = _base()
    del bad["decision_surfaces"][REQUIRED_DECISION_SURFACES[-1]]
    with pytest.raises(ScenarioPackageError, match="missing required decision surfaces"):
        build_scenario_package(
            current_base_fingerprint="base-a",
            base_result=bad,
            owned_elements=OWNED,
            evaluate=_evaluator,
        )


def test_p4_captain_doubt_must_be_owned() -> None:
    with pytest.raises(ScenarioPackageError, match="must belong to OUR15"):
        build_scenario_package(
            current_base_fingerprint="base-a",
            base_result=_base(),
            owned_elements=OWNED,
            evaluate=_evaluator,
            captain_doubt_elements=[999],
        )
