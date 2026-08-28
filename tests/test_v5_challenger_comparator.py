from __future__ import annotations

import copy

from src.v5.config_cache import load_json_config
from src.v5.decision.challenger_comparator import build_comparator


CONFIG = "config/v5_challenger_comparator_registry.json"


def _gw_rows(start: int, values: list[float], *, std: float = 0.5, opponent_base: int = 10):
    rows = []
    for offset, mean in enumerate(values):
        gw = start + offset
        rows.append(
            {
                "gw": gw,
                "mean": mean,
                "std": std,
                "fixtures": [
                    {
                        "gw": gw,
                        "event": gw,
                        "kickoff_time": f"2026-09-{gw:02d}T15:00:00Z",
                        "opponent": opponent_base + offset,
                        "home": offset % 2 == 0,
                        "clean_sheet_probability": 0.30,
                    }
                ],
            }
        )
    return rows


def _player(
    element: int,
    name: str,
    *,
    position: str = "MID",
    team_id: int = 1,
    now_cost: int = 60,
    means: list[float] | None = None,
    start_probability: float = 0.80,
    expected_minutes: float = 72.0,
    dnp_probability: float = 0.08,
    xg90: float = 0.20,
    xa90: float = 0.18,
    set_piece_share: float = 0.0,
    penalty_share: float = 0.0,
    defcon90: float = 0.20,
    confidence: str = "HIGH",
    status: str = "a",
    congestion: bool = False,
):
    values = means or [3.0] * 5
    rows = _gw_rows(2, values, opponent_base=team_id * 10)
    overlay = {
        "application_mode": "SHADOW_ONLY",
        "fixtures": [],
    }
    if congestion:
        overlay["fixtures"] = [
            {
                "event": 2,
                "kickoff_time": rows[0]["fixtures"][0]["kickoff_time"],
                "baseline": {"start_probability": start_probability, "expected_minutes": expected_minutes},
                "shadow": {"start_probability": start_probability - 0.05, "expected_minutes": expected_minutes - 5},
                "delta": {"start_probability": -0.05, "expected_minutes": -5},
                "congestion": {
                    "status": "ACTIVE",
                    "applied": True,
                    "rest_context": {"status": "ACTIVE", "days_rest": 2.4},
                },
                "authoritative_xmins_replaced": False,
            }
        ]
    return {
        "element": element,
        "name": name,
        "position": position,
        "team_id": team_id,
        "now_cost": now_cost,
        "status": status,
        "xpts_by_gw": rows,
        "xpts_3": round(sum(values[:3]), 3),
        "xpts_5": round(sum(values[:5]), 3),
        "xpts_10": round(sum(values[:5]), 3),
        "xpts_15": round(sum(values[:5]), 3),
        "xmins": {
            "start_probability": start_probability,
            "expected_minutes": expected_minutes,
            "dnp_probability": dnp_probability,
        },
        "role": {
            "rotation_risk": 0.10,
            "set_piece_share": set_piece_share,
            "penalty_share": penalty_share,
        },
        "rates": {"xg90": xg90, "xa90": xa90},
        "defensive_contribution": {"expected_points90": defcon90},
        "projection_confidence": confidence,
        "fixture_congestion_overlay": overlay,
    }


