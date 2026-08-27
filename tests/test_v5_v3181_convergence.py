from __future__ import annotations

import json
from pathlib import Path

from src.v5.services.decision import _apply_package_guardrails, _dss_full_active

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PRODUCTION_SHA = "02d0ce597e111e9b7d464f88479d78d462b616eb"


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _source_map() -> dict[str, dict]:
    return {
        str(row["id"]): row
        for row in _load("config/sources/registry.json").get("sources") or []
    }


def test_v3181_baseline_and_schema_are_converged() -> None:
    manifest = _load("config/v5_convergence_manifest.json")
    acceptance = _load("config/v5_acceptance_registry.json")
    engine = _load("config/engine.json")

    production_truth = str(manifest["baselines"]["production_truth"])
    assert production_truth == "v3.18.1"
    assert acceptance["convergence"]["production_baseline"] == production_truth
    assert manifest["baselines"]["production_main_sha"] == EXPECTED_PRODUCTION_SHA
    assert acceptance["convergence"]["production_main_sha"] == EXPECTED_PRODUCTION_SHA
    assert production_truth in str(manifest["baselines"]["prediction_intelligence"])
    assert engine["schema_version"] == 47
    assert int(engine["strategic_horizon_gws"]) >= int(engine["projection_horizon_gws"])


def test_v3181_challenger_source_contracts_are_converged() -> None:
    registry = _load("config/sources/registry.json")
    acceptance = _load("config/v5_acceptance_registry.json")
    authority = _load("config/v5_source_authority_registry.json")
    policy = registry["policy"]
    governance = authority["governance"]
    sources = _source_map()

    assert policy["source_reachability_is_separate_from_capability_health"] is True
    assert policy["stale_observations_are_never_silently_current"] is True
    assert policy["challenger_observation_contract"] == "challenger_observation_v2"
    assert governance["source_reachability_is_separate_from_capability_health"] is True
    assert governance["stale_observations_are_never_silently_current"] is True
    assert governance["challenger_observation_contract"] == "challenger_observation_v2"

    onefpl = sources["onefpl"]
    assert onefpl["structured_url"] == "https://onefpl.com/prices"
    assert onefpl["parser_contract"] == acceptance["convergence"]["onefpl_parser_contract_required"] == "onefpl-price-v2"
    assert onefpl["fallback_structured_urls"]
    assert {"onefpl.com", "www.onefpl.com"}.issubset(set(onefpl["allowed_hosts"]))
    assert int(onefpl["observation_ttl_seconds"]) > 0

    livefpl = sources["livefpl"]
    assert livefpl["structured_url"] == "https://www.livefpl.net/prices"
    assert livefpl["parser_contract"] == acceptance["convergence"]["livefpl_parser_contract_required"] == "livefpl-price-v1"
    assert int(livefpl["observation_ttl_seconds"]) > 0


def test_v5_runtime_enrichment_sources_are_declared_in_authority_registry() -> None:
    authority = _load("config/v5_source_authority_registry.json")
    sources = authority["sources"]
    assert sources["understat"]["enabled"] is True
    assert sources["api_football"]["enabled"] is True
    assert authority["domains"]["cross_competition_schedule_context"] == ["api_football"]
    assert "understat" in authority["domains"]["advanced_player_stats"]


def test_package_guardrails_have_single_config_authority() -> None:
    package = _load("config/intelligence/package_optimizer.json")
    decision = _load("config/v5_decision_registry.json")

    assert package["early_season_change_cap"]["enabled"] is True
    assert package["team_cluster_penalty"]["enabled"] is True
    assert decision["package_selection"]["guardrail_authority"] == "config/intelligence/package_optimizer.json"
    assert "team_cluster_penalty" not in decision["package_selection"]


def test_early_season_cap_and_cluster_penalty_execute() -> None:
    packages = {
        "status": "READY",
        "local_legality_prevalidated": True,
        "packages": [
            {"id": "HOLD", "changes": 0, "outs": [], "ins": [], "score": {"valid": True, "robust_score": 10.0, "performance": {}}},
            {"id": "2:test", "changes": 2, "outs": [], "ins": [], "score": {"valid": True, "robust_score": 11.0, "performance": {}}},
            {"id": "3:reject", "changes": 3, "outs": [], "ins": [], "score": {"valid": True, "robust_score": 99.0, "performance": {}}},
        ],
    }
    team = {
        "squad": [
            {"element": 1, "team_id": 1},
            {"element": 2, "team_id": 1},
            {"element": 3, "team_id": 1},
            {"element": 4, "team_id": 2},
        ]
    }
    prediction = {"players": [{"element": row["element"], "team_id": row["team_id"]} for row in team["squad"]]}

    guarded = _apply_package_guardrails(packages, prediction, team, planning_gw=2)
    ids = {row["id"] for row in guarded["packages"]}

    assert "3:reject" not in ids
    assert guarded["early_season_change_cap_applied"] is True
    assert guarded["team_cluster_penalty_applied"] is True
    assert guarded["guardrails"]["over_cap_packages_rejected"] == 1
    hold = next(row for row in guarded["packages"] if row["id"] == "HOLD")
    assert hold["score"]["team_cluster_penalty_points"] > 0
    assert hold["score"]["robust_score"] < hold["score"]["raw_robust_score"]


def test_strict_postflight_requires_all_dss_active() -> None:
    full = {
        "core": {"expected": 50, "integrity_ok": True, "counts": {"ACTIVE": 50}},
        "extensions": {"expected": 16, "integrity_ok": True, "counts": {"ACTIVE": 16}},
    }
    partial = {
        "core": {"expected": 50, "integrity_ok": True, "counts": {"ACTIVE": 49, "PARTIAL": 1}},
        "extensions": {"expected": 16, "integrity_ok": True, "counts": {"ACTIVE": 16}},
    }

    assert _dss_full_active(full) is True
    assert _dss_full_active(partial) is False
