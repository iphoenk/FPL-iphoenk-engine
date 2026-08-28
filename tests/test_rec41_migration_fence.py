import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_rec41_migration_fence_is_closed_after_runtime_publication():
    profiles = json.loads((ROOT / "config/runtime/execution_profiles.json").read_text())
    policy = profiles["policy"]
    assert policy["rec41_player_feature_migration_fence_active"] is False
    assert policy["rec41_player_feature_migration_verified_in_runtime_data"] is True
    assert profiles["profiles"]["fast_decision"]["reuse_services"]["advanced_stats"]["max_age_seconds"] == 21600
    assert profiles["profiles"]["live"]["reuse_services"]["advanced_stats"]["max_age_seconds"] == 21600
