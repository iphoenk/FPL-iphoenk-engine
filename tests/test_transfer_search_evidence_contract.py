from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.engines.canonical_decision_methodology import (
    CANONICAL_WEIGHTS,
    MethodologyContractError,
    compute_football_score,
    validate_owned_out_scan,
    validate_pairwise_battles,
    validate_search_proof,
)
from src.engines.v12_package_search import search_packages
from src.engines.v12_tactical_role import (
    CANONICAL_WEIGHT,
    TACTICAL_EVIDENCE_CLASSES,
    TacticalRoleContractError,
    classify_tactical_evidence,
)
from src.platform.legacy_execution_isolation_validate import validate as validate_legacy_isolation


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_CANONICAL_V12.txt"
STATE = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_STATE_V12.json"
WORKFLOW = ROOT / ".github" / "workflows" / "repository-governance.yml"


def _full_search_proof(**overrides):
    proof = {
        "owned_expected": 15,
        "owned_evaluated": 15,
        "eligible_universe_expected": 647,
        "eligible_universe_evaluated": 647,
        "outgoing_candidate_count": 15,
        "outgoing_combination_count": 120,
        "legal_route_count": 1,
        "hold_included": True,
        "lossy_pruning": False,
        "search_authority": "FULL",
    }
    proof.update(overrides)
    return proof


def _legal_squad():
    rows = []
    element = 1
    for position, count in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _ in range(count):
            rows.append(
                {
                    "element": element,
                    "position": position,
                    "team_id": element,
                    "now_cost": 50,
                    "sell_value": 50,
                    "status": "a",
                    "eligible": True,
                }
            )
            element += 1
    return rows


def _candidate_universe():
    return [
        {"element": 101, "position": "GK", "team_id": 16, "now_cost": 50, "status": "a", "eligible": True},
        {"element": 102, "position": "DEF", "team_id": 17, "now_cost": 50, "status": "a", "eligible": True},
        {"element": 103, "position": "MID", "team_id": 18, "now_cost": 50, "status": "a", "eligible": True},
        {"element": 104, "position": "FWD", "team_id": 19, "now_cost": 50, "status": "a", "eligible": True},
    ]


def test_01_canonical_has_zero_legacy_oracle_execution_permission():
    text = CANONICAL.read_text(encoding="utf-8")
    assert "may execute as MIGRATION_ORACLE" not in text
    assert "remains CI REGRESSION_ORACLE" not in text
    assert "MIGRATION_ORACLE execution is forbidden" in text
    assert "CI REGRESSION_ORACLE execution is forbidden" in text


def test_02_static_legacy_guard_proves_v3_v4_v5_execution_forbidden():
    assert validate_legacy_isolation(ROOT) == []


def test_03_full_serious_search_requires_exact_owned15_and_denominator_proof():
    validated = validate_search_proof(_full_search_proof(), search_authority="FULL")
    assert validated["owned_expected"] == 15
    assert validated["owned_evaluated"] == 15
    assert validated["denominator_complete"] is True
    with pytest.raises(MethodologyContractError):
        validate_search_proof(
            _full_search_proof(owned_evaluated=14),
            search_authority="FULL",
        )


def test_04_user_named_out_is_hypothesis_not_mandatory_outgoing():
    scan = validate_owned_out_scan(
        {
            "evaluated_owned_element_ids": list(range(1, 16)),
            "selected_outgoing_element_ids": [2],
            "user_named_outgoing_element_ids": [1],
            "selection_is_result_not_precondition": True,
            "user_named_out_is_hypothesis_only": True,
        },
        require_complete=True,
    )
    assert scan["selected_outgoing_element_ids"] == [2]
    assert scan["user_named_outgoing_element_ids"] == [1]
    assert scan["second_outgoing_score_created"] is False


def test_05_weak_link_must_be_result_not_input_precondition():
    with pytest.raises(MethodologyContractError):
        validate_owned_out_scan(
            {
                "evaluated_owned_element_ids": list(range(1, 16)),
                "selected_outgoing_element_ids": [1],
                "selection_is_result_not_precondition": False,
                "user_named_out_is_hypothesis_only": True,
            },
            require_complete=True,
        )


def test_06_hold_is_mandatory_for_full_search_authority():
    with pytest.raises(MethodologyContractError):
        validate_search_proof(
            _full_search_proof(hold_included=False),
            search_authority="FULL",
        )


def test_07_full_requires_exact_universe_denominator_agreement():
    with pytest.raises(MethodologyContractError):
        validate_search_proof(
            _full_search_proof(eligible_universe_evaluated=646),
            search_authority="FULL",
        )


def test_08_partial_is_the_only_truthful_authority_when_denominator_is_incomplete():
    partial = _full_search_proof(
        eligible_universe_evaluated=646,
        search_authority="PARTIAL",
    )
    validated = validate_search_proof(partial, search_authority="PARTIAL")
    assert validated["search_authority"] == "PARTIAL"
    assert validated["denominator_complete"] is False


def test_09_full_forbids_lossy_pruning():
    with pytest.raises(MethodologyContractError):
        validate_search_proof(
            _full_search_proof(lossy_pruning=True),
            search_authority="FULL",
        )


def test_10_pairwise_battle_retains_owned_challenger_and_material_deltas():
    battle = validate_pairwise_battles(
        [
            {
                "owned_element_id": 1,
                "challenger_element_id": 101,
                "material_deltas": {
                    "football_score": 3.2,
                    "gw_plus_1_xpts": 1.1,
                    "three_gw_xpts": 2.4,
                    "five_gw_xpts": 3.0,
                },
                "operational_action": "WAIT",
                "reversal_trigger": "confirmed lineup changes P(start)",
            }
        ]
    )[0]
    assert battle["owned_element_id"] == 1
    assert battle["challenger_element_id"] == 101
    assert battle["material_deltas"]["football_score"] == 3.2


