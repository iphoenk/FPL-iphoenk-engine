"""Regression: CLOSE captain must not look like a locked recommendation in DEEP."""

from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines
from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery


def _visible(section_id, payload):
    lines, _ = _render_deep_visible_contract_lines(
        section_id=section_id,
        content=payload,
        owned_ids=set(),
        owned_names={},
    )
    return "\n".join(lines)


def test_s08_prepare_labels_gk_as_provisional_baseline():
    body = _visible("S08", {
        "captain": {"player": "Tzolakis"},
        "vice_captain": {"player": "B.Fernandes"},
        "football_leader": {"player": "Tzolakis"},
        "decision_state": "PREPARE",
        "football_frontier_classification": "CLOSE",
        "reconciliation_reason": "GK captain CLOSE: attacker has stronger haul tail",
        "review_pair": {"captain": {"player": "B.Fernandes"}, "status": "PREPARE_NOT_EXECUTABLE"},
    })
    assert "CAPTAIN DECISION NOT LOCKED" in body
    assert "Current C baseline: Tzolakis" in body
    assert "state PREPARE" in body
    assert "NOT a final captain recommendation" in body
    assert "Attacking captain review alternative: B.Fernandes" in body


def test_s19_prepare_never_presents_gk_as_final_recommendation():
    body = _visible("S19", {
        "final_judgement": {
            "transfer_action": "WAIT",
            "final_captain": {"player": "Tzolakis"},
            "vice": {"player": "B.Fernandes"},
            "captain_state": "PREPARE",
            "captain_review_pair": {"captain": {"player": "B.Fernandes"}},
        }
    })
    assert "CAPTAIN NOT FINAL" in body
    assert "Captain baseline: Tzolakis (PREPARE)" in body
    assert "Vice baseline: B.Fernandes" in body
    assert "Captain attacking review candidate: B.Fernandes" in body


def test_locked_captain_does_not_get_provisional_warning():
    body = _visible("S08", {
        "captain": {"player": "Bruno"},
        "vice_captain": {"player": "Haaland"},
        "decision_state": "LOCK",
    })
    assert "CAPTAIN DECISION NOT LOCKED" not in body
    assert "state LOCK" in body


def _s08_visibility_failures(payload, rendered):
    report = {
        "sections": [
            {"section_id": "S08", "state": "COMPLETE", "content": payload}
        ]
    }
    failures = validate_deep_decision_content_delivery(report, rendered)
    return [
        reason for reason in failures
        if reason in {
            "S08_CURRENT_CAPTAIN_NOT_VISIBLE",
            "S08_CURRENT_VICE_NOT_VISIBLE",
        }
    ]


def test_s08_prepare_baseline_labels_pass_strict_visibility_qa():
    payload = {
        "decision_state": "PREPARE",
        "captain": {"player": "Tzolakis"},
        "vice_captain": {"player": "B.Fernandes"},
    }
    rendered = _visible("S08", payload)
    assert "Current C baseline: Tzolakis" in rendered
    assert "Current VC baseline: B.Fernandes" in rendered
    assert _s08_visibility_failures(payload, rendered) == []


def test_s08_lock_requires_locked_labels_not_provisional_labels():
    payload = {
        "decision_state": "LOCK",
        "captain": {"player": "Bruno"},
        "vice_captain": {"player": "Haaland"},
    }
    rendered = _visible("S08", payload)
    assert "Current C: Bruno" in rendered
    assert "Current VC: Haaland" in rendered
    assert _s08_visibility_failures(payload, rendered) == []
    misleading = rendered.replace("Current C: Bruno", "Current C baseline: Bruno")
    assert "S08_CURRENT_CAPTAIN_NOT_VISIBLE" in _s08_visibility_failures(payload, misleading)


def test_s08_prepare_rejects_missing_provisional_c_and_vc_labels():
    payload = {
        "decision_state": "PREPARE",
        "captain": {"player": "Tzolakis"},
        "vice_captain": {"player": "B.Fernandes"},
    }
    rendered = _visible("S08", payload)
    misleading = rendered.replace("Current C baseline:", "Captain:").replace(
        "Current VC baseline:", "Vice:"
    )
    assert set(_s08_visibility_failures(payload, misleading)) == {
        "S08_CURRENT_CAPTAIN_NOT_VISIBLE",
        "S08_CURRENT_VICE_NOT_VISIBLE",
    }