def _bundle(
    *,
    owned_players: list[dict] | None = None,
    challengers: list[dict] | None = None,
    watchlist_ids: list[int] | None = None,
    bank: int | None = 10,
    sell_costs: dict[int, int | None] | None = None,
    wildcard: bool = False,
    extra_squad_rows: list[dict] | None = None,
):
    owned_players = owned_players or [
        _player(1, "Owned A", team_id=1, now_cost=60, means=[3, 3, 3, 3, 3]),
        _player(2, "Owned B", team_id=2, now_cost=65, means=[4, 4, 4, 4, 4]),
    ]
    challengers = challengers or [
        _player(
            101,
            "Watch Challenger",
            team_id=3,
            now_cost=60,
            means=[4, 4, 4, 4, 4],
            start_probability=0.88,
            expected_minutes=80,
            xg90=0.35,
            xa90=0.22,
        )
    ]
    players = [*owned_players, *challengers]
    prediction = {
        "generated_at": "2026-08-28T22:58:41Z",
        "planning_gw": 2,
        "players": players,
    }
    sell_costs = sell_costs or {int(player["element"]): int(player["now_cost"]) for player in owned_players}
    squad = [
        {"element": player["element"], "team_id": player["team_id"], "position": player["position"]}
        for player in owned_players
    ]
    squad.extend(extra_squad_rows or [])
    truth = {
        "context": {"planning_gw": 2},
        "chip_state": {"active_chip": "wildcard" if wildcard else None},
        "team": {
            "squad": squad,
            "finance": {
                "bank": bank,
                "players": [
                    {
                        "element": player["element"],
                        "sell_cost": sell_costs.get(int(player["element"])),
                        "finance_source": "test",
                        "finance_exact": sell_costs.get(int(player["element"])) is not None,
                    }
                    for player in owned_players
                ],
            },
        },
    }
    watchlist_ids = watchlist_ids if watchlist_ids is not None else [101]
    by_id = {int(player["element"]): player for player in players}
    positions = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for element in watchlist_ids:
        player = by_id[element]
        positions[player["position"]].append(
            {
                "element": element,
                "name": player["name"],
                "position": player["position"],
                "admission_status": "STRICT",
            }
        )
    watchlist = {"status": "READY", "positions": positions}
    decision = {
        "selected_package_id": "HOLD",
        "lineup": {
            "bench": [{"element": owned_players[0]["element"]}],
            "captain": {"element": owned_players[1]["element"]},
            "vice_captain": {"element": owned_players[0]["element"]},
            "chip_context": {"active_chip": "wildcard" if wildcard else None},
        },
    }
    return prediction, truth, watchlist, decision


def _run(**kwargs):
    prediction, truth, watchlist, decision = _bundle(**kwargs)
    return build_comparator(prediction, truth, watchlist, decision, {})


def _comparison(result, *, challenger=101, owned=1):
    return next(
        row
        for row in result["comparisons"]
        if row["player_in"]["element"] == challenger and row["player_out"]["element"] == owned
    )


def test_generic_governed_watchlist_comparison_uses_common_contract():
    result = _run()
    assert result["contract"] == "V5_OWNED_CHALLENGER_COMPARATOR_V1"
    assert result["operating_status"] == "ADVISORY_ONLY"
    assert result["governed_watchlist_challengers"] == 1
    assert result["comparison_count"] >= 1
    pair = _comparison(result)
    assert pair["challenger_type"] == "GOVERNED_WATCHLIST"
    assert pair["planning_gw"] == 2
    assert set((1, 2, 3, 5)) == set(result["horizons"])
    assert pair["governance"]["canonical_transfer_recommendation_overwritten"] is False
    assert pair["governance"]["watchlist_mutated"] is False


def test_horizon_math_is_1_2_3_5_and_fixture_by_fixture():
    challenger = _player(101, "C", team_id=3, means=[4, 5, 6, 7, 8], xg90=0.5, xa90=0.3)
    result = _run(challengers=[challenger])
    pair = _comparison(result)
    assert pair["horizon_1gw"]["mean"] == 4.0
    assert pair["horizon_2gw"]["mean"] == 9.0
    assert pair["horizon_3gw"]["mean"] == 15.0
    assert pair["horizon_5gw"]["mean"] == 30.0
    assert pair["raw_gain_2gw"] == 3.0
    assert pair["raw_gain_3gw"] == 6.0
    assert pair["raw_gain_5gw"] == 15.0
    assert [row["gw"] for row in pair["fixture_by_fixture"]] == [2, 3, 4, 5, 6]


