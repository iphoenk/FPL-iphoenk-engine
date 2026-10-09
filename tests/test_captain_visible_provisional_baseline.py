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


def _cross_position_frontier():
    return [
        {
            "element_id": 30, "player": "Defender A", "position": "DEF",
            "expected_points": 4.81, "p_blank": 0.43,
            "p_ge_10": 0.11, "q90": 10, "p_start": 0.96,
            "xmins": 89.0, "football_evidence_complete": True,
        },
        {
            "element_id": 40, "player": "Midfielder B", "position": "MID",
            "expected_points": 4.68, "p_blank": 0.31,
            "p_ge_10": 0.14, "q90": 11, "p_start": 0.92,
            "xmins": 84.0, "football_evidence_complete": True,
        },
        {
            "element_id": 50, "player": "Forward C", "position": "FWD",
            "expected_points": 4.67, "p_blank": 0.36,
            "p_ge_10": 0.16, "q90": 12, "p_start": 0.90,
            "xmins": 81.0, "football_evidence_complete": True,
        },
    ]


def test_s19_close_frontier_explains_all_positions_not_highest_mean_only():
    frontier = _cross_position_frontier()
    body = _visible("S19", {
        "final_judgement": {
            "transfer_action": "WAIT",
            "final_captain": {"player": "Defender A"},
            "vice": {"player": "Midfielder B"},
            "captain_state": "PREPARE",
            "captain_frontier_classification": "CLOSE",
            "captain_frontier": frontier,
            "captain_tiebreak": {
                "risk_posture": "ATTACK",
                "tie_break_status": "CONTEXT_INCOMPLETE",
                "vice_fallback_reason": "Start-security fallback",
            },
        }
    })
    assert "Captain football frontier: CLOSE" in body
    assert "Captain frontier comparison (canonical S08;" in body
    assert "Defender A [DEF]: xPts 4.81; P(blank) 43.0%; P(10+) 11.0%" in body
    assert "Midfielder B [MID]: xPts 4.68; P(blank) 31.0%; P(10+) 14.0%" in body
    assert "Forward C [FWD]: xPts 4.67; P(blank) 36.0%; P(10+) 16.0%" in body
    assert "tie-break CONTEXT_INCOMPLETE" in body
    assert "Captain baseline: Defender A (PREPARE)" in body
    assert "CAPTAIN NOT FINAL" in body
    assert "EO is not expected points" in body


def test_s19_close_frontier_missing_evidence_is_explicit():
    body = _visible("S19", {
        "final_judgement": {
            "captain_state": "PREPARE",
            "captain_frontier_classification": "CLOSE",
            "captain_frontier": [
                {"element_id": 50, "player": "Forward C", "position": "FWD"}
            ],
        },
    })
    assert "P(blank) UNAVAILABLE" in body
    assert "P(10+) UNAVAILABLE" in body
    assert "evidence INCOMPLETE" in body
    assert "Captain baseline: UNAVAILABLE (PREPARE)" in body


def test_s19_close_qa_rejects_missing_and_mismatched_frontier():
    rows = _cross_position_frontier()
    s08 = {
        "decision_state": "PREPARE",
        "football_frontier_classification": "CLOSE",
        "captain_frontier": rows,
    }
    s19 = {
        "captain_state": "PREPARE",
        "captain_frontier_classification": "CLOSE",
        "captain_frontier": rows,
        "consumed_sections": ["S08", "S15B"],
    }

    def failures(judgement, visible):
        report = {"sections": [
            {"section_id": "S08", "state": "COMPLETE", "content": s08},
            {"section_id": "S19", "state": "COMPLETE",
             "content": {"final_judgement": judgement}},
        ]}
        return validate_deep_decision_content_delivery(report, visible)

    visible = _visible("S19", {"final_judgement": s19})
    close_failures = failures(s19, visible)
    assert not any(x.startswith("S19_CAPTAIN_FRONTIER") for x in close_failures)

    missing = dict(s19, captain_frontier=[])
    errors = failures(missing, _visible("S19", {"final_judgement": missing}))
    assert "S19_CAPTAIN_FRONTIER_NOT_CANONICAL" in errors
    assert "S19_CAPTAIN_FRONTIER_NOT_VISIBLE" in errors

    reordered = dict(s19, captain_frontier=list(reversed(rows)))
    errors = failures(reordered, _visible("S19", {"final_judgement": reordered}))
    assert "S19_CAPTAIN_FRONTIER_NOT_CANONICAL" in errors
