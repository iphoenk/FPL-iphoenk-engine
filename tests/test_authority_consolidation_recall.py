from __future__ import annotations

import json
from pathlib import Path


FIXTURES = Path(__file__).parent / "fixtures" / "authority_consolidation"
PRE = FIXTURES / "runtime_recall_pre_v11_1.json"
EXPECTED = FIXTURES / "authority_v11_1_expected.json"

REQUIRED_RECALL_STAGES = (
    "DECISION CONTEXT HYDRATION",
    "ACQUISITION / TERMINAL CONTINUATION",
    "EXACT REPORT-PREFETCH CHECK / RECOVERY",
    "DELIVERY_ACKNOWLEDGED",
    "IMMUTABLE SAME-SLOT RECEIPT",
)


def _payload(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_pre_v11_recall_is_preserved_as_known_red_proof():
    """The historical fixture must continue proving the drift that triggered V1.1."""
    recall = _payload(PRE)["final_execution_recall"]
    missing = [stage for stage in REQUIRED_RECALL_STAGES if stage not in recall]
    assert missing == list(REQUIRED_RECALL_STAGES)


def test_v11_1_expected_recall_contains_complete_ordered_pipeline():
    expected = _payload(EXPECTED)
    stages = expected["final_execution_recall"]
    for stage in REQUIRED_RECALL_STAGES:
        assert stage in stages
    assert stages[-4:] == [
        "VISIBLE_EMITTED",
        "DELIVERY_ACKNOWLEDGED",
        "IMMUTABLE SAME-SLOT RECEIPT",
        "REPORT_SLOT_FULFILLED",
    ]
    assert len(stages) == len(set(stages))


def test_active_txt_authority_count_is_exactly_two():
    expected = _payload(EXPECTED)
    assert expected["active_txt_authority"] == [
        "/FPL/FPL_MASTER_RUNTIME_CONTRACT.txt",
        "/FPL/FPL_MASTER_SPEC_V11.txt",
    ]
    assert len(expected["active_txt_authority"]) == 2
    assert expected["state"]["authority"] is False
    assert expected["state"]["v6_factual_authority"] is False


def test_timing_semantics_are_separate_even_when_values_match():
    timing = _payload(EXPECTED)["timing_semantics"]
    assert timing["dispatch"]["name"] != timing["terminal"]["name"]
    assert timing["dispatch"]["owner"] == "Runtime 1A"
    assert timing["terminal"]["owner"] == "Runtime 3C"
    assert timing["dispatch"]["value"] == timing["terminal"]["value"] == 90


def test_runtime_ownership_invariants_have_single_canonical_owners():
    owners = _payload(EXPECTED)["ownership"]
    assert owners == {
        "terminal_continuation_owner": "Runtime 3C",
        "report_prefetch_identity_owner": "Runtime 3B",
        "report_prefetch_continuation_owner": "Runtime 3E",
        "delivery_receipt_owner": "Runtime 8E",
        "natural_acceptance_owner": "Runtime 8D",
    }


def test_presentation_routes_resolve_to_one_canonical_y_definition():
    routes = _payload(EXPECTED)["presentation_routes"]
    assert routes == {
        "FULL": "Y2",
        "PRICE": "Y3",
        "MATCH": "Y4",
        "DEADLINE": "Y6",
        "FINAL": "Y7",
        "AD_HOC": "Y9",
        "CATCH_UP": "Y11",
    }


def test_rolling_natural_acceptance_does_not_revive_48_or_count_recovery():
    acceptance = _payload(EXPECTED)["natural_acceptance"]
    assert acceptance["window"] == 12
    assert acceptance["natural_only"] is True
    assert acceptance["manual_counts"] is False
    assert acceptance["recovery_counts"] is False
    assert acceptance["historical_rewrite"] is False
    assert acceptance["legacy_48_revived"] is False
