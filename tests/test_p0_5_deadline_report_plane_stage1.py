from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.domains.report_plane.decision_context import hydrate_current_decision_context
from src.runtime_v6.domains.report_plane.report_contract import resolve_report_data_readiness
from src.runtime_v6.domains.report_plane import report_prefetch
from src.runtime_v6.delivery_integrity import MANDATORY_SECTIONS, build_report_slot_id
from src.runtime_v6.report_compute import build_report_compute_contract
from src.runtime_v6.report_qa import validate_p05_post_render_qa, validate_p05_pre_render_qa
from test_support.report_provenance import r5_partitions, r5_section_payloads
from test_support.report_rank20 import rank20_rows
from test_support.report_visible_body import valid_visible_body


SLOT = "2026-09-18T17:30:00+07:00"
REPORT_SLOT_ID = build_report_slot_id(logical_slot=SLOT, report_type="DEADLINE")


def _our15():
    rows = []
    for player_id in (1, 2):
        rows.append({"element_id": player_id, "position": "GK"})
    for player_id in range(3, 8):
        rows.append({"element_id": player_id, "position": "DEF"})
    for player_id in range(8, 13):
        rows.append({"element_id": player_id, "position": "MID"})
    for player_id in range(13, 16):
        rows.append({"element_id": player_id, "position": "FWD"})
    return rows


def _watchlist20():
    rows = []
    next_id = 101
    for position in ("GK", "DEF", "MID", "FWD"):
        for _ in range(5):
            rows.append({"element_id": next_id, "position": position})
            next_id += 1
    return rows


