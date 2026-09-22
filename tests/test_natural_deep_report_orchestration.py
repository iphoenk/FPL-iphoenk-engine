from __future__ import annotations

from pathlib import Path

import pytest

from src.engines.price_radar import MODEL_THRESHOLD
from src.engines.visible_content_proof import canonical_mode_contract
from src.runtime_v6.domains.report_plane.delivery_integrity import (
    DEEP_MANDATORY_SECTIONS,
    FINAL_MANDATORY_SECTIONS,
    MATCH_MANDATORY_SECTIONS,
    POST_ALL_MATCH_MANDATORY_SECTIONS,
    PRICE_MANDATORY_SECTIONS,
)
from src.runtime_v6.domains.report_plane.visible_body_contract import _parse_sections
from src.engines.v12_report_orchestration import (
    ReportOrchestrationError,
    analytic_execution_truth,
    build_actionable_price_radar,
    build_icon_subscopes,
    build_price20,
    build_signal_delta,
    build_visible_mathematical_decision_stack,
    build_watchlist20,
    compact_engine_data_status,
    materialize_all15,
    materialize_deep_report,
    materialize_natural_post_match_report,
    render_deep_text,
    render_natural_post_match_text,
    validate_human_facing_body,
    weather_report_time_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "control" / "fpl_master_v12" / "FPL_MASTER_CANONICAL_V12.txt"


def _universe():
    rows = []
    element = 100
    for position in ("GK", "DEF", "MID", "FWD"):
        for index in range(8):
            rows.append(
                {
                    "element_id": element,
                    "name": f"{position}-{index}",
                    "position": position,
                    "eligible": True,
                    "canonical_evaluation_complete": True,
                    "canonical_rank": index + 1,
                    "football_score": 80 - index,
                }
            )
            element += 1
    return rows


def _owned15():
    rows = []
    element = 1
    for position, count in (("GK", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for index in range(count):
            rows.append(
                {
                    "element_id": element,
                    "name": f"Owned-{position}-{index}",
                    "position": position,
                    "current_price": 5.0 + index / 10,
                }
            )
            element += 1
    return rows


def _predictor():
    rows = []
    for i in range(25):
        rows.append(
            {
                "element_id": 500 + i,
                "name": f"Rise-{i}",
                "direction": "RISE",
                "rank": i + 1,
            }
        )
        rows.append(
            {
                "element_id": 700 + i,
                "name": f"Fall-{i}",
                "direction": "FALL",
                "rank": i + 1,
            }
        )
    return {"health": "GREEN", "rows": rows}


def test_repository_python_false_does_not_suppress_chatgpt_v12_analytics():
    result = analytic_execution_truth(
        repository_python_qa_executed=False,
        repository_python_execution_evidence=None,
        valid_current_inputs=True,
        chatgpt_v12_analytic_executed=True,
        analytic_outputs={"our15": 15, "watchlist20": 20},
        model_timestamp="2026-09-20T12:30:00+07:00",
    )
    assert result["repository_python"]["executed"] is False
    assert result["chatgpt_v12_analytics"]["executed"] is True
    assert result["chatgpt_v12_analytics"]["model_refresh"] == "CURRENT"
    assert result["repository_python_nonexecution_suppresses_v12_analytics"] is False


def test_repository_python_execution_cannot_be_falsely_claimed():
    with pytest.raises(ReportOrchestrationError, match="requires exact"):
        analytic_execution_truth(
            repository_python_qa_executed=True,
            repository_python_execution_evidence=None,
            valid_current_inputs=True,
            chatgpt_v12_analytic_executed=False,
            analytic_outputs=None,
        )


def test_chatgpt_analytics_need_valid_inputs_and_real_outputs():
    with pytest.raises(ReportOrchestrationError, match="valid current"):
        analytic_execution_truth(
            repository_python_qa_executed=False,
            repository_python_execution_evidence=None,
            valid_current_inputs=False,
            chatgpt_v12_analytic_executed=True,
            analytic_outputs={"fake": True},
        )
    with pytest.raises(ReportOrchestrationError, match="outputs"):
        analytic_execution_truth(
            repository_python_qa_executed=False,
            repository_python_execution_evidence=None,
            valid_current_inputs=True,
            chatgpt_v12_analytic_executed=True,
            analytic_outputs={},
        )


def test_watchlist_full_universe_produces_exact_5_5_5_5_not_zero():
    result = build_watchlist20(
        evaluated_universe=_universe(),
        owned_element_ids=list(range(1, 16)),
        universe_authority="FULL",
    )
    assert result["state"] == "COMPLETE"
    assert result["available_count"] == 20
    assert result["position_counts"] == {"GK": 5, "DEF": 5, "MID": 5, "FWD": 5}


def test_watchlist_partial_degrades_at_field_level_instead_of_blank_collapse():
    rows = [row for row in _universe() if not (row["position"] == "GK" and row["canonical_rank"] > 3)]
    result = build_watchlist20(
        evaluated_universe=rows,
        owned_element_ids=[],
        universe_authority="PARTIAL",
    )
    assert result["state"] == "DEGRADED"
    assert result["available_count"] > 0
    assert result["available_count"] < 20
    assert "missing" in result["degradation_reason"]


def test_rise20_and_fall20_use_current_existing_predictor_exact20():
    rise = build_price20(predictor_artifact=_predictor(), direction="RISE")
    fall = build_price20(predictor_artifact=_predictor(), direction="FALL")
    assert rise["state"] == "COMPLETE"
    assert rise["available_count"] == 20
    assert fall["state"] == "COMPLETE"
    assert fall["available_count"] == 20
    assert rise["new_price_predictor_created"] is False
    assert fall["new_price_predictor_created"] is False


def test_zero_price_rows_require_concrete_unavailable_reason():
    rise = build_price20(
        predictor_artifact={"health": "GREEN", "rows": []},
        direction="RISE",
    )
    assert rise["state"] == "UNAVAILABLE"
    assert rise["available_count"] == 0
    assert "rows=0/20" in rise["degradation_reason"]


def test_actionable_price_radar_keeps_all15_price_facts_even_without_predictor():
    result = build_actionable_price_radar(owned15=_owned15(), predictor_artifact=None)
    assert result["state"] == "COMPLETE"
    assert result["available_count"] == 15
    assert len(result["rows"]) == 15
    assert all(row["price_fact"] == "FACT" for row in result["rows"])
    assert all(row["predictor_direction"] == "UNAVAILABLE" for row in result["rows"])


def test_icon_submitted_picks_survive_standings_failure():
    picks = [{"manager_id": i, "players": [1, 2, 3]} for i in range(1, 6)]
    result = build_icon_subscopes(
        submitted_picks=picks,
        submitted_denominator=5,
        standings=None,
        standings_denominator=5,
        eo_rows=None,
    )
    assert result["submitted_picks_exposure"]["state"] == "COMPLETE"
    assert result["live_standings_rank"]["state"] == "UNAVAILABLE"
    assert result["eo"]["state"] == "UNAVAILABLE"
    assert result["subscopes_fail_operational_independently"] is True


def test_partial_icon_coverage_never_masquerades_as_full_denominator():
    picks = [{"manager_id": i} for i in range(1, 4)]
    result = build_icon_subscopes(
        submitted_picks=picks,
        submitted_denominator=5,
        standings=None,
        standings_denominator=5,
    )
    assert result["submitted_picks_exposure"]["state"] == "PARTIAL"
    assert result["submitted_picks_exposure"]["available_count"] == 3
    assert result["submitted_picks_exposure"]["expected_count"] == 5


def test_all15_preserves_exact_owned_identities_when_model_fields_missing():
    result = materialize_all15(owned15=_owned15(), model_rows=[])
    assert result["state"] == "COMPLETE"
    assert result["available_count"] == 15
    assert len({row["element_id"] for row in result["rows"]}) == 15
    assert result["identity_complete"] is True
    assert result["model_complete"] is False
    assert all(row["p_start"] == "UNAVAILABLE" for row in result["rows"])


def test_1230_signal_delta_exists_and_baseline_unavailable_is_explicit():
    result = build_signal_delta(
        baseline_0430=None,
        current_1230={"p_start": 0.82, "xmins": 71},
    )
    assert result["status"] == "BASELINE UNAVAILABLE"
    assert {row["signal"] for row in result["rows"]} >= {"p_start", "xmins", "weather", "decision_route"}


def test_deep_materializer_renders_every_canonical_block_in_exact_order():
    canonical = CANONICAL.read_text(encoding="utf-8")
    report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads={},
        checkpoint_time="12:30",
        signal_delta={"status": "BASELINE UNAVAILABLE", "rows": []},
    )
    assert report["numbered_headings"] == 19
    assert report["rendered_blocks_including_15B"] == 23
    assert report["rendered_blocks_including_suffix_sections"] == 23
    assert report["exact_canonical_order"] is True
    assert len(report["sections"]) == 23
    assert report["sections"][0]["label"] == "DECISION / CURRENT STATUS"
    assert report["sections"][-1]["label"] == "FINAL JUDGEMENT"
    assert all(row["state"] == "UNAVAILABLE" for row in report["sections"])


def test_deep_decision_delta_contains_1230_signal_delta():
    canonical = CANONICAL.read_text(encoding="utf-8")
    report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads={
            "S03": {
                "state": "COMPLETE",
                "content": {"decision_delta": "NO MATERIAL DECISION CHANGE"},
            }
        },
        checkpoint_time="12:30",
        signal_delta={"status": "AVAILABLE", "rows": [{"signal": "price"}]},
    )
    decision_delta = next(row for row in report["sections"] if row["section_id"] == "S03")
    assert decision_delta["content"]["signal_delta_since_0430"]["status"] == "AVAILABLE"


def test_locked_gw_sections_remain_visible_after_deadline():
    canonical = CANONICAL.read_text(encoding="utf-8")
    report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads={},
        current_gw_locked=True,
        locked_state={
            "formation": "3-5-2",
            "xi": list(range(1, 12)),
            "bench": list(range(12, 16)),
            "captain": 1,
            "vice_captain": 2,
            "chip": "NONE",
        },
    )
    by_id = {row["section_id"]: row for row in report["sections"]}
    assert by_id["S06"]["state"] == "COMPLETE"
    assert "LOCKED" in by_id["S06"]["content"]["status"]
    assert by_id["S07"]["state"] == "COMPLETE"
    assert by_id["S08"]["state"] == "COMPLETE"
    assert by_id["S09"]["state"] == "COMPLETE"