def test_target_selection_compares_same_position_only_and_ranks_logical_outs():
    owned_mid = _player(1, "MID owned", position="MID", team_id=1, means=[2] * 5, start_probability=0.60)
    owned_fwd = _player(2, "FWD owned", position="FWD", team_id=2, means=[1] * 5)
    challenger = _player(101, "MID challenger", position="MID", team_id=3, means=[5] * 5, xg90=0.5, xa90=0.3)
    result = _run(owned_players=[owned_mid, owned_fwd], challengers=[challenger], sell_costs={1: 60, 2: 65})
    assert result["comparison_count"] == 1
    pair = result["comparisons"][0]
    assert pair["player_out"]["position"] == "MID"
    assert pair["player_in"]["position"] == "MID"


def test_same_price_direct_swap_is_affordable():
    pair = _comparison(_run(bank=0, sell_costs={1: 60, 2: 65}))
    assert pair["affordability"]["affordable"] is True
    assert pair["affordability"]["remaining_bank_tenths"] == 0


def test_upgrade_uses_itb_and_downgrade_releases_funds():
    upgrade = _player(101, "Upgrade", team_id=3, now_cost=65, means=[4] * 5, xg90=0.5, xa90=0.2)
    pair = _comparison(_run(challengers=[upgrade], bank=5, sell_costs={1: 60, 2: 65}))
    assert pair["affordability"]["affordable"] is True
    assert pair["affordability"]["remaining_bank_tenths"] == 0

    downgrade = _player(101, "Downgrade", team_id=3, now_cost=55, means=[4] * 5, xg90=0.5, xa90=0.2)
    pair = _comparison(_run(challengers=[downgrade], bank=0, sell_costs={1: 60, 2: 65}))
    assert pair["affordability"]["affordable"] is True
    assert pair["affordability"]["remaining_bank_tenths"] == 5


def test_unaffordable_swap_fails_safe_to_hold():
    expensive = _player(101, "Too Expensive", team_id=3, now_cost=80, means=[6] * 5, xg90=0.6, xa90=0.3)
    pair = _comparison(_run(challengers=[expensive], bank=0, sell_costs={1: 60, 2: 65}))
    assert pair["affordability"]["affordable"] is False
    assert pair["decision"] == "HOLD_OWNED"


def test_wildcard_zeroes_transfer_opportunity_cost_but_normal_mode_does_not():
    normal = _comparison(_run(wildcard=False))
    wildcard = _comparison(_run(wildcard=True))
    assert normal["opportunity_cost"] == 1.0
    assert wildcard["opportunity_cost"] == 0.0
    assert wildcard["net_transfer_value"] == normal["net_transfer_value"] + 1.0


def test_club_limit_violation_blocks_swap():
    challenger = _player(101, "Club Four", team_id=3, means=[6] * 5, xg90=0.7, xa90=0.3)
    extras = [
        {"element": 900, "team_id": 3, "position": "DEF"},
        {"element": 901, "team_id": 3, "position": "FWD"},
        {"element": 902, "team_id": 3, "position": "GK"},
    ]
    pair = _comparison(_run(challengers=[challenger], extra_squad_rows=extras))
    assert pair["club_legality"]["legal"] is False
    assert pair["decision"] == "HOLD_OWNED"


def test_missing_tactical_data_is_proxy_and_never_fabricated():
    pair = _comparison(_run())
    tactical = pair["tactical_matchup_by_gw"][0]["challenger"][0]
    assert tactical["status"] == "PROXY_ONLY"
    assert tactical["current_coach_evidence"] == "UNAVAILABLE"
    assert tactical["matchup_edge"] == "UNVERIFIED_TACTICAL"
    assert tactical["governance"]["specific_press_block_or_vulnerability_inferred"] is False
    assert pair["data_quality"]["tactical_evidence"] == "PROXY_ONLY"


def test_congestion_is_surfaced_but_stays_shadow_advisory():
    challenger = _player(101, "Congested", team_id=3, means=[4] * 5, xg90=0.5, xa90=0.2, congestion=True)
    pair = _comparison(_run(challengers=[challenger]))
    row = pair["rest_congestion_by_gw"][0]["challenger"]
    assert row["congestion"]["rest_context"]["status"] == "ACTIVE"
    assert row["authoritative_xmins_replaced"] is False


