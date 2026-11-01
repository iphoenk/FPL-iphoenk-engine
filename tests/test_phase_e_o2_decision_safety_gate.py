"""Phase E O2: decision safety gate acceptance and negative tests."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from src.engines import v12_integrated_report_runner as runner
from src.engines.v12_decision_safety_gate import evaluate_decision_safety_gate
from src.engines.v12_report_orchestration import _render_deep_visible_contract_lines

FIXTURE = Path(__file__).parent / "fixtures/phase_e/deep_current15_authority_20261025_20261030.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _rows():
    return [
        {"element_id": 1, "player": "A", "name": "A", "position": "MID", "expected_points": 6.0},
        {"element_id": 2, "player": "B", "name": "B", "position": "FWD", "expected_points": 7.0},
        {"element_id": 3, "player": "C", "name": "C", "position": "GK", "expected_points": 5.0},
    ]


def _surface(monkeypatch, gate, *, state="LOCK"):
    rows = _rows()
    decision = {
        "decision_state": state, "classification": "CLEAR",
        "captain": rows[1], "vice_captain": rows[0], "football_leader": rows[1],
        "profiles": rows, "frontier": rows[:2],
        "review_pair": {},
    }
    monkeypatch.setattr(runner, "decide_captain_vice", lambda *a, **k: decision)
    kwargs = {} if gate is None else {"our15_gate": gate}
    return runner._captain_decision_surface(
        owned=rows,
        lineup={"starting_xi": rows, "captain": rows[1], "vice_captain": rows[0]},
        lineup_state="COMPLETE",
        mini_detail={},
        projections={},
        **kwargs,
    )


def _dashboard(gate, *, lineup_battle=None, captain_state="LOCK"):
    kwargs = {} if gate is None else {"our15_gate": gate}
    return runner._decision_dashboard(
        operational_action="WAIT",
        planning_gw=9,
        stage3_decision={},
        lineup_state="COMPLETE",
        lineup={"main_starting_xi_battle": lineup_battle or {}},
        captain_surface={"decision_state": captain_state},
        chip_available=True,
        price_radar={},
        auth_state="AUTH_AVAILABLE",
        finance={},
        **kwargs,
    )


def test_o2_t1_previous_gw_fallback_rejects_captain_lock_and_xi_executable(monkeypatch):
    res = _fixture()["20261030_123000"]["personal_resolution"]
    assert res["status"] == "PREVIOUS_GW_IDENTITY_FALLBACK"
    gate = evaluate_decision_safety_gate(res)
    assert gate["executable"] is False and gate["max_state"] == "PREPARE"
    assert "OUR15_NOT_CURRENT_VALID" in gate["reason_codes"]
    surface = _surface(monkeypatch, gate, state="LOCK")
    assert surface["decision_state"] == "PREPARE"
    assert surface["recommendation_status"] == "PROVISIONAL_PRIORITY"
    assert surface["s08_acceptance"]["decision_state"] == "PREPARE"
    assert surface["decision_safety_gate"]["reason_codes"] == ["OUR15_NOT_CURRENT_VALID"]
    dash = _dashboard(gate)
    assert dash["XI"] != "LOCK" and dash["CAPTAIN"] != "LOCK"
    assert "OUR15_NOT_CURRENT_VALID" in dash["CURRENT_BLOCKERS"]
    assert dash["DECISION_EXECUTABLE"] is False


def test_o2_t2_current_valid_keeps_legitimate_behaviour(monkeypatch):
    res = _fixture()["20261025_213000"]["personal_resolution"]
    assert res["status"] == "CURRENT_VALID"
    gate = evaluate_decision_safety_gate(res)
    assert gate["executable"] is True
    surface = _surface(monkeypatch, gate, state="LOCK")
    baseline = _surface(monkeypatch, None, state="LOCK")
    assert surface["decision_state"] == baseline["decision_state"] == "LOCK"
    assert surface["recommendation_status"] == "EXECUTABLE_LOCK"
    dash, base = _dashboard(gate), _dashboard(None)
    assert dash["XI"] == base["XI"] == "LOCK" and dash["CAPTAIN"] == base["CAPTAIN"] == "LOCK"


def test_o2_t3_valid_our15_but_critical_evidence_failed_downgrades(monkeypatch):
    res = _fixture()["20261025_213000"]["personal_resolution"]
    gate = evaluate_decision_safety_gate(
        res, critical_evidence={"V6_PUBLISH_INTEGRITY": "FAIL", "OFFICIAL_FACTS": "PASS"}
    )
    assert gate["executable"] is False and gate["max_state"] == "PREPARE"
    assert gate["reason_codes"] == ["CRITICAL_EVIDENCE_DEGRADED"]
    assert "V6_PUBLISH_INTEGRITY=FAIL" in gate["reasons"][0]["detail"]
    assert _surface(monkeypatch, gate)["decision_state"] == "PREPARE"


def test_o2_t4_noncritical_secondary_failure_does_not_downgrade(monkeypatch):
    res = _fixture()["20261025_213000"]["personal_resolution"]
    # Noncritical ids are simply not supplied as critical evidence.
    gate = evaluate_decision_safety_gate(res, critical_evidence={"OFFICIAL_FACTS": "PASS", "V6_PUBLISH_INTEGRITY": "PASS"})
    assert gate["executable"] is True and gate["reasons"] == []
    assert _surface(monkeypatch, gate)["decision_state"] == "LOCK"


def test_o2_unavailable_resolution_forces_wait():
    gate = evaluate_decision_safety_gate({"resolution_status": "UNAVAILABLE"})
    assert gate["max_state"] == "WAIT" and gate["reason_codes"] == ["OUR15_UNAVAILABLE"]
    assert _dashboard(gate)["XI"] == "WAIT" and _dashboard(gate)["CAPTAIN"] == "WAIT"
    assert evaluate_decision_safety_gate(None)["max_state"] == "WAIT"
    assert evaluate_decision_safety_gate({})["executable"] is False


def test_o2_negative_stale_flag_and_unknown_critical_status_fail_closed():
    stale = evaluate_decision_safety_gate({"resolution_status": "CURRENT_VALID", "stale": True})
    assert stale["executable"] is False and "OUR15_STALE" in stale["reason_codes"]
    unknown = evaluate_decision_safety_gate(
        {"resolution_status": "CURRENT_VALID"}, critical_evidence={"X": None}
    )
    assert unknown["executable"] is False


def test_o2_negative_public_inferred_is_not_executable_grade():
    gate = evaluate_decision_safety_gate({"resolution_status": "PUBLIC_INFERRED"})
    assert gate["executable"] is False and gate["max_state"] == "PREPARE"


def test_o2_negative_caller_detected_inconsistency_blocks():
    gate = evaluate_decision_safety_gate(
        {"resolution_status": "CURRENT_VALID"}, our15_consistency_failures=["CAPTAIN_NOT_IN_OUR15"]
    )
    assert gate["executable"] is False and gate["reason_codes"] == ["OUR15_INCONSISTENT"]


def test_o2_gate_never_raises_a_state_above_input(monkeypatch):
    gate = evaluate_decision_safety_gate({"resolution_status": "CURRENT_VALID"})
    assert _surface(monkeypatch, gate, state="WAIT")["decision_state"] == "WAIT"
    assert _surface(monkeypatch, gate, state="PREPARE")["decision_state"] == "PREPARE"


def test_o2_t5_historical_fixture_hashes_unchanged(tmp_path):
    copy = tmp_path / FIXTURE.name
    shutil.copy(FIXTURE, copy)
    before_src = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    before_copy = hashlib.sha256(copy.read_bytes()).hexdigest()
    data = json.loads(copy.read_text(encoding="utf-8"))
    for slot in data.values():
        evaluate_decision_safety_gate(slot["personal_resolution"])
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == before_src
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == before_copy


def test_o2_t6_captain_vice_and_frontier_consistent_after_clamp(monkeypatch):
    gate = evaluate_decision_safety_gate({"resolution_status": "PREVIOUS_GW_IDENTITY_FALLBACK"})
    clamped = _surface(monkeypatch, gate, state="LOCK")
    open_ = _surface(monkeypatch, None, state="LOCK")
    assert clamped["captain"] == open_["captain"] and clamped["vice_captain"] == open_["vice_captain"]
    assert clamped["captain_frontier"] == open_["captain_frontier"]
    assert clamped["s08_acceptance"]["decision_state"] == clamped["decision_state"]
    assert clamped["s08_acceptance"]["frontier_count"] == open_["s08_acceptance"]["frontier_count"]


def _visible(section_id, payload):
    lines, _ = _render_deep_visible_contract_lines(
        section_id=section_id, content=payload, owned_ids=set(), owned_names={}
    )
    return "\n".join(lines)


def test_o2_t7_consumers_do_not_read_clamped_status_as_executable(monkeypatch):
    gate = evaluate_decision_safety_gate({"resolution_status": "PREVIOUS_GW_IDENTITY_FALLBACK"})
    surface = _surface(monkeypatch, gate, state="LOCK")
    body = _visible("S08", {**surface, "captain": {"player": "B"}, "vice_captain": {"player": "A"}})
    assert "CAPTAIN DECISION NOT LOCKED" in body
    assert "EXECUTABLE_LOCK" not in body
    s19 = _visible("S19", {"final_judgement": {
        "transfer_action": "WAIT", "final_captain": {"player": "B"}, "vice": {"player": "A"},
        "captain_state": surface["decision_state"],
    }})
    assert "CAPTAIN NOT FINAL" in s19


def test_o2_surface_shows_specific_traceable_reason(monkeypatch):
    res = _fixture()["20261030_123000"]["personal_resolution"]
    gate = evaluate_decision_safety_gate(res)
    surface = _surface(monkeypatch, gate)
    reason = surface["reconciliation_reason"]
    assert "OUR15_NOT_CURRENT_VALID" in reason and "PREVIOUS_GW_IDENTITY_FALLBACK" in reason
    assert "submitted_picks" in reason


def _report(resolution_status, *, s08="LOCK", xi="LOCK", cap="LOCK", s19="EXECUTABLE_LOCK"):
    def sec(sid, content):
        return {"section_id": sid, "state": "COMPLETE", "content": content}
    return {"sections": [
        sec("S01", {"decision_dashboard": {"XI": xi, "CAPTAIN": cap}}),
        sec("S02", {"personal_resolution": {"status": resolution_status}}),
        sec("S08", {"decision_state": s08}),
        sec("S19", {"final_judgement": {"recommendation_status": s19}}),
    ]}


def test_o2_validator_rejects_executable_surfaces_without_current_our15():
    from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery

    failures = validate_deep_decision_content_delivery(_report("PREVIOUS_GW_IDENTITY_FALLBACK"), "")
    hit = [f for f in failures if f.startswith("O2_EXECUTABLE_DECISION_WITHOUT_CURRENT_OUR15")]
    assert hit and "S08_CAPTAIN_LOCK" in hit[0] and "S01_XI_LOCK" in hit[0] and "S19_EXECUTABLE_LOCK" in hit[0]


def test_o2_validator_allows_current_valid_and_clamped_states():
    from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery

    ok = validate_deep_decision_content_delivery(_report("CURRENT_VALID"), "")
    assert not [f for f in ok if f.startswith("O2_")]
    clamped = validate_deep_decision_content_delivery(
        _report("PREVIOUS_GW_IDENTITY_FALLBACK", s08="PREPARE", xi="PREPARE", cap="PREPARE", s19="PROVISIONAL_PRIORITY"), ""
    )
    assert not [f for f in clamped if f.startswith("O2_")]