def test_human_facing_body_rejects_low_level_machine_plumbing_when_healthy():
    body = (
        "Decision: WAIT\n"
        "issue #431 mutation/readback passed\n"
        "NATURAL_CORE_UPKEEP_GATE complete\n"
        "authoritative_runtime_snapshot=true"
    )
    failures = validate_human_facing_body(body, material_technical_failure=False)
    assert any("issue #431" in item for item in failures)
    assert any("natural_core_upkeep_gate" in item for item in failures)
    assert any("authoritative_runtime_snapshot" in item for item in failures)


def test_healthy_deep_render_contains_no_raw_run_ids_or_issue_narration():
    canonical = CANONICAL.read_text(encoding="utf-8")
    report = materialize_deep_report(canonical_text=canonical, section_payloads={})
    body = render_deep_text(report)
    assert validate_human_facing_body(body) == []
    assert "issue #431" not in body.lower()
    assert "workflow run" not in body.lower()


def test_compact_engine_status_stays_human_facing():
    status = compact_engine_data_status(
        v6_data="GREEN",
        publication="PASS",
        universe="FULL",
        personal_squad_data="AVAILABLE",
        model_refresh="CURRENT",
        mc="NOT RUN",
        icon="PARTIAL",
        data_time="2026-09-20T12:30:00+07:00",
    )
    assert set(status) == {
        "V6 data",
        "Publication",
        "Universe",
        "Personal squad data",
        "Model refresh",
        "MC",
        "ICON+",
        "Data time",
    }


def test_weather_is_report_time_evidence_not_v6_dependency():
    available = weather_report_time_evidence(
        venue="Verified Venue",
        kickoff="2026-09-26T15:00:00+01:00",
        weather={
            "fixture": "AAA-BBB",
            "condition": "Cloudy",
            "temperature_c": 18,
            "precipitation_chance_pct": 20,
            "wind_kmh": 15,
            "fpl_impact": "NORMAL",
            "weather_evidence_timestamp": "2026-09-20T10:30:00+00:00",
        },
        fixture="AAA-BBB",
        lookup_accessible=True,
    )
    assert available["state"] == "COMPLETE"
    assert available["source_layer"] == "REPORT_TIME"
    assert available["v6_weather_required"] is False

    missing = weather_report_time_evidence(
        venue="Verified Venue",
        kickoff="2026-09-26T15:00:00+01:00",
        weather=None,
        lookup_accessible=False,
    )
    assert missing["state"] == "UNAVAILABLE"
    assert "V6" not in missing["degradation_reason"]


def test_canonical_contains_new_analytic_execution_and_anti_blanking_semantics():
    text = CANONICAL.read_text(encoding="utf-8")
    assert "GENERIC PLAYER-vs-PLAYER COMPARATOR ORCHESTRATION" in text
    assert "REPOSITORY PYTHON EXECUTION TRUTH and CHATGPT V12 ANALYTIC EXECUTION TRUTH are separate" in text
    assert "repository_python_qa_executed=false alone can never justify Watchlist20=0/20" in text
    assert "official_price_predictor artifact" in text
    assert "A valid NO_CROSSING row is healthy evidence, not degradation." in text
    assert "unrelated core, repository-Python, workflow, QA, or plumbing status must not downgrade" in text
    assert "AD_HOC MODE-EQUIVALENCE IS MANDATORY." in text
    assert "Manual/chat composition MUST NOT bypass visible-body QA" in text
    assert "Weather is REPORT-TIME evidence and does not belong in V6" in text


def test_optional_provider_failure_does_not_force_whole_report_collapse():
    canonical = CANONICAL.read_text(encoding="utf-8")
    sections = {
        "S11": {
            "state": "COMPLETE",
            "available_count": 20,
            "expected_count": 20,
            "content": {"watchlist": list(range(20))},
        },
        "S15B": {
            "state": "DEGRADED",
            "available_count": 5,
            "expected_count": 8,
            "degradation_reason": "standings unavailable; submitted picks current",
            "content": {"submitted_picks": "COMPLETE", "standings": "UNAVAILABLE"},
        },
    }
    report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads=sections,
    )
    by_id = {row["section_id"]: row for row in report["sections"]}
    assert by_id["S11"]["state"] == "COMPLETE"
    assert by_id["S15B"]["state"] == "DEGRADED"


def _real_price_predictor():
    players = []
    for index in range(30):
        projected = round(-75.0 + index * 5.0, 2)
        players.append(
            {
                "id": 900 + index,
                "web_name": f"Real-{index}",
                "team": (index % 20) + 1,
                "element_type": (index % 4) + 1,
                "now_cost": 45 + index,
                "selected_by_percent": str(round(1.0 + index / 10, 1)),
                "transfers_in_event": 1000 + index,
                "transfers_out_event": 500 + index,
                "price_change_percent": round(projected / 2.0, 2),
                "price_change_hourly_rate": round(projected / 24.0, 4),
                "price_change_projections": [
                    {"offset": 0, "projected_percent": projected, "likelihood": "MEDIUM"},
                    {"offset": 1, "projected_percent": projected + 10.0, "likelihood": "LOW"},
                ],
                "price_change_locked_until": None,
                "price_change_calibrating": False,
            }
        )
    return {
        "health": "GREEN",
        "checked_at": "2026-09-20T10:28:23.609531+00:00",
        "data": {"players": players},
    }


