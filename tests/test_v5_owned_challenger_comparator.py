from __future__ import annotations

from copy import deepcopy

from src.v5.evaluation.owned_challenger_comparator import compare
from src.v5.reporting import build_report
from src.v5.services.evaluation import handle as evaluation_handle


def _gw(mean: float, std: float = 1.0, start: int = 2):
    return [
        {
            "gw": start + i,
            "mean": mean,
            "std": std,
            "fixtures": [
                {
                    "home": i % 2 == 0,
                    "opponent": 10 + i,
                    "kickoff_time": f"2026-09-{5+i:02d}T14:00:00Z",
                    "mean": mean,
                    "std": std,
                }
            ],
        }
        for i in range(5)
    ]


def _player(element: int, name: str, pos: str, cost: int, mean: float, *, team: int, start_p: float = .9, dnp: float = .05, tactical: bool = True):
    return {
        "element": element,
        "name": name,
        "position": pos,
        "team_id": team,
        "now_cost": cost,
        "status": "a",
        "xpts_by_gw": _gw(mean),
        "xpts_5": mean * 5,
        "xmins": {
            "expected_minutes": 82,
            "start_probability": start_p,
            "dnp_probability": dnp,
        },
        "role": {
            "rotation_risk": .1,
            "competition_pressure": .2,
            "set_piece_share": .2,
            "penalty_share": 0,
        },
        "tactical_matchup": {"status": "VERIFIED", "score": .7} if tactical else None,
        "projection_confidence": "HIGH",
    }


def _fixture():
    owned = [
        _player(1, "Owned MID", "MID", 70, 3.5, team=1),
        _player(2, "Owned DEF", "DEF", 50, 3.0, team=2),
        _player(3, "Owned FWD", "FWD", 75, 4.0, team=3),
    ]
    challengers = [
        _player(101, "Challenger MID", "MID", 72, 4.5, team=4),
        _player(102, "Challenger DEF", "DEF", 48, 3.8, team=5),
        _player(103, "Challenger FWD", "FWD", 80, 4.2, team=6),
    ]
    prediction = {"planning_gw": 2, "players": owned + challengers}
    team = {
        "owned_ids": [1, 2, 3],
        "finance": {
            "bank": 5,
            "players": [
                {"element": 1, "now_cost": 70, "sell_cost": 69},
                {"element": 2, "now_cost": 50, "sell_cost": 50},
                {"element": 3, "now_cost": 75, "sell_cost": 74},
            ],
        },
    }
    watchlist = {
        "status": "READY",
        "positions": {
            "MID": [{"element": 101, "name": "Challenger MID", "position": "MID", "admission_status": "STRICT"}],
            "DEF": [{"element": 102, "name": "Challenger DEF", "position": "DEF", "admission_status": "STRICT"}],
            "FWD": [{"element": 103, "name": "Challenger FWD", "position": "FWD", "admission_status": "STRICT"}],
            "GK": [],
        },
    }
    workload = {
        "1": {"status": "VERIFIED", "days_rest": 6},
        "2": {"status": "VERIFIED", "days_rest": 7},
        "3": {"status": "VERIFIED", "days_rest": 5},
        "101": {"status": "VERIFIED", "days_rest": 7},
        "102": {"status": "VERIFIED", "days_rest": 6},
        "103": {"status": "VERIFIED", "days_rest": 7},
    }
    return prediction, team, watchlist, workload


def test_generic_comparator_has_no_named_pair_contract_and_all_horizons():
    prediction, team, watchlist, workload = _fixture()
    out = compare(prediction=prediction, team=team, watchlist=watchlist, workload_context=workload, transfer_state={"wildcard_active": True})
    assert out["authority"] == "ADVISORY_ONLY"
    assert out["pair_count"] >= 3
    for row in out["pairs"]:
        assert set(row["horizons"]) == {"1", "2", "3", "5"}
        assert row["owned"]["position"] == row["challenger"]["position"]
        assert row["owned"]["name"] != row["challenger"]["name"]


def test_same_position_and_price_band_bound_pairing():
    prediction, team, watchlist, workload = _fixture()
    prediction["players"].append(_player(104, "Very Expensive MID", "MID", 130, 9.0, team=7))
    watchlist["positions"]["MID"].append({"element": 104, "position": "MID", "admission_status": "STRICT"})
    out = compare(prediction=prediction, team=team, watchlist=watchlist, workload_context=workload)
    assert not any(row["challenger"]["element"] == 104 for row in out["pairs"])
    assert out["pair_count"] <= 24


