from pathlib import Path

from src.engines.v12_integrated_report_runner import _analytics_production_acceptance
from src.engines.v12_deep_delivery import validate_s19_canonical_binding


def test_s08_acceptance_is_bound_to_the_canonical_frontier_object(tmp_path: Path):
    frontier = [
        {"element_id": 11, "player": "Haaland"},
        {"element_id": 12, "player": "De Cuyper"},
    ]
    _, acceptance = _analytics_production_acceptance(
        runtime_data_root=tmp_path,
        official={},
        rows=[],
        captain_surface={
            "decision_state": "LOCK",
            "captain_frontier": frontier,
            "s08_acceptance": {
                "evidence_status": "PASS",
                "decision_state": "LOCK",
                "frontier_count": 2,
                "frontier_source": "S08_CANONICAL_CAPTAIN_FRONTIER",
                "canonical_binding": True,
            },
        },
    )
    actual = acceptance["s08_captain"]
    assert actual["evidence_status"] == "PASS"
    assert actual["decision_state"] == "LOCK"
    assert actual["frontier_count"] == 2
    assert actual["frontier_source"] == "S08_CANONICAL_CAPTAIN_FRONTIER"
    assert actual["canonical_binding"] is True


def test_missing_canonical_frontier_is_partial_not_text_based_pass(tmp_path: Path):
    _, acceptance = _analytics_production_acceptance(
        runtime_data_root=tmp_path,
        official={},
        rows=[],
        captain_surface={
            "decision_state": "LOCK",
            "captain_frontier": [],
            "rendered_text": "frontier CLOSE Haaland De Cuyper",
        },
    )
    assert acceptance["s08_captain"]["evidence_status"] == "PARTIAL"
    assert acceptance["s08_captain"]["frontier_count"] == 0
    assert acceptance["s08_captain"]["canonical_binding"] is False


def _valid_sections():
    frontier = [{"element_id": 11}, {"element_id": 12}]
    s08 = {
        "decision_state": "LOCK",
        "captain": {"element_id": 11},
        "vice_captain": {"element_id": 12},
        "captain_frontier": frontier,
    }
    s19 = {
        "final_judgement": {
            "captain_state": "LOCK",
            "final_captain": {"element_id": 11},
            "vice": {"element_id": 12},
            "captain_frontier": frontier,
            "consumed_sections": ["S08", "S15B"],
        }
    }
    return s08, s19, frontier


def test_s19_cvc_and_frontier_are_pass_when_all_bindings_match():
    s08, s19, _ = _valid_sections()
    assert validate_s19_canonical_binding(
        s06={"captain": {"element_id": 11}, "vice_captain": {"element_id": 12}, "starting_xi": [11, 12]},
        s08=s08,
        s15b={},
        s19=s19,
        s08_acceptance={
            "evidence_status": "PASS",
            "decision_state": "LOCK",
            "frontier_count": 2,
            "frontier_source": "S08_CANONICAL_CAPTAIN_FRONTIER",
            "canonical_binding": True,
        },
    ) == []


def test_s19_fails_closed_on_cvc_mismatch_and_missing_consumers():
    s08, s19, _ = _valid_sections()
    s19["final_judgement"]["vice"] = {"element_id": 11}
    s19["final_judgement"]["consumed_sections"] = ["S08"]
    failures = validate_s19_canonical_binding(
        s06={"captain": {"element_id": 99}, "vice_captain": {"element_id": 12}, "starting_xi": [11, 12]},
        s08=s08,
        s15b={},
        s19=s19,
        s08_acceptance={"evidence_status": "PARTIAL", "frontier_count": 0, "canonical_binding": False},
    )
    assert "S19_S06_S08_CVC_MISMATCH" in failures
    assert "S19_S08_FINAL_CVC_MISMATCH" in failures
    assert "S19_REQUIRED_CONSUMERS_MISSING" in failures
    assert "S19_S08_ACCEPTANCE_BINDING_NOT_PASS" in failures


def test_s19_prepare_cannot_be_marked_executable():
    s08, s19, frontier = _valid_sections()
    s08["decision_state"] = "PREPARE"
    s19["final_judgement"]["captain_state"] = "PREPARE"
    s19["final_judgement"]["recommendation_status"] = "EXECUTABLE_LOCK"
    failures = validate_s19_canonical_binding(
        s06={"captain": {"element_id": 11}, "vice_captain": {"element_id": 12}, "starting_xi": [11, 12]},
        s08=s08,
        s15b={},
        s19=s19,
        s08_acceptance={
            "evidence_status": "PASS", "decision_state": "PREPARE",
            "frontier_count": len(frontier), "frontier_source": "S08_CANONICAL_CAPTAIN_FRONTIER",
            "canonical_binding": True,
        },
        rendered_text="CAPTAIN NOT FINAL",
    )
    assert "S19_PREPARE_MARKED_EXECUTABLE" in failures
