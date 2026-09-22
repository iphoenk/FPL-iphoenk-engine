from __future__ import annotations

import inspect
from collections import Counter
from copy import deepcopy

import pytest

from src.engines import v12_package_search as search


def _current() -> list[dict]:
    rows = [
        (1, "GK", 1, 45), (2, "GK", 2, 45),
        (3, "DEF", 3, 45), (4, "DEF", 4, 45), (5, "DEF", 5, 45),
        (6, "DEF", 6, 45), (7, "DEF", 7, 45),
        (8, "MID", 8, 60), (9, "MID", 9, 60), (10, "MID", 10, 60),
        (11, "MID", 11, 60), (12, "MID", 12, 60),
        (13, "FWD", 13, 70), (14, "FWD", 14, 70), (15, "FWD", 15, 70),
    ]
    return [
        {
            "element": element,
            "name": f"P{element}",
            "position": position,
            "team_id": team,
            "now_cost": price,
            "sell_cost": price - (element % 2),
            "status": "a",
        }
        for element, position, team, price in rows
    ]


def _candidates() -> list[dict]:
    rows = [
        (101, "GK", 16, 44),
        (102, "DEF", 16, 44),
        (103, "DEF", 1, 46),
        (104, "MID", 17, 58),
        (105, "MID", 2, 61),
        (106, "FWD", 18, 68),
        (107, "FWD", 3, 72),
    ]
    return [
        {
            "element": element,
            "name": f"C{element}",
            "position": position,
            "team_id": team,
            "now_cost": price,
            "status": "a",
            "eligible": True,
        }
        for element, position, team, price in rows
    ]


def _universe() -> list[dict]:
    # A complete supplied universe may include owned players; P1.2A excludes
    # them deterministically before defining the eligible candidate denominator.
    return [
        {
            "element": row["element"],
            "name": row["name"],
            "position": row["position"],
            "team_id": row["team_id"],
            "now_cost": row["now_cost"],
            "status": "a",
        }
        for row in _current()
    ] + _candidates()


def _run(**kwargs):
    return search.search_packages(
        current_squad=kwargs.pop("current_squad", _current()),
        candidate_universe=kwargs.pop("candidate_universe", _universe()),
        bank=kwargs.pop("bank", 5),
        max_transfers=kwargs.pop("max_transfers", 2),
        universe_complete=kwargs.pop("universe_complete", True),
        expected_eligible_universe_count=kwargs.pop(
            "expected_eligible_universe_count", len(_candidates())
        ),
        **kwargs,
    )


def _ids(payload: dict) -> list[str]:
    return [row["route_id"] for row in payload["routes"]]


def test_01_hold_always_exists():
    payload = _run(max_transfers=0)
    assert _ids(payload) == ["HOLD"]
    assert payload["governance"]["hold_included"] is True


def test_02_every_route_final_squad_has_exactly_15():
    payload = _run()
    assert payload["routes"]
    assert all(len(row["final_squad_elements"]) == 15 for row in payload["routes"])


def test_03_exact_position_composition_is_preserved():
    current_by_id = {row["element"]: row for row in _current()}
    candidates_by_id = {row["element"]: row for row in _candidates()}
    for route in _run()["routes"]:
        final = []
        for element in route["final_squad_elements"]:
            final.append(current_by_id.get(element) or candidates_by_id[element])
        counts = Counter(row["position"] for row in final)
        assert counts == Counter({"GK": 2, "DEF": 5, "MID": 5, "FWD": 3})


def test_04_final_squad_players_are_unique():
    for route in _run()["routes"]:
        ids = route["final_squad_elements"]
        assert len(ids) == len(set(ids)) == 15


def test_05_max_three_per_club_always_holds():
    assert all(max(row["clubs_after"].values()) <= 3 for row in _run()["routes"])


def test_06_affordability_is_exact_integer_economics():
    current = _current()
    target = next(
        row for row in _run(current_squad=current, bank=5, max_transfers=1)["routes"]
        if row["players_out"]
        and row["players_out"][0]["element"] == 8
        and row["players_in"][0]["element"] == 104
    )
    expected = 5 + current[7]["sell_cost"] - 58
    assert target["bank_after"] == expected
    assert target["affordable"] is (expected >= 0)


def test_07_exact_sell_value_is_used_not_current_market_value():
    current = _current()
    current[7]["now_cost"] = 75
    current[7]["sell_cost"] = 59
    route = next(
        row for row in _run(current_squad=current, bank=0, max_transfers=1)["routes"]
        if row["players_out"]
        and row["players_out"][0]["element"] == 8
        and row["players_in"][0]["element"] == 104
    )
    assert route["gross_sell_value"] == 59
    assert route["gross_sell_value"] != 75
    assert route["sell_value_fallback_to_market_price"] is False


def test_08_missing_authenticated_sell_value_is_unresolved_never_guessed():
    current = _current()
    current[7].pop("sell_cost")
    route = next(
        row for row in _run(current_squad=current, bank=50, max_transfers=1)["routes"]
        if row["players_out"]
        and row["players_out"][0]["element"] == 8
        and row["players_in"][0]["element"] == 104
    )
    assert route["economics_status"] == "UNRESOLVED_SELL_VALUE"
    assert route["affordable"] is None
    assert route["bank_after"] is None
    assert route["gross_sell_value"] is None
    assert route["unresolved_sell_value_elements"] == [8]


