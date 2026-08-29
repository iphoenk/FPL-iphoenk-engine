from src.services.prediction_service import _team_value_totals


def test_team_value_totals_distinguish_market_sell_and_transferable_funds():
    ledger = [
        {"now_cost": 46, "sell_cost": 45},
        {"now_cost": 56, "sell_cost": 55},
        {"now_cost": 99, "sell_cost": 97},
    ]
    result = _team_value_totals(ledger, 5)
    assert result["squad_market_value"] == 201
    assert result["itb"] == 5
    assert result["total_market_funds"] == 206
    assert result["squad_sell_value"] == 197
    assert result["transferable_funds"] == 202
    assert result["unit"] == "tenths_gbp_million"
    # These aliases exist only to avoid breaking an older machine contract.
    # Human reports must consume the explicit semantic fields above.
    assert result["market_value"] == result["squad_market_value"]
    assert result["sell_value"] == result["squad_sell_value"]
