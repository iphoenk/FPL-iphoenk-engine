from __future__ import annotations

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
