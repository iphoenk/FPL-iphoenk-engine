from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.engines.price_radar import (
    MODEL_THRESHOLD,
    WIB,
    _normalise_player,
    _raw_payload_hash,
    _scheduled_update,
    _served_evidence,
    canonical_contract,
)
from src.engines.v4_decision_arbitration import _attach_price_timing
from src.engines.v4_price_context import build_market_context, price_squeeze


def _player(element=1, **overrides):
    row = {
        "id": element,
        "web_name": f"P{element}",
        "first_name": "Test",
        "second_name": "Fixture",
        "team": 1,
        "element_type": 3,
        "now_cost": 55,
        "selected_by_percent": "10.0",
        "transfers_in": 1000,
        "transfers_in_event": 100,
        "transfers_out": 500,
        "transfers_out_event": 20,
        "price_change_percent": 92.4,
        "price_change_hourly_rate": 3.7,
        "price_change_projections": [
            {"offset": 0, "projected_percent": 107.1, "likelihood": 4},
            {"offset": 1, "projected_percent": 120.0, "likelihood": 5},
            {"offset": 2, "projected_percent": 130.0, "likelihood": 5},
        ],
        "price_change_locked_until": None,
        "price_change_calibrating": False,
    }
    row.update(overrides)
    return row


def _normalise(player, now=None, observed_at=None, confirmed=None):
    now = now or datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    observed_at = observed_at or now
    return _normalise_player(
        player,
        position_by_type={1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"},
        observed_at=observed_at,
        now=now,
        raw_payload_hash=_raw_payload_hash([player]),
        confirmed_change=confirmed,
    )


def test_v4_reuses_v3_canonical_policy_and_contract():
    contract = canonical_contract()
    assert contract["model_id"] == "official_price_radar_v3"
    assert contract["schema_version"] == 3
    assert contract["source_authority"][0] == "OFFICIAL_FPL"
    assert contract["likelihood_preserved_raw"] is True
    assert contract["threshold_is_official_rule"] is False
    assert contract["no_intra_cycle_crossing_eta"] is True
    assert MODEL_THRESHOLD == 100.0


def test_next_update_uses_london_dst_not_hardcoded_wib_hour():
    summer = _scheduled_update(datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)).astimezone(WIB)
    winter = _scheduled_update(datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)).astimezone(WIB)
    assert summer.hour == 6
    assert winter.hour == 7


def test_raw_likelihood_preserved_and_no_false_crossing_eta():
    row = _normalise(_player())
    assert row["current_progress_percent"] == 92.4
    assert row["projection_offset_0_likelihood"] == 4
    assert row["official_likelihood_raw"]["offset_0"] == 4
    assert row["predicted_change_cycle"] == "NEXT_UPDATE"
    assert row["predicted_change_at"] == row["projection_offset_0_at"]
    assert row["trajectory_eta_hours"] is None
    assert row["trajectory_predicted_change_deadline"] is None
    assert all("likelihood_label" not in item for item in row["official_projections"])


def test_sanitized_fixture_states_are_directional_without_guarantee():
    a = _normalise(_player(price_change_percent=102.5, price_change_projections=[
        {"offset": 0, "projected_percent": 116.9, "likelihood": 5},
        {"offset": 1, "projected_percent": 134.5, "likelihood": 5},
        {"offset": 2, "projected_percent": 152.0, "likelihood": 5},
    ]))
    b = _normalise(_player())
    c = _normalise(_player(price_change_percent=34.3, price_change_projections=[
        {"offset": 0, "projected_percent": 39.8, "likelihood": 1},
        {"offset": 1, "projected_percent": 45.0, "likelihood": 1},
        {"offset": 2, "projected_percent": 50.0, "likelihood": 1},
    ]))
    d = _normalise(_player(price_change_percent=-10.0, price_change_projections=[
        {"offset": 0, "projected_percent": -12.2, "likelihood": -1},
        {"offset": 1, "projected_percent": -13.8, "likelihood": -1},
        {"offset": 2, "projected_percent": -15.5, "likelihood": -1},
    ]))
    assert a["direction"] == "RISE" and a["model_urgency"] == "CRITICAL"
    assert b["direction"] == "RISE" and b["predicted_change_cycle"] == "NEXT_UPDATE"
    assert c["direction"] == "RISE" and c["model_urgency"] == "LOW"
    assert d["direction"] == "FALL" and d["predicted_change_cycle"] == "NONE"
    assert "bukan jaminan" in a["narrative"]


