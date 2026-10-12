"""Regression for exact canonical C/VC and honest missing evidence labels."""
from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery
from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines


def _report(vice_in_pitch=115, vice_in_final=109):
    return {
        "sections": [
            {"section_id": "S02", "state": "COMPLETE", "content": {"rows": []}},
            {"section_id": "S06", "state": "COMPLETE", "content": {
                "starting_xi": [{"element": 411}, {"element": 109}, {"element": 115}],
                "captain": {"element": 411},
                "vice_captain": {"element": vice_in_pitch},
            }},
            {"section_id": "S08", "state": "COMPLETE", "content": {
                "captain": {"element_id": 411},
                "vice_captain": {"element_id": 109},
            }},
            {"section_id": "S19", "state": "COMPLETE", "content": {
                "final_judgement": {
                    "final_captain": {"element_id": 411},
                    "vice": {"element_id": vice_in_final},
                },
            }},
        ],
    }


def test_s06_vice_mismatch_fails_closed():
    failures = validate_deep_decision_content_delivery(_report(), "")
    assert "S06_S08_VICE_CANONICAL_MISMATCH" in failures


def test_s19_vice_mismatch_fails_closed():
    failures = validate_deep_decision_content_delivery(
        _report(vice_in_pitch=109, vice_in_final=115), ""
    )
    assert "S08_S19_VICE_CANONICAL_MISMATCH" in failures


def test_matching_cross_section_cvc_has_no_mismatch():
    failures = validate_deep_decision_content_delivery(
        _report(vice_in_pitch=109, vice_in_final=109), ""
    )
    assert not any("CANONICAL_MISMATCH" in failure for failure in failures)


def test_s02_preserves_estimates_but_labels_missing_evidence():
    content = {
        "rows": [{
            "player": "Haaland", "position": "FWD", "p_start": 0.83,
            "xmins": 71.4, "projection_1gw": 5.62,
        }],
        "full_season_history": {"status": "UNAVAILABLE"},
        "analytics_acceptance": {
            "p_start": {
                "evidence_status": "UNAVAILABLE",
                "resolution_status": "UNAVAILABLE",
                "rows_with_evidence": 0,
                "rows_with_probability": 1,
            }
        },
    }
    lines, _ = _render_deep_visible_contract_lines(
        section_id="S02", content=content, owned_ids=set(), owned_names={}
    )
    body = "\n".join(lines)
    assert "EVIDENCE WARNING:" in body
    assert "0.83" in body
    assert "Haaland" in body
    assert "high-confidence production evidence" in body
