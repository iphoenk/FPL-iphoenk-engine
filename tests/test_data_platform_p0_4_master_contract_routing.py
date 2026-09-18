from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from src.runtime_v6.domains.report_plane.report_contract import (
    evaluate_rolling_natural_acceptance,
    resolve_master_report_occurrence,
)

JKT = ZoneInfo("Asia/Jakarta")


def dt(day: int, hour: int, minute: int, second: int = 0, microsecond: int = 0) -> datetime:
    return datetime(2030, 1, day, hour, minute, second, microsecond, tzinfo=JKT)


def route(
    *,
    intended: datetime,
    observed: datetime | None = None,
    deadline: datetime | None = None,
    match_live: bool = False,
    post_all_match_due: bool = False,
    v6_degraded: bool = False,
    transport_failed: bool = False,
    report_prefetch_state: str = "CURRENT",
):
    return resolve_master_report_occurrence(
        intended_report_slot=intended,
        observed_at=observed or intended,
        official_deadline=deadline,
        match_live=match_live,
        post_all_match_due=post_all_match_due,
        v6_degraded=v6_degraded,
        transport_failed=transport_failed,
        report_prefetch_state=report_prefetch_state,
    )


def natural_row(hour: int, *, visible_due: bool = False, delivered: bool = True) -> dict:
    logical = dt(1, hour % 24, 0).isoformat()
    return {
        "logical_slot": logical,
        "natural": True,
        "schedule_kind": "chatgpt_scheduler",
        "core_acceptance": "PASS",
        "manual": False,
        "recovery": False,
        "report_prefetch": False,
        "ad_hoc": False,
        "retro": False,
        "future_fill": False,
        "mandatory_visible_report": visible_due,
        "report_contract_pass": delivered if visible_due else False,
        "report_slot_fulfilled": delivered if visible_due else False,
        "delivery_proof_valid": delivered if visible_due else False,
        "visible_emitted": delivered if visible_due else False,
        "status_only": False,
    }


def test_01_normal_on_time_silent_hourly():
    result = route(intended=dt(1, 3, 30))
    assert result["occurrence_state"] == "ON_TIME"
    assert result["route_mode"] == "SILENT"
    assert result["visible_occurrence_due"] is False


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(4, "DEEP"), (5, "PRICE"), (12, "DEEP"), (21, "DEEP")],
)
def test_02_05_normal_fixed_visible_routes(hour: int, expected: str):
    result = route(intended=dt(1, hour, 30))
    assert result["route_mode"] == expected
    assert result["visible_occurrence_due"] is True


def test_06_deadline_active_on_time_hourly():
    deadline = dt(2, 18, 30)
    result = route(intended=dt(2, 16, 30), deadline=deadline)
    assert result["occurrence_state"] == "ON_TIME"
    assert result["route_mode"] == "DEADLINE"
    assert result["visible_occurrence_due"] is True


def test_07_deadline_active_plus_217_seconds_is_late_recoverable_and_still_due():
    deadline = dt(2, 18, 30)
    intended = dt(2, 16, 30)
    observed = intended + timedelta(seconds=217, microseconds=920157)
    result = route(intended=intended, observed=observed, deadline=deadline)
    assert result["occurrence_state"] == "LATE_RECOVERABLE"
    assert result["route_mode"] == "DEADLINE"
    assert result["visible_occurrence_due"] is True
    assert result["late_catch_up"] is True
    assert result["intended_report_slot"] == intended.isoformat()
    assert result["observed_at"] == observed.isoformat()


def test_08_occurrence_and_recovery_boundaries_are_deterministic():
    intended = dt(2, 16, 30)
    deadline = dt(2, 18, 30)
    cases = [
        (89, "ON_TIME"),
        (90, "ON_TIME"),
        (91, "LATE_RECOVERABLE"),
        (217, "LATE_RECOVERABLE"),
    ]
    for seconds, expected in cases:
        result = route(
            intended=intended,
            observed=intended + timedelta(seconds=seconds),
            deadline=deadline,
        )
        assert result["occurrence_state"] == expected

    boundary = intended + timedelta(hours=1)
    assert route(intended=intended, observed=boundary - timedelta(seconds=1), deadline=deadline)["occurrence_state"] == "LATE_RECOVERABLE"
    assert route(intended=intended, observed=boundary, deadline=deadline)["occurrence_state"] == "LATE_RECOVERABLE"
    expired = route(intended=intended, observed=boundary + timedelta(seconds=1), deadline=deadline)
    assert expired["occurrence_state"] == "LATE_EXPIRED"
    assert expired["visible_occurrence_due"] is False
    assert expired["historical_delivery_state"] == "UNDELIVERED"


