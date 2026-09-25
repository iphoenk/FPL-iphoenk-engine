from __future__ import annotations

import json
from pathlib import Path

from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery

FIXTURE = Path(__file__).parent / "fixtures/v12_semantic/run_36126675342_sanitized.json"


def _fixture_report() -> dict:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["source_run_id"] == 36126675342
    assert payload["source_artifact"] == "v12-report-DEEP-36126675342"
    return {"sections": payload["sections"]}


def test_real_36126675342_fixture_proves_old_human_pass_was_semantically_false():
    failures = validate_deep_decision_content_delivery(_fixture_report(), "")
    expected = {
        "S06_SCORE_SEMANTICS_MISSING",
        "S14_EXECUTION_ECONOMICS_AUTHORITY_MISSING=1:426->52",
        "S14B_FT_AUTHORITY_MISSING",
        "S17_AUTH_AUTHORITY_MISSING",
    }
    assert expected.issubset(set(failures))


def test_complete_s17_missing_authority_fails_closed():
    report = _fixture_report()
    failures = validate_deep_decision_content_delivery(report, "")
    assert "S17_AUTH_AUTHORITY_MISSING" in failures


def test_rank20_real_fixture_preserves_terminal_date_state():
    report = _fixture_report()
    failures = validate_deep_decision_content_delivery(report, "")
    assert not [x for x in failures if x.startswith("S12_TERMINAL_DATE_STATE_MISSING")]
    assert not [x for x in failures if x.startswith("S13_TERMINAL_DATE_STATE_MISSING")]


def test_repaired_authority_fields_close_stage_a_false_pass_classes():
    report = _fixture_report()
    sections = {row["section_id"]: row for row in report["sections"]}

    sections["S06"]["content"]["score_semantics"] = {
        "lineup_score.xpts_mean": "XI_BASE_XPTS",
        "lineup_score.robust": "LINEUP_ROUTE_UTILITY",
        "formation_comparison[].expected_fpl_points_with_captain_vice": "CAPTAIN_ADJUSTED_XPTS",
        "formation_comparison[].route_utility": "LINEUP_ROUTE_UTILITY",
    }
    sections["S14B"]["content"]["ft_authority"] = {
        "free_transfers": None,
        "status": "NOT_SUPPORTED",
        "known": False,
    }
    sections["S14B"]["content"]["staging_rows"][0]["planned_move"] = "NO TRANSFER NOW"
    sections["S14B"]["content"]["staging_rows"][1]["planned_move"] = (
        "REOPTIMIZE FULL FRONTIER / FT STATE UNAVAILABLE"
    )
    sections["S14B"]["content"]["ft_saving_plan"] = "FT STATE UNAVAILABLE"
    sections["S14B"]["content"]["order_of_transfers"] = "NO TRANSFER NOW"

    challenger = sections["S14"]["content"]["package_routes"][1]
    challenger["execution_economics_status"] = "DEGRADED"
    challenger["executable"] = False

    sections["S17"]["content"]["authority"] = {
        "personal_auth_state": "AUTH_EXPIRED",
        "personal_resolution_status": "CURRENT_VALID",
        "finance_allowed": False,
    }
    sections["S17"]["content"]["source_health"]["authenticated_personal_scope"] = "AUTH_EXPIRED"

    failures = validate_deep_decision_content_delivery(report, "")
    assert "S06_SCORE_SEMANTICS_MISSING" not in failures
    assert "S14B_FT_AUTHORITY_MISSING" not in failures
    assert "S14B_FT_CLAIM_WITHOUT_AUTHORITY" not in failures
    assert not [x for x in failures if x.startswith("S14_EXECUTION_ECONOMICS_AUTHORITY_MISSING")]
    assert not [x for x in failures if x.startswith("S14_EXECUTABLE_WITHOUT_FINANCE")]
    assert "S17_AUTH_AUTHORITY_MISSING" not in failures
    assert not [x for x in failures if x.startswith("S17_AUTH_CONTRADICTION")]
