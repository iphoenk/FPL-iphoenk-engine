from __future__ import annotations

import json
from pathlib import Path


PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "performance"
    / "v12_cache_dependency_matrix.json"
)

CHANGE_CLASSES = {
    "UNCHANGED",
    "PRICE_ONLY",
    "INJURY_STATUS",
    "OWNED_AVAILABILITY",
    "XMINS",
    "ROLE",
    "SET_PIECE_ROLE",
    "FIXTURE",
    "TEAM_FINANCE",
    "MINI_LEAGUE_ONLY",
    "RUNTIME_CLASS",
    "SCENARIO_OVERRIDE",
    "CHALLENGER_ONLY",
}
LAYERS = {"Stage2", "P1.7", "MC", "scenario", "stability"}
STATES = {"HIT", "MISS", "PARTIAL_INVALIDATION", "NOT_APPLICABLE"}


def _payload():
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_matrix_is_complete_and_four_state_before_performance_ab():
    payload = _payload()
    assert payload["authority"] == "FPL_V12_CACHE_DEPENDENCY_MATRIX"
    assert payload["frozen_before_performance_ab"] is True
    assert set(payload["matrix"]) == CHANGE_CLASSES
    assert set(payload["layers"]) == LAYERS
    assert set(payload["states"]) == STATES
    for change, row in payload["matrix"].items():
        assert set(row) == LAYERS, change
        assert set(row.values()) <= STATES


def test_failure_semantics_are_fail_closed():
    semantics = _payload()["semantics"]
    assert semantics["expected_miss_actual_hit"] == "CORRECTNESS_FAIL"
    assert (
        semantics["expected_hit_actual_miss"]
        == "PERFORMANCE_OVER_INVALIDATION"
    )
    assert (
        semantics["partial_invalidation_reuses_affected_subentry"]
        == "CORRECTNESS_FAIL"
    )
    assert semantics["warm_not_equal_canonical_cold"] == "CORRECTNESS_FAIL"


def test_partial_invalidation_requires_explicit_dependency_scope():
    contract = _payload()["partial_invalidation_contract"]
    assert contract["must_identify_affected_dependency_keys"] is True
    assert contract["must_recompute_affected_subentries"] is True
    assert contract["must_compare_warm_to_canonical_cold"] is True
    assert contract["fallback_when_scope_is_uncertain"] == "MISS"


def test_public_private_boundaries_are_explicit():
    rows = _payload()["matrix"]
    assert rows["OWNED_AVAILABILITY"]["Stage2"] == "HIT"
    assert rows["OWNED_AVAILABILITY"]["P1.7"] == "MISS"
    assert rows["MINI_LEAGUE_ONLY"]["MC"] == "HIT"
    assert rows["MINI_LEAGUE_ONLY"]["stability"] == "MISS"


def test_price_and_finance_use_selective_invalidation_not_global_recompute():
    rows = _payload()["matrix"]
    assert rows["PRICE_ONLY"]["Stage2"] == "HIT"
    assert rows["PRICE_ONLY"]["MC"] == "PARTIAL_INVALIDATION"
    assert rows["TEAM_FINANCE"]["Stage2"] == "HIT"
    assert rows["TEAM_FINANCE"]["MC"] == "PARTIAL_INVALIDATION"


def test_runtime_and_model_semantic_changes_fail_closed():
    rows = _payload()["matrix"]
    for change in (
        "RUNTIME_CLASS",
        "XMINS",
        "ROLE",
        "SET_PIECE_ROLE",
        "FIXTURE",
    ):
        assert all(value == "MISS" for value in rows[change].values())


def test_challenger_only_is_context_only_until_admitted():
    row = _payload()["matrix"]["CHALLENGER_ONLY"]
    assert row["Stage2"] == "HIT"
    assert row["P1.7"] == "HIT"
    assert row["MC"] == "HIT"
    assert row["scenario"] == "NOT_APPLICABLE"
    assert row["stability"] == "NOT_APPLICABLE"
