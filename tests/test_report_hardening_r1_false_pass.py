from __future__ import annotations

import json
from pathlib import Path

from src.runtime_v6.report_compute import build_report_compute_contract


_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "report_false_pass_2026-09-16T172951+0700.json"
)


def _load_incident() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _our15() -> list[dict]:
    rows: list[dict] = []
    for player_id in (1, 2):
        rows.append({"element_id": player_id, "position": "GK"})
    for player_id in range(3, 8):
        rows.append({"element_id": player_id, "position": "DEF"})
    for player_id in range(8, 13):
        rows.append({"element_id": player_id, "position": "MID"})
    for player_id in range(13, 16):
        rows.append({"element_id": player_id, "position": "FWD"})
    return rows


def _watchlist20() -> list[dict]:
    rows: list[dict] = []
    start = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for offset in range(5):
            rows.append({"element_id": start + offset, "position": position})
        start += 10
    return rows


def _compute_kwargs(incident: dict) -> dict:
    return {
        "scope_matrix_report_ready": True,
        "our15_rows": _our15(),
        "starting_xi_ids": [1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        "bench_ids": [2, 7, 12, 15],
        "watchlist_rows": _watchlist20(),
        "rise_rows": incident["rise20"],
        "fall_rows": incident["fall20"],
        "facts": {
            "fixture_fact": {"source": "R1_GOLDEN_FIXTURE", "value": True},
        },
        "models": {
            "fixture_model": {"model": "R1_GOLDEN_FIXTURE", "value": 1.0},
        },
    }


def test_r1_fixture_preserves_the_observed_false_pass_contradiction():
    incident = _load_incident()
    markers = incident["observed_markers"]

    assert incident["fixture_kind"] == "golden_failing_incident_reconstruction"
    assert incident["fidelity"]["structural_defect_preserved"] is True
    assert incident["fidelity"]["exact_visible_report_body_available"] is False
    assert markers["VISIBLE_EMITTED"] is True
    assert markers["REPORT_CONTRACT_PASS"] is False
    assert markers["REPORT_CONTRACT_STATUS"] == "FAIL"
    assert markers["REPORT_INCOMPLETE_SECTIONS"] == ["RISE20", "FALL20"]
    assert markers["SURFACED_RUN_COMPLETE_STATUS"] == "PASS"


def test_r1_golden_fixture_must_fail_compute_when_rank20_rows_have_no_eta():
    """Golden RED test for the 17:29 false-PASS defect.

    R1 intentionally changes no production code. The incident had 20 visible rows in
    each price list, but the rows were structurally incomplete. ETA is the minimum
    missing field used by this R1 proof; the complete row schema belongs to R2.

    Current production behavior incorrectly returns PASS because validate_rank20 only
    checks count and identity. This test MUST stay red until the defect is fixed in a
    later wave.
    """
    incident = _load_incident()
    required_field = incident["r1_required_field_for_defect_proof"]
    rank_rows = [*incident["rise20"], *incident["fall20"]]

    assert required_field == "eta"
    assert len(incident["rise20"]) == 20
    assert len(incident["fall20"]) == 20
    assert all(required_field not in row for row in rank_rows)

    result = build_report_compute_contract(**_compute_kwargs(incident))

    assert result["status"] == "FAIL", (
        "R1 defect reproduced: count-only RISE20/FALL20 validation accepted 20 "
        "structurally incomplete rows and surfaced compute PASS."
    )
    assert result["compute_ready"] is False
    assert result["RISE20"]["status"] == "FAIL"
    assert result["FALL20"]["status"] == "FAIL"
