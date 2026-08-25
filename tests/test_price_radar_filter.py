from src.engines.price_radar import apply_to_payload, classify


def test_classify_suppresses_tiny_denominator_noise():
    out = classify(976, 0.0, 1)
    assert out["actionable"] is False
    assert out["confidence"] == "NOISE"


def test_filter_keeps_actionable_market_pressure():
    payload = {
        "confirmed_changes": [],
        "top_buy_pressure": [
            {"element": 1, "name": "Noise", "net_transfers": 976, "ownership_pct": 0.0, "momentum": 976.0},
            {"element": 2, "name": "Real", "net_transfers": 300000, "ownership_pct": 5.6, "momentum": 0.55},
        ],
        "top_sell_pressure": [
            {"element": 3, "name": "NoiseSell", "net_transfers": -700, "ownership_pct": 0.0, "momentum": -700.0},
            {"element": 4, "name": "RealSell", "net_transfers": -25000, "ownership_pct": 4.0, "momentum": -0.08},
        ],
    }
    out = apply_to_payload(payload)
    assert [x["name"] for x in out["top_buy_pressure"]] == ["Real"]
    assert [x["name"] for x in out["top_sell_pressure"]] == ["RealSell"]
    assert out["top_buy_pressure"][0]["confidence"] == "HIGH"
    assert out["market_noise"]["buy"][0]["name"] == "Noise"
    assert out["filter_policy"]["min_ownership_pct"] == 0.5
    assert out["filter_policy"]["min_abs_net_transfers"] == 5000