def test_real_price_artifact_data_players_produces_exact20_with_visible_direction_contract():
    artifact = _real_price_predictor()
    rise = build_price20(predictor_artifact=artifact, direction="RISE")
    fall = build_price20(predictor_artifact=artifact, direction="FALL")
    assert rise["state"] == "COMPLETE"
    assert fall["state"] == "COMPLETE"
    assert rise["degradation_reason"] is None
    assert fall["degradation_reason"] is None
    assert rise["no_crossing_count"] > 0
    assert fall["no_crossing_count"] > 0
    assert rise["available_count"] == 20
    assert fall["available_count"] == 20
    assert rise["artifact_adapter"] == "V6_DATA_PLAYERS_OFFSET0"
    assert fall["artifact_adapter"] == "V6_DATA_PLAYERS_OFFSET0"
    assert rise["sort_contract"] == "projected_percent DESC, id ASC"
    assert fall["sort_contract"] == "projected_percent ASC, id ASC"
    assert all(row["date_state"] in {"EXPECTED_CHANGE_DATE", "NO_CROSSING_WITHIN_GOVERNED_HORIZON"} for row in rise["rows"] + fall["rows"])
    assert all(row["price_fact"] == "FACT" for row in rise["rows"] + fall["rows"])
    assert all(row["predictor_classification"] == "MODEL" for row in rise["rows"] + fall["rows"])
    assert all(row["direction"] in {"RISE", "FALL", "NEUTRAL"} for row in rise["rows"] + fall["rows"])
    assert all("rank" not in row for row in rise["rows"] + fall["rows"])
    assert all("next_official_price_cycle_uk" in row for row in rise["rows"] + fall["rows"])
    assert all("next_official_price_cycle_wib" in row for row in rise["rows"] + fall["rows"])


def test_real_price_artifact_with_failed_source_health_still_degrades_truthfully():
    artifact = _real_price_predictor()
    artifact["health"] = "FAIL"
    rise = build_price20(predictor_artifact=artifact, direction="RISE")
    assert rise["state"] == "DEGRADED"
    assert rise["available_count"] == 20
    assert "health=FAIL" in rise["degradation_reason"]


def test_real_price_artifact_offset_zero_is_required_not_substituted():
    artifact = _real_price_predictor()
    for row in artifact["data"]["players"][:15]:
        row["price_change_projections"] = [
            {"offset": 1, "projected_percent": 99.0, "likelihood": "HIGH"}
        ]
    rise = build_price20(predictor_artifact=artifact, direction="RISE")
    assert rise["state"] == "DEGRADED"
    assert rise["available_count"] == 15
    assert rise["usable_eligible_rows"] == 15
    assert "offset-0" in rise["degradation_reason"]


def test_real_price_sort_tie_uses_lower_element_id_for_rise_and_fall():
    artifact = _real_price_predictor()
    rows = artifact["data"]["players"]
    # Make all rows neutral then create top/bottom ties with reversed input IDs.
    for row in rows:
        row["price_change_projections"][0]["projected_percent"] = 0.0
    rows[0]["id"] = 1202
    rows[1]["id"] = 1201
    rows[0]["price_change_projections"][0]["projected_percent"] = 80.0
    rows[1]["price_change_projections"][0]["projected_percent"] = 80.0
    rows[2]["id"] = 1102
    rows[3]["id"] = 1101
    rows[2]["price_change_projections"][0]["projected_percent"] = -80.0
    rows[3]["price_change_projections"][0]["projected_percent"] = -80.0

    rise = build_price20(predictor_artifact=artifact, direction="RISE")
    fall = build_price20(predictor_artifact=artifact, direction="FALL")
    assert [row["element_id"] for row in rise["rows"][:2]] == [1201, 1202]
    assert [row["element_id"] for row in fall["rows"][:2]] == [1101, 1102]


def test_real_price_output_preserves_required_fact_and_model_fields():
    rise = build_price20(predictor_artifact=_real_price_predictor(), direction="RISE")
    row = rise["rows"][0]
    assert set(
        (
            "element_id",
            "player",
            "current_price",
            "projected_percent",
            "likelihood",
            "price_change_percent",
            "price_change_hourly_rate",
            "selected_by_percent",
            "transfers_in_event",
            "transfers_out_event",
            "locked_until",
            "calibrating",
        )
    ).issubset(row)
    assert row["current_price"] != "UNAVAILABLE"
    assert row["price_fact"] == "FACT"
    assert row["predictor_classification"] == "MODEL"


# ---------------------------------------------------------------------------
# V12 RISE20/FALL20 + ACTIONABLE PRICE RADAR + SIMPLE WEATHER visible contract
# Permanent required regressions (PRICE 1-20 / WEATHER 21-30)
# ---------------------------------------------------------------------------

def _contract_price_row(element_id: int, projected: float, *, likelihood: int = 3, offset1: float | None = None, offset2: float | None = None) -> dict:
    p1 = projected if offset1 is None else offset1
    p2 = projected if offset2 is None else offset2
    return {
        "id": element_id,
        "web_name": f"P{element_id}",
        "team": ((element_id - 1) % 20) + 1,
        "element_type": ((element_id - 1) % 4) + 1,
        "now_cost": 50 + (element_id % 20),
        "selected_by_percent": "1.0",
        "transfers_in_event": 1000 + element_id,
        "transfers_out_event": 500 + element_id,
        "price_change_percent": f"{projected:.1f}",
        "price_change_hourly_rate": 10 if projected > 0 else -10 if projected < 0 else 0,
        "price_change_projections": [
            {"offset": 0, "projected_percent": projected, "likelihood": likelihood},
            {"offset": 1, "projected_percent": p1, "likelihood": likelihood},
            {"offset": 2, "projected_percent": p2, "likelihood": likelihood},
        ],
        "price_change_locked_until": None,
        "price_change_calibrating": False,
    }


def _contract_price_artifact(rows: list[dict], *, checked_at: str = "2026-09-20T10:28:23.609531+00:00") -> dict:
    return {"health": "GREEN", "checked_at": checked_at, "data": {"players": rows}}


def _crossing_contract_price_artifact() -> dict:
    rows = []
    for index in range(25):
        rows.append(_contract_price_row(1000 + index, 130.0 - index))
    for index in range(25):
        rows.append(_contract_price_row(2000 + index, -130.0 + index))
    return _contract_price_artifact(rows)


def _contract_owned15() -> list[dict]:
    return [
        {
            "element_id": 1000 + index,
            "name": f"Owned-{index}",
            "current_price": 55 + index,
            "selling_price": 54 + index,
        }
        for index in range(15)
    ]


# PRICE 1
def test_positive_projected_percent_maps_to_rise() -> None:
    result = build_price20(predictor_artifact=_contract_price_artifact([_contract_price_row(i, 120 + i) for i in range(1, 25)]), direction="RISE")
    assert result["rows"][0]["direction"] == "RISE"


# PRICE 2
def test_negative_projected_percent_maps_to_fall() -> None:
    result = build_price20(predictor_artifact=_contract_price_artifact([_contract_price_row(i, -120 - i) for i in range(1, 25)]), direction="FALL")
    assert result["rows"][0]["direction"] == "FALL"


# PRICE 3
def test_zero_projected_percent_maps_to_neutral() -> None:
    result = build_price20(predictor_artifact=_contract_price_artifact([_contract_price_row(i, 0.0) for i in range(1, 25)]), direction="RISE")
    assert all(row["direction"] == "NEUTRAL" for row in result["rows"])


# PRICE 4
def test_rise_sort_desc_then_element_id_asc() -> None:
    rows = [_contract_price_row(i, 80.0) for i in range(1, 25)]
    rows[0]["id"], rows[1]["id"] = 99, 98
    rows[0]["price_change_projections"][0]["projected_percent"] = 110.0
    rows[1]["price_change_projections"][0]["projected_percent"] = 110.0
    result = build_price20(predictor_artifact=_contract_price_artifact(rows), direction="RISE")
    assert [row["element_id"] for row in result["rows"][:2]] == [98, 99]


# PRICE 5
def test_fall_sort_asc_then_element_id_asc() -> None:
    rows = [_contract_price_row(i, -80.0) for i in range(1, 25)]
    rows[0]["id"], rows[1]["id"] = 99, 98
    rows[0]["price_change_projections"][0]["projected_percent"] = -110.0
    rows[1]["price_change_projections"][0]["projected_percent"] = -110.0
    result = build_price20(predictor_artifact=_contract_price_artifact(rows), direction="FALL")
    assert [row["element_id"] for row in result["rows"][:2]] == [98, 99]


