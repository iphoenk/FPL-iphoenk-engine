from src.engines.checkpoint_policy import resolve_checkpoint


def test_live_night_collision_is_one_match_report_with_night_contract_merged():
    context = resolve_checkpoint(
        "daily",
        "2026-09-05T10:00:00Z",
        is_live=True,
        as_of="2026-08-29T21:30:00+07:00",
    )
    assert context["policy_id"] == "MATCHDAY_LIVE"
    assert context["collision_merged"] is True
    assert context["absorbed_policy_ids"] == ["NIGHT_TACTICAL_PRICE_2130"]
    assert context["price_radar_required"] is True
    assert context["roster_contract"] == {"owned": 15, "watchlist": 20}
    assert "event_live" in context["report_scope"]
    assert "price_radar" in context["report_scope"]
    assert "squad_structure" in context["report_scope"]


def test_normal_deadline_final_review_can_fire_at_1700_for_1830_deadline():
    context = resolve_checkpoint(
        "daily",
        "2026-08-29T11:30:00Z",  # 18:30 WIB
        as_of="2026-08-29T17:00:00+07:00",
    )
    assert context["policy_id"] == "FINAL_DEADLINE_REVIEW"
    assert context["is_final_review"] is True
    assert context["minutes_to_deadline"] == 90
    assert context["visible_output_authorized"] is True
    assert context["is_master_hourly_checkpoint"] is False
    assert context["timing_probe_only"] is False


def test_non_final_1700_deadline_timing_probe_stays_silent():
    context = resolve_checkpoint(
        "daily",
        "2026-08-29T12:30:00Z",  # 19:30 WIB, final review target 18:00
        as_of="2026-08-29T17:00:00+07:00",
    )
    assert context["deadline_day_active"] is True
    assert context["policy_id"] == "INTERNAL_HOURLY_SILENT"
    assert context["timing_probe_only"] is True
    assert context["visible_output_authorized"] is False


def test_deadline_day_ordinary_hourly_report_only_at_30_checkpoint():
    at_30 = resolve_checkpoint(
        "daily",
        "2026-08-29T11:30:00Z",
        as_of="2026-08-29T16:30:00+07:00",
    )
    assert at_30["policy_id"] == "DEADLINE_MONITOR"
    assert at_30["visible_output_authorized"] is True

    at_00 = resolve_checkpoint(
        "daily",
        "2026-08-29T11:30:00Z",
        as_of="2026-08-29T16:00:00+07:00",
    )
    assert at_00["policy_id"] == "INTERNAL_HOURLY_SILENT"
    assert at_00["visible_output_authorized"] is False


def test_late_window_never_authorizes_early_normal_report():
    early = resolve_checkpoint(
        "daily",
        "2026-09-05T10:00:00Z",
        as_of="2026-08-29T21:10:00+07:00",
    )
    assert early["policy_id"] == "INTERNAL_HOURLY_SILENT"
    assert early["visible_output_authorized"] is False

    delayed = resolve_checkpoint(
        "daily",
        "2026-09-05T10:00:00Z",
        as_of="2026-08-29T21:42:00+07:00",
    )
    assert delayed["policy_id"] == "NIGHT_TACTICAL_PRICE_2130"
    assert delayed["visible_output_authorized"] is True
