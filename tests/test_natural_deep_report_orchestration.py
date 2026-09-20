from __future__ import annotations

from pathlib import Path

import pytest

from src.engines.v12_report_orchestration import (
    ReportOrchestrationError,
    analytic_execution_truth,
    build_actionable_price_radar,
    build_icon_subscopes,
    build_price20,
    build_signal_delta,
    build_watchlist20,
    compact_engine_data_status,
    materialize_all15,
    materialize_deep_report,
    render_deep_text,
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
    assert report["rendered_blocks_including_15B"] == 20
    assert report["exact_canonical_order"] is True
    assert len(report["sections"]) == 20
    assert report["sections"][0]["label"] == "Decision/status"
    assert report["sections"][-1]["label"] == "Final judgement"
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
    by_label = {row["label"]: row for row in report["sections"]}
    assert by_label["Formation/XI/bench"]["state"] == "COMPLETE"
    assert "LOCKED" in by_label["Formation/XI/bench"]["content"]["status"]
    assert by_label["XI battle"]["state"] == "COMPLETE"
    assert by_label["C/VC"]["state"] == "COMPLETE"
    assert by_label["Chip"]["state"] == "COMPLETE"


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
    assert rise["state"] == "DEGRADED"
    assert fall["state"] == "DEGRADED"
    assert rise["available_count"] == 20
    assert fall["available_count"] == 20
    assert rise["artifact_adapter"] == "V6_DATA_PLAYERS_OFFSET0"
    assert fall["artifact_adapter"] == "V6_DATA_PLAYERS_OFFSET0"
    assert rise["sort_contract"] == "projected_percent DESC, id ASC"
    assert fall["sort_contract"] == "projected_percent ASC, id ASC"
    assert all(row["projection_offset"] == 0 for row in rise["rows"] + fall["rows"])
    assert all(row["price_fact"] == "FACT" for row in rise["rows"] + fall["rows"])
    assert all(row["predictor_classification"] == "MODEL" for row in rise["rows"] + fall["rows"])
    assert all(row["direction"] in {"RISE", "FALL", "NEUTRAL"} for row in rise["rows"] + fall["rows"])
    assert all("rank" not in row for row in rise["rows"] + fall["rows"])
    assert all("next_official_price_cycle_uk" in row for row in rise["rows"] + fall["rows"])
    assert all("next_official_price_cycle_wib" in row for row in rise["rows"] + fall["rows"])


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
