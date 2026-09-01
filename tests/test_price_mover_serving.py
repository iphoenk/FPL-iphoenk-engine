from src.engines.price_mover_serving import apply_ranked_price_movers


def _row(element, direction, progress, projected, likelihood, cycle="NONE", urgency="LOW", hourly=0, net=0):
    return {
        "element_id": element,
        "player_name": f"P{element}",
        "direction": direction,
        "current_progress_percent": progress,
        "projection_offset_0_percent": projected,
        "projection_offset_0_likelihood": likelihood,
        "predicted_change_cycle": cycle,
        "model_urgency": urgency,
        "price_change_hourly_rate": hourly,
        "net_transfers": net,
        "confidence": "HIGH",
        "source": "OFFICIAL_FPL",
    }


def test_exact_20x20_and_predictor_rank_not_transfer_pressure():
    rises = [_row(i, "RISE", i, i, 1, net=i * 100) for i in range(1, 26)]
    falls = [_row(100 + i, "FALL", -i, -i, -1, net=-i * 100) for i in range(1, 26)]
    rises.append(_row(999, "RISE", 95, 125, 5, cycle="NEXT_UPDATE", urgency="CRITICAL", hourly=2000, net=-999999))
    payload = apply_ranked_price_movers({"players": rises + falls})
    assert len(payload["top_20_risers"]) == 20
    assert len(payload["top_20_fallers"]) == 20
    assert payload["top_20_risers"][0]["element"] == 999
    assert payload["price_mover_serving_contract"]["status"] == "PASS"
    assert payload["price_mover_serving_contract"]["transfer_pressure_used_for_rank"] is False
    assert payload["price_mover_serving_contract"]["comprehensive_price_mover_verdict_allowed"] is True


def test_incomplete_directional_coverage_fails_closed():
    rows = [_row(i, "RISE", i, i, 1) for i in range(1, 20)] + [_row(100 + i, "FALL", -i, -i, -1) for i in range(1, 25)]
    payload = apply_ranked_price_movers({"players": rows})
    contract = payload["price_mover_serving_contract"]
    assert len(payload["top_20_risers"]) == 19
    assert len(payload["top_20_fallers"]) == 20
    assert contract["status"] == "PARTIAL"
    assert contract["reason"] == "PRICE_MOVER_20X20_INCOMPLETE"
    assert contract["comprehensive_price_mover_verdict_allowed"] is False