def test_missing_congestion_and_international_context_fail_neutral():
    pair = _comparison(_run())
    assert pair["rest_congestion_by_gw"][0]["challenger"]["status"] == "UNAVAILABLE"
    assert pair["international_context"]["status"] == "UNAVAILABLE_AT_PLAYER_LEVEL"
    assert "not inferred" in pair["international_context"]["detail"]


def test_emerging_requires_sustainable_process_not_a_result_field():
    weak = _player(
        201,
        "One Haul Only",
        team_id=4,
        means=[2] * 5,
        start_probability=0.40,
        expected_minutes=35,
        dnp_probability=0.40,
        xg90=0.05,
        xa90=0.05,
    )
    weak["event_points"] = 18
    result = _run(challengers=[weak], watchlist_ids=[])
    row = next(item for item in result["emerging_screening"] if item["element"] == 201)
    assert row["signal"]["result_signal_used"] is False
    assert row["signal"]["label"] == "NOISE"
    assert row["full_comparison_eligible"] is False
    assert result["emerging_full_comparison_eligible"] == 0


def test_emerging_process_can_become_sustainable_candidate():
    strong = _player(
        201,
        "Process Breakout",
        team_id=4,
        means=[4.5] * 5,
        start_probability=0.90,
        expected_minutes=82,
        dnp_probability=0.04,
        xg90=0.45,
        xa90=0.22,
        set_piece_share=0.75,
        defcon90=0.60,
    )
    result = _run(challengers=[strong], watchlist_ids=[])
    row = next(item for item in result["emerging_screening"] if item["element"] == 201)
    assert row["signal"]["label"] == "SUSTAINABLE_CANDIDATE"
    assert row["full_comparison_eligible"] is True
    assert result["emerging_full_comparison_eligible"] == 1
    pair = _comparison(result, challenger=201, owned=1)
    assert pair["challenger_type"] == "EMERGING_CHALLENGER"


def test_small_positive_edge_does_not_force_transfer():
    challenger = _player(101, "Marginal", team_id=3, means=[3.2] * 5, xg90=0.45, xa90=0.15)
    pair = _comparison(_run(challengers=[challenger]))
    assert pair["raw_gain_5gw"] > 0
    assert pair["decision"] in {"WATCH_CHALLENGER", "REVIEW"}
    assert pair["decision"] not in {"LEAN_TRANSFER", "STRONG_TRANSFER"}


def test_large_edge_can_lean_but_proxy_tactical_evidence_blocks_strong():
    challenger = _player(101, "Large Edge", team_id=3, means=[5] * 5, xg90=0.65, xa90=0.30)
    pair = _comparison(_run(challengers=[challenger], bank=20))
    assert pair["raw_gain_5gw"] == 10.0
    assert pair["decision"] == "LEAN_TRANSFER"
    assert pair["decision"] != "STRONG_TRANSFER"
    assert "proxy-only" in " ".join(pair["decision_risks"])


def test_unknown_owned_finance_blocks_lean_or_strong():
    challenger = _player(101, "Finance Unknown", team_id=3, means=[5] * 5, xg90=0.65, xa90=0.30)
    pair = _comparison(_run(challengers=[challenger], bank=20, sell_costs={1: None, 2: 65}))
    assert pair["affordability"]["affordable"] is None
    assert pair["decision"] in {"REVIEW", "WATCH_CHALLENGER"}
    assert pair["decision"] not in {"LEAN_TRANSFER", "STRONG_TRANSFER"}


def test_premium_or_captain_core_player_has_structural_safeguard():
    premium = _player(2, "Premium Core", team_id=2, now_cost=100, means=[3] * 5)
    owned = [_player(1, "Bench", team_id=1, means=[2] * 5), premium]
    challenger = _player(101, "C", team_id=3, now_cost=60, means=[6] * 5, xg90=0.7, xa90=0.3)
    result = _run(owned_players=owned, challengers=[challenger], bank=50, sell_costs={1: 60, 2: 100})
    premium_pair = _comparison(result, owned=2)
    bench_pair = _comparison(result, owned=1)
    assert premium_pair["target_selection"]["premium_or_core_safeguard"] is True
    assert premium_pair["structural_cost"] > bench_pair["structural_cost"]