def _compute(*, watchlist=None, rise=None, fall=None):
    our15 = _our15()
    facts, models, inferences = r5_partitions(
        fact_key="official_price",
        model_key="deadline_model",
        fact_source="OFFICIAL_FPL",
        model_name="V6_DEADLINE_MODEL",
    )
    return build_report_compute_contract(
        scope_matrix_report_ready=True,
        our15_rows=our15,
        starting_xi_ids=[1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        bench_ids=[2, 7, 12, 15],
        watchlist_rows=_watchlist20() if watchlist is None else watchlist,
        rise_rows=rank20_rows(201, "RISE") if rise is None else rise,
        fall_rows=rank20_rows(301, "FALL") if fall is None else fall,
        section_payloads=r5_section_payloads(our15),
        facts=facts,
        models=models,
        inferences=inferences,
    )


def _manifest():
    return [{"section_id": section_id, "status": "COMPLETE"} for section_id in MANDATORY_SECTIONS]


def _context(events=None):
    if events is None:
        events = [
            {
                "scenario_id": "bruno-route",
                "state": "CONTEMPLATED",
                "updated_at": "2026-09-18T17:15:00+07:00",
                "visible_marker": "Bruno Fernandes",
                "player_candidates": ["Bruno Fernandes"],
                "route": {"out": "Bruno Fernandes", "in": "candidate"},
                "horizons": ["ONE_GW", "3GW", "5GW"],
            },
            {
                "scenario_id": "jp-route",
                "state": "CONTEMPLATED",
                "updated_at": "2026-09-18T17:16:00+07:00",
                "visible_marker": "João Pedro",
                "player_candidates": ["João Pedro"],
                "route": {"out": "João Pedro", "in": "candidate"},
                "horizons": ["ONE_GW", "3GW", "5GW"],
            },
            {
                "scenario_id": "sangare-route",
                "state": "CONTEMPLATED",
                "updated_at": "2026-09-18T17:17:00+07:00",
                "visible_marker": "Sangaré",
                "player_candidates": ["Sangaré"],
                "route": {"out": "Sangaré", "in": "candidate"},
                "horizons": ["ONE_GW", "3GW", "5GW"],
            },
        ]
    return hydrate_current_decision_context(
        report_slot_id=REPORT_SLOT_ID,
        hydrated_at="2026-09-18T17:28:00+07:00",
        confirmed_our15=_our15(),
        latest_confirmed_squad_state={"source": "latest-confirmed-user-state"},
        current_xi=[1, 3, 4, 5, 6, 8, 9, 10, 11, 13, 14],
        current_bench=[2, 7, 12, 15],
        latest_manual_state={"source": "screenshots"},
        scenario_events=events,
        current_horizon="ONE_GW",
        latest_user_constraints=["deadline-day", "full-universe-search"],
        locked_decisions=[],
        decision_window_open=True,
    )


def _prefetch_ready():
    return {
        "ready": True,
        "report_kind_match": True,
        "target_logical_slot_match": True,
        "scope_match": True,
        "selected_report_prefetch_run_id": "prefetch-1730",
        "selected_target_logical_report_slot": SLOT,
        "refresh_identity": f"deadline_review|{SLOT}|personal,mini_league|fpl_master_report_prefetch_recovery",
    }


def _weather_available():
    return {
        "weather_attempted": True,
        "weather_result": "AVAILABLE",
        "source": "weather-provider",
        "provenance": {"fixture": "official-venue", "request_id": "weather-1730"},
        "evaluated_at": "2026-09-18T17:28:30+07:00",
    }


def _pre(**overrides):
    kwargs = {
        "report_slot_id": REPORT_SLOT_ID,
        "evaluated_at": "2026-09-18T17:29:00+07:00",
        "compute_contract": _compute(),
        "section_manifest": _manifest(),
        "mini_league_denominator_complete": True,
        "report_mode": "DEADLINE",
        "decision_context": _context(),
        "prefetch_readiness": _prefetch_ready(),
        "weather_evidence": _weather_available(),
    }
    kwargs.update(overrides)
    return validate_p05_pre_render_qa(**kwargs)


def _body(pre):
    return (
        valid_visible_body(pre)
        + "\n\nACTIVE USER SCENARIOS: Bruno Fernandes | João Pedro | Sangaré\n"
    )


def _post(pre=None, **overrides):
    pre = pre or _pre()
    kwargs = {
        "pre_render_qa": pre,
        "report_slot_id": REPORT_SLOT_ID,
        "evaluated_at": "2026-09-18T17:29:20+07:00",
        "render_completed_at": "2026-09-18T17:29:10+07:00",
        "rendered_report_mode": "DEADLINE",
        "rendered_body": _body(pre),
        "rendered_section_ids": pre["expected_section_ids"],
        "rendered_section_states": {
            row["section_id"]: row["status"] for row in pre["section_manifest"]
        },
        "rendered_compute_fingerprint": pre["compute_fingerprint"],
        "render_contract_token": pre["render_contract_token"],
        "rendered_counts": pre["expected_counts"],
        "rendered_fact_keys": pre["expected_fact_keys"],
        "rendered_model_keys": pre["expected_model_keys"],
        "rendered_mini_league_denominator_complete": (
            pre["mini_league_contract_state"] == "COMPLETE"
        ),
        "rendered_weather_direct_chat_present": (
            pre["weather_contract_state"] == "DIRECT_CHATGPT"
        ),
        "rendered_weather_contract_state": pre["weather_contract_state"],
        "truncated": False,
        "status_only": False,
    }
    kwargs.update(overrides)
    return validate_p05_post_render_qa(**kwargs)


def _publication(*, generated_at="2026-09-18T17:20:00+07:00", sha="a" * 40):
    return {
        "generated_at": generated_at,
        "authoritative_runtime_snapshot": True,
        "publish_integrity": "PASS",
        "provenance_valid": True,
        "available_scopes": ["deadline_report"],
        "publication_sha": sha,
    }


def test_01_original_generic_wait_body_is_red():
    pre = _pre()
    post = _post(
        pre,
        rendered_body="FPL DEADLINE REPORT 17:30 WIB\n\nKeputusan: WAIT.",
        rendered_section_ids=[],
        rendered_section_states={},
        rendered_counts={},
        rendered_fact_keys=[],
        rendered_model_keys=[],
    )
    assert post["status"] == "FAIL"
    assert post["can_emit"] is False


def test_02_in_progress_with_recent_authoritative_publication_is_not_blanket_degraded():
    result = resolve_report_data_readiness(
        current_acquisition_state="IN_PROGRESS",
        current_acquisition_id="v6-1730",
        current_publication=None,
        authoritative_publications=[_publication()],
        observed_at="2026-09-18T17:29:00+07:00",
        maximum_age_minutes=35,
        required_scope="deadline_report",
        waited_seconds=0,
    )
    assert result["status"] == "PASS"
    assert result["readiness_state"] == "CURRENT_ACQUISITION_IN_PROGRESS"
    assert result["source"] == "FRESHEST_VALID_AUTHORITATIVE_PUBLICATION_WITHIN_SLA"
    assert result["blanket_degraded"] is False
    assert result["poll_same_acquisition"] is True


def test_03_acquisition_completion_replaces_prior_snapshot():
    prior = resolve_report_data_readiness(
        current_acquisition_state="IN_PROGRESS",
        current_acquisition_id="v6-1730",
        current_publication=None,
        authoritative_publications=[_publication(sha="a" * 40)],
        observed_at="2026-09-18T17:29:00+07:00",
        maximum_age_minutes=35,
        required_scope="deadline_report",
        waited_seconds=5,
    )
    newest = resolve_report_data_readiness(
        current_acquisition_state="COMPLETE",
        current_acquisition_id="v6-1730",
        current_publication=_publication(
            generated_at="2026-09-18T17:29:05+07:00", sha="b" * 40
        ),
        authoritative_publications=[_publication(sha="a" * 40)],
        observed_at="2026-09-18T17:29:10+07:00",
        maximum_age_minutes=35,
        required_scope="deadline_report",
        waited_seconds=10,
    )
    assert prior["recompute_on_current_completion"] is True
    assert newest["source"] == "FRESH_CURRENT_PUBLICATION"
    assert newest["publication_validation"]["publication_sha"] == "b" * 40


def test_04_in_progress_never_starts_duplicate_acquisition():
    result = resolve_report_data_readiness(
        current_acquisition_state="IN_PROGRESS",
        current_acquisition_id="v6-1730",
        current_publication=None,
        authoritative_publications=[],
        observed_at="2026-09-18T17:29:00+07:00",
        maximum_age_minutes=35,
        required_scope="deadline_report",
        waited_seconds=5,
    )
    assert result["start_new_acquisition"] is False
    assert result["duplicate_acquisition_allowed"] is False
    assert result["next_action"] == "BOUNDED_WAIT_SAME_ACQUISITION"


def test_05_active_bruno_jp_sangare_scenarios_are_preserved_and_visible():
    context = _context()
    assert context["active_scenario_count"] == 3
    assert context["active_scenario_ids"] == ["bruno-route", "jp-route", "sangare-route"]
    post = _post()
    assert post["status"] == "PASS"
    assert post["active_scenario_ids_missing"] == []


def test_06_contemplated_transfer_is_not_treated_as_executed():
    context = _context()
    assert context["executed_scenario_ids"] == []
    assert all(row["state"] == "CONTEMPLATED" for row in context["active_scenarios"])


def test_07_optimizer_omission_cannot_remove_active_user_scenario():
    context = _context()
    optimizer_selected = {"optimizer-alternative"}
    assert "sangare-route" not in optimizer_selected
    assert "sangare-route" in context["active_scenario_ids"]


def test_08_latest_explicit_execution_supersedes_contemplated_state():
    events = [
        {
            "scenario_id": "jp-route",
            "state": "CONTEMPLATED",
            "updated_at": "2026-09-18T17:10:00+07:00",
            "visible_marker": "João Pedro",
            "player_candidates": ["João Pedro"],
        },
        {
            "scenario_id": "jp-route",
            "state": "EXECUTED",
            "updated_at": "2026-09-18T17:20:00+07:00",
            "visible_marker": "João Pedro",
            "player_candidates": ["João Pedro"],
        },
    ]
    context = _context(events)
    assert context["active_scenario_ids"] == []
    assert context["executed_scenario_ids"] == ["jp-route"]


def test_09_stale_prefetch_requests_exactly_one_governed_refresh():
    snapshot = {
        "report_kind": "deadline_review",
        "target_logical_report_slot": SLOT,
        "scope": ["personal", "mini_league"],
        "generated_at": "2026-09-18T16:00:00+07:00",
        "public_core_complete": True,
        "complete": True,
        "report_prefetch_run_id": "prefetch-old",
    }
    first = report_prefetch.evaluate_report_prefetch_readiness(
        snapshot,
        report_kind="deadline_review",
        requested_logical_slot=SLOT,
        maximum_age_minutes=35,
        refresh_attempt=0,
        max_refresh_attempts=1,
        scope=("personal", "mini_league"),
        observed_at="2026-09-18T17:29:00+07:00",
    )
    exhausted = report_prefetch.evaluate_report_prefetch_readiness(
        snapshot,
        report_kind="deadline_review",
        requested_logical_slot=SLOT,
        maximum_age_minutes=35,
        refresh_attempt=1,
        max_refresh_attempts=1,
        scope=("personal", "mini_league"),
        observed_at="2026-09-18T17:29:00+07:00",
    )
    assert first["refresh_required"] is True
    assert first["refresh_transport"] == "ISSUE_431_COMMENT"
    assert exhausted["refresh_required"] is False


def test_10_prefetch_identity_mismatch_fails_pre_render_gate():
    prefetch = _prefetch_ready()
    prefetch["ready"] = False
    prefetch["target_logical_slot_match"] = False
    result = _pre(prefetch_readiness=prefetch)
    assert result["status"] == "FAIL"
    assert "PREFETCH_IDENTITY_GATE_FAILED" in result["failed_checks"]


def test_11_missing_watchlist20_fails_pre_render():
    result = _pre(compute_contract=_compute(watchlist=[]))
    assert result["status"] == "FAIL"
    assert result["can_render"] is False


def test_12_missing_rise20_fails_pre_render():
    result = _pre(compute_contract=_compute(rise=[]))
    assert result["status"] == "FAIL"
    assert result["can_render"] is False


def test_13_missing_fall20_fails_pre_render():
    result = _pre(compute_contract=_compute(fall=[]))
    assert result["status"] == "FAIL"
    assert result["can_render"] is False


def test_14_single_degraded_field_does_not_remove_structural_section():
    manifest = _manifest()
    for row in manifest:
        if row["section_id"] == "S14B":
            row["status"] = "PARTIAL"
    result = _pre(
        section_manifest=manifest,
        mini_league_denominator_complete=False,
    )
    assert result["status"] == "PASS"
    assert result["mini_league_contract_state"] == "DEGRADED"
    assert "S14B" in result["expected_section_ids"]


def test_15_weather_available_requires_real_attempt_metadata():
    result = _pre()
    assert result["status"] == "PASS"
    assert result["weather_attempt"]["weather_attempted"] is True
    assert result["weather_attempt"]["source"] == "weather-provider"
    assert result["weather_attempt"]["provenance"]


def test_16_weather_failure_is_degraded_only_after_attempt():
    weather = {
        "weather_attempted": True,
        "weather_result": "DEGRADED_AFTER_ATTEMPT",
        "source": "weather-provider",
        "provenance": {"request_id": "weather-failed", "error": "provider_unavailable"},
        "evaluated_at": "2026-09-18T17:28:30+07:00",
    }
    result = _pre(weather_evidence=weather)
    assert result["status"] == "PASS"
    assert result["weather_contract_state"] == "SOURCE_DEGRADED"


def test_17_status_only_body_cannot_masquerade_as_canonical_report():
    pre = _pre()
    result = _post(pre, status_only=True)
    assert result["status"] == "FAIL"
    assert result["can_emit"] is False
    assert "STATUS_ONLY_NOT_CANONICAL_REPORT" in result["failed_checks"]


def test_18_full_repaired_fixture_passes_post_render_and_only_then_can_emit():
    pre = _pre()
    assert pre["status"] == "PASS"
    assert pre["can_emit"] is False
    post = _post(pre)
    assert post["status"] == "PASS"
    assert post["pre_render_qa_pass"] is True
    assert post["post_render_qa_pass"] is True
    assert post["report_contract_pass"] is True
    assert post["can_emit"] is True
    assert post["visible_emitted"] is False
