from __future__ import annotations

import json
from pathlib import Path

from src.engines.v12_deep_delivery import validate_deep_decision_content_delivery
from src.engines.v12_integrated_report_runner import _lineup_content, _three_gw_staging
from src.engines.v12_report_orchestration import _price_source_freshness


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "v12_semantic_regression_36126675342.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _section(payload: dict, section_id: str) -> dict:
    return next(
        row
        for row in payload["report"]["sections"]
        if row["section_id"] == section_id
    )


def test_regression_fixture_is_sanitized_slice_of_real_occurrence_36126675342():
    payload = _fixture()
    provenance = payload["_fixture_provenance"]
    assert provenance["source_run_id"] == 36126675342
    assert provenance["source_artifact"] == "v12-report-DEEP-36126675342"
    assert provenance["source_head_sha"] == "f1402818519237d3628184e298bd58c0240983bb"
    assert provenance["sanitized"] is True


def test_real_occurrence_36126675342_fails_new_semantic_barrier():
    payload = _fixture()
    failures = validate_deep_decision_content_delivery(payload["report"], "")

    expected = {
        "S17_AUTH_AUTHORITY_MISSING",
        "S17_PRIVATE_AUTH_STATE_MISSING",
        "S14B_FT_AUTHORITY_MISSING",
        "S14B_FT_STATUS_MISSING",
        "S14B_FT_CLAIM_WITHOUT_AUTHORITY",
        "S14_EXECUTION_ECONOMICS_AUTHORITY_MISSING",
        "S14_EXECUTION_ECONOMICS_STATUS_MISSING",
        "S14_ROUTE_EXECUTION_STATE_MISSING=1:426->52",
        "S06_SCORE_SEMANTICS_AUTHORITY_MISSING",
        "S06_SCORE_VALUES_MISSING",
        "S10_PRICE_FRESHNESS_AUTHORITY_MISSING=1",
        "S12_PRICE_FRESHNESS_AUTHORITY_MISSING=1",
        "S13_PRICE_FRESHNESS_AUTHORITY_MISSING=1",
    }
    assert expected.issubset(set(failures))

    # ETA/date-state itself was already present in the source occurrence and
    # must not be falsely reported missing.
    assert not any("TERMINAL_DATE_STATE_MISSING" in row for row in failures)


def test_real_occurrence_exposes_auth_false_pass_evidence():
    payload = _fixture()
    s17 = _section(payload, "S17")["content"]
    assert payload["bound_authority"]["v6_private_auth_state"] == "AUTH_EXPIRED"
    assert s17["source_health"]["authenticated_personal_scope"] == "HEALTHY"


def test_lineup_producer_labels_the_two_real_361266_score_surfaces():
    payload = _fixture()
    old = _section(payload, "S06")["content"]
    lineup = {
        "formation": old["formation_comparison"][0]["formation"],
        "starting_xi": [],
        "bench": {"gk": None, "order": []},
        "captain": None,
        "vice_captain": None,
        "lineup_score": old["lineup_score"],
        "formation_comparison": old["formation_comparison"],
    }
    got = _lineup_content(lineup)
    assert got["xi_base_xpts"] == 49.777897
    assert got["captain_adjusted_xpts"] == 55.012527
    assert got["score_semantics"]["authority"] == "P1_7_LINEUP"
    assert got["score_semantics"]["relationship"] == "DISTINCT_BY_DESIGN"


def test_unknown_ft_from_real_occurrence_cannot_render_save_or_roll_ft():
    payload = _fixture()
    old_s14 = _section(payload, "S14")["content"]
    old_s14b = _section(payload, "S14B")["content"]
    budget = old_s14b["budget_dependency"]
    got = _three_gw_staging(
        planning_gw=6,
        action="WAIT",
        stage3_decision={"selected_route_id": "HOLD", "reason": "fixture-regression"},
        stage3_visible={"package_routes": old_s14["package_routes"]},
        all15_rows=[],
        lineup=None,
        finance={
            "bank": budget["bank"],
            "bank_status": budget["bank_status"],
            "sell_value_status": budget["sell_value_status"],
            "free_transfers": None,
            "free_transfers_status": "NOT_SUPPORTED",
            "personal_evidence_source": "fixture:36126675342",
            "personal_evidence_observed_at": payload["_fixture_provenance"]["report_slot"],
        },
    )
    assert got["ft_authority"]["known"] is False
    assert got["ft_saving_plan"] == "FT STATE UNAVAILABLE"
    assert "SAVE FT" not in str(got).upper()
    assert "ROLL FT" not in str(got).upper()


def test_price_freshness_uses_real_occurrence_evidence_timestamp():
    payload = _fixture()
    s10 = _section(payload, "S10")["content"]
    evidence_timestamp = s10["rows"][0]["evidence_timestamp"]
    got = _price_source_freshness(
        evidence_timestamp,
        payload["_fixture_provenance"]["report_slot"],
        "GREEN",
    )
    assert got["freshness"] == "FRESH"
    assert got["source_age_minutes"] is not None
    assert 495.0 < got["source_age_minutes"] < 497.0