def test_direct_swap_affordability_uses_sell_value_plus_bank():
    prediction, team, watchlist, workload = _fixture()
    out = compare(prediction=prediction, team=team, watchlist=watchlist, workload_context=workload, transfer_state={"wildcard_active": True})
    mid = next(row for row in out["pairs"] if row["challenger"]["element"] == 101)
    assert mid["affordability"]["owned_sell_cost"] == 69
    assert mid["affordability"]["bank"] == 5
    assert mid["affordability"]["affordable"] is True


def test_unaffordable_swap_is_hold_owned():
    prediction, team, watchlist, workload = _fixture()
    team["finance"]["bank"] = 0
    challenger = next(row for row in prediction["players"] if row["element"] == 101)
    challenger["now_cost"] = 80
    out = compare(prediction=prediction, team=team, watchlist=watchlist, workload_context=workload, transfer_state={"wildcard_active": True})
    mid = next(row for row in out["pairs"] if row["challenger"]["element"] == 101)
    assert mid["affordability"]["affordable"] is False
    assert mid["classification"] == "HOLD_OWNED"


def test_missing_future_tactical_and_workload_never_fabricated_and_cap_actionability():
    prediction, team, watchlist, _ = _fixture()
    challenger = next(row for row in prediction["players"] if row["element"] == 101)
    for row in challenger["xpts_by_gw"]:
        row["mean"] = 7.0
        row["fixtures"][0]["mean"] = 7.0
    challenger["xpts_5"] = 35
    out = compare(prediction=prediction, team=team, watchlist=watchlist, transfer_state={"wildcard_active": True})
    mid = next(row for row in out["pairs"] if row["challenger"]["element"] == 101)
    assert mid["evidence"]["future_tactical"] == "UNVERIFIED"
    assert mid["evidence"]["workload_context"] == "UNVERIFIED"
    assert mid["classification"] == "REVIEW"
    assert "CRITICAL_EVIDENCE_MISSING_CAPS_ACTIONABILITY" in mid["reasons"]


def test_wildcard_removes_unknown_ft_actionability_cap_when_other_evidence_is_verified_enough():
    prediction, team, watchlist, workload = _fixture()
    challenger = next(row for row in prediction["players"] if row["element"] == 101)
    for row in challenger["xpts_by_gw"]:
        row["mean"] = 6.0
        row["fixtures"][0]["mean"] = 6.0
    challenger["xpts_5"] = 30
    out = compare(prediction=prediction, team=team, watchlist=watchlist, workload_context=workload, transfer_state={"wildcard_active": True, "authoritative": True})
    mid = next(row for row in out["pairs"] if row["challenger"]["element"] == 101)
    # Future tactical is still intentionally UNVERIFIED, so transfer grade must remain capped.
    assert mid["classification"] == "REVIEW"
    assert "TRANSFER_COST_UNVERIFIED" not in mid["reasons"]


def test_free_hit_caps_permanent_transfer_actionability():
    prediction, team, watchlist, workload = _fixture()
    challenger = next(row for row in prediction["players"] if row["element"] == 101)
    for row in challenger["xpts_by_gw"]:
        row["mean"] = 6.5
        row["fixtures"][0]["mean"] = 6.5
    challenger["xpts_5"] = 32.5
    out = compare(prediction=prediction, team=team, watchlist=watchlist, workload_context=workload, transfer_state={"free_hit_active": True, "free_transfers": 5, "authoritative": True})
    mid = next(row for row in out["pairs"] if row["challenger"]["element"] == 101)
    assert mid["classification"] == "REVIEW"


def test_ineligible_start_security_blocks_challenger():
    prediction, team, watchlist, workload = _fixture()
    candidate = next(row for row in prediction["players"] if row["element"] == 101)
    candidate["xmins"]["start_probability"] = .20
    candidate["xmins"]["dnp_probability"] = .60
    out = compare(prediction=prediction, team=team, watchlist=watchlist, workload_context=workload)
    assert not any(row["challenger"]["element"] == 101 for row in out["pairs"])


