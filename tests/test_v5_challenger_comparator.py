from __future__ import annotations

import copy

import pytest

from src.v5.config_cache import load_json_config
from src.v5.decision.challenger_comparator import build_comparator

CONFIG = "config/v5_challenger_comparator_registry.json"
VALIDATION_SCENARIOS = [
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
]


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
) -> dict:
    values = means or [3.0] * 5
    rows = []
    for offset, mean in enumerate(values):
        gw = 2 + offset
        rows.append(
            {
                "gw": gw,
                "mean": mean,
                "std": 0.5,
                "fixtures": [
                    {
                        "gw": gw,
                        "event": gw,
                        "opponent": team_id * 10 + offset,
                        "home": offset % 2 == 0,
                        "clean_sheet_probability": 0.30,
                    }
                ],
            }
        )
    overlay = {"application_mode": "SHADOW_ONLY", "fixtures": []}
    if congestion:
        overlay["fixtures"] = [
            {
                "event": 2,
                "shadow": {"start_probability": start_probability - 0.05, "expected_minutes": expected_minutes - 5},
                "delta": {"start_probability": -0.05, "expected_minutes": -5},
                "congestion": {"status": "ACTIVE", "applied": True, "rest_context": {"status": "ACTIVE", "days_rest": 2.4}},
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
        "xpts_3": sum(values[:3]),
        "xpts_5": sum(values[:5]),
        "xpts_10": sum(values[:5]),
        "xpts_15": sum(values[:5]),
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


def _inputs(
    *,
    owned: list[dict] | None = None,
    challengers: list[dict] | None = None,
    watchlist_ids: list[int] | None = None,
    bank: int | None = 10,
    sell_costs: dict[int, int | None] | None = None,
    wildcard: bool = False,
    extra_squad: list[dict] | None = None,
):
    owned = owned or [
        _player(1, "Owned A", team_id=1, now_cost=60, means=[3] * 5),
        _player(2, "Owned B", team_id=2, now_cost=65, means=[4] * 5),
    ]
    challengers = challengers or [
        _player(101, "Watch Challenger", team_id=3, now_cost=60, means=[4] * 5, start_probability=0.88, expected_minutes=80, xg90=0.35, xa90=0.22)
    ]
    prediction = {"generated_at": "2026-08-28T22:58:41Z", "planning_gw": 2, "players": [*owned, *challengers]}
    sell_costs = sell_costs or {int(row["element"]): int(row["now_cost"]) for row in owned}
    squad = [{"element": row["element"], "team_id": row["team_id"], "position": row["position"]} for row in owned]
    squad.extend(extra_squad or [])
    truth = {
        "context": {"planning_gw": 2},
        "chip_state": {"active_chip": "wildcard" if wildcard else None},
        "team": {
            "squad": squad,
            "finance": {
                "bank": bank,
                "players": [
                    {
                        "element": row["element"],
                        "sell_cost": sell_costs.get(int(row["element"])),
                        "finance_source": "test",
                        "finance_exact": sell_costs.get(int(row["element"])) is not None,
                    }
                    for row in owned
                ],
            },
        },
    }
    by_id = {int(row["element"]): row for row in [*owned, *challengers]}
    positions = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for element in ([101] if watchlist_ids is None else watchlist_ids):
        row = by_id[element]
        positions[row["position"]].append({"element": element, "name": row["name"], "position": row["position"]})
    watchlist = {"status": "READY", "positions": positions}
    decision = {
        "selected_package_id": "HOLD",
        "lineup": {
            "bench": [{"element": owned[0]["element"]}],
            "captain": {"element": owned[1]["element"]},
            "vice_captain": {},
            "chip_context": {"active_chip": "wildcard" if wildcard else None},
        },
    }
    return prediction, truth, watchlist, decision


def _run(**kwargs):
    prediction, truth, watchlist, decision = _inputs(**kwargs)
    return build_comparator(prediction, truth, watchlist, decision, {})


def _pair(result: dict, challenger: int = 101, owned: int = 1) -> dict:
    return next(row for row in result["comparisons"] if row["player_in"]["element"] == challenger and row["player_out"]["element"] == owned)


def test_generic_contract_and_canonical_reuse_are_advisory_only():
    result = _run()
    pair = _pair(result)
    assert result["contract"] == "V5_OWNED_CHALLENGER_COMPARATOR_V1"
    assert result["operating_status"] == "ADVISORY_ONLY"
    assert result["horizons"] == [1, 2, 3, 5]
    assert pair["challenger_type"] == "GOVERNED_WATCHLIST"
    assert pair["governance"]["canonical_transfer_recommendation_overwritten"] is False
    assert pair["governance"]["watchlist_mutated"] is False
    assert "prediction.xpts_by_gw" in result["canonical_inputs_reused"]
    assert "prediction.xmins" in result["canonical_inputs_reused"]


def test_horizon_and_fixture_math_is_1_2_3_5():
    challenger = _player(101, "C", team_id=3, means=[4, 5, 6, 7, 8], xg90=0.5, xa90=0.3)
    pair = _pair(_run(challengers=[challenger]))
    assert [pair[f"horizon_{n}gw"]["mean"] for n in (1, 2, 3, 5)] == [4.0, 9.0, 15.0, 30.0]
    assert pair["raw_gain_2gw"] == 3.0
    assert pair["raw_gain_3gw"] == 6.0
    assert pair["raw_gain_5gw"] == 15.0
    assert [row["gw"] for row in pair["fixture_by_fixture"]] == [2, 3, 4, 5, 6]


def test_same_position_target_selection_and_multiple_out_candidates():
    owned = [
        _player(1, "Weak Mid", position="MID", team_id=1, means=[2] * 5, start_probability=0.60),
        _player(2, "Strong Mid", position="MID", team_id=2, means=[4] * 5),
        _player(3, "Forward", position="FWD", team_id=5, means=[1] * 5),
    ]
    challenger = _player(101, "Mid Challenger", position="MID", team_id=3, means=[5] * 5, xg90=0.5, xa90=0.3)
    result = _run(owned=owned, challengers=[challenger], sell_costs={1: 60, 2: 60, 3: 60})
    pairs = [row for row in result["comparisons"] if row["player_in"]["element"] == 101]
    assert {row["player_out"]["element"] for row in pairs} == {1, 2}
    assert all(row["player_out"]["position"] == "MID" for row in pairs)
    summary = next(row for row in result["challenger_summaries"] if row["element"] == 101)
    assert summary["candidate_out_rank"][0]["element"] == 1


def test_affordability_same_price_upgrade_downgrade_and_unaffordable():
    same = _pair(_run(bank=0, sell_costs={1: 60, 2: 65}))
    assert same["affordability"]["affordable"] is True
    assert same["affordability"]["remaining_bank_tenths"] == 0

    upgrade = _player(101, "Upgrade", team_id=3, now_cost=65, means=[4] * 5, xg90=0.5, xa90=0.2)
    assert _pair(_run(challengers=[upgrade], bank=5))["affordability"]["remaining_bank_tenths"] == 0

    downgrade = _player(101, "Downgrade", team_id=3, now_cost=55, means=[4] * 5, xg90=0.5, xa90=0.2)
    assert _pair(_run(challengers=[downgrade], bank=0))["affordability"]["remaining_bank_tenths"] == 5

    expensive = _player(101, "Too Expensive", team_id=3, now_cost=80, means=[6] * 5, xg90=0.6, xa90=0.3)
    blocked = _pair(_run(challengers=[expensive], bank=0))
    assert blocked["affordability"]["affordable"] is False
    assert blocked["decision"] == "HOLD_OWNED"


def test_wildcard_removes_normal_transfer_opportunity_cost():
    normal = _pair(_run(wildcard=False))
    wildcard = _pair(_run(wildcard=True))
    assert normal["opportunity_cost"] == 1.0
    assert wildcard["opportunity_cost"] == 0.0
    assert wildcard["net_transfer_value"] == normal["net_transfer_value"] + 1.0


def test_club_limit_violation_fails_safe():
    challenger = _player(101, "Club Four", team_id=3, means=[6] * 5, xg90=0.7, xa90=0.3)
    extras = [
        {"element": 900, "team_id": 3, "position": "DEF"},
        {"element": 901, "team_id": 3, "position": "FWD"},
        {"element": 902, "team_id": 3, "position": "GK"},
    ]
    pair = _pair(_run(challengers=[challenger], extra_squad=extras))
    assert pair["club_legality"]["legal"] is False
    assert pair["decision"] == "HOLD_OWNED"


def test_tactical_missing_is_proxy_not_fabricated_and_caps_confidence():
    pair = _pair(_run())
    tactical = pair["tactical_matchup_by_gw"][0]["challenger"][0]
    assert tactical["status"] == "PROXY_ONLY"
    assert tactical["current_coach_evidence"] == "UNAVAILABLE"
    assert tactical["matchup_edge"] == "UNVERIFIED_TACTICAL"
    assert tactical["governance"]["specific_press_block_or_vulnerability_inferred"] is False
    assert pair["confidence"]["tactical_cap_applied"] is True


def test_congestion_is_surfaced_as_shadow_and_missing_context_is_neutral():
    congested = _player(101, "Congested", team_id=3, means=[4] * 5, xg90=0.5, xa90=0.2, congestion=True)
    row = _pair(_run(challengers=[congested]))["rest_congestion_by_gw"][0]["challenger"]
    assert row["congestion"]["rest_context"]["status"] == "ACTIVE"
    assert row["authoritative_xmins_replaced"] is False

    neutral = _pair(_run())
    assert neutral["rest_congestion_by_gw"][0]["challenger"]["status"] == "UNAVAILABLE"
    assert neutral["international_context"]["status"] == "UNAVAILABLE_AT_PLAYER_LEVEL"
    assert "TBD/UNVERIFIED" in neutral["midweek_schedule"]["detail"]
    assert "no fixture is fabricated" in neutral["midweek_schedule"]["detail"]


def test_one_haul_is_not_used_as_buy_signal_but_process_can_promote_emerging():
    weak = _player(201, "One Haul", team_id=4, means=[2] * 5, start_probability=0.40, expected_minutes=35, dnp_probability=0.40, xg90=0.05, xa90=0.05)
    weak["event_points"] = 18
    weak_result = _run(challengers=[weak], watchlist_ids=[])
    weak_row = next(row for row in weak_result["emerging_screening"] if row["element"] == 201)
    assert weak_row["signal"]["result_signal_used"] is False
    assert weak_row["signal"]["label"] == "NOISE"
    assert weak_result["emerging_full_comparison_eligible"] == 0

    strong = _player(201, "Process Breakout", team_id=4, means=[4.5] * 5, start_probability=0.90, expected_minutes=82, dnp_probability=0.04, xg90=0.45, xa90=0.22, set_piece_share=0.75, defcon90=0.60)
    strong_result = _run(challengers=[strong], watchlist_ids=[])
    strong_row = next(row for row in strong_result["emerging_screening"] if row["element"] == 201)
    assert strong_row["signal"]["label"] == "SUSTAINABLE_CANDIDATE"
    assert _pair(strong_result, challenger=201)["challenger_type"] == "EMERGING_CHALLENGER"


def test_small_edge_does_not_force_transfer_and_large_edge_cannot_be_strong_with_proxy_tactics():
    marginal = _player(101, "Marginal", team_id=3, means=[3.2] * 5, xg90=0.45, xa90=0.15)
    marginal_pair = _pair(_run(challengers=[marginal]))
    assert marginal_pair["raw_gain_5gw"] > 0
    assert marginal_pair["decision"] in {"WATCH_CHALLENGER", "REVIEW"}

    large = _player(101, "Large Edge", team_id=3, means=[5] * 5, xg90=0.65, xa90=0.30)
    large_pair = _pair(_run(challengers=[large], bank=20))
    assert large_pair["raw_gain_5gw"] == 10.0
    assert large_pair["decision"] == "LEAN_TRANSFER"
    assert large_pair["decision"] != "STRONG_TRANSFER"
    assert any("proxy-only" in risk for risk in large_pair["decision_risks"])


def test_unknown_finance_blocks_lean_or_strong():
    challenger = _player(101, "Finance Unknown", team_id=3, means=[5] * 5, xg90=0.65, xa90=0.30)
    pair = _pair(_run(challengers=[challenger], bank=20, sell_costs={1: None, 2: 65}))
    assert pair["affordability"]["affordable"] is None
    assert pair["decision"] not in {"LEAN_TRANSFER", "STRONG_TRANSFER"}


def test_premium_and_core_safeguards_raise_structural_resistance():
    premium = _player(2, "Premium Core", team_id=2, now_cost=100, means=[3] * 5)
    owned = [_player(1, "Bench", team_id=1, means=[2] * 5), premium]
    challenger = _player(101, "C", team_id=3, now_cost=60, means=[6] * 5, xg90=0.7, xa90=0.3)
    result = _run(owned=owned, challengers=[challenger], bank=50, sell_costs={1: 60, 2: 100})
    premium_pair = _pair(result, owned=2)
    bench_pair = _pair(result, owned=1)
    assert premium_pair["target_selection"]["premium_or_core_safeguard"] is True
    assert bench_pair["target_selection"]["premium_or_core_safeguard"] is False
    assert premium_pair["structural_cost"] > bench_pair["structural_cost"]


def test_external_consensus_reversal_triggers_and_evidence_classes_are_explicit():
    pair = _pair(_run())
    assert pair["external_consensus"]["state"] == "NEUTRAL"
    assert pair["external_consensus"]["majority_vote_used"] is False
    assert "price_move_breaks_affordability" in pair["reversal_triggers"]
    assert "current_coach_tactical_structure_changes" in pair["reversal_triggers"]
    assert pair["evidence_classes"]["TACTICAL_EVIDENCE"] == "PROXY_ONLY"
    assert pair["evidence_classes"]["COMMUNITY_SIGNAL"] == "NOT_USED_AS_FACT"


def test_comparator_never_mutates_canonical_decision_or_watchlist():
    prediction, truth, watchlist, decision = _inputs()
    before_watchlist = copy.deepcopy(watchlist)
    before_decision = copy.deepcopy(decision)
    result = build_comparator(prediction, truth, watchlist, decision, {})
    assert watchlist == before_watchlist
    assert decision == before_decision
    assert result["governance"]["canonical_decision_mutated"] is False
    assert result["governance"]["may_override_canonical_transfer"] is False
    assert result["governance"]["may_override_watchlist"] is False


def test_common_output_contract_is_complete_for_multi_engine_orchestration():
    pair = _pair(_run())
    required = {
        "player_out", "player_in", "challenger_type", "comparison_timestamp", "planning_gw",
        "horizon_1gw", "horizon_2gw", "horizon_3gw", "horizon_5gw", "fixture_by_fixture",
        "xpts_by_gw", "xmins_by_gw", "start_probability_by_gw", "tactical_matchup_by_gw",
        "rest_congestion_by_gw", "midweek_schedule", "international_context", "role_sustainability",
        "performance_signal", "raw_gain_2gw", "raw_gain_3gw", "raw_gain_5gw", "structural_cost",
        "opportunity_cost", "net_transfer_value", "affordability", "confidence", "decision",
        "decision_reasons", "decision_risks", "reversal_triggers", "data_quality",
    }
    assert required <= set(pair)


@pytest.mark.parametrize("scenario", VALIDATION_SCENARIOS)
def test_required_validation_scenario_is_governed_and_never_player_pair_hardcoded(scenario):
    cfg = load_json_config(CONFIG)
    assert scenario in cfg["validation_matrix"]
    assert cfg["status"] == "ADVISORY_ONLY"
    assert cfg["governance"]["generic_not_player_pair_specific"] is True
    assert cfg["governance"]["missing_evidence_is_unavailable_not_zero"] is True
    serialized = str(cfg).lower()
    assert "rogers" not in serialized
    assert "cherki" not in serialized
