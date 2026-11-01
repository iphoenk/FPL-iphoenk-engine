from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.engines.v12_delivery_schedule import (
    deadline_checkpoints,
    is_price_checkpoint,
    precompute_window,
    price_checkpoint_for_london_date,
    resolve_delivery_decision,
)


WIB = ZoneInfo("Asia/Jakarta")
LONDON = ZoneInfo("Europe/London")


def test_fixed_deep_slots_and_silent_other_half_hours():
    for hour in (4, 12, 21):
        got = resolve_delivery_decision(datetime(2026, 9, 27, hour, 30, tzinfo=WIB))
        assert got.visible is True
        assert "DEEP" in got.obligations
        assert got.single_visible_report is True

    silent = resolve_delivery_decision(datetime(2026, 9, 27, 10, 30, tzinfo=WIB))
    assert silent.visible is False
    assert silent.obligations == ()


def test_price_is_2330_london_and_moves_from_0530_to_0630_wib_across_dst():
    bst = price_checkpoint_for_london_date(datetime(2026, 10, 24, tzinfo=LONDON).date())
    gmt = price_checkpoint_for_london_date(datetime(2026, 10, 25, tzinfo=LONDON).date())
    next_gmt = price_checkpoint_for_london_date(datetime(2026, 10, 26, tzinfo=LONDON).date())

    assert bst.isoformat() == "2026-10-25T05:30:00+07:00"
    assert gmt.isoformat() == "2026-10-26T06:30:00+07:00"
    assert next_gmt.isoformat() == "2026-10-27T06:30:00+07:00"
    assert is_price_checkpoint(bst)
    assert is_price_checkpoint(gmt)
    assert is_price_checkpoint(next_gmt)


def test_dst_window_has_exactly_one_price_publication_per_london_day():
    for london_day in (
        datetime(2026, 10, 24, tzinfo=LONDON).date(),
        datetime(2026, 10, 25, tzinfo=LONDON).date(),
        datetime(2026, 10, 26, tzinfo=LONDON).date(),
    ):
        target = price_checkpoint_for_london_date(london_day)
        local_day = target.date()
        candidates = [
            datetime(local_day.year, local_day.month, local_day.day, 5, 30, tzinfo=WIB),
            datetime(local_day.year, local_day.month, local_day.day, 6, 30, tzinfo=WIB),
        ]
        assert sum(is_price_checkpoint(row) for row in candidates) == 1


def test_deadline_matrix_is_exact_and_ordered():
    deadline = datetime(2026, 10, 10, 17, 0, tzinfo=WIB)
    rows = deadline_checkpoints(deadline)
    assert [row.key for row in rows] == [
        "T-24H", "T-12H", "T-6H", "T-3H", "T-2H",
        "T-1H", "T-30M", "T-15M", "T-5M",
    ]
    assert [row.contract for row in rows] == [
        "DEEP", "DEEP", "DEEP", "DEEP", "DELTA",
        "DELTA_EXECUTION", "FINAL_REVIEW", "GO_NO_GO", "FINAL_CONFIRMATION",
    ]
    assert rows[-1].at == datetime(2026, 10, 10, 16, 55, tzinfo=WIB)


def test_deadline_checkpoint_matches_by_absolute_instant():
    deadline = datetime(2026, 10, 10, 17, 0, tzinfo=WIB)
    t15 = datetime(2026, 10, 10, 16, 45, tzinfo=WIB)
    got = resolve_delivery_decision(t15, official_deadline=deadline)
    assert got.visible is True
    assert got.deadline_checkpoint == "T-15M"
    assert got.primary_mode == "DEADLINE:GO_NO_GO"


def test_pre_t3_deadline_checkpoint_does_not_break_quiet_hours():
    deadline = datetime(2026, 9, 28, 1, 0, tzinfo=WIB)
    t24 = datetime(2026, 9, 27, 1, 0, tzinfo=WIB)
    got = resolve_delivery_decision(t24, official_deadline=deadline)
    assert got.deadline_checkpoint == "T-24H"
    assert got.quiet_window is True
    assert got.quiet_suppressed is True
    assert got.visible is False


def test_quiet_match_is_suppressed_but_owner_and_t3_deadline_are_visible():
    quiet = datetime(2026, 9, 27, 1, 30, tzinfo=WIB)
    match = resolve_delivery_decision(quiet, match_live=True)
    assert match.quiet_window is True
    assert match.quiet_suppressed is True
    assert match.visible is False

    owner = resolve_delivery_decision(quiet, owner_adhoc=True)
    assert owner.visible is True
    assert owner.quiet_suppressed is False

    deadline = datetime(2026, 9, 27, 4, 0, tzinfo=WIB)
    t3 = datetime(2026, 9, 27, 1, 0, tzinfo=WIB)
    deadline_mode = resolve_delivery_decision(t3, official_deadline=deadline)
    assert deadline_mode.visible is True
    assert deadline_mode.deadline_checkpoint == "T-3H"


