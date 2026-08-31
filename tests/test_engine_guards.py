from src.engines.reliability import leakage_allowed, validate_snapshot
from src.models.price_model import price_pressure
from src.models.xmins_v3 import estimate_xmins


def test_leakage_gate():
    assert leakage_allowed("2026-08-28T17:00:00Z", "2026-08-28T17:30:00Z")
    assert not leakage_allowed("2026-08-28T18:00:00Z", "2026-08-28T17:30:00Z")
    assert not leakage_allowed(None, "2026-08-28T17:30:00Z")


def test_snapshot_validator():
    snapshot = {
        "schema_version": 32,
        "engine_version": "3.3.1",
        "generated_at": "x",
        "phase": {},
        "entry": {
            "id": 3462711,
            "current_event": 1,
            "summary_overall_points": 71,
            "summary_overall_rank": 462166,
            "summary_event_points": 71,
            "summary_event_rank": 462167,
            "fetched_at": "2026-08-25T17:00:00+00:00",
        },
        "team_summary": {"itb": 5, "market_value": 995, "sell_value": 995},
        "files": {key: key for key in ("team", "live", "prices", "health", "universe", "chips")},
        "meta": {},
    }
    assert validate_snapshot(snapshot)["ok"]


def test_canonical_xmins_distribution_is_bounded():
    player = {"status": "a", "minutes": 90, "starts": 1, "element_type": 3}
    distribution = estimate_xmins(player)
    assert distribution["model"] == "xmins_v3_hierarchical_prior"
    assert 0 <= distribution["start_probability"] <= 1
    assert 0 <= distribution["expected_minutes"] <= 90
    assert distribution["governance"]["current_official_availability_is_authority"] is True


def test_price_probability_bounds():
    result = price_pressure(
        {"selected_by_percent": "10", "transfers_in_event": 1000, "transfers_out_event": 100},
        100000,
    )
    assert 0 <= result["rise_probability"] <= 1