def test_09_same_input_produces_same_deterministic_route_set():
    assert _ids(_run()) == _ids(_run())


def test_10_full_denominator_is_exact_and_truthful():
    payload = _run()
    assert payload["search_authority"] == "FULL"
    assert payload["eligible_universe_count"] == len(_candidates())
    assert payload["searched_universe_count"] == len(_candidates())
    assert payload["coverage"]["coverage_complete"] is True


def test_11_incomplete_universe_downgrades_to_partial():
    payload = _run(universe_complete=False)
    assert payload["search_authority"] == "PARTIAL"
    assert payload["coverage"]["coverage_complete"] is False


def test_12_eligible_denominator_mismatch_downgrades_to_partial():
    payload = _run(expected_eligible_universe_count=len(_candidates()) + 1)
    assert payload["search_authority"] == "PARTIAL"


def test_13_lossy_pruning_flag_can_never_claim_full():
    payload = _run(lossy_pruning=True)
    assert payload["search_authority"] == "PARTIAL"
    assert payload["coverage"]["lossy_pruning"] is True


def test_14_lossless_position_pruning_preserves_bruteforce_legal_route_space():
    # For one transfer, a legal 2/5/5/3 final squad necessarily replaces like
    # position. Brute force all current x candidate pairs and compare.
    current = _current()
    candidates = _candidates()
    brute: set[str] = {"HOLD"}
    for outgoing in current:
        for incoming in candidates:
            final = [row for row in current if row["element"] != outgoing["element"]] + [incoming]
            legal, _ = search.legal_squad(final)
            if legal:
                brute.add(f"1:{outgoing['element']}->{incoming['element']}")
    exact = set(_ids(_run(candidate_universe=candidates, max_transfers=1)))
    assert exact == brute


def test_15_batch_route_set_is_exactly_scalar_route_set():
    scalar = _run(execution_mode="SCALAR")
    batch = _run(execution_mode="BATCH", batch_size=3)
    assert _ids(batch) == _ids(scalar)
    assert batch["execution"]["execution_layer_is_not_search_authority"] is True


def test_16_sharded_route_set_is_exactly_unsharded_route_set():
    scalar = _run(execution_mode="SCALAR")
    sharded = _run(execution_mode="SHARDED", shard_count=4)
    assert _ids(sharded) == _ids(scalar)


def test_17_frontier_is_representation_only_and_cannot_mutate_search_routes():
    payload = _run()
    before = list(_ids(payload))
    frontier = search.build_search_frontier(payload["routes"])
    assert _ids(payload) == before
    assert frontier["authority"] == "REPRESENTATION_ONLY"
    assert frontier["scoring_authority"] is False
    assert frontier["route_set_mutated"] is False


def test_18_search_output_contains_no_decision_score_or_action():
    payload = _run()
    serialized = repr(payload)
    assert "'score':" not in serialized
    assert "'robust_score':" not in serialized
    assert "'recommendation':" not in serialized
    assert "'action':" not in serialized


def test_19_search_owner_has_no_ft_shadow_or_horizon_utility_dependency():
    source = inspect.getsource(search)
    assert "canonical_decision_methodology" not in source
    assert "package_optimizer_v2" not in source
    assert "derive_dynamic_ft_shadow_value" not in source
    assert "build_horizon_analysis" not in source


def test_20_search_owner_has_no_20_25_30_25_or_lineup_utility_owner():
    source = inspect.getsource(search)
    assert "CANONICAL_WEIGHTS" not in source
    assert "compute_football_score" not in source
    assert "v12_lineup_optimizer" not in source


def test_21_no_mini_league_monte_carlo_v6_or_runtime_v3_dependency():
    source = inspect.getsource(search)
    for forbidden in (
        "runtime_v6",
        "runtime_v3",
        "mini_league",
        "simulate_objective",
        "monte_carlo",
    ):
        assert f"import {forbidden}" not in source
        assert f"from src.{forbidden}" not in source


def test_22_transfer_bound_is_bounded_and_fail_closed():
    cfg = search.load_config()
    with pytest.raises(search.PackageSearchError):
        _run(max_transfers=int(cfg["maximum_supported_transfers"]) + 1)


def test_23_search_governance_declares_v6_and_authority_unchanged():
    governance = search.load_config()["governance"]
    assert governance["v6_mutated"] is False
    assert governance["authority_added"] is False
    assert governance["scheduler_changed"] is False
    assert governance["search_decision_utility_separated"] is True


def test_stage3_unavailable_private_bank_preserves_structural_full_search():
    current = _current()
    universe = _universe()
    for row in current:
        row["sell_cost"] = None
    result = search.search_packages(
        current_squad=current,
        candidate_universe=universe,
        bank=None,
        max_transfers=1,
        universe_complete=True,
        expected_eligible_universe_count=None,
        lossy_pruning=False,
    )
    assert result["status"] == "READY"
    assert result["search_authority"] == "FULL"
    assert result["max_transfers_evaluated"] == 1
    assert result["search_proof"]["transfer_depth_complete_within_bound"] is True
    assert any(row["route_id"] != "HOLD" for row in result["routes"])
    changes = [row for row in result["routes"] if row["route_id"] != "HOLD"]
    assert all(row["economics_status"] in {"UNRESOLVED_SELL_VALUE", "UNRESOLVED_BANK"} for row in changes)
    assert all(row["affordable"] is None for row in changes)
    assert all(row["sell_value_fallback_to_market_price"] is False for row in changes)
