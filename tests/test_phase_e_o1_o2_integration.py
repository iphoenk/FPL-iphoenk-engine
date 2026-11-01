"""Phase E trial integration: O1 resolution feeding the O2 decision gate through
the real runner entry point (_personal_evidence_resolution)."""
from __future__ import annotations

import json
from pathlib import Path

from src.engines import v12_integrated_report_runner as runner
from src.engines.v12_decision_safety_gate import evaluate_decision_safety_gate
from tests.test_phase_e_o1_current15_resolution import (
    AJAYI, BARRY, EVA, FX, JOAO, META, NJ, RUNTIME, VANH, _utc, make_private_root,
)

BOOTSTRAP = {"elements": [{"id": k, "web_name": v["name"], "element_type": v["element_type"], "team": v["team"]} for k, v in META.items()]}


def _resolve(tmp_path: Path, key: str, *, archive: bool, transfers: bool):
    report = FX["reports"][key]
    root = make_private_root(tmp_path, runtime_utc=RUNTIME[key], archive=archive)
    rt = tmp_path / "rt"
    (rt / "data/v6/personal").mkdir(parents=True)
    if transfers:
        (rt / "data/v6/personal/entry_transfers.json").write_text(json.dumps(FX["transfers"]))
    return runner._personal_evidence_resolution(
        rt, None, planning_gw=9, private_data_root=root, allow_legacy_private_sources=False,
        report_slot=report["slot"], source_cutoff=_utc(report["cutoff"]), bootstrap=BOOTSTRAP,
    )


def _ids(res):
    return {int(r.get("element_id") or r.get("element")) for r in res["rows"]}


def test_integration_evidence_repaired_30_oct_is_correct_and_executable(tmp_path):
    res = _resolve(tmp_path, "20261030_123000", archive=True, transfers=True)
    assert res["resolution_status"] == "CURRENT_VALID"
    assert {EVA, NJ} <= _ids(res) and not ({BARRY, JOAO} & _ids(res)) and AJAYI in _ids(res) and VANH not in _ids(res)
    gate = evaluate_decision_safety_gate(res)
    assert gate["executable"] is True
    owned = runner._owned15(res, BOOTSTRAP)
    assert len(owned) == 15 and {r["name"] for r in owned} >= {"Evanilson", "N.Jackson"}


def test_integration_public_inferred_29_oct_correct_identity_but_not_executable(tmp_path):
    res = _resolve(tmp_path, "20261029_213000", archive=True, transfers=True)
    assert res["resolution_status"] == "PUBLIC_INFERRED"
    assert {EVA, NJ} <= _ids(res) and not ({BARRY, JOAO} & _ids(res))
    assert res["stale"] is True and res["finance_allowed"] is False
    gate = evaluate_decision_safety_gate(res)
    assert gate["executable"] is False and gate["max_state"] == "PREPARE"
    owned = runner._owned15(res, BOOTSTRAP)
    assert all(r["purchase_price"] is None and r["selling_price"] is None for r in owned)


def test_integration_evidence_still_unavailable_fails_closed_and_blocks_lock(tmp_path):
    res = _resolve(tmp_path, "20261030_123000", archive=False, transfers=False)
    assert res["resolution_status"] == "PREVIOUS_GW_IDENTITY_FALLBACK" and res["stale"] is True
    gate = evaluate_decision_safety_gate(res)
    assert gate["executable"] is False
    dash = runner._decision_dashboard(
        operational_action="WAIT", planning_gw=9, stage3_decision={}, lineup_state="COMPLETE",
        lineup={}, captain_surface={"decision_state": "LOCK"}, chip_available=True,
        price_radar={}, auth_state="AUTH_AVAILABLE", finance={}, our15_gate=gate,
    )
    assert dash["CAPTAIN"] != "LOCK" and dash["XI"] != "LOCK" and dash["DECISION_EXECUTABLE"] is False


def test_integration_official_source_cutoff_helper():
    assert runner._official_source_cutoff({"payload": {"checked_at": "2026-10-30T06:25:37.1+00:00"}}).isoformat().startswith("2026-10-30T06:25:37")
    assert runner._official_source_cutoff({"payload": {"checked_at": "2026-10-30T06:25:37"}}) is None
    assert runner._official_source_cutoff({}) is None


def test_integration_default_production_shape_no_transfer_feed_is_not_executable(tmp_path):
    # Archive readable, snapshot hours older than the cutoff, no transfer evidence:
    # identity is valid but unverifiable against transfers -> gate must block LOCK.
    res = _resolve(tmp_path, "20261030_123000", archive=True, transfers=False)
    assert res["resolution_status"] == "CURRENT_VALID"
    assert res["transfer_gap_check"] == "NOT_PERFORMED_NO_TRANSFER_EVIDENCE"
    gate = evaluate_decision_safety_gate(res)
    assert gate["executable"] is False and gate["reason_codes"] == ["OUR15_TRANSFER_GAP_UNCHECKED"]
    assert {EVA, NJ} <= _ids(res)


def test_integration_unparseable_cutoff_is_not_silently_legacy(tmp_path):
    report = FX["reports"]["20261030_123000"]
    root = make_private_root(tmp_path, runtime_utc=RUNTIME["20261030_123000"])
    res = runner._personal_evidence_resolution(
        tmp_path / "rt", None, planning_gw=9, private_data_root=root, allow_legacy_private_sources=False,
        report_slot=report["slot"], source_cutoff="UNPARSEABLE_SOURCE_CUTOFF", bootstrap=BOOTSTRAP,
    )
    assert res["resolution_status"] != "CURRENT_VALID"


def test_integration_cutoff_helper_distinguishes_absent_from_invalid():
    f = runner._official_source_cutoff_or_sentinel
    assert f({"payload": {}}) is None
    assert f({"payload": {"checked_at": "garbage"}}) == "UNPARSEABLE_SOURCE_CUTOFF"
    assert f({"payload": {"checked_at": "2026-10-30T06:25:38"}}) == "UNPARSEABLE_SOURCE_CUTOFF"
    assert f({"payload": {"checked_at": "2026-10-30T06:25:38Z"}}).isoformat().startswith("2026-10-30T06:25:38")
