from __future__ import annotations

from datetime import datetime, timezone

from src.engines.v4_decision_arbitration import _attach_price_timing
from src.sources.official_price_predictor import (
    CONTRACT,
    build_market_context,
    next_official_update,
    normalize_player,
    price_squeeze,
)


def _player(**overrides):
    row = {
        "id": 1,
        "web_name": "Fixture",
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


def test_next_update_uses_london_dst_not_hardcoded_wib_hour():
    summer = next_official_update(datetime(2026, 8, 31, 10, 0, tzinfo=timezone.utc))
    winter = next_official_update(datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc))
    assert summer["next_official_price_update_wib"].endswith("06:00:00+07:00")
    assert winter["next_official_price_update_wib"].endswith("07:00:00+07:00")
    assert summer["timezone_authority"] == "Europe/London"


def test_raw_likelihood_preserved_and_no_false_crossing_eta():
    row = normalize_player(
        _player(),
        observed_at="2026-08-31T09:55:00+00:00",
        now="2026-08-31T10:00:00+00:00",
    )
    assert row["contract"] == CONTRACT
    assert row["current_official_progress"] == 92.4
    assert row["official_likelihood_raw"]["0"] == 4
    assert row["predicted_change_cycle"] == 0
    assert row["predicted_change_at"] == row["next_official_price_update_at"]
    assert "crossing" not in row["eta_human"].lower()
    assert row["guardrails"]["hourly_rate_not_used_for_exact_crossing_eta"] is True
    assert row["guardrails"]["official_label_mapping_invented"] is False


def test_sanitized_fixture_states_are_directional_without_guarantee():
    a = normalize_player(_player(price_change_percent=102.5, price_change_projections=[
        {"offset": 0, "projected_percent": 116.9, "likelihood": 5},
        {"offset": 1, "projected_percent": 134.5, "likelihood": 5},
        {"offset": 2, "projected_percent": 152.0, "likelihood": 5},
    ]), now="2026-08-31T10:00:00+00:00")
    b = normalize_player(_player(), now="2026-08-31T10:00:00+00:00")
    c = normalize_player(_player(price_change_percent=34.3, price_change_projections=[{"offset": 0, "projected_percent": 39.8, "likelihood": 1}]), now="2026-08-31T10:00:00+00:00")
    d = normalize_player(_player(price_change_percent=-10.0, price_change_projections=[
        {"offset": 0, "projected_percent": -12.2, "likelihood": -1},
        {"offset": 1, "projected_percent": -13.8, "likelihood": -1},
        {"offset": 2, "projected_percent": -15.5, "likelihood": -1},
    ]), now="2026-08-31T10:00:00+00:00")
    assert a["direction"] == "RISE" and a["model_urgency"] == "CRITICAL"
    assert b["direction"] == "RISE" and b["predicted_change_cycle"] == 0
    assert c["direction"] == "RISE" and c["model_urgency"] == "LOW"
    assert d["direction"] == "FALL" and d["predicted_change_cycle"] is None


def test_calibration_and_lock_are_partial_and_suppress_early_candidate():
    calibrating = normalize_player(_player(price_change_calibrating=True), now="2026-08-31T10:00:00+00:00")
    assert calibrating["evidence_state"] == "PARTIAL"
    assert calibrating["predicted_change_cycle"] is None
    assert calibrating["model_urgency"] == "LOW"

    locked = normalize_player(
        _player(price_change_locked_until="2026-09-02T00:00:00+00:00"),
        now="2026-08-31T10:00:00+00:00",
    )
    assert locked["evidence_state"] == "PARTIAL"
    assert locked["predicted_change_cycle"] == 2
    assert locked["model_urgency"] == "LOW"


def test_null_predictor_values_are_not_coerced_to_zero():
    row = normalize_player(_player(
        price_change_percent=None,
        price_change_hourly_rate=None,
        price_change_projections=[{"offset": 0, "projected_percent": None, "likelihood": None}],
    ), now="2026-08-31T10:00:00+00:00")
    assert row["current_official_progress"] is None
    assert row["official_hourly_rate_raw"] is None
    assert row["official_projections"][0]["projected_percent"] is None
    assert row["official_likelihood_raw"]["0"] is None


def test_market_context_preserves_price_ownership_offsets_and_all15_all20():
    elements = []
    for element in range(1, 40):
        elements.append(_player(id=element, web_name=f"P{element}", now_cost=45 + element % 10))
    market = build_market_context(
        {"elements": elements},
        observed_at="2026-08-31T09:55:00+00:00",
        now="2026-08-31T10:00:00+00:00",
        owned_ids=set(range(1, 16)),
        watchlist_ids=range(16, 36),
    )
    assert market["source"] == "OFFICIAL_FPL"
    assert market["health"]["status"] == "PASS"
    assert len(market["all15"]) == 15
    assert len(market["all20_watchlist"]) == 20
    assert market["players"][0]["official_projections"][0]["offset"] == 0


def test_price_squeeze_uses_governed_sell_value_and_models_01_02():
    outgoing = normalize_player(_player(id=10, now_cost=54, price_change_percent=-90.0, price_change_projections=[{"offset": 0, "projected_percent": -105.0, "likelihood": -4}]), now="2026-08-31T10:00:00+00:00")
    incoming = normalize_player(_player(id=20, now_cost=53, price_change_percent=90.0, price_change_projections=[{"offset": 0, "projected_percent": 105.0, "likelihood": 4}]), now="2026-08-31T10:00:00+00:00")
    squeeze = price_squeeze(outgoing, incoming, {"element": 10, "purchase_cost": 50, "sell_cost": 52}, bank=1)
    by_name = {row["scenario"]: row for row in squeeze["scenarios"]}
    assert by_name["BASE"]["affordable"] is True
    assert by_name["BOTH_SQUEEZE_0_1"]["affordable"] is False
    assert by_name["BOTH_SQUEEZE_0_1"]["sell_value_impact"] == -1
    assert by_name["BOTH_SQUEEZE_0_1"]["structural_flexibility_impact"] == -2
    assert by_name["BOTH_SQUEEZE_0_2"]["required_extra_budget"] >= 2


def test_price_risk_cannot_promote_hold_to_change():
    outgoing = normalize_player(_player(id=10, now_cost=54, price_change_percent=-90.0, price_change_projections=[{"offset": 0, "projected_percent": -105.0, "likelihood": -4}]), now="2026-08-31T10:00:00+00:00")
    incoming = normalize_player(_player(id=20, now_cost=53, price_change_percent=90.0, price_change_projections=[{"offset": 0, "projected_percent": 105.0, "likelihood": 4}]), now="2026-08-31T10:00:00+00:00")
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
