from src.services.prediction_service import _team_value_totals


def test_team_value_totals_distinguish_market_sell_and_transferable_funds():
    ledger = [
        {"now_cost": 46, "sell_cost": 45},
        {"now_cost": 56, "sell_cost": 55},
        {"now_cost": 99, "sell_cost": 97},
    ]
    result = _team_value_totals(ledger, 5)
    assert result == {
        "squad_market_value": 201,
        "itb": 5,
        "total_market_funds": 206,
        "squad_sell_value": 197,
        "transferable_funds": 202,
        "unit": "tenths_gbp_million",
    }
