from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from src.models.observed_tactical_context import merge_recent_history
from src.runtime_v3.incremental_reuse import _semantic_hash, _tactical_official_snapshot


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "runtime" / "incremental_reuse.json"
EXECUTION_PROFILES = ROOT / "config" / "runtime" / "execution_profiles.json"


def _config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _execution_profiles() -> dict:
    return json.loads(EXECUTION_PROFILES.read_text(encoding="utf-8"))


def _official_tactical_payload() -> dict:
    return {
        "phase": {"current_gw": 2, "planning_gw": 3},
        "official_freshness": {
            "snapshot_id": "snapshot-a",
            "last_verified_at": "2026-09-03T00:00:00Z",
        },
        "endpoint_health": {"bootstrap": {"latency_ms": 100}},
        "bootstrap": {
            "teams": [{"id": 1, "name": "Arsenal", "short_name": "ARS", "strength": 5}],
            "elements": [{
                "id": 8,
                "team": 1,
                "element_type": 2,
                "web_name": "Calafiori",
                "first_name": "Riccardo",
                "second_name": "Calafiori",
                "now_cost": 56,
                "selected_by_percent": "43.6",
            }],
        },
        "fixtures": [{
            "id": 31,
            "event": 3,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-09-04T19:00:00Z",
            "finished": False,
            "started": False,
            "team_h_score": None,
            "team_a_score": None,
        }],
    }


def test_tactical_context_reuse_is_exact_content_addressed_not_ttl() -> None:
    cfg = _config()
    policy = cfg["policy"]
    tactical = cfg["services"]["tactical_context"]

    assert policy["reuse_requires_matching_input_fingerprint"] is True
    assert policy["reuse_requires_all_declared_artifacts"] is True
    assert policy["reuse_never_bypasses_artifact_validation"] is True
    assert policy["reuse_is_invalidated_by_source_tree_change"] is True
    assert policy["full_refresh_and_deep_stats_never_use_fingerprint_reuse"] is True
    assert policy["football_formulas_unchanged"] is True
    assert "ttl" not in tactical


def test_tactical_context_reuse_fingerprints_all_material_evidence_and_policy() -> None:
    inputs = set(_config()["services"]["tactical_context"]["inputs"])
    required = {
        "src/",
        "official_snapshot.json",
        "player_features.json",
        "stats/shots_current.json",
        "stats/playermatchstats_current.json",
        "recent_tactical_form.json",
        "stats/understat_epl_2026.json",
        "config/intelligence/tactical_observed_context.json",
        "config/intelligence/understat_tactical.json",
    }

    assert required <= inputs


def test_tactical_official_semantic_state_ignores_non_consumed_refresh_metadata() -> None:
    base = _official_tactical_payload()
    changed = deepcopy(base)
    changed["official_freshness"]["snapshot_id"] = "snapshot-b"
    changed["official_freshness"]["last_verified_at"] = "2026-09-03T00:10:00Z"
    changed["endpoint_health"]["bootstrap"]["latency_ms"] = 9999
    changed["bootstrap"]["elements"][0]["now_cost"] = 57
    changed["bootstrap"]["elements"][0]["selected_by_percent"] = "50.0"
    changed["fixtures"][0]["started"] = True
    changed["fixtures"][0]["team_h_score"] = 1

    base_semantic = _tactical_official_snapshot(base)
    changed_semantic = _tactical_official_snapshot(changed)
    assert base_semantic == changed_semantic
    assert _semantic_hash(base_semantic, top_level=True) == _semantic_hash(changed_semantic, top_level=True)


def test_tactical_official_semantic_state_invalidates_material_identity_and_fixture_input() -> None:
    base = _official_tactical_payload()
    baseline = _semantic_hash(_tactical_official_snapshot(base), top_level=True)

    identity = deepcopy(base)
    identity["bootstrap"]["elements"][0]["team"] = 2
    assert _semantic_hash(_tactical_official_snapshot(identity), top_level=True) != baseline

    name = deepcopy(base)
    name["bootstrap"]["elements"][0]["second_name"] = "Changed"
    assert _semantic_hash(_tactical_official_snapshot(name), top_level=True) != baseline

    fixture = deepcopy(base)
    fixture["fixtures"][0]["team_a"] = 3
    assert _semantic_hash(_tactical_official_snapshot(fixture), top_level=True) != baseline

    finished = deepcopy(base)
    finished["fixtures"][0]["finished"] = True
    assert _semantic_hash(_tactical_official_snapshot(finished), top_level=True) != baseline

    phase = deepcopy(base)
    phase["phase"]["current_gw"] = 3
    assert _semantic_hash(_tactical_official_snapshot(phase), top_level=True) != baseline


def test_tactical_context_reuse_is_not_live_opted_in() -> None:
    cfg = _config()
    tactical = cfg["services"]["tactical_context"]
    profiles = _execution_profiles()["profiles"]

    assert cfg["policy"]["disable_when_current_scoring_fixture_live"] is True
    assert cfg["policy"]["live_reuse_requires_explicit_service_opt_in"] is True
    assert tactical.get("allow_during_live") is not True
    assert "tactical_context" not in profiles["live"]["reuse_services"]


def test_tactical_context_exact_reuse_is_declared_by_fast_profile_without_age_reuse() -> None:
    profiles_cfg = _execution_profiles()
    policy = profiles_cfg["policy"]
    fast_reuse = profiles_cfg["profiles"]["fast_decision"]["reuse_services"]

    assert policy["non_positive_ttl_disables_age_reuse"] is True
    assert policy["tactical_context_age_reuse_forbidden"] is True
    assert policy["tactical_context_content_addressed_reuse_requires_exact_fingerprint_match"] is True
    assert fast_reuse["tactical_context"] == {"max_age_seconds": 0}


def test_tactical_context_records_post_execution_fingerprint_only_for_owned_rolling_state() -> None:
    cfg = _config()
    policy = cfg["policy"]
    tactical = cfg["services"]["tactical_context"]
    prediction = cfg["services"]["prediction"]

    assert policy["self_owned_rolling_state_may_record_post_execution_fingerprint_only_when_idempotent"] is True
    assert tactical["record_post_execution_fingerprint"] is True
    assert tactical["self_owned_rolling_state"] == "recent_tactical_form.json"
    assert tactical["self_owned_rolling_state"] in tactical["inputs"]
    assert prediction.get("record_post_execution_fingerprint") is not True


def test_recent_tactical_history_merge_is_idempotent_for_same_observed_match() -> None:
    observed = {
        "gw": 2,
        "match_id": "gw2-team1-team2",
        "opponent_team_id": 2,
        "home": True,
        "formation": "4-3-3",
        "strengths": ["box_pressure"],
        "vulnerabilities": [],
    }
    cfg = {"recent_gw_window": 5}

    once = merge_recent_history(
        {"teams": {"1": []}},
        {1: [observed]},
        [1],
        cfg,
    )
    twice = merge_recent_history(
        {"teams": once},
        {1: [observed]},
        [1],
        cfg,
    )

    assert twice == once
