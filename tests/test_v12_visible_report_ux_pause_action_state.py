from __future__ import annotations

import json
from pathlib import Path

from src.engines.canonical_decision_methodology import ACTION_STATES
from src.engines.visible_content_proof import canonical_mode_contract
from src.runtime_v6.domains.report_plane.report_qa import (
    _validate_operational_action_labels,
)


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
STATE = ROOT / "control/fpl_master_v12/FPL_MASTER_STATE_V12.json"


def _canonical() -> str:
    return CANONICAL.read_text(encoding="utf-8")


def _state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8"))


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def test_global_visible_presentation_contract_is_decision_first_and_compact():
    text = _canonical()
    assert "GLOBAL VISIBLE PRESENTATION CONTRACT — ALL VISIBLE MODES" in text
    assert "A. DECISION-FIRST" in text
    assert "B. POINTER / TABLE FIRST" in text
    assert "C. STANDARD SEMANTIC FLOW" in text
    assert "D. ACTION BOARD" in text
    assert "E. FACT / MODEL / INFERENCE / RUMOR" in text
    assert "F. COMPACT ENGINE / DATA STATUS" in text
    for field in (
        "V6 core:",
        "Publication:",
        "Universe authority:",
        "Personal auth:",
        "Model snapshot:",
        "MC:",
        "ICON+:",
        "Data timestamp:",
    ):
        assert field in text


def test_global_presentation_layer_does_not_change_deep_exact_structure():
    contract = canonical_mode_contract(_canonical(), "DEEP")
    assert len(contract["expected_section_ids"]) == 20
    assert contract["expected_visible_order"][0] == "Decision/status"
    assert contract["expected_visible_order"][-1] == "Final judgement"


def test_operational_action_enum_is_exact_and_aliases_are_rejected():
    assert ACTION_STATES == frozenset({"WAIT", "PREPARE", "ACT"})
    for label in ("ACT-CANDIDATE", "NEAR-ACT", "STRONG-ACT-CANDIDATE", "MONITOR"):
        assert label not in ACTION_STATES

    text = _canonical()
    assert "Operational action enum is EXACTLY WAIT / PREPARE / ACT." in text
    assert "Price movement alone cannot convert PREPARE to ACT." in text

    for label in ("ACT-CANDIDATE", "NEAR-ACT", "STRONG-ACT-CANDIDATE"):
        failures = _validate_operational_action_labels(f"Operational state: {label}")
        assert f"PROHIBITED_OPERATIONAL_ACTION={label}" in failures

    assert _validate_operational_action_labels(
        "Operational state: MONITOR"
    ) == ["PROHIBITED_OPERATIONAL_ACTION=MONITOR"]
    assert _validate_operational_action_labels(
        "Football note: monitor injury news; operational state: PREPARE"
    ) == []


def test_observation_without_execution_cannot_claim_model_recomputation():
    text = _canonical()
    assert "An observed match event cannot be described as a changed Bayesian posterior, xMins or P(start) unless exact recomputation/execution evidence exists." in text
    assert "A strong post-match observation without the required fresh full-universe/model/economics execution normally remains PREPARE." in text


def test_scheduler_pause_semantics_preserve_history_and_post_resume_acceptance():
    text = _canonical()
    for state in (
        "ACTIVE_FULFILLED",
        "ACTIVE_MISSED",
        "INTENTIONALLY_PAUSED",
        "HISTORICAL_UNKNOWN",
    ):
        assert state in text
    assert "HISTORICAL GAP / USER-PAUSE CONTEXT KNOWN" in text
    assert "Current scheduler acceptance is evaluated from post-resume natural continuity." in text
    assert "Never rewrite factual history, fabricate fulfillment, reset counters merely to make health GREEN" in text
    assert "Do not backfill intentionally paused historical slots." in text


def test_temporary_sangare_gross_special_watch_is_not_active_authority_or_state():
    canonical = _canonical()
    assert "Temporary Sangaré -> Groß" not in canonical
    assert "TEMPORARY PRICE-RISK WATCH — SANGARÉ -> PASCAL GROSS" not in canonical.upper()

    values = list(_strings(_state()))
    assert not any("GROSS" in value.upper() or "GROß" in value.upper() for value in values)


def test_state_remains_context_not_presentation_authority_and_has_no_stale_action_alias():
    state_text = STATE.read_text(encoding="utf-8")
    assert "GLOBAL VISIBLE PRESENTATION CONTRACT" not in state_text
    assert "ENGINE / DATA STATUS" not in state_text

    aliases = {"ACT-CANDIDATE", "NEAR-ACT", "STRONG-ACT-CANDIDATE"}
    values = {value.upper() for value in _strings(_state())}
    assert aliases.isdisjoint(values)