def test_calibration_lock_and_null_semantics_match_governed_v3_contract():
    now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    calibrating = _normalise(_player(price_change_projections=None, price_change_calibrating=True), now=now)
    assert calibrating["evidence_state"] == "CALIBRATING"
    assert calibrating["projection_offset_0_percent"] is None
    assert calibrating["projection_offset_0_percent"] != 0

    first_update = _scheduled_update(now, 0)
    locked = _normalise(_player(
        price_change_percent=99.0,
        price_change_locked_until=(first_update + timedelta(hours=2)).isoformat(),
        price_change_projections=[
            {"offset": 0, "projected_percent": 120.0, "likelihood": 5},
            {"offset": 1, "projected_percent": 70.0, "likelihood": 3},
            {"offset": 2, "projected_percent": 80.0, "likelihood": 3},
        ],
    ), now=now)
    assert locked["evidence_state"] == "LOCKED"
    assert locked["predicted_change_cycle"] == "NONE"
    assert locked["predicted_change_at"] is None

    nulls = _normalise(_player(
        price_change_percent=None,
        price_change_hourly_rate=None,
        price_change_projections=[{"offset": 0, "projected_percent": None, "likelihood": None}],
    ), now=now)
    assert nulls["current_progress_percent"] is None
    assert nulls["price_change_hourly_rate"] is None
    assert nulls["projection_offset_0_percent"] is None
    assert nulls["projection_offset_0_likelihood"] is None
    assert nulls["current_progress_percent"] != 0


def test_market_context_preserves_price_ownership_offsets_and_all15_all20():
    elements = [_player(element=i, now_cost=45 + i % 10) for i in range(1, 40)]
    market = build_market_context(
        {
            "elements": elements,
            "element_types": [
                {"id": 1, "singular_name_short": "GKP"},
                {"id": 2, "singular_name_short": "DEF"},
                {"id": 3, "singular_name_short": "MID"},
                {"id": 4, "singular_name_short": "FWD"},
            ],
        },
        observed_at="2026-08-31T09:55:00+00:00",
        now=datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc),
        owned_ids=set(range(1, 16)),
        watchlist_ids=range(16, 36),
        transport_health={"status": "LIVE"},
    )
    assert market["source"] == "OFFICIAL_FPL"
    assert market["health"]["status"] == "PASS"
    assert len(market["all15_actionable_price_radar"]) == 15
    assert len(market["all20_external_dss_watchlist"]) == 20
    assert market["players"][0]["official_projections"][0]["offset"] == 0
    assert market["v3_v4_canonical_parity"]["model_id"] == "official_price_radar_v3"


def test_price_squeeze_uses_governed_sell_value_and_models_01_02():
    outgoing = _normalise(_player(element=10, now_cost=54, price_change_percent=-90.0, price_change_projections=[
        {"offset": 0, "projected_percent": -105.0, "likelihood": -4},
        {"offset": 1, "projected_percent": -110.0, "likelihood": -4},
        {"offset": 2, "projected_percent": -120.0, "likelihood": -5},
    ]))
    incoming = _normalise(_player(element=20, now_cost=53, price_change_percent=90.0, price_change_projections=[
        {"offset": 0, "projected_percent": 105.0, "likelihood": 4},
        {"offset": 1, "projected_percent": 110.0, "likelihood": 4},
        {"offset": 2, "projected_percent": 120.0, "likelihood": 5},
    ]))
    squeeze = price_squeeze(outgoing, incoming, {"element": 10, "purchase_cost": 50, "sell_cost": 52}, bank=1)
    by_name = {row["scenario"]: row for row in squeeze["scenarios"]}
    assert by_name["BASE"]["affordable"] is True
    assert by_name["BOTH_SQUEEZE_0_1"]["affordable"] is False
    assert by_name["BOTH_SQUEEZE_0_1"]["sell_value_impact"] == -1
    assert by_name["BOTH_SQUEEZE_0_1"]["structural_flexibility_impact"] == -2
    assert by_name["BOTH_SQUEEZE_0_2"]["required_extra_budget"] >= 2