def test_11_pairwise_evidence_cannot_create_second_decision_authority():
    with pytest.raises(MethodologyContractError):
        validate_pairwise_battles(
            [
                {
                    "owned_element_id": 1,
                    "challenger_element_id": 101,
                    "material_deltas": {"football_score": 1.0},
                    "operational_action": "ACT",
                    "reversal_trigger": "new evidence",
                    "decision_authority": True,
                }
            ]
        )


def test_12_tactical_evidence_enum_is_exact():
    assert TACTICAL_EVIDENCE_CLASSES == frozenset(
        {"OBSERVED_ROLE", "INFERRED_ROLE", "FPL_POSITION_ONLY", "UNKNOWN"}
    )


def test_13_fpl_position_only_is_not_observed_tactical_role():
    row = classify_tactical_evidence(
        element_id=10,
        evidence_class="FPL_POSITION_ONLY",
    )
    assert row["fpl_position_is_tactical_role_proof"] is False
    assert row["tactical_numeric_evidence"] is None
    with pytest.raises(TacticalRoleContractError):
        classify_tactical_evidence(
            element_id=10,
            evidence_class="FPL_POSITION_ONLY",
            tactical_numeric_evidence=0.6,
        )


def test_14_unknown_cannot_silently_become_numeric_tactical_evidence():
    with pytest.raises(TacticalRoleContractError):
        classify_tactical_evidence(
            element_id=10,
            evidence_class="UNKNOWN",
            tactical_numeric_evidence=0.5,
        )


def test_15_state_remains_non_authoritative():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    assert state["authority"] is False
    assert state["non_authoritative_state_file"] is True
    assert state["latest_explicit_user_state_wins"] is True


def test_16_state_does_not_duplicate_raw_v6_payload():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    assert state["model_evidence"]["raw_v6_payload_persisted"] is False
    serialized = json.dumps(state, sort_keys=True)
    assert '"raw_v6_payload":' not in serialized
    assert '"raw_v6_payloads":' not in serialized


def test_17_package_search_emits_exact_owned15_first_search_proof():
    result = search_packages(
        current_squad=_legal_squad(),
        candidate_universe=_candidate_universe(),
        bank=0,
        max_transfers=2,
        universe_complete=True,
        expected_eligible_universe_count=4,
        lossy_pruning=False,
    )
    proof = result["search_proof"]
    assert proof == {
        "owned_expected": 15,
        "owned_evaluated": 15,
        "eligible_universe_expected": 4,
        "eligible_universe_evaluated": 4,
        "outgoing_candidate_count": 15,
        "outgoing_combination_count": 120,
        "legal_route_count": len(result["routes"]),
        "hold_included": True,
        "lossy_pruning": False,
        "search_authority": "FULL",
    }
    assert result["owned_out_scan"]["evaluated_owned_element_ids"] == list(range(1, 16))
    assert result["owned_out_scan"]["selection_is_result_not_precondition"] is True
    assert result["governance"]["user_named_out_is_never_search_precondition"] is True


def test_18_static_v12_test_workflow_contains_no_legacy_runtime_execution():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m src.runtime_v3" not in text
    assert "python -m src.runtime_v4" not in text
    assert "python -m src.runtime_v5" not in text
    assert "package_optimizer_shards" not in text
    assert "package_optimizer_exhaustive_accelerated" not in text


def test_19_canonical_search_proof_surface_is_explicit_and_no_fake_full_claim():
    text = CANONICAL.read_text(encoding="utf-8")
    for token in (
        "OUR15_EXPECTED",
        "OUR15_EVALUATED",
        "ELIGIBLE_UNIVERSE_EXPECTED",
        "ELIGIBLE_UNIVERSE_EVALUATED",
        "OUTGOING_CANDIDATES_EVALUATED",
        "OUTGOING_COMBINATIONS_EVALUATED",
        "LEGAL_ROUTES_EVALUATED",
        "HOLD_INCLUDED",
        "LOSSY_PRUNING",
        "SEARCH_AUTHORITY",
    ):
        assert token in text
    assert "Never render FULL-UNIVERSE OPTIMIZED unless FULL authority is proven" in text


def test_20_canonical_20_25_30_25_is_unchanged():
    assert CANONICAL_WEIGHTS == {
        "PROVEN_HISTORICAL": 0.20,
        "TACTICAL_ROLE": 0.25,
        "CURRENT_UNDERLYING": 0.30,
        "FIXTURE_SECURITY": 0.25,
    }
    score = compute_football_score(
        {
            "PROVEN_HISTORICAL": 50,
            "TACTICAL_ROLE": 50,
            "CURRENT_UNDERLYING": 50,
            "FIXTURE_SECURITY": 50,
        }
    )
    assert score["football_score"] == 50.0


def test_21_tactical_taxonomy_does_not_change_p1_6_math():
    observed = classify_tactical_evidence(
        element_id=10,
        evidence_class="OBSERVED_ROLE",
        tactical_numeric_evidence=0.6,
        provenance="fixture-role-observation",
        fingerprint="abc123",
    )
    assert CANONICAL_WEIGHT == 0.25
    assert observed["changes_canonical_score"] is False
    assert observed["changes_p1_6_math"] is False


def test_22_static_guard_text_preserves_zero_legacy_fallback_and_v6_data_only():
    text = CANONICAL.read_text(encoding="utf-8")
    assert "Production factual data plane = V6 ONLY. NEVER V3/V4/V5." in text
    assert "No legacy fallback is permitted." in text
    assert "V3/V4/V5 runtime execution is forbidden." in text