# PRICE 6
def test_current_price_is_fact() -> None:
    row = build_price20(predictor_artifact=_crossing_contract_price_artifact(), direction="RISE")["rows"][0]
    assert row["price_fact"] == "FACT"
    assert isinstance(row["current_price"], float)


# PRICE 7
def test_predictor_is_model() -> None:
    row = build_price20(predictor_artifact=_crossing_contract_price_artifact(), direction="RISE")["rows"][0]
    assert row["predictor_classification"] == "MODEL"


# PRICE 8
def test_official_price_cycle_is_london_midnight() -> None:
    row = build_price20(predictor_artifact=_crossing_contract_price_artifact(), direction="RISE")["rows"][0]
    assert "T00:00:00+01:00" in row["next_official_price_cycle_uk"]


# PRICE 9
def test_bst_cycle_converts_to_0600_wib() -> None:
    row = build_price20(predictor_artifact=_crossing_contract_price_artifact(), direction="RISE")["rows"][0]
    assert "T06:00:00+07:00" in row["next_official_price_cycle_wib"]


# PRICE 10
def test_gmt_cycle_converts_to_0700_wib() -> None:
    art = _contract_price_artifact(_crossing_contract_price_artifact()["data"]["players"], checked_at="2026-12-20T10:00:00+00:00")
    row = build_price20(predictor_artifact=art, direction="RISE")["rows"][0]
    assert "T07:00:00+07:00" in row["next_official_price_cycle_wib"]


# PRICE 11
def test_wib_cycle_is_not_permanently_hardcoded_to_0600() -> None:
    bst = build_price20(predictor_artifact=_crossing_contract_price_artifact(), direction="RISE")["rows"][0]
    gmt_art = _contract_price_artifact(_crossing_contract_price_artifact()["data"]["players"], checked_at="2026-12-20T10:00:00+00:00")
    gmt = build_price20(predictor_artifact=gmt_art, direction="RISE")["rows"][0]
    assert bst["next_official_price_cycle_wib"] != gmt["next_official_price_cycle_wib"]


# PRICE 12
def test_predictor_observation_is_separate_from_official_execution_cycle() -> None:
    row = build_price20(predictor_artifact=_crossing_contract_price_artifact(), direction="RISE")["rows"][0]
    assert row["evidence_timestamp"] == "2026-09-20T10:28:23.609531+00:00"
    assert row["next_official_price_cycle_uk"] != row["evidence_timestamp"]


# PRICE 13
def test_unsupported_cycle_eta_remains_unavailable_but_healthy_no_crossing_is_complete() -> None:
    art = _contract_price_artifact([_contract_price_row(i, 50.0, offset1=60.0, offset2=70.0) for i in range(1, 25)])
    result = build_price20(predictor_artifact=art, direction="RISE")
    assert result["state"] == "COMPLETE"
    assert result["degradation_reason"] is None
    assert result["date_state_complete_count"] == 20
    assert result["expected_change_date_count"] == 0
    assert result["no_crossing_count"] == 20
    assert all(row["date_state"] == "NO_CROSSING_WITHIN_GOVERNED_HORIZON" for row in result["rows"])
    assert all(row["cycles_to_expected_change"] == "UNAVAILABLE" for row in result["rows"])
    assert all(row["estimated_change_window"] == "UNAVAILABLE" for row in result["rows"])
    assert all(row["eta_reason"] == "NO_EXISTING_PREDICTOR_CYCLE_CROSSES_GOVERNED_THRESHOLD" for row in result["rows"])
    assert all(row["eta_context"].startswith("Belum terdeteksi berubah sampai") for row in result["rows"])


# PRICE 14
def test_eta_uses_existing_governed_threshold_and_calendar_dates() -> None:
    assert MODEL_THRESHOLD == 100.0
    art = _contract_price_artifact([_contract_price_row(i, 99.9, offset1=99.9, offset2=99.9) for i in range(1, 25)])
    row = build_price20(predictor_artifact=art, direction="RISE")["rows"][0]
    assert row["governed_threshold_percent"] == MODEL_THRESHOLD
    assert row["date_state"] == "NO_CROSSING_WITHIN_GOVERNED_HORIZON"
    assert row["estimated_change_date_wib"] is None

    one_cycle = _contract_price_artifact([_contract_price_row(i, 90.0, offset1=105.0, offset2=110.0) for i in range(1, 25)])
    one_row = build_price20(predictor_artifact=one_cycle, direction="RISE")["rows"][0]
    assert one_row["cycles_to_expected_change"] == "1 CYCLE"
    assert one_row["projection_offset"] == 1
    assert one_row["estimated_change_date_uk"] == "22 Sep 2026 • 00:00 BST"
    assert one_row["estimated_change_date_wib"] == "22 Sep 2026 • 06:00 WIB"
    assert one_row["estimated_change_window"] == "22 Sep 2026 • 06:00 WIB"

    two_cycles = _contract_price_artifact([_contract_price_row(i, 90.0, offset1=95.0, offset2=105.0) for i in range(1, 25)])
    two_row = build_price20(predictor_artifact=two_cycles, direction="RISE")["rows"][0]
    assert two_row["cycles_to_expected_change"] == "2 CYCLES"
    assert two_row["projection_offset"] == 2
    assert two_row["estimated_change_date_wib"] == "23 Sep 2026 • 06:00 WIB"


# PRICE 15
def test_complete_rise20_rows_have_full_visible_contract() -> None:
    result = build_price20(predictor_artifact=_crossing_contract_price_artifact(), direction="RISE")
    assert result["state"] == "COMPLETE"
    assert result["available_count"] == 20
    required = set(result["visible_contract_fields"])
    assert all(required <= set(row) for row in result["rows"])


# PRICE 16
def test_complete_fall20_rows_have_full_visible_contract() -> None:
    result = build_price20(predictor_artifact=_crossing_contract_price_artifact(), direction="FALL")
    assert result["state"] == "COMPLETE"
    assert result["available_count"] == 20
    required = set(result["visible_contract_fields"])
    assert all(required <= set(row) for row in result["rows"])


# PRICE 17
def test_missing_cycle_timestamp_degrades_with_exact_date_unavailable_reason() -> None:
    art = _crossing_contract_price_artifact()
    art.pop("checked_at")
    result = build_price20(predictor_artifact=art, direction="RISE")
    assert result["available_count"] == 20
    assert result["state"] == "DEGRADED"
    assert all(row["date_state"] == "DATE_UNAVAILABLE" for row in result["rows"])
    assert all(row["degradation_reason"] == "EVIDENCE_TIMESTAMP_UNAVAILABLE" for row in result["rows"])


# PRICE 18
def test_all15_price_radar_stays_exact15() -> None:
    result = build_actionable_price_radar(owned15=_contract_owned15(), predictor_artifact=_crossing_contract_price_artifact())
    assert result["available_count"] == 15
    assert result["identity_complete"] is True
    assert all("cycles_to_expected_change" in row for row in result["rows"])
    assert all("estimated_change_window" in row for row in result["rows"])


# PRICE 19
def test_real_schema_all15_direction_uses_offset_zero() -> None:
    result = build_actionable_price_radar(owned15=_contract_owned15(), predictor_artifact=_crossing_contract_price_artifact())
    assert all(row["predictor_direction"] == "RISE" for row in result["rows"])


# PRICE 20
def test_price_movement_alone_cannot_create_act() -> None:
    result = build_actionable_price_radar(owned15=_contract_owned15(), predictor_artifact=_crossing_contract_price_artifact())
    assert result["price_alone_may_create_act"] is False
    assert all("ACT" not in str(row["decision_implication"]) for row in result["rows"])


# DATE-ETA COMPLETION REGRESSIONS
def test_first_governed_crossing_wins_over_stronger_later_projection() -> None:
    art = _contract_price_artifact([
        _contract_price_row(i, 98.0, offset1=101.0, offset2=140.0)
        for i in range(1, 25)
    ])
    row = build_price20(predictor_artifact=art, direction="RISE")["rows"][0]
    assert row["date_state"] == "EXPECTED_CHANGE_DATE"
    assert row["projection_offset"] == 1
    assert row["estimated_change_date_wib"] == "22 Sep 2026 • 06:00 WIB"