def test_overlap_is_one_report_with_all_obligations():
    observed = datetime(2026, 9, 27, 12, 30, tzinfo=WIB)
    deadline = datetime(2026, 9, 28, 12, 30, tzinfo=WIB)
    got = resolve_delivery_decision(
        observed,
        official_deadline=deadline,
        match_live=True,
    )
    assert got.visible is True
    assert got.single_visible_report is True
    assert set(got.obligations) == {"DEEP", "MATCH", "DEADLINE:DEEP"}
    assert got.primary_mode == "DEADLINE:DEEP"


def test_precompute_window_is_t15_to_t10():
    slot = datetime(2026, 9, 27, 12, 30, tzinfo=WIB)
    start, freeze_target = precompute_window(slot)
    assert start == datetime(2026, 9, 27, 12, 15, tzinfo=WIB)
    assert freeze_target == datetime(2026, 9, 27, 12, 20, tzinfo=WIB)


def test_t24_deadline_is_a_visible_deep_occurrence():
    deadline = datetime(2026, 10, 10, 17, 0, tzinfo=WIB)
    t24 = datetime(2026, 10, 9, 17, 0, tzinfo=WIB)
    got = resolve_delivery_decision(t24, official_deadline=deadline)
    assert got.visible is True
    assert got.deadline_checkpoint == "T-24H"
    assert got.primary_mode == "DEADLINE:DEEP"
    assert got.single_visible_report is True


def test_deadline_checkpoint_and_match_are_one_report():
    deadline = datetime(2026, 10, 10, 17, 0, tzinfo=WIB)
    t3 = datetime(2026, 10, 10, 14, 0, tzinfo=WIB)
    got = resolve_delivery_decision(t3, official_deadline=deadline, match_live=True)
    assert got.deadline_checkpoint == "T-3H"
    assert set(got.obligations) == {"MATCH", "DEADLINE:DEEP"}
    assert got.single_visible_report is True


def test_existing_orchestrator_admits_exact_t30_final_review_not_other_deadline_modes():
    """Strict existing full-DEEP path accepts only matching governed T-30M FINAL_REVIEW."""
    from pathlib import Path

    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github" / "workflows" / "fpl-master-occurrence-orchestrator.yml"
    ).read_text(encoding="utf-8")
    assert 'if official_deadline is None:' in workflow
    assert 'if candidate == dt and (' in workflow
    assert 'contract == "DEEP"' in workflow
    assert '(key == "T-30M" and contract == "FINAL_REVIEW")' in workflow
    assert 'if len(matches) != 1:' in workflow
    assert 'raise SystemExit("DEEP occurrence is not an exact governed deadline checkpoint")' in workflow

    deadline = datetime(2026, 10, 17, 17, 0, tzinfo=WIB)
    rows = deadline_checkpoints(deadline)
    permitted = [
        item for item in rows
        if item.contract == "DEEP"
        or (item.key == "T-30M" and item.contract == "FINAL_REVIEW")
    ]
    assert [x.key for x in permitted] == [
        "T-24H", "T-12H", "T-6H", "T-3H", "T-30M",
    ]
    assert [x.at.strftime("%H:%M") for x in permitted[-2:]] == ["14:00", "16:30"]
    assert all(
        item not in permitted
        for item in rows if item.contract in {"DELTA", "DELTA_EXECUTION", "GO_NO_GO", "FINAL_CONFIRMATION"}
    )



# BARATAYUDA night-MATCH acceptance, no second scheduler or model.
def _night_match_event(**overrides):
    row = {
        "authority": "OFFICIAL_FPL",
        "owner_locked_picks_verified": True,
        "official_event_facts_verified": True,
        "scoring_gw": 10,
        "official_fixture_id": 9876,
        "checked_at": "2026-11-01T18:29:00Z",
        "event_kind": "OWNER_MATCH_STARTED",
        "previous_value": "NOT_STARTED",
        "current_value": "LIVE",
        "owner_fixture_verified": True,
        "captain_locked_verified": True,
        "league_coverage_full": True,
    }
    row.update(overrides)
    return row


def test_night_match_verified_owner_kickoff_bypasses_quiet_once():
    slot = datetime(2026, 11, 2, 1, 30, tzinfo=WIB)
    resolved = resolve_delivery_decision(
        slot, match_live=True, match_material_evidence=_night_match_event()
    )
    assert resolved.visible is True
    assert resolved.quiet_window is True
    assert resolved.quiet_suppressed is False
    assert resolved.material_match_override is True
    assert resolved.primary_mode == "MATCH"
    assert resolved.single_visible_report is True
    assert resolved.material_match_event_key.startswith("GW10|FIX9876|")


