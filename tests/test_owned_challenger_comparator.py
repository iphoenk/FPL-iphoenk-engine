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
    return {"element": proj["element"], "name": proj["name"], "position": proj["position"], "team_id": proj["team_id"], "sell_cost": sell_cost, "now_cost": proj["now_cost"], "projection": proj}


def _evidence_read_json(path, default=None):
    name = getattr(path, "name", "")
    if name == "recent_competitive_load.json":
        return {"players": {"2": {"state": "NORMAL"}}}
    return default if default is not None else {}


def test_output_states_are_exact_contract():
    assert comp.load_policy()["output_states"] == ["HOLD", "WATCH", "REVIEW", "LEAN_TRANSFER", "STRONG_TRANSFER"]


def test_exact_sell_value_and_same_position_drive_legality(monkeypatch):
    monkeypatch.setattr(comp, "read_json", _evidence_read_json)
    out_proj = _proj(1, "MID", 1, [2, 2, 2, 2, 2])
    incoming = _proj(2, "MID", 2, [3, 3, 3, 3, 3], cost=60)
    owned = [_owned_row(out_proj, sell_cost=55)]
    external = {"overall": "ALIGN", "subjects": []}
    row = comp._compare(owned[0], incoming, "GOVERNED_WATCHLIST", [], True, owned, 5, {}, external)
    assert row["finance"]["exact_sell_cost"] == 55
    assert row["finance"]["affordable"] is True
    assert row["legality"]["same_position"] is True


def test_missing_critical_evidence_caps_positive_edge_at_review(monkeypatch):
    monkeypatch.setattr(comp, "read_json", lambda path, default=None: default if default is not None else {})
    out_proj = _proj(1, "FWD", 1, [1] * 15)
    incoming = _proj(2, "FWD", 2, [3] * 15, tactical=False)
    owned = [_owned_row(out_proj)]
    row = comp._compare(owned[0], incoming, "GOVERNED_WATCHLIST", [], True, owned, 20, {}, {"overall": "INSUFFICIENT_EVIDENCE", "subjects": []})
    assert row["horizons"]["5"]["projected_edge"] > 3
    assert row["state"] == "REVIEW"
    assert "competitive_load" in row["missing_critical_evidence"]
    assert "external_consensus" in row["missing_critical_evidence"]


def test_one_haul_cannot_promote_unsustainable_emerging_candidate(monkeypatch):
    monkeypatch.setattr(comp, "read_json", _evidence_read_json)
    out_proj = _proj(1, "MID", 1, [2] * 15)
    incoming = _proj(2, "MID", 2, [4] * 15)
    owned = [_owned_row(out_proj)]
    row = comp._compare(owned[0], incoming, "EMERGING_CHALLENGER", ["MULTIPLE_MATCH_RETURNS"], False, owned, 20, {}, {"overall": "ALIGN", "subjects": []})
    assert row["anti_haul_chasing"]["single_haul_is_not_sufficient"] is True
    assert row["state"] == "WATCH"


def test_comparator_never_claims_authoritative_mutation():
    governance = comp.load_policy()["governance"]
    assert governance["may_not_overwrite_canonical_transfer_recommendation"] is True
    assert governance["may_not_overwrite_starting_xi"] is True
    assert governance["may_not_overwrite_captain_or_vice"] is True
    assert governance["may_not_overwrite_chip_decision"] is True
    assert governance["advisory_until_calibrated"] is True