def test_offset_zero_crossing_maps_to_first_official_calendar_cycle() -> None:
    row = build_price20(
        predictor_artifact=_contract_price_artifact([
            _contract_price_row(i, 105.0, offset1=120.0, offset2=140.0)
            for i in range(1, 25)
        ]),
        direction="RISE",
    )["rows"][0]
    assert row["projection_offset"] == 0
    assert row["estimated_change_date_uk"] == "21 Sep 2026 • 00:00 BST"
    assert row["estimated_change_date_wib"] == "21 Sep 2026 • 06:00 WIB"


def test_non_crossing_never_linearly_extrapolates_a_fourth_cycle() -> None:
    art = _contract_price_artifact([
        _contract_price_row(i, 90.0, offset1=95.0, offset2=99.9)
        for i in range(1, 25)
    ])
    row = build_price20(predictor_artifact=art, direction="RISE")["rows"][0]
    assert row["date_state"] == "NO_CROSSING_WITHIN_GOVERNED_HORIZON"
    assert row["estimated_change_date_wib"] is None
    assert row["last_supported_projection_date_wib"] == "23 Sep 2026 • 06:00 WIB"
    assert row["horizon_cycles"] == 3
    assert row["latest_supported_projection"] == 99.9
    assert row["horizon_extension_used"] is False


def test_existing_horizon_remains_exactly_offsets_zero_one_two() -> None:
    result = build_price20(predictor_artifact=_crossing_contract_price_artifact(), direction="RISE")
    assert tuple(result["governed_projection_offsets"]) == (0, 1, 2)
    assert result["horizon_extension_used"] is False
    assert result["new_price_predictor_created"] is False
    assert result["new_price_threshold_model_created"] is False


def test_dst_boundary_maps_each_london_midnight_to_same_instant_wib() -> None:
    rows = [_contract_price_row(i, 90.0, offset1=105.0, offset2=120.0) for i in range(1, 25)]
    art = _contract_price_artifact(rows, checked_at="2026-10-24T21:00:00+00:00")
    row = build_price20(predictor_artifact=art, direction="RISE")["rows"][0]
    assert row["estimated_change_at_uk"] == "2026-10-26T00:00:00+00:00"
    assert row["estimated_change_at_wib"] == "2026-10-26T07:00:00+07:00"
    assert row["estimated_change_date_wib"] == "26 Oct 2026 • 07:00 WIB"


def test_all15_predictor_supported_rows_have_terminal_date_state() -> None:
    result = build_actionable_price_radar(
        owned15=_contract_owned15(),
        predictor_artifact=_crossing_contract_price_artifact(),
    )
    assert result["available_count"] == 15
    assert result["date_state_complete_count"] == 15
    assert all(row["date_state"] == "EXPECTED_CHANGE_DATE" for row in result["rows"])


def test_all15_without_predictor_keeps_identity_and_truthful_date_unavailable() -> None:
    result = build_actionable_price_radar(owned15=_contract_owned15(), predictor_artifact=None)
    assert result["available_count"] == 15
    assert result["identity_complete"] is True
    assert result["date_state_complete_count"] == 15
    assert all(row["date_state"] == "DATE_UNAVAILABLE" for row in result["rows"])
    assert all(row["date_state_reason"] == "PREDICTOR_EVIDENCE_UNAVAILABLE" for row in result["rows"])


def test_stale_authenticated_sell_value_is_classified_not_refreshed_or_fabricated() -> None:
    owned = _contract_owned15()
    for row in owned:
        row["authenticated_evidence_state"] = "STALE"
    result = build_actionable_price_radar(
        owned15=owned,
        predictor_artifact=_crossing_contract_price_artifact(),
    )
    assert all(row["sell_value_evidence_state"] == "STALE_AUTHENTICATED_FALLBACK" for row in result["rows"])
    assert all(row["authenticated_sell_value"] != "UNAVAILABLE" for row in result["rows"])


def test_visible_price_contract_retains_cycle_eta_and_date_state_fields() -> None:
    result = build_price20(predictor_artifact=_crossing_contract_price_artifact(), direction="RISE")
    fields = set(result["visible_contract_fields"])
    assert "next_official_price_cycle_uk" in fields
    assert "next_official_price_cycle_wib" in fields
    assert "cycles_to_expected_change" in fields
    assert "estimated_change_window" in fields
    assert "estimated_change_date_wib" in fields
    assert "date_state" in fields



def test_no_crossing_keeps_price_section_complete_with_truthful_unavailable_eta() -> None:
    art = _contract_price_artifact([
        _contract_price_row(i, 75.0, offset1=80.0, offset2=85.0)
        for i in range(1, 25)
    ])
    result = build_price20(predictor_artifact=art, direction="RISE")
    assert result["available_count"] == 20
    assert result["state"] == "COMPLETE"
    assert result["degradation_reason"] is None
    assert all(row["date_state"] == "NO_CROSSING_WITHIN_GOVERNED_HORIZON" for row in result["rows"])
    assert all(row["cycles_to_expected_change"] == "UNAVAILABLE" for row in result["rows"])
    assert all(row["estimated_change_window"] == "UNAVAILABLE" for row in result["rows"])


def test_all15_real_schema_exposes_direction_progress_strength_cycle_and_eta() -> None:
    result = build_actionable_price_radar(
        owned15=_contract_owned15(),
        predictor_artifact=_crossing_contract_price_artifact(),
    )
    assert result["available_count"] == 15
    assert all(row["predictor_direction"] == "RISE" for row in result["rows"])
    assert all(row["predictor_progress"] != "UNAVAILABLE" for row in result["rows"])
    assert all(row["prediction_strength"] != "UNAVAILABLE" for row in result["rows"])
    assert all(row["next_official_price_cycle_wib"] != "UNAVAILABLE" for row in result["rows"])
    assert all(row["cycles_to_expected_change"] != "UNAVAILABLE" for row in result["rows"])
    assert all(row["estimated_change_window"] != "UNAVAILABLE" for row in result["rows"])


def _weather_payload(impact: str = "NORMAL") -> dict:
    return {
        "fixture": "AAA-BBB",
        "condition": "Cloudy",
        "temperature_c": 17,
        "precipitation_chance_pct": 20,
        "wind_kmh": 14,
        "fpl_impact": impact,
        "impact_reason": "no material FPL adjustment" if impact == "NORMAL" else "advisory weather context",
        "weather_evidence_timestamp": "2026-09-20T10:30:00+00:00",
    }


# WEATHER 21
def test_weather_is_report_time_not_v6() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="2026-09-20T15:00:00+01:00",
        weather=_weather_payload(),
        lookup_accessible=True,
    )
    assert result["source_layer"] == "REPORT_TIME"
    assert result["v6_weather_required"] is False


# WEATHER 22
def test_canonical_requires_simple_visible_weather_block() -> None:
    canonical = CANONICAL.read_text(encoding="utf-8")
    assert "Minimum visible WEATHER row" in canonical
    assert "DEEP / Deadline / Final Review" in canonical


# WEATHER 23
def test_normal_weather_remains_normal_context() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="2026-09-20T15:00:00+01:00",
        weather=_weather_payload("NORMAL"),
        lookup_accessible=True,
    )
    assert result["visible_row"]["fpl_impact"] == "NORMAL"


# WEATHER 24
def test_missing_weather_source_degrades_weather_only() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="2026-09-20T15:00:00+01:00",
        weather=None,
        lookup_accessible=False,
        failure_reason="source inaccessible",
    )
    assert result["state"] == "UNAVAILABLE"
    assert result["degradation_reason"] == "source inaccessible"


# WEATHER 25
def test_weather_failure_does_not_become_report_or_v6_failure() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="2026-09-20T15:00:00+01:00",
        weather=None,
        lookup_accessible=False,
    )
    assert result["v6_weather_required"] is False
    assert result["weather_may_independently_create_action"] is False
    assert "must not collapse" in CANONICAL.read_text(encoding="utf-8")


# WEATHER 26
def test_weather_does_not_mutate_xpts() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB", venue="Example Ground", kickoff="K", weather=_weather_payload(), lookup_accessible=True
    )
    assert result["weather_adjusted_xpts"] is False


