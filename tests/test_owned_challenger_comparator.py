import src.engines.owned_challenger_comparator as comp


def _proj(element, position, team_id, means, start=0.8, tactical=True, cost=50):
    return {
        "element": element,
        "name": f"P{element}",
        "position": position,
        "team_id": team_id,
        "now_cost": cost,
        "status": "a",
        "projection_confidence": "MEDIUM",
        "xmins": {"expected_minutes": 75.0, "start_probability": start, "dnp_probability": 0.05},
        "xpts_by_gw": [{"gw": 3 + i, "mean": mean, "std": 1.0} for i, mean in enumerate(means)],
        "rates": {"xg90": 0.3, "xa90": 0.2},
        "tactical_matchup": {"evidence_state": "READY"} if tactical else {},
    }


def _owned_row(proj, sell_cost=50):
    return {
        "element": proj["element"],
        "name": proj["name"],
        "position": proj["position"],
        "team_id": proj["team_id"],
        "sell_cost": sell_cost,
        "now_cost": proj["now_cost"],
        "projection": proj,
    }


def _candidate(proj, *, mandatory=False):
    return {
        "projection": proj,
        "challenger_types": ["MANDATORY_VALUE_MARKET_REVIEW"] if mandatory else ["GOVERNED_WATCHLIST"],
        "discovery": {
            "mandatory_challenger_review": mandatory,
            "identity_sanity": {"status": "PASS", "downstream_projection_trusted": True},
        },
    }


def _loads(*elements):
    return {int(element): {"state": "NORMAL"} for element in elements}


def test_output_states_are_exact_governed_contract():
    policy = comp.load_policy()
    assert policy["pair_states"] == ["HOLD", "WATCH", "REVIEW", "LEAN_TRANSFER", "STRONG_TRANSFER"]
    assert policy["decision_states"] == ["HOLD", "REVIEW", "REVIEW_NOW", "CHANGE", "BLOCKED"]
    assert policy["capability_status"] == "GOVERNED_DECISION"


def test_exact_sell_value_and_same_position_drive_legality():
    out_proj = _proj(1, "MID", 1, [2] * 15)
    incoming = _proj(2, "MID", 2, [3] * 15, cost=60)
    owned = [_owned_row(out_proj, sell_cost=55)]
    row = comp._compare(
        owned[0],
        _candidate(incoming),
        owned=owned,
        itb=5,
        prices={},
        single_packages={(1, 2): {"robust_gain_vs_hold": 3.0, "hit_cost": 0}},
        load_map=_loads(1, 2),
    )
    assert row["finance"]["exact_sell_cost"] == 55
    assert row["finance"]["affordable"] is True
    assert row["legality"]["same_position"] is True


def test_missing_critical_evidence_caps_positive_edge_at_review():
    out_proj = _proj(1, "FWD", 1, [1] * 15)
    incoming = _proj(2, "FWD", 2, [3] * 15, tactical=False)
    owned = [_owned_row(out_proj)]
    row = comp._compare(
        owned[0],
        _candidate(incoming),
        owned=owned,
        itb=20,
        prices={},
        single_packages={(1, 2): {"robust_gain_vs_hold": 8.0, "hit_cost": 0}},
        load_map=_loads(1),
    )
    assert row["horizons"]["5"]["projected_edge"] > 3
    assert row["state"] == "REVIEW"
    assert "tactical_context" in row["missing_critical_evidence"]
    assert "competitive_load" in row["missing_critical_evidence"]


def test_price_urgency_changes_timing_not_football_truth():
    out_proj = _proj(1, "DEF", 1, [2] * 15)
    incoming = _proj(2, "DEF", 2, [2.1] * 15, cost=45)
    owned = [_owned_row(out_proj)]
    prices = {
        2: {
            "risk_direction": "RISE",
            "urgency": "CRITICAL",
            "freshness_seconds": 60,
            "evidence_state": "AVAILABLE",
        }
    }
    row = comp._compare(
        owned[0],
        _candidate(incoming, mandatory=True),
        owned=owned,
        itb=10,
        prices=prices,
        single_packages={},
        load_map=_loads(1, 2),
    )
    assert row["market_timing"]["football_decision_authority"] is False
    assert row["state"] in {"HOLD", "REVIEW"}
    assert row["actionability"]["level"] != "ACTIONABLE_CHANGE"


def test_no_player_specific_out_hardcode_and_canonical_package_reuse():
    governance = comp.load_policy()["governance"]
    assert governance["no_player_specific_out_hardcode"] is True
    assert governance["reuse_canonical_package_legality_and_scoring"] is True
    assert governance["mandatory_value_market_candidate_must_be_evaluated_before_publication"] is True
    assert governance["may_not_overwrite_starting_xi"] is True
    assert governance["may_not_overwrite_captain_or_vice"] is True
    assert governance["may_not_overwrite_chip_decision"] is True
