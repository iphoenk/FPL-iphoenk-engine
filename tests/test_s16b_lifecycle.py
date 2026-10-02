from __future__ import annotations

from src.engines.v12_s16b_lifecycle import (
    STATE_SCHEMA,
    assess_post_match_evidence_ready,
    normalize_delivery_state,
    resolve_completed_gw,
    resolve_s16b_context,
    state_after_occurrence,
)


def _fixtures(gw: int = 6, count: int = 10, *, unfinished: int | None = None):
    rows = []
    for index in range(1, count + 1):
        finished = index != unfinished
        rows.append(
            {
                "id": 6000 + index,
                "event": gw,
                "started": True if finished else False,
                "finished": finished,
                "team_h": index,
                "team_a": index + 20,
            }
        )
    return rows


def _settled_rows(gw: int = 6, count: int = 10, *, omit: int | None = None):
    rows = []
    for index in range(1, count + 1):
        if index == omit:
            continue
        rows.append(
            {
                "gw": gw,
                "fixture": 6000 + index,
                "player_id": 100 + index,
                "minutes": 90,
                "total_points": index % 8,
            }
        )
    return rows


def _prior(last_delivered_gw: int = 5):
    return {
        "schema": STATE_SCHEMA,
        "baseline_completed_gw": last_delivered_gw,
        "last_delivered_gw": last_delivered_gw,
        "delivered_occurrence": f"DEEP|GW{last_delivered_gw}",
        "body_fingerprint": "abc",
        "generated_at": "2026-09-29T04:30:00+07:00",
        "migration": "ESTABLISHED",
    }


def test_a_gw_still_live_0430_s16b_absent():
    context = resolve_s16b_context(
        report_slot="2026-10-03T04:30:00+07:00",
        report_mode="DEEP",
        fixtures=_fixtures(unfinished=10),
        player_match_rows=_settled_rows(omit=10),
        prior_delivery_state=_prior(),
    )
    assert context["s16b_due"] is False
    assert context["expected_section_count"] == 22
    assert context["due_reason"] == "GW_NOT_FULLY_COMPLETE"


def test_b_finished_ready_0430_s16b_due():
    context = resolve_s16b_context(
        report_slot="2026-10-03T04:30:00+07:00",
        report_mode="DEEP",
        fixtures=_fixtures(),
        player_match_rows=_settled_rows(),
        prior_delivery_state=_prior(),
    )
    assert context["completed_gw"] == 6
    assert context["gw_completion"]["expected_fixture_count"] == 10
    assert context["gw_completion"]["completed_fixture_count"] == 10
    assert context["post_match_evidence"]["ready"] is True
    assert context["s16b_due"] is True
    assert context["expected_section_count"] == 23


def test_c_finished_ready_1230_never_due():
    context = resolve_s16b_context(
        report_slot="2026-10-03T12:30:00+07:00",
        report_mode="DEEP",
        fixtures=_fixtures(),
        player_match_rows=_settled_rows(),
        prior_delivery_state=_prior(),
    )
    assert context["s16b_due"] is False
    assert context["due_reason"] == "NOT_04_30_ASIA_JAKARTA"
    assert context["expected_section_count"] == 22


def test_d_finished_ready_2130_never_due():
    context = resolve_s16b_context(
        report_slot="2026-10-03T21:30:00+07:00",
        report_mode="DEEP",
        fixtures=_fixtures(),
        player_match_rows=_settled_rows(),
        prior_delivery_state=_prior(),
    )
    assert context["s16b_due"] is False
    assert context["due_reason"] == "NOT_04_30_ASIA_JAKARTA"


def test_e_once_delivered_next_0430_absent():
    first = resolve_s16b_context(
        report_slot="2026-10-03T04:30:00+07:00",
        report_mode="DEEP",
        fixtures=_fixtures(),
        player_match_rows=_settled_rows(),
        prior_delivery_state=_prior(),
    )
    delivered = state_after_occurrence(
        first,
        occurrence_id="DEEP|2026-10-03T04:30:00+07:00",
        generated_at="2026-10-03T04:40:00+07:00",
        body_fingerprint="body",
    )
    later = resolve_s16b_context(
        report_slot="2026-10-04T04:30:00+07:00",
        report_mode="DEEP",
        fixtures=_fixtures(),
        player_match_rows=_settled_rows(),
        prior_delivery_state=delivered,
    )
    assert later["s16b_due"] is False
    assert later["due_reason"] == "ALREADY_DELIVERED_FOR_COMPLETED_GW"
    assert later["expected_section_count"] == 22


def test_f_finished_but_match_facts_not_settled_defer_then_due():
    deferred = resolve_s16b_context(
        report_slot="2026-10-03T04:30:00+07:00",
        report_mode="DEEP",
        fixtures=_fixtures(),
        player_match_rows=_settled_rows(omit=10),
        prior_delivery_state=_prior(),
    )
    assert deferred["s16b_due"] is False
    assert deferred["due_reason"] == "MATCH_LEVEL_FACTS_NOT_SETTLED"

    next_day = resolve_s16b_context(
        report_slot="2026-10-04T04:30:00+07:00",
        report_mode="DEEP",
        fixtures=_fixtures(),
        player_match_rows=_settled_rows(),
        prior_delivery_state=_prior(),
    )
    assert next_day["s16b_due"] is True


def test_g_ten_match_gw_completion_proof_exact():
    proof = resolve_completed_gw(_fixtures())
    assert proof["completed_gw"] == 6
    assert proof["proof"]["expected_fixture_count"] == 10
    assert proof["proof"]["completed_fixture_count"] == 10
    assert len(set(proof["proof"]["expected_fixture_ids"])) == 10


def test_h_postponed_or_unfinished_fixture_blocks_final_review():
    proof = resolve_completed_gw(_fixtures(unfinished=4))
    assert proof["completed_gw"] is None
    assert proof["proof"] == {}


def test_i_missing_advanced_metric_does_not_block_readiness():
    completion = resolve_completed_gw(_fixtures())
    rows = _settled_rows()
    assert all("xg" not in row for row in rows)
    ready = assess_post_match_evidence_ready(
        completed_gw=completion["completed_gw"],
        completed_gw_proof=completion["proof"],
        player_match_rows=rows,
    )
    assert ready["ready"] is True
    assert ready["advanced_metrics_required"] is False


def test_prospective_migration_does_not_manufacture_historical_delivery():
    state = normalize_delivery_state(None, completed_gw=6)
    assert state["baseline_completed_gw"] == 6
    assert state["last_delivered_gw"] == 6
    assert state["delivered_occurrence"] is None
    assert state["migration"] == "PROSPECTIVE_BASELINE_NO_HISTORICAL_INVENTION"

    context = resolve_s16b_context(
        report_slot="2026-10-03T04:30:00+07:00",
        report_mode="DEEP",
        fixtures=_fixtures(),
        player_match_rows=_settled_rows(),
        prior_delivery_state=None,
    )
    assert context["s16b_due"] is False
    assert context["due_reason"] == "ALREADY_DELIVERED_FOR_COMPLETED_GW"
