from __future__ import annotations

import json

import src.engines.dss_operationalization_overlay as operationalization
from src.engines.dss_operationalization_overlay import EVALUATORS, load_policy
from src.models.package_optimizer_v2 import load_config, score_package


def _player(element: int, position: str, team_id: int) -> dict:
    return {
        "element": element,
        "position": position,
        "team_id": team_id,
        "xpts_by_gw": [
            {"gw": gw, "mean": 4.0 + (element % 3) * 0.1, "std": 1.5}
            for gw in range(2, 17)
        ],
    }


def _legal_shape_players() -> list[dict]:
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return [_player(idx + 1, position, (idx % 7) + 1) for idx, position in enumerate(positions)]


def test_every_operationalization_capability_has_registered_evaluator():
    policy = load_policy()
    capabilities = policy["capabilities"]
    assert capabilities
    for probe, spec in capabilities.items():
        assert spec.get("owner"), probe
        assert spec.get("evaluator") in EVALUATORS, probe
        if "fallback" in spec:
            assert spec["fallback"], probe
    assert policy["policy"]["missing_external_evidence_is_never_fabricated"] is True
    assert policy["policy"]["strict_postflight_requires_all_dss_active"] is True


def test_transfer_momentum_uses_official_counts_and_current_price_linkage(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(operationalization, "DATA", data)

    players = [
        {
            "element": element,
            "now_cost": 50 + element,
            "transfers_in_event": element * 10,
            "transfers_out_event": element * 3,
        }
        for element in range(1, 21)
    ]
    price_cache = {
        "players": {
            str(player["element"]): {"now_cost": player["now_cost"], "ownership": 1.0}
            for player in players
        }
    }
    (data / "universe.json").write_text(json.dumps({"players": players}), encoding="utf-8")
    (data / "price_cache.json").write_text(json.dumps(price_cache), encoding="utf-8")

    spec = load_policy()["capabilities"]["transfer_momentum"]
    ok, detail = operationalization._transfer_momentum(spec)

    assert ok is True
    assert detail["evidence_state"] == "AVAILABLE"
    assert detail["transfer_count_coverage_ratio"] == 1.0
    assert detail["price_cache_linkage_ratio"] == 1.0
    assert detail["current_price_match_ratio"] == 1.0
    assert detail["net_transfers_event"] == sum(player["transfers_in_event"] - player["transfers_out_event"] for player in players)
    assert detail["external_threshold_invented"] is False
    assert detail["predicted_price_change_invented"] is False
    assert load_policy()["evidence_maturity"]["evaluator_available_tier"]["transfer_momentum"] == "DERIVED"


def test_transfer_momentum_fails_closed_when_price_linkage_is_incomplete(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(operationalization, "DATA", data)

    players = [
        {
            "element": element,
            "now_cost": 50,
            "transfers_in_event": 100,
            "transfers_out_event": 50,
        }
        for element in range(1, 21)
    ]
    cache = {str(element): {"now_cost": 50} for element in range(1, 19)}
    (data / "universe.json").write_text(json.dumps({"players": players}), encoding="utf-8")
    (data / "price_cache.json").write_text(json.dumps({"players": cache}), encoding="utf-8")

    ok, detail = operationalization._transfer_momentum(load_policy()["capabilities"]["transfer_momentum"])

    assert ok is False
    assert detail["evidence_state"] == "INSUFFICIENT"
    assert detail["price_cache_linkage_ratio"] == 0.9


def test_package_optimizer_executes_cluster_and_early_season_guardrails():
    cfg = load_config()
    players = _legal_shape_players()
    scored = score_package(players, planning_gw=2, changes=0)
    assert scored["valid"] is True
    guards = scored["guardrails"]
    assert guards["team_cluster_penalty_enabled"] is True
    assert guards["early_season_change_cap_enabled"] is True
    assert scored["team_cluster_penalty_points"] >= 0

    early = cfg["early_season_change_cap"]
    over_cap = int(early["max_changes"]) + 1
    rejected = score_package(players, planning_gw=min(2, int(early["through_gw"])), changes=over_cap)
    assert rejected["valid"] is False
    assert rejected["reason"] == "early_season_change_cap_exceeded"
