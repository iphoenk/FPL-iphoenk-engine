import json
from datetime import datetime, timedelta, timezone

from src.engines.price_radar import (
    MODEL_THRESHOLD,
    _normalise_player,
    _overall_health,
    _raw_payload_hash,
    _scheduled_update,
    _served_evidence,
    patch_files,
)


def _player(element=1, **overrides):
    payload = {
        "id": element,
        "first_name": f"First{element}",
        "second_name": f"Second{element}",
        "web_name": f"Player{element}",
        "team": 1 + (element % 5),
        "element_type": 1 + (element % 4),
        "now_cost": 45 + element,
        "selected_by_percent": "5.0",
        "transfers_in": 10000,
        "transfers_in_event": 1000,
        "transfers_out": 5000,
        "transfers_out_event": 500,
        "price_change_percent": 10.0,
        "price_change_hourly_rate": 20,
        "price_change_projections": [
            {"offset": 0, "projected_percent": 20.0, "likelihood": 1},
            {"offset": 1, "projected_percent": 30.0, "likelihood": 1},
            {"offset": 2, "projected_percent": 40.0, "likelihood": 2},
        ],
        "price_change_locked_until": None,
        "price_change_calibrating": False,
    }
    payload.update(overrides)
    return payload


def _normalise(player, now, observed_at=None, confirmed=None):
    observed_at = observed_at or now
    return _normalise_player(
        player,
        position_by_type={1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"},
        observed_at=observed_at,
        now=now,
        raw_payload_hash=_raw_payload_hash([player]),
        confirmed_change=confirmed,
    )


def test_sanitized_fixture_a_is_next_update_rise_candidate_without_guarantee():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    row = _normalise(_player(
        price_change_percent=102.5,
        price_change_projections=[
            {"offset": 0, "projected_percent": 116.9, "likelihood": 5},
            {"offset": 1, "projected_percent": 134.5, "likelihood": 5},
            {"offset": 2, "projected_percent": 152.0, "likelihood": 5},
        ],
    ), now)
    assert row["direction"] == "RISE"
    assert row["predicted_change_cycle"] == "NEXT_UPDATE"
    assert row["model_urgency"] == "CRITICAL"
    assert row["prediction_source"] == "OFFICIAL_PROJECTED_PROGRESS"
    assert "bukan jaminan" in row["narrative"]


def test_sanitized_fixture_b_never_fabricates_intra_cycle_crossing_time():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    row = _normalise(_player(
        price_change_percent=92.4,
        price_change_hourly_rate=350,
        price_change_projections=[
            {"offset": 0, "projected_percent": 107.1, "likelihood": 5},
            {"offset": 1, "projected_percent": 115.0, "likelihood": 5},
            {"offset": 2, "projected_percent": 120.0, "likelihood": 5},
        ],
    ), now)
    assert row["current_progress_percent"] == 92.4
    assert row["projection_offset_0_percent"] == 107.1
    assert row["predicted_change_cycle"] == "NEXT_UPDATE"
    assert row["predicted_change_at"] == row["projection_offset_0_at"]
    assert row["trajectory_eta_hours"] is None
    assert row["trajectory_predicted_change_deadline"] is None


def test_sanitized_fixture_c_has_fall_direction_without_near_term_threshold_urgency():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    row = _normalise(_player(
        price_change_percent=-10.0,
        price_change_hourly_rate=-5,
        price_change_projections=[
            {"offset": 0, "projected_percent": -12.2, "likelihood": -1},
            {"offset": 1, "projected_percent": -13.8, "likelihood": -1},
            {"offset": 2, "projected_percent": -15.5, "likelihood": -1},
        ],
    ), now)
    assert row["direction"] == "FALL"
    assert row["predicted_change_cycle"] == "NONE"
    assert row["model_urgency"] == "LOW"


def test_current_and_projected_progress_are_separate_evidence():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    row = _normalise(_player(
        price_change_percent=44.0,
        price_change_projections=[
            {"offset": 0, "projected_percent": 101.0, "likelihood": 4},
            {"offset": 1, "projected_percent": 110.0, "likelihood": 5},
            {"offset": 2, "projected_percent": 120.0, "likelihood": 5},
        ],
    ), now)
    assert row["current_progress_percent"] == 44.0
    assert row["projection_offset_0_percent"] == 101.0
    assert row["official_progress_pct"] == 44.0


def test_likelihood_is_preserved_raw_and_unverified_mapping_is_absent():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    row = _normalise(_player(), now)
    assert row["projection_offset_0_likelihood"] == 1
    assert row["official_projections"][0] == {"offset": 0, "projected_percent": 20.0, "likelihood": 1}
    assert all("likelihood_label" not in item for item in row["official_projections"])


def test_calibrating_null_projections_are_partial_not_real_zero():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    row = _normalise(_player(price_change_projections=None, price_change_calibrating=True), now)
    assert row["evidence_state"] == "CALIBRATING"
    assert row["fallback_reason"] == "CALIBRATING"
    assert row["projection_offset_0_percent"] is None
    assert row["projection_offset_0_percent"] != 0
    health = _overall_health([row], {"status": "LIVE"})
    assert health["status"] == "PARTIAL"


def test_active_lock_prevents_prediction_before_lock_timestamp():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    first_update = _scheduled_update(now, 0)
    row = _normalise(_player(
        price_change_percent=99.0,
        price_change_locked_until=(first_update + timedelta(hours=2)).isoformat(),
        price_change_projections=[
            {"offset": 0, "projected_percent": 120.0, "likelihood": 5},
            {"offset": 1, "projected_percent": 70.0, "likelihood": 3},
            {"offset": 2, "projected_percent": 80.0, "likelihood": 3},
        ],
    ), now)
    assert row["evidence_state"] == "LOCKED"
    assert row["predicted_change_cycle"] == "NONE"
    assert row["predicted_change_at"] is None


def test_missing_ownership_is_not_collapsed_to_zero():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    player = _player()
    del player["selected_by_percent"]
    row = _normalise(player, now)
    assert row["ownership_percent"] is None
    assert row["ownership_pct"] is None
    assert row["evidence_state"] in {"FIELD_MISSING", "SCHEMA_CHANGED"}
    assert "selected_by_percent:FIELD_MISSING" in row["schema_errors"]


def test_likelihood_type_drift_degrades_schema_instead_of_guessing_mapping():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    row = _normalise(_player(price_change_projections=[
        {"offset": 0, "projected_percent": 20.0, "likelihood": "VERY_LIKELY"},
        {"offset": 1, "projected_percent": 30.0, "likelihood": 1},
        {"offset": 2, "projected_percent": 40.0, "likelihood": 2},
    ]), now)
    assert row["evidence_state"] == "SCHEMA_CHANGED"
    assert any("likelihood_type_changed" in error for error in row["schema_errors"])
    assert row["projection_offset_0_likelihood"] == "VERY_LIKELY"


def test_stale_observation_is_explicit_and_never_presented_as_fresh_official():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    row = _normalise(_player(), now, observed_at=now - timedelta(hours=1))
    assert row["evidence_state"] == "STALE"
    assert row["fallback_reason"] == "STALE"
    assert row["confidence"] == "LOW"


def test_london_midnight_converts_to_wib_dynamically_for_bst_and_gmt():
    summer_now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    winter_now = datetime(2026, 12, 1, 4, 30, tzinfo=timezone.utc)
    summer_row = _normalise(_player(), summer_now)
    winter_row = _normalise(_player(), winter_now)
    assert datetime.fromisoformat(summer_row["next_official_price_update_at"]).hour == 6
    assert datetime.fromisoformat(winter_row["next_official_price_update_at"]).hour == 7


def test_projection_offsets_remain_dst_safe_across_clock_change():
    now = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)
    offset0 = _scheduled_update(now, 0)
    offset1 = _scheduled_update(now, 1)
    assert offset0 == datetime(2026, 10, 24, 23, 0, tzinfo=timezone.utc)
    assert offset1 == datetime(2026, 10, 26, 0, 0, tzinfo=timezone.utc)
    assert (offset1 - offset0).total_seconds() == 25 * 3600


