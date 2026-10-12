from src.engines.v12_package_utility import (
    _build_resolved_transfer_economics,
    _hit_economics,
    _route_net_horizons,
)


def _route(*, transfer_count=1, bank_after=14, affordable=True, sell_value=10):
    return {
        "route_id": "1:1->2",
        "transfer_count": transfer_count,
        "economics_status": "RESOLVED",
        "bank_after": bank_after,
        "affordable": affordable,
        "players_out": [{"element": 1, "sell_value": sell_value}],
    }


def _shadow():
    return {
        "status": "PASS",
        "ft_shadow_value": 0.0,
        "fixed_universal_ft_value": False,
        "frontier_snapshot_id": "fixture-frontier",
    }


def test_one_transfer_with_free_transfer_has_canonical_zero_hit():
    hit = _hit_economics(transfer_count=1, free_transfers=1, hit_cost_per_extra_transfer=4)
    result = _build_resolved_transfer_economics(
        _route(), hit=hit, shadow=_shadow(), projection_by_id={1: {"now_cost": 10}}
    )
    assert result["status"] == "PASS"
    assert result["transfer_count"] == 1
    assert result["ft_consumed"] == 1
    assert result["hit_points"] == 0
    assert result["bank_after"] == 14
    assert result["affordable"] is True


def test_one_transfer_with_zero_free_transfers_has_four_point_hit():
    hit = _hit_economics(transfer_count=1, free_transfers=0, hit_cost_per_extra_transfer=4)
    result = _build_resolved_transfer_economics(
        _route(), hit=hit, shadow=_shadow(), projection_by_id={1: {"now_cost": 10}}
    )
    assert result["status"] == "PASS"
    assert result["ft_consumed"] == 0
    assert result["hit_points"] == 4


def test_two_transfers_with_zero_free_transfers_have_eight_point_hit():
    hit = _hit_economics(transfer_count=2, free_transfers=0, hit_cost_per_extra_transfer=4)
    result = _build_resolved_transfer_economics(
        _route(transfer_count=2), hit=hit, shadow=_shadow(), projection_by_id={1: {"now_cost": 10}}
    )
    assert result["status"] == "PASS"
    assert result["ft_consumed"] == 0
    assert result["hit_points"] == 8


def test_unavailable_sell_value_fails_closed_and_is_not_executable():
    hit = _hit_economics(transfer_count=1, free_transfers=0, hit_cost_per_extra_transfer=4)
    result = _build_resolved_transfer_economics(
        _route(sell_value=None), hit=hit, shadow=_shadow(), projection_by_id={1: {"now_cost": 10}}
    )
    assert result["status"] == "PARTIAL"
    assert result["hit_points"] == 4
    assert result["bank_after"] == 14
    assert result["affordable"] is True
    assert result["executable"] is False


def test_unresolved_economics_does_not_replace_horizon_net_with_zero():
    horizons, _ = _route_net_horizons(
        {"per_gw": []},
        {"per_gw": []},
        execution_economics={"status": "PARTIAL", "hit_points": None},
        rental=False,
    )
    assert horizons["GW+1"]["net_delta_vs_hold"] is None
    assert horizons["3GW"]["net_delta_vs_hold"] is None
    assert horizons["5GW"]["net_delta_vs_hold"] is None
