from src.engines.gameweek_lifecycle_intelligence import build_gameweek_lifecycle


def _previous():
    squad = []
    positions = ["GK", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD", "GK", "DEF", "MID", "FWD"]
    for index, position in enumerate(positions, start=1):
        squad.append({
            "element": index,
            "name": f"P{index}",
            "position": position,
            "pick_position": index,
            "captain": index == 9,
            "vice_captain": index == 10,
        })
    return {
        "gw": 1,
        "status": "FINAL",
        "actual_points": 71,
        "chip": "BENCH_BOOST",
        "submitted_squad": squad,
    }


def _event_live(points=None, minutes=None):
    points = points or {}
    minutes = minutes or {}
    return {
        "elements": [
            {"id": element, "stats": {"total_points": points.get(element, 2), "minutes": minutes.get(element, 90), "starts": 1}}
            for element in range(1, 25)
        ]
    }


def _payload(*, final=False):
    previous = _previous()
    current_ids = list(range(1, 8)) + list(range(16, 24))
    team = {"team_value_ledger": [{"element": e, "name": f"C{e}", "position": "MID"} for e in current_ids]}
    live = {
        "scoring_gw": 2,
        "status": "FINAL" if final else "PROVISIONAL",
        "gross_points": 50,
        "hit": 0,
        "net_points": 50,
        "players": [{"element": e, "name": f"C{e}", "position": "MID", "pick_position": n + 1, "multiplier": 1, "minutes": 90, "total_points": 2} for n, e in enumerate(current_ids)],
    }
    snapshot = {"phase": {"scoring_gw": 2}, "event_live": _event_live(), "endpoint_health": {"event_live": {"status": "OK"}}}
    context = {"historical": [previous], "planning": {"gw": 3, "estimated_points": 48.5}}
    return build_gameweek_lifecycle(
        gameweek_context=context,
        team=team,
        live=live,
        official_snapshot=snapshot,
        prediction_accuracy={"status": "WAIT_FOR_DATA", "aggregate": {"sample_size": 0}},
        auth={"state": "DISABLED", "expected_entry": 3462711, "raw_authenticated_payload_persisted": False},
        price_model_health={"status": "WARMUP", "direction_samples": 3},
    )


def test_lifecycle_transition_uses_identity_and_never_previous_points_as_wc_loss():
    payload = _payload()
    transition = payload["transition"]
    assert len(transition["kept"]) == 7
    assert len(transition["ins"]) == 8
    assert len(transition["outs"]) == 8
    assert transition["governance"]["previous_gw_points_never_count_as_transfer_or_wildcard_loss"] is True
    assert payload["previous_gw"]["actual_points"] == 71


def test_provisional_counterfactual_cannot_be_finalized():
    payload = _payload(final=False)
    pnl = payload["counterfactual_pnl"]
    assert pnl["status"] == "PROVISIONAL"
    assert pnl["verdict"] == "PROVISIONAL"
    assert pnl["old_squad_counterfactual"]["status"] == "PROVISIONAL_NO_AUTOSUB_FINALIZATION"
    assert pnl["governance"]["never_finalize_before_current_gw_final"] is True


def test_final_counterfactual_settles_same_gameweek_actuals():
    payload = _payload(final=True)
    pnl = payload["counterfactual_pnl"]
    assert pnl["status"] == "SETTLED"
    assert pnl["old_squad_counterfactual"]["governance"]["same_gameweek_actuals_only"] is True
    assert pnl["old_squad_counterfactual"]["governance"]["no_previous_gameweek_points_used"] is True
    assert isinstance(pnl["realized_or_live_pnl"], float)


def test_auth_disabled_is_explicit_red_without_authority_upgrade():
    payload = _payload()
    auth = payload["authenticated_official"]
    assert auth["health"] == "RED"
    assert auth["state"] == "DISABLED"
    assert auth["authority_upgrade_allowed"] is False
    assert auth["raw_authenticated_payload_persisted"] is False


def test_price_warmup_is_advisory_only_and_never_single_trigger():
    payload = _payload()
    price = payload["price_calibration"]
    assert price["status"] == "WARMUP"
    assert price["actionability"] == "ADVISORY_ONLY"
    assert price["price_alone_can_trigger_transfer"] is False


def test_learning_wait_for_data_is_preserved_not_fabricated():
    payload = _payload()
    learning = payload["learning"]
    assert learning["status"] == "WAIT_FOR_DATA"
    assert learning["governance"]["genuine_predeadline_samples_only"] is True
    assert learning["governance"]["retrospective_forecast_fabrication_forbidden"] is True