def test_external_consensus_is_advisory_and_not_majority_vote():
    prediction, team, watchlist, workload = _fixture()
    out = compare(
        prediction=prediction,
        team=team,
        watchlist=watchlist,
        workload_context=workload,
        external_consensus={"101": {"state": "DIVERGE"}},
    )
    mid = next(row for row in out["pairs"] if row["challenger"]["element"] == 101)
    assert mid["external_consensus"]["state"] == "DIVERGE"
    assert mid["external_consensus"]["governance"] == "ADVISORY_ONLY_NO_MAJORITY_VOTE"


def test_emerging_challenger_is_discovery_lane_not_direct_buy():
    prediction, team, watchlist, workload = _fixture()
    emerging = _player(105, "Emerging MID", "MID", 70, 4.8, team=8)
    prediction["players"].append(emerging)
    out = compare(
        prediction=prediction,
        team=team,
        watchlist=watchlist,
        workload_context={**workload, "105": {"status": "VERIFIED", "days_rest": 7}},
        emerging_candidates=[{"element": 105, "triggered": True, "trigger": "GOAL_PLUS_ASSIST"}],
    )
    row = next(row for row in out["pairs"] if row["challenger"]["element"] == 105)
    assert row["challenger"]["lane"] == "EMERGING_CHALLENGER"
    assert row["classification"] not in {"BUY", "SELL"}


def test_evaluation_service_owns_comparator_operation():
    prediction, team, watchlist, workload = _fixture()
    out = evaluation_handle(
        "compare_owned_challenger",
        {
            "prediction": prediction,
            "truth": {"team": team, "context": {"planning_gw": 2}},
            "watchlist": watchlist,
            "workload_context": workload,
        },
    )
    assert out["model"] == "v5_owned_challenger_comparator_v1"
    assert evaluation_handle("status", {})["capabilities"].count("owned_challenger_comparator") == 1


def _report_payload(comparator):
    return {
        "truth": {"team": {"authority": "test", "owned_ids": list(range(1, 16))}},
        "decision": {
            "selected_package_id": "HOLD",
            "selected_package": {},
            "decision_trace": {"confidence": "HIGH"},
            "lineup": {
                "formation": "3-5-2",
                "starters": [{"element": x} for x in range(1, 12)],
                "bench": [{"element": x} for x in range(12, 16)],
                "captain": {"element": 1, "start_probability": .95, "expected_minutes": 88, "dnp_probability": .02},
                "vice_captain": {"element": 2},
                "captain_safe_pool": [{"element": 1, "captain_score": 8}, {"element": 2, "captain_score": 7}],
                "chip_context": {"active_chip": None},
                "main_starting_xi_battle": {"status": "CLEAR", "margin": 1.0},
            },
            "dss": {},
        },
        "prediction": {},
        "price": {"alerts": {"alerts": []}},
        "governance": {"overall": "GREEN", "go_allowed": True},
        "watchlist": {"status": "READY", "positions": {}},
        "owned_challenger_comparator": comparator,
        "previous_report_state": {},
    }


def test_report_overlay_is_additive_and_never_mutates_canonical_decision():
    prediction, team, watchlist, workload = _fixture()
    comparator = compare(prediction=prediction, team=team, watchlist=watchlist, workload_context=workload)
    payload = _report_payload(comparator)
    before = deepcopy(payload["decision"])
    report = build_report(payload)
    assert payload["decision"] == before
    assert report["user_report"]["decision"]["state"] == "HOLD"
    assert report["user_report"]["owned_vs_challenger"]["authority"] == "ADVISORY_ONLY"
    assert report["technical_appendix"]["owned_challenger_comparator"]["model"] == "v5_owned_challenger_comparator_v1"


def test_comparator_change_is_material_report_delta():
    prediction, team, watchlist, workload = _fixture()
    comparator = compare(prediction=prediction, team=team, watchlist=watchlist, workload_context=workload)
    first = build_report(_report_payload(comparator))
    changed = deepcopy(comparator)
    changed["top_comparisons"][0]["classification"] = "REVIEW"
    second_payload = _report_payload(changed)
    second_payload["previous_report_state"] = first["report_state"]
    second = build_report(second_payload)
    assert second["user_report"]["changes_since_last_report"]["material_change"] is True
    assert "owned_vs_challenger" in second["user_report"]["changes_since_last_report"]["changed"]