def test_09_deadline_to_final_boundary_uses_first_canonical_checkpoint():
    deadline = dt(2, 18, 30)
    before = route(intended=dt(2, 16, 30), deadline=deadline)
    first_final = route(intended=dt(2, 17, 30), deadline=deadline)
    at_lock = route(intended=deadline, deadline=deadline)
    post_lock = route(intended=dt(2, 19, 30), deadline=deadline)

    assert before["route_mode"] == "DEADLINE"
    assert first_final["route_mode"] == "FINAL"
    assert first_final["first_final_checkpoint"] == dt(2, 17, 30).isoformat()
    assert at_lock["deadline_locked"] is True
    assert at_lock["route_mode"] not in {"DEADLINE", "FINAL"}
    assert post_lock["deadline_locked"] is True


def test_09b_midnight_band_final_window_uses_three_hours_then_canonical_checkpoint():
    deadline = dt(2, 1, 30)
    result = route(intended=dt(1, 22, 30), deadline=deadline)
    assert result["first_final_checkpoint"] == dt(1, 22, 30).isoformat()
    assert result["route_mode"] == "FINAL"


def test_10_pure_match():
    result = route(intended=dt(1, 10, 30), match_live=True)
    assert result["route_mode"] == "MATCH"
    assert result["visible_occurrence_due"] is True


def test_11_full_plus_match():
    result = route(intended=dt(1, 12, 30), match_live=True)
    assert result["route_mode"] == "FULL+MATCH"


def test_12_deadline_plus_match():
    deadline = dt(2, 18, 30)
    result = route(intended=dt(2, 16, 30), deadline=deadline, match_live=True)
    assert result["route_mode"] == "DEADLINE+MATCH"


def test_13_final_plus_match():
    deadline = dt(2, 18, 30)
    result = route(intended=dt(2, 17, 30), deadline=deadline, match_live=True)
    assert result["route_mode"] == "FINAL+MATCH"


def test_14_post_all_match():
    result = route(intended=dt(1, 21, 30), post_all_match_due=True)
    assert result["route_mode"] == "POST_ALL_MATCH"
    assert result["visible_occurrence_due"] is True


def test_15_v6_degraded_cannot_cancel_due_report():
    deadline = dt(2, 18, 30)
    result = route(intended=dt(2, 16, 30), deadline=deadline, v6_degraded=True)
    assert result["visible_occurrence_due"] is True
    assert result["delivery_required"] is True
    assert result["v6_degraded"] is True


def test_16_transport_failure_cannot_cancel_due_report():
    deadline = dt(2, 18, 30)
    result = route(intended=dt(2, 16, 30), deadline=deadline, transport_failed=True)
    assert result["visible_occurrence_due"] is True
    assert result["delivery_required"] is True
    assert result["transport_failed"] is True


def test_17_report_prefetch_stale_routes_governed_refresh_without_suppressing_report():
    result = route(
        intended=dt(1, 12, 30),
        report_prefetch_state="STALE",
    )
    assert result["visible_occurrence_due"] is True
    assert result["report_prefetch_action"] == "GOVERNED_REFRESH_THEN_CONTINUE"


def test_18_status_only_candidate_is_rejected_for_visible_natural_acceptance():
    rows = [natural_row(hour) for hour in range(12)]
    rows[-1] = natural_row(11, visible_due=True, delivered=False)
    rows[-1]["status_only"] = True
    result = evaluate_rolling_natural_acceptance(rows)
    assert result["production_green"] is False
    assert result["pass_count"] == 11
    assert result["latest_window"][-1]["acceptance"] == "FAIL"


def test_19_duplicate_scheduler_occurrence_is_rejected():
    rows = [natural_row(hour) for hour in range(12)]
    duplicate = dict(rows[-1])
    rows.append(duplicate)
    result = evaluate_rolling_natural_acceptance(rows)
    assert result["production_green"] is False
    assert result["duplicate_logical_slots"]


def test_20_rolling_12_of_12_only_counts_genuine_natural_occurrences():
    rows = [natural_row(hour, visible_due=(hour in {4, 5})) for hour in range(12)]
    noise = natural_row(12)
    noise.update({"natural": False, "manual": True, "logical_slot": dt(1, 12, 0).isoformat()})
    rows.append(noise)

    result = evaluate_rolling_natural_acceptance(rows)
    assert result["window_target"] == 12
    assert result["countable_natural_count"] == 12
    assert result["pass_count"] == 12
    assert result["production_green"] is True


def test_final_0530_overlap_embeds_price_obligation_without_duplicate_report():
    deadline = dt(2, 6, 30)
    result = route(intended=dt(2, 5, 30), deadline=deadline)
    assert result["route_mode"] == "FINAL"
    assert "PRICE" in result["embedded_obligations"]
    assert result["visible_report_count"] == 1