def test_confirmed_change_is_kept_separate_from_predictor_signal():
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    confirmed = {"element": 1, "previous": 45, "current": 46, "delta": 1}
    row = _normalise(_player(price_change_percent=-20.0), now, confirmed=confirmed)
    assert row["confirmed_price_change"] == confirmed
    assert row["direction"] == "FALL"


def test_threshold_is_model_governed_not_claimed_as_official_rule():
    assert MODEL_THRESHOLD == 100.0
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    row = _normalise(_player(price_change_percent=99.9), now)
    served = _served_evidence(row, owned=False)
    assert served["source"] == "OFFICIAL_FPL"
    assert "bukan jaminan" not in served["narrative"] or isinstance(served["narrative"], str)


def test_patch_files_covers_all_15_owned_players_with_full_governed_evidence(tmp_path):
    now = datetime.now(timezone.utc)
    raw = [_player(element=i) for i in range(1, 21)]
    prices = {
        "generated_at": now.isoformat(),
        "confirmed_changes": [],
        "top_buy_pressure": [],
        "top_sell_pressure": [],
        "official_predictor_raw": raw,
        "official_predictor_observed_at": now.isoformat(),
        "official_predictor_transport_health": {"status": "LIVE", "fetched_at": now.isoformat()},
        "official_element_types": [
            {"id": 1, "singular_name_short": "GKP"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
    }
    team = {"squad": [{"element": i} for i in range(1, 16)]}
    (tmp_path / "prices.json").write_text(json.dumps(prices), encoding="utf-8")
    (tmp_path / "team.json").write_text(json.dumps(team), encoding="utf-8")
    (tmp_path / "latest.json").write_text(json.dumps({"price_summary": {}, "files": {}}), encoding="utf-8")
    patch_files(tmp_path)
    alerts = json.loads((tmp_path / "price_alerts.json").read_text(encoding="utf-8"))
    assert alerts["owned_price_radar_count"] == 15
    assert len(alerts["owned_price_radar"]) == 15
    required = {
        "current_price", "ownership_percent", "current_progress_percent", "projection_offset_0_percent",
        "projection_offset_0_likelihood", "direction", "next_official_price_update_at", "eta_human",
        "predicted_change_cycle", "model_urgency", "source", "freshness_seconds", "action",
    }
    assert all(required.issubset(row) for row in alerts["owned_price_radar"])
    updated_prices = json.loads((tmp_path / "prices.json").read_text(encoding="utf-8"))
    assert updated_prices["official_price_predictor_health"]["status"] == "PASS"
    assert updated_prices["official_price_predictor_contract"]["threshold_is_official_rule"] is False
    assert updated_prices["official_price_predictor_contract"]["no_intra_cycle_crossing_eta"] is True