def test_price_risk_cannot_promote_hold_to_change():
    outgoing = _normalise(_player(element=10, now_cost=54, price_change_percent=-90.0, price_change_projections=[
        {"offset": 0, "projected_percent": -105.0, "likelihood": -4},
        {"offset": 1, "projected_percent": -110.0, "likelihood": -4},
        {"offset": 2, "projected_percent": -120.0, "likelihood": -5},
    ]))
    incoming = _normalise(_player(element=20, now_cost=53, price_change_percent=90.0, price_change_projections=[
        {"offset": 0, "projected_percent": 105.0, "likelihood": 4},
        {"offset": 1, "projected_percent": 110.0, "likelihood": 4},
        {"offset": 2, "projected_percent": 120.0, "likelihood": 5},
    ]))
    prices = {"health": {"status": "PASS"}, "players": [outgoing, incoming]}
    team = {
        "team_value_ledger": [{"element": 10, "purchase_cost": 50, "sell_cost": 52}],
        "totals": {"itb": 1},
    }
    transfer = {
        "action": "HOLD",
        "execution_authorized": False,
        "replacements": 1,
        "out": [{"element": 10, "position": "MID"}],
        "in": [{"element": 20, "position": "MID"}],
    }
    enriched = _attach_price_timing(transfer, prices, team)
    assert enriched["action"] == "HOLD"
    assert enriched["execution_authorized"] is False
    assert enriched["price_context"]["price_only_execution_authorized"] is False
    assert enriched["price_context"]["execution_timing"] == "REVIEW_PRICE_SQUEEZE_NO_EXECUTION_AUTHORITY"



def test_predictor_publication_states_and_provenance_are_explicit():
    now = datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc)
    no_signal = _normalise(_player(
        price_change_percent=34.3,
        price_change_projections=[
            {"offset": 0, "projected_percent": 39.8, "likelihood": 1},
            {"offset": 1, "projected_percent": 45.0, "likelihood": 1},
            {"offset": 2, "projected_percent": 50.0, "likelihood": 1},
        ],
    ), now=now)
    served = _served_evidence(no_signal, owned=False)
    assert served["predictor_serving_state"] == "NO_SIGNAL"
    assert served["raw_evidence_state"] == "AVAILABLE"
    assert served["provider"] == "OFFICIAL_FPL"
    assert served["observed_at"] == served["fetched_at"]
    assert served["fetched_at_distinct"] is False
    assert served["age_seconds"] == served["freshness_seconds"]
    assert served["freshness_state"] == "FRESH"
    assert served["trajectory_basis"]["current_progress_percent"] == 34.3
    assert served["trajectory_basis"]["model_threshold_percent"] == MODEL_THRESHOLD

    stale = _normalise(_player(element=2), now=now, observed_at=now - timedelta(hours=3))
    stale_served = _served_evidence(stale, owned=False)
    assert stale_served["predictor_serving_state"] == "STALE"
    assert stale_served["freshness_state"] == "STALE"
    assert stale_served["age_seconds"] == 10800

    unavailable_player = _player(element=3)
    unavailable_player.pop("price_change_percent")
    unavailable = _normalise(unavailable_player, now=now)
    assert _served_evidence(unavailable, owned=False)["predictor_serving_state"] == "UNAVAILABLE"

    actionable = _normalise(_player(element=4), now=now)
    assert _served_evidence(actionable, owned=False)["predictor_serving_state"] == "AVAILABLE"