# WEATHER 27
def test_weather_does_not_mutate_pstart_or_xmins() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB", venue="Example Ground", kickoff="K", weather=_weather_payload(), lookup_accessible=True
    )
    assert result["weather_mutates_p_start"] is False
    assert result["weather_mutates_xmins"] is False


# WEATHER 28
def test_visible_weather_contract_creates_no_new_weather_model_owner() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB", venue="Example Ground", kickoff="K", weather=_weather_payload(), lookup_accessible=True
    )
    assert result["new_weather_model_created"] is False


# WEATHER 29
def test_visible_weather_row_has_required_fields() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="2026-09-20T15:00:00+01:00",
        weather=_weather_payload(),
        lookup_accessible=True,
    )
    required = {
        "fixture",
        "venue",
        "kickoff",
        "condition",
        "temperature_c",
        "temperature",
        "precipitation_probability",
        "precipitation_chance_pct",
        "wind_kph",
        "wind_kmh",
        "fpl_impact",
        "impact_class",
        "impact_reason",
        "evidence_timestamp",
        "weather_evidence_timestamp",
    }
    assert required <= set(result["visible_row"])
    assert result["state"] == "COMPLETE"


# WEATHER 30
def test_visible_weather_row_hides_raw_provider_plumbing() -> None:
    payload = {**_weather_payload(), "provider": "example", "latitude": 1.2, "longitude": 3.4, "raw": {"x": 1}}
    result = weather_report_time_evidence(
        fixture="AAA-BBB", venue="Example Ground", kickoff="K", weather=payload, lookup_accessible=True
    )
    visible = result["visible_row"]
    assert result["raw_provider_plumbing_visible"] is False
    assert {"provider", "latitude", "longitude", "raw"}.isdisjoint(visible)



def test_weather_does_not_mutate_p1_6_tactical_score() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="K",
        weather=_weather_payload(),
        lookup_accessible=True,
    )
    assert result["weather_mutates_p1_6_tactical_score"] is False


def test_weather_unavailable_visible_row_carries_reason_without_v6_dependency() -> None:
    result = weather_report_time_evidence(
        fixture="AAA-BBB",
        venue="Example Ground",
        kickoff="K",
        weather=None,
        lookup_accessible=False,
        failure_reason="forecast horizon unavailable",
    )
    assert result["state"] == "UNAVAILABLE"
    assert result["visible_row"]["impact_reason"] == "forecast horizon unavailable"
    assert result["v6_weather_required"] is False
    assert result["weather_failure_isolated_to_weather"] is True



def _post_match_projection_payload(
    *,
    classifications,
    name="Mover",
    points=2,
    xgi=0.8,
    owned=False,
    material_count=1,
    scanned_count=100,
    eligible_count=100,
    search_authority="FULL",
    deep_executed=True,
):
    material_rows = []
    if material_count:
        material_rows.append(
            {
                "element_id": 9001,
                "name": name,
                "position": "FWD",
                "owned": owned,
                "primary_classification": classifications[0],
                "classifications": list(classifications),
                "materiality_score": 3.0,
                "latest_match": {
                    "fpl_points": points,
                    "xgi": xgi,
                },
                "xmins": {"delta": 24.0},
                "p_start": {"delta": 0.22},
                "universe_comparison": {
                    "state": (
                        "OWNED_PLAYER_REVIEW"
                        if owned
                        else "FULL_UNIVERSE_PACKAGE_CHALLENGER"
                    ),
                    "published_position_pool_rank": 2,
                    "beats_hold_in_any_published_package": not owned,
                },
                "deep_analysis_required": True,
                "deep_detail_available": deep_executed,
            }
        )
    scan = {
        "scope": "FULL_ELIGIBLE_FPL_PLAYER_UNIVERSE",
        "scanned_count": scanned_count,
        "eligible_count": eligible_count,
        "material_count": material_count,
        "material_players": material_rows,
        "deep_analysis_element_ids": [9001] if material_count else [],
        "universe_comparison": {
            "search_authority": search_authority,
            "eligible_universe_count": eligible_count,
        },
    }
    deep = {
        "status": "COMPLETE",
        "deep_execution_scope": (
            "COMPLETE" if material_count else "NO_MATERIAL_TARGETS"
        ),
        "deep_requested_count": material_count,
        "deep_executed_count": material_count if deep_executed else 0,
        "deep_deferred_count": 0,
        "executed_element_ids": (
            [9001] if material_count and deep_executed else []
        ),
        "details": [],
    }
    return {
        "post_match_universe_scan": scan,
        "post_match_deep_analysis": deep,
    }


def test_natural_post_match_materializer_wires_universe_movers_not_helper_only():
    canonical = CANONICAL.read_text(encoding="utf-8")
    projections = _post_match_projection_payload(
        classifications=["BREAKOUT_PROCESS", "OUTPUT_CONFIRMING_PROCESS"],
        name="Confirmed Mover",
        points=15,
        xgi=1.1,
    )
    report = materialize_natural_post_match_report(
        canonical_text=canonical,
        report_mode="POST_MATCH",
        projections_payload=projections,
        section_payloads={
            "RELEVANT LEAGUE-WIDE SIGNALS": {
                "state": "COMPLETE",
                "content": {"existing_signal": "preserved"},
            }
        },
    )
    assert report["universe_movers_attachment_count"] == 1
    target = next(
        row
        for row in report["sections"]
        if row["label"] == "RELEVANT LEAGUE-WIDE SIGNALS"
    )
    assert target["content"]["existing_signal"] == "preserved"
    assert target["content"]["universe_movers"]["title"] == "UNIVERSE MOVERS"
    body = render_natural_post_match_text(report)
    assert "UNIVERSE MOVERS" in body
    assert "BREAKOUT / CONFIRMATION" in body
    assert "Confirmed Mover" in body


def test_natural_post_match_non_scorer_renders_process_up_category():
    canonical = CANONICAL.read_text(encoding="utf-8")
    projections = _post_match_projection_payload(
        classifications=["UNDERLYING_IMPROVING_NO_RETURN"],
        name="Two Point Process Riser",
        points=2,
        xgi=0.8,
    )
    report = materialize_natural_post_match_report(
        canonical_text=canonical,
        report_mode="POST_MATCH",
        projections_payload=projections,
        section_payloads={
            "RELEVANT LEAGUE-WIDE SIGNALS": {
                "state": "COMPLETE",
                "content": {},
            }
        },
    )
    body = render_natural_post_match_text(report)
    assert "PROCESS UP — RETURNS NOT YET ARRIVED" in body
    assert "Two Point Process Riser" in body
    assert "Pts 2" in body
    assert "xGI 0.8" in body
    assert "DEEP" in body


def test_natural_post_match_poor_process_haul_renders_noise_and_regression():
    canonical = CANONICAL.read_text(encoding="utf-8")
    projections = _post_match_projection_payload(
        classifications=["OUTPUT_WITHOUT_PROCESS", "REGRESSION_RISK"],
        name="Low Process Haul",
        points=17,
        xgi=0.10,
    )
    report = materialize_natural_post_match_report(
        canonical_text=canonical,
        report_mode="POST_MATCH",
        projections_payload=projections,
        section_payloads={
            "RELEVANT LEAGUE-WIDE SIGNALS": {
                "state": "COMPLETE",
                "content": {},
            }
        },
    )
    body = render_natural_post_match_text(report)
    assert "NOISE / DO NOT CHASE" in body
    assert "REGRESSION / SELL-RISK" in body
    assert "Low Process Haul" in body
    assert "Action: ACT" not in body
    mover_rows = [
        row
        for rows in report["post_match_universe_movers"]["categories"].values()
        for row in rows
        if row["element_id"] == 9001
    ]
    assert mover_rows
    assert all(
        row["automatic_transfer_recommendation"] is False
        for row in mover_rows
    )


def test_natural_post_match_zero_materiality_renders_no_material_movers():
    canonical = CANONICAL.read_text(encoding="utf-8")
    projections = _post_match_projection_payload(
        classifications=[],
        material_count=0,
    )
    report = materialize_natural_post_match_report(
        canonical_text=canonical,
        report_mode="POST_MATCH",
        projections_payload=projections,
        section_payloads={
            "RELEVANT LEAGUE-WIDE SIGNALS": {
                "state": "COMPLETE",
                "content": {},
            }
        },
    )
    body = render_natural_post_match_text(report)
    assert "UNIVERSE MOVERS" in body
    assert "NO MATERIAL MOVERS" in body


