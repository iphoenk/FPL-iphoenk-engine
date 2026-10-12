"""Regression: one canonical S08 captain/vice for final S06 pitch badges.

P1.7 formation-frontier score provenance is retained rather than silently
recomputed when the vice-captain decision differs from the optimizer route.
"""
from pathlib import Path

import pytest

from src.engines.v12_report_orchestration import (
    ReportOrchestrationError,
    materialize_deep_report,
)

CANONICAL = (
    Path(__file__).resolve().parents[1]
    / "control/fpl_master_v12/FPL_MASTER_CANONICAL_V12.txt"
)


def _build(vice_id=2):
    return materialize_deep_report(
        canonical_text=CANONICAL.read_text(encoding="utf-8"),
        section_payloads={
            "S06": {
                "state": "COMPLETE",
                "content": {
                    "formation": "5-3-2",
                    "starting_xi": [
                        {"element": 1, "name": "Captain"},
                        {"element": 2, "name": "Canonical VC"},
                        {"element": 3, "name": "Optimizer VC"},
                    ],
                    "captain": {"element_id": 1},
                    "vice_captain": {"element_id": 3},
                    "captain_adjusted_xpts": 53.46,
                    "xi_base_xpts": 47.35,
                },
            },
            "S08": {
                "state": "COMPLETE",
                "content": {
                    "decision_state": "LOCK",
                    "captain": {"element_id": 1, "player": "Captain"},
                    "vice_captain": {"element_id": vice_id, "player": "Canonical VC"},
                },
            },
        },
    )


def test_s06_pitch_uses_s08_canonical_vice_with_provenance():
    report = _build()
    s06 = next(s for s in report["sections"] if s["section_id"] == "S06")["content"]
    assert s06["vice_captain"]["element_id"] == 2
    assert s06["canonical_cvc_binding"]["source_section"] == "S08"
    assert s06["lineup_frontier_cvc"]["vice_captain"]["element_id"] == 3
    assert s06["captain_adjusted_xpts"] == 53.46
    assert s06["captain_adjusted_projection_scope"] == (
        "P1_7_FRONTIER_SCORE_NOT_S08_FINAL_CVC_RECOMPUTE"
    )


def test_canonical_vice_outside_xi_fails_closed():
    with pytest.raises(ReportOrchestrationError, match="cannot be bound"):
        _build(vice_id=99)