def test_night_match_owner_points_delta_is_material():
    slot = datetime(2026, 11, 2, 1, 30, tzinfo=WIB)
    resolved = resolve_delivery_decision(
        slot, match_live=True,
        match_material_evidence=_night_match_event(
            event_kind="OWNER_POINTS_CHANGED",
            previous_value=3, current_value=8,
        ),
    )
    assert resolved.visible
    assert "OWNER_POINTS_CHANGED|3>8" in resolved.material_match_event_key


def test_night_match_captain_delta_requires_locked_captain():
    slot = datetime(2026, 11, 2, 1, 30, tzinfo=WIB)
    event = _night_match_event(
        event_kind="CAPTAIN_POINTS_CHANGED",
        previous_value=2, current_value=5, captain_locked_verified=False,
    )
    assert not resolve_delivery_decision(
        slot, match_live=True, match_material_evidence=event
    ).visible
    event["captain_locked_verified"] = True
    assert resolve_delivery_decision(
        slot, match_live=True, match_material_evidence=event
    ).visible


def test_night_match_live_league_rank_change_requires_full_coverage():
    slot = datetime(2026, 11, 2, 1, 30, tzinfo=WIB)
    event = _night_match_event(
        event_kind="LEAGUE_RANK_CHANGED",
        previous_value=7, current_value=6, league_coverage_full=False,
    )
    assert not resolve_delivery_decision(
        slot, match_live=True, match_material_evidence=event
    ).visible
    event["league_coverage_full"] = True
    assert resolve_delivery_decision(
        slot, match_live=True, match_material_evidence=event
    ).visible


def test_night_match_verified_owner_finish_can_report_post_all_match_once():
    slot = datetime(2026, 11, 2, 1, 30, tzinfo=WIB)
    event = _night_match_event(
        event_kind="OWNER_MATCH_FINISHED",
        previous_value="LIVE", current_value="FINAL",
    )
    resolved = resolve_delivery_decision(
        slot, post_all_match=True, match_material_evidence=event,
    )
    assert resolved.visible
    assert resolved.primary_mode == "POST_ALL_MATCH"
    assert resolved.single_visible_report


def test_night_match_stale_or_future_evidence_never_bypasses_quiet():
    slot = datetime(2026, 11, 2, 1, 30, tzinfo=WIB)
    for when in ("2026-11-01T16:00:00Z", "2026-11-01T18:31:00Z", "BAD", ""):
        assert not resolve_delivery_decision(
            slot, match_live=True,
            match_material_evidence=_night_match_event(checked_at=when),
        ).visible


def test_night_match_dedupes_exact_material_event_key():
    slot = datetime(2026, 11, 2, 1, 30, tzinfo=WIB)
    event = _night_match_event()
    first = resolve_delivery_decision(
        slot, match_live=True, match_material_evidence=event
    )
    second = resolve_delivery_decision(
        slot, match_live=True, match_material_evidence=event,
        last_delivered_match_event_key=first.material_match_event_key,
    )
    assert first.visible and not second.visible
    assert second.material_match_reason == "MATCH_EVENT_ALREADY_DELIVERED"


def test_night_match_unknown_source_or_unverified_picks_is_suppressed():
    slot = datetime(2026, 11, 2, 1, 30, tzinfo=WIB)
    for changes in (
        {"authority": "DASHBOARD"},
        {"owner_locked_picks_verified": False},
        {"official_event_facts_verified": False},
        {"scoring_gw": 0},
        {"official_fixture_id": None},
        {"event_kind": "UNSPECIFIED_HYPE"},
    ):
        got = resolve_delivery_decision(
            slot, match_live=True, match_material_evidence=_night_match_event(**changes)
        )
        assert not got.visible
        assert got.quiet_suppressed


def test_night_match_no_owner_change_is_suppressed_even_when_live():
    slot = datetime(2026, 11, 2, 1, 30, tzinfo=WIB)
    for event in (
        _night_match_event(owner_fixture_verified=False),
        _night_match_event(
            event_kind="OWNER_POINTS_CHANGED", previous_value=3, current_value=3
        ),
        None,
    ):
        assert not resolve_delivery_decision(
            slot, match_live=True, match_material_evidence=event
        ).visible


def test_overlap_deep_with_match_material_remains_one_report():
    slot = datetime(2026, 11, 1, 21, 30, tzinfo=WIB)
    got = resolve_delivery_decision(
        slot, match_live=True, match_material_evidence=_night_match_event()
    )
    assert got.visible and got.single_visible_report
    assert set(got.obligations) == {"DEEP", "MATCH"}
    assert got.primary_mode == "DEEP"
    assert got.material_match_override is False  # not quiet, existing DEEP wins