def test_natural_post_all_match_nests_movers_in_existing_scout_surface():
    canonical = CANONICAL.read_text(encoding="utf-8")
    projections = _post_match_projection_payload(
        classifications=["LINKUP_BREAKOUT"],
        name="Link Riser",
    )
    report = materialize_natural_post_match_report(
        canonical_text=canonical,
        report_mode="POST_ALL_MATCH",
        projections_payload=projections,
        section_payloads={
            "GW COMPLETED MATCH-BY-MATCH SCOUT": {
                "state": "COMPLETE",
                "content": {"fixtures": [101, 102]},
            }
        },
    )
    target = next(
        row
        for row in report["sections"]
        if row["label"] == "GW COMPLETED MATCH-BY-MATCH SCOUT"
    )
    assert "universe_movers" in target["content"]
    assert report["universe_movers_attachment_count"] == 1
    assert render_natural_post_match_text(report).count("UNIVERSE MOVERS") == 1


@pytest.mark.parametrize("mode", ["FULL+MATCH", "DEEP+MATCH", "MATCH+FULL", "MATCH+DEEP", "OVERLAP"])
def test_natural_overlap_modes_attach_universe_movers_exactly_once(mode):
    canonical = CANONICAL.read_text(encoding="utf-8")
    projections = _post_match_projection_payload(
        classifications=["MINUTES_BREAKOUT"],
        name="Minutes Riser",
    )
    report = materialize_natural_post_match_report(
        canonical_text=canonical,
        report_mode=mode,
        projections_payload=projections,
        section_payloads={
            "Changes": {
                "state": "COMPLETE",
                "content": {"existing_changes": ["role"]},
            }
        },
    )
    assert report["universe_movers_attachment_count"] == 1
    body = render_natural_post_match_text(report)
    assert body.count("UNIVERSE MOVERS") == 1
    assert "Minutes Riser" in body


def test_natural_post_match_partial_universe_is_visibly_degraded():
    canonical = CANONICAL.read_text(encoding="utf-8")
    projections = _post_match_projection_payload(
        classifications=["BREAKOUT_PROCESS"],
        scanned_count=90,
        eligible_count=100,
        search_authority="PARTIAL",
    )
    report = materialize_natural_post_match_report(
        canonical_text=canonical,
        report_mode="POST_MATCH",
        projections_payload=projections,
        section_payloads={
            "RELEVANT LEAGUE-WIDE SIGNALS": {
                "state": "COMPLETE",
                "content": {},
            }
        },
    )
    movers = report["post_match_universe_movers"]
    assert movers["state"] == "DEGRADED"
    assert movers["scanned_count"] == 90
    assert movers["eligible_count"] == 100
    assert movers["search_authority"] == "PARTIAL"
    body = render_natural_post_match_text(report)
    assert "DEGRADED" in body
    assert "Coverage: 90/100" in body


def test_pure_price_cannot_force_universe_movers():
    canonical = CANONICAL.read_text(encoding="utf-8")
    with pytest.raises(ReportOrchestrationError):
        materialize_natural_post_match_report(
            canonical_text=canonical,
            report_mode="PRICE",
            projections_payload=_post_match_projection_payload(
                classifications=["BREAKOUT_PROCESS"]
            ),
            section_payloads={},
        )

def _complete_match_scout_rows():
    common = {
        "formation_system": "4-2-3-1 vs 4-3-3",
        "coach_pattern": "high press / mid-block transitions",
        "player_roles": "key role changes captured",
        "minutes_substitution_pattern": "starters and substitutions captured",
        "xg_xa_xgi_shots_chances": "team/player process summary",
        "set_pieces_penalties": "takers and targets captured",
        "defcon": "defensive contribution context",
        "opponent_channels": "left/right/central channel evidence",
        "sustainable_vs_noisy": "process-led with noise separated",
        "implication_for_our15": "owned-player impact",
        "implication_for_next_opponent": "next-GW matchup implication",
        "posterior_calibration_implication": "Bayesian calibration input only",
    }
    return [
        {"fixture_id": 501, "result": "HOME 2-1 AWAY", **common},
        {"fixture_id": 502, "result": "HOME 0-0 AWAY", **common},
    ]


def test_post_all_match_renderer_exposes_every_fixture_detail_not_only_movers():
    canonical = CANONICAL.read_text(encoding="utf-8")
    scout = _complete_match_scout_rows()
    report = materialize_natural_post_match_report(
        canonical_text=canonical,
        report_mode="POST_ALL_MATCH",
        projections_payload=_post_match_projection_payload(
            classifications=["BREAKOUT_PROCESS"],
        ),
        section_payloads={
            "GW COMPLETED MATCH-BY-MATCH SCOUT": {
                "state": "COMPLETE",
                "content": {"match_scout": scout},
            }
        },
    )
    body = render_natural_post_match_text(report)
    assert body.count("#### FIXTURE ID:") == 2
    for fixture in ("501", "502"):
        assert f"#### FIXTURE ID: {fixture}" in body
    for label in (
        "RESULT:",
        "FORMATION/SYSTEM:",
        "COACH PATTERN:",
        "PLAYER ROLES:",
        "MINUTES/SUBS:",
        "xG/xA/xGI/SHOTS/CHANCES:",
        "SET PIECES/PENALTIES:",
        "DEFCON:",
        "OPPONENT CHANNELS:",
        "SUSTAINABLE VS NOISE:",
        "OUR15 IMPLICATION:",
        "NEXT OPPONENT IMPLICATION:",
        "POSTERIOR CALIBRATION IMPLICATION:",
    ):
        assert body.count(label) == 2


def test_deep_renderer_exposes_post_match_carryover_and_mathematical_decision_stack():
    canonical = CANONICAL.read_text(encoding="utf-8")
    decision_proof = {
        "bayesian_shrinkage_lineage": {
            "prior": "role/minutes prior",
            "posterior": "updated posterior",
            "shrinkage": "small-sample shrinkage",
        },
        "probability_state": {
            "unconditional": {
                "p_available": 0.96,
                "p_start": 0.84,
                "p_bench": 0.12,
                "p_cameo": 0.09,
                "p_late_cameo": 0.03,
                "p_dnp": 0.04,
            }
        },
        "xmins_distribution": {
            "mean": 72.0,
            "states": [
                {"state": "START", "probability": 0.84},
                {"state": "CAMEO", "probability": 0.09},
                {"state": "LATE_CAMEO", "probability": 0.03},
                {"state": "ZERO_MINUTES", "probability": 0.04},
            ],
        },
        "posterior_predictive": {
            "source_contract": "P1.3/P1.3B_POSTERIOR_PREDICTIVE",
            "event_probabilities": {
                "p_goal_return": 0.31,
                "p_assist_return": 0.24,
                "p_attacking_return": 0.48,
                "p_total_ga_ge_2": 0.14,
                "p_no_attacking_return": 0.52,
            },
            "point_distribution": {
                "p_fpl_blank": 0.44,
                "p_haul_10_plus": 0.11,
                "expected_points": 5.8,
                "variance": 8.41,
                "std": 2.9,
                "quantiles": {"p10": 2, "p50": 5, "p90": 10},
                "tails": {"ge_10": 0.11, "ge_15": 0.03},
            },
        },
        "horizons": {
            "GW+1": {"xpts": 5.8},
            "3GW": {"xpts": 17.1},
            "5GW": {"xpts": 27.2},
        },
        "robustness": {
            "p_outperform": 0.61,
            "expected_regret": 0.7,
            "conditional_floor": 2.0,
            "upper_tail": 12.0,
        },
        "information_value_of_waiting": 0.9,
        "covariance_correlation": {"same_club": 0.18},
        "monte_carlo": {
            "execution_state": "EXECUTED",
            "actual_paths": 500000,
            "correlated": True,
            "convergence_evidence": "stable paired-route delta",
        },
    }
    stack = build_visible_mathematical_decision_stack(decision_proof)
    report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads={},
        post_all_match_scout=_complete_match_scout_rows(),
        mathematical_decision_stack=stack,
    )
    body = render_deep_text(report)
    assert "### POST-MATCH MATCH-BY-MATCH SCOUT" in body
    assert body.count("#### FIXTURE ID:") == 2
    assert "### MATHEMATICAL DECISION STACK" in body
    assert "BAYESIAN PRIOR -> POSTERIOR / SHRINKAGE:" in body
    assert "P(AVAILABLE)=0.96" in body
    assert "P(GOAL)=0.31" in body
    assert "P(RETURN)=0.48" in body
    assert "P(HAUL)=0.11" in body
    assert "P(BLANK)=0.44" in body
    assert "P(NO ATTACK RETURN)=0.52" in body
    assert "P1.3B POINT DISTRIBUTION:" in body
    assert "E[xPts]=5.8" in body
    assert "variance=8.41" in body
    assert "HORIZONS 1GW / 3GW / 5GW:" in body
    assert "EXPECTED REGRET: 0.7" in body
    assert "MONTE CARLO: state=EXECUTED | N=500000 | correlated=True" in body



