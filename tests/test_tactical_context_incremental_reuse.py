from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "runtime" / "incremental_reuse.json"


def _config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


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


def test_tactical_context_reuse_is_not_live_opted_in() -> None:
    cfg = _config()
    tactical = cfg["services"]["tactical_context"]

    assert cfg["policy"]["disable_when_current_scoring_fixture_live"] is True
    assert cfg["policy"]["live_reuse_requires_explicit_service_opt_in"] is True
    assert tactical.get("allow_during_live") is not True