def test_external_consensus_is_neutral_without_player_level_external_evidence():
    pair = _comparison(_run())
    assert pair["external_consensus"]["state"] == "NEUTRAL"
    assert pair["external_consensus"]["majority_vote_used"] is False


def test_reversal_triggers_are_always_exposed():
    pair = _comparison(_run())
    assert "challenger_fails_to_start" in pair["reversal_triggers"]
    assert "price_move_breaks_affordability" in pair["reversal_triggers"]
    assert "current_coach_tactical_structure_changes" in pair["reversal_triggers"]


def test_comparator_does_not_mutate_watchlist_or_canonical_decision():
    prediction, truth, watchlist, decision = _bundle()
    before_watchlist = copy.deepcopy(watchlist)
    before_decision = copy.deepcopy(decision)
    result = build_comparator(prediction, truth, watchlist, decision, {})
    assert watchlist == before_watchlist
    assert decision == before_decision
    assert result["governance"]["canonical_decision_mutated"] is False
    assert result["governance"]["may_override_canonical_transfer"] is False
    assert result["governance"]["may_override_watchlist"] is False


def test_watchlist_governance_is_suggestion_only():
    strong = _player(
        201,
        "Emerging",
        team_id=4,
        means=[5] * 5,
        start_probability=0.90,
        expected_minutes=82,
        dnp_probability=0.04,
        xg90=0.50,
        xa90=0.25,
        set_piece_share=0.8,
    )
    result = _run(challengers=[strong], watchlist_ids=[])
    pair = _comparison(result, challenger=201, owned=1)
    assert pair["watchlist_governance_suggestion"] in {"PROMOTE_TO_WATCHLIST", "NO_CHANGE"}
    assert pair["governance"]["watchlist_mutated"] is False


def test_required_validation_matrix_is_registered_without_player_pair_hardcoding():
    cfg = load_json_config(CONFIG)
    expected = {
        "same_price_direct_swap",
        "upgrade_requiring_itb",
        "downgrade",
        "active_wildcard",
        "normal_free_transfer",
        "european_congestion",
        "domestic_cup_congestion",
        "international_duty",
        "missing_tactical_data",
        "missing_external_source",
        "tbd_midweek_opponent",
        "injury",
        "suspension",
        "one_haul_trigger",
        "weak_underlying_after_haul",
        "improving_xmins",
        "deteriorating_xmins",
        "club_limit_violation",
        "position_legality",
        "early_season_low_confidence",
        "watchlist_promotion",
        "watchlist_demotion",
        "multiple_challengers_one_owned",
        "one_challenger_multiple_owned",
        "cross_engine_divergence",
    }
    assert set(cfg["validation_matrix"]) == expected
    serialized = str(cfg).lower()
    assert "rogers" not in serialized
    assert "cherki" not in serialized


def test_output_common_contract_contains_required_multi_engine_semantics():
    pair = _comparison(_run())
    required = {
        "player_out",
        "player_in",
        "challenger_type",
        "comparison_timestamp",
        "planning_gw",
        "horizon_1gw",
        "horizon_2gw",
        "horizon_3gw",
        "horizon_5gw",
        "fixture_by_fixture",
        "xpts_by_gw",
        "xmins_by_gw",
        "start_probability_by_gw",
        "tactical_matchup_by_gw",
        "rest_congestion_by_gw",
        "midweek_schedule",
        "international_context",
        "role_sustainability",
        "performance_signal",
        "raw_gain_2gw",
        "raw_gain_3gw",
        "raw_gain_5gw",
        "structural_cost",
        "opportunity_cost",
        "net_transfer_value",
        "affordability",
        "confidence",
        "decision",
        "decision_reasons",
        "decision_risks",
        "reversal_triggers",
        "data_quality",
    }
    assert required <= set(pair)