def _complete_universe_package_content():
    return {
        "package_search_proof": {
            "owned_expected": 15,
            "owned_evaluated": 15,
            "eligible_universe_expected": 667,
            "eligible_universe_evaluated": 667,
            "outgoing_candidate_count": 15,
            "legal_route_count": 42,
            "hold_included": True,
            "lossy_pruning": False,
            "search_authority": "FULL",
        },
        "package_universe_challengers": [
            {
                "rank": 1,
                "element_id": 901,
                "player": "Candidate A",
                "position": "MID",
                "club": "AAA",
                "best_outgoing": "Owned Weak Link",
                "package_route": "Owned Weak Link -> Candidate A",
                "football_score": 82.4,
                "football_score_components": {
                    "PROVEN_HISTORICAL": 78,
                    "TACTICAL_ROLE": 84,
                    "CURRENT_UNDERLYING": 86,
                    "FIXTURE_SECURITY": 80,
                },
                "p_available": 0.99,
                "p_start": 0.91,
                "p_cameo": 0.05,
                "p_dnp": 0.04,
                "xmins": {"mean": 78.2},
                "p_return": 0.47,
                "p_blank": 0.43,
                "p_haul": 0.14,
                "expected_points_distribution": {"mean": 6.1, "p90": 11},
                "tactical_role": "secure multi-channel creator",
                "set_piece_penalty_role": "set pieces",
                "gw_plus_1": 6.1,
                "three_gw": 18.0,
                "five_gw": 29.2,
                "package_utility_delta_vs_hold": 3.4,
                "price_economics": "affordable",
                "structure_effect": "improves starting XI and bench optionality",
                "expected_regret": 0.7,
                "information_value_of_waiting": 0.5,
                "mini_league_leverage": "downstream overlay only",
                "main_upside": "role + underlying + fixtures",
                "main_risk": "fixture swing",
                "action": "PREPARE",
            }
        ],
        "package_routes": [
            {
                "route": "HOLD",
                "moves": [],
                "transfer_cost": 0,
                "gw1_net": 0.0,
                "two_gw_if_relevant": None,
                "three_gw": 0.0,
                "five_gw": 0.0,
                "p_beats_hold": 0.5,
                "expected_regret": 1.1,
                "robustness": "baseline",
                "price_risk": "none",
                "structure_effect": "current squad",
                "action_verdict": "WAIT",
            },
            {
                "route": "Owned Weak Link -> Candidate A",
                "moves": ["OUT Owned Weak Link", "IN Candidate A"],
                "transfer_cost": 0,
                "gw1_net": 1.2,
                "two_gw_if_relevant": None,
                "three_gw": 2.5,
                "five_gw": 3.4,
                "p_beats_hold": 0.61,
                "expected_regret": 0.7,
                "robustness": "positive",
                "price_risk": "manageable",
                "structure_effect": "improves XI",
                "action_verdict": "PREPARE",
            },
        ],
    }


def test_deep_package_frontier_complete_requires_full_universe_search_proof():
    canonical = CANONICAL.read_text(encoding="utf-8")
    label = "PACKAGE OPTIMIZER / TRANSFER FRONTIER"

    incomplete = materialize_deep_report(
        canonical_text=canonical,
        section_payloads={
            label: {
                "state": "COMPLETE",
                "content": {
                    "package_routes": [
                        {
                            "route": "HOLD",
                            "moves": [],
                        }
                    ]
                },
            }
        },
    )
    incomplete_row = next(
        row
        for row in incomplete["sections"]
        if "PACKAGE OPTIMIZER" in str(row.get("label") or "").upper()
    )
    assert incomplete_row["state"] == "DEGRADED"
    assert "SEARCH_PROOF_MISSING" in incomplete_row["degradation_reason"]
    assert "SCAN_DERIVED_CHALLENGERS_MISSING" in incomplete_row["degradation_reason"]

    complete = materialize_deep_report(
        canonical_text=canonical,
        section_payloads={
            label: {
                "state": "COMPLETE",
                "content": _complete_universe_package_content(),
            }
        },
    )
    complete_row = next(
        row
        for row in complete["sections"]
        if "PACKAGE OPTIMIZER" in str(row.get("label") or "").upper()
    )
    assert complete_row["state"] == "COMPLETE"
    body = render_deep_text(complete)
    assert "### UNIVERSE SCAN / OPTIMAL TEAM IMPACT" in body
    assert "UNIVERSE 667/667" in body
    assert "OUTGOING 15/15" in body
    assert "Candidate A" in body
    assert "UTILITY ΔHOLD 3.4" in body
    assert "Owned Weak Link -> Candidate A" in body



def test_report_plane_mode_catalogs_cannot_drift_from_canonical_v12():
    canonical = CANONICAL.read_text(encoding="utf-8")
    expected = {
        "DEEP": DEEP_MANDATORY_SECTIONS,
        "MATCH": MATCH_MANDATORY_SECTIONS,
        "PRICE": PRICE_MANDATORY_SECTIONS,
        "POST_ALL_MATCH": POST_ALL_MATCH_MANDATORY_SECTIONS,
        "FINAL": FINAL_MANDATORY_SECTIONS,
    }
    for mode, runtime_catalog in expected.items():
        contract = canonical_mode_contract(canonical, mode)
        assert list(runtime_catalog) == contract["expected_section_ids"], mode


def test_visible_section_parser_supports_all_current_two_digit_mode_sections():
    canonical = CANONICAL.read_text(encoding="utf-8")
    bodies = {
        "MATCH": "\n".join(
            f"## MATCH {index} — section"
            for index in range(1, 14)
        ),
        "PRICE": "\n".join(
            f"## PRICE {index} — section"
            for index in range(1, 12)
        ),
        "POST_ALL_MATCH": "\n".join(
            f"## POST-ALL-MATCH {index} — section"
            for index in range(1, 14)
        ),
    }
    for mode, body in bodies.items():
        parsed, _, _ = _parse_sections(body)
        assert parsed == canonical_mode_contract(
            canonical, mode
        )["expected_section_ids"], mode


def test_deep_renderer_headings_are_visible_qa_parseable_and_canonical_ordered():
    canonical = CANONICAL.read_text(encoding="utf-8")
    report = materialize_deep_report(
        canonical_text=canonical,
        section_payloads={},
    )
    body = render_deep_text(report)
    parsed, _, _ = _parse_sections(body)
    assert parsed == canonical_mode_contract(
        canonical, "DEEP"
    )["expected_section_ids"]


def test_price_signal_visible_identity_is_verified_official_fpl_predictor_guidance():
    row = build_price20(
        predictor_artifact=_crossing_contract_price_artifact(),
        direction="RISE",
    )["rows"][0]
    assert row["price_fact"] == "FACT"
    assert row["predictor_classification"] == "MODEL"
    assert row["artifact_source"] == "official_price_predictor"
    assert row["estimate_source"] == "OFFICIAL_FPL_PRICE_CHANGE_PREDICTOR"
    assert "Official FPL Price Change Predictor" in row["visible_source_label"]
    assert "not a guarantee" in row["visible_source_label"]
