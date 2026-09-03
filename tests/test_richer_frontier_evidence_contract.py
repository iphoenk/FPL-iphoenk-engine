from __future__ import annotations

import json

from src.runtime_v3 import frontier_evidence_contract as frontier


def _write(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def _player(element, team_id, *, minutes_std=10.0, tactical_state="AVAILABLE", transfer_state="SAME_CLUB"):
    return {
        "element": element,
        "team_id": team_id,
        "xmins": {"minutes_std": minutes_std},
        "tactical_matchup": {"evidence_dimensions": {"role": tactical_state, "formation": tactical_state}},
        "historical_prior": {"transfer_adaptation": {"state": transfer_state, "confidence_ceiling": "MEDIUM" if transfer_state != "SAME_CLUB" else None, "old_role_prior_retired": False}},
    }


def _score(value=10.0, std=2.0):
    return {"robust_score": value, "objective_std": std, "horizons": {str(h): {"mean": value * h} for h in (3, 5, 10, 15)}}


def test_richer_frontier_uses_governed_representation_only_dimensions(monkeypatch, tmp_path):
    players = [_player(i, i, minutes_std=5.0) for i in range(1, 16)] + [_player(100, 16, minutes_std=18.0, tactical_state="PARTIAL", transfer_state="INTRA_PL_TRANSFER")]
    _write(tmp_path / "projections.json", {"players": players})
    _write(tmp_path / "team.json", {"team_value_ledger": [{"element": i} for i in range(1, 16)]})
    _write(tmp_path / "prices.json", {"players": [{"element_id": 100, "direction": "FALL", "projection_offset_0_percent": -82.0, "current_progress_percent": -70.0}]})
    monkeypatch.setattr(frontier, "DATA", tmp_path)
    frontier._evidence.cache_clear()

    hold = {"id": "HOLD", "changes": 0, "outs": [], "ins": [], "affordability": {"resulting_itb": 0}, "score": _score()}
    transfer = {"id": "1:1->100", "changes": 1, "outs": [{"element": 1}], "ins": [{"element": 100}], "affordability": {"resulting_itb": 5}, "score": _score(11.0, 2.1)}
    instance = frontier.Frontier.from_hold(hold)
    instance.add(hold)
    instance.add(transfer)
    output = instance.output(20, 2)

    assert output["authority"] == "REPRESENTATION_ONLY"
    assert output["representation_input"] == "ALL_EVALUATED_LEGAL_PACKAGES"
    assert output["dimensions_pending_richer_runtime_evidence"] == []
    assert "xmins_uncertainty_minutes_std_sum" in output["dimensions_used"]
    assert "tactical_role_uncertainty_missing_dimensions" in output["dimensions_used"]
    assert "price_risk_adverse_progress_percent" in output["dimensions_used"]
    assert "club_slot_headroom" in output["dimensions_used"]
    assert "roster_change_uncertainty_players" in output["dimensions_used"]
    row = next(row for row in output["packages"] if row["id"] == "1:1->100")
    assert row["price_risk_adverse_progress_percent"] == 82.0
    assert row["tactical_role_uncertainty_missing_dimensions"] == 2
    assert row["roster_change_uncertainty_players"] == 1


def test_richer_frontier_does_not_mutate_package_scores(monkeypatch, tmp_path):
    players = [_player(i, i) for i in range(1, 16)]
    _write(tmp_path / "projections.json", {"players": players})
    _write(tmp_path / "team.json", {"team_value_ledger": [{"element": i} for i in range(1, 16)]})
    _write(tmp_path / "prices.json", {"players": []})
    monkeypatch.setattr(frontier, "DATA", tmp_path)
    frontier._evidence.cache_clear()
    package = {"id": "HOLD", "changes": 0, "outs": [], "ins": [], "affordability": {"resulting_itb": 0}, "score": _score()}
    before = json.loads(json.dumps(package["score"]))
    frontier.metrics(package, package["score"]["horizons"])
    assert package["score"] == before


def test_runtime_install_keeps_canonical_search_and_scoring_owners():
    from src.engines import package_optimizer_exhaustive_accelerated as accelerated
    from src.engines import package_optimizer_exhaustive_finalize as base
    assert base._Frontier is frontier.Frontier
    assert base._metrics is frontier.metrics
    assert accelerated.exact_skyline_indices is frontier.skyline_indices
