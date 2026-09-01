from __future__ import annotations

import json
from pathlib import Path


PROFILE_PATH = Path("config/runtime/execution_profiles.json")


def test_fast_official_detail_has_only_bounded_retry_jitter_grace():
    payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    assert payload["registry"] == "RUNTIME_EXECUTION_PROFILES_V1"

    profiles = payload["profiles"]
    fast = profiles["fast_decision"]
    live = profiles["live"]

    fast_reuse = fast["reuse_services"]
    live_reuse = live["reuse_services"]

    assert fast_reuse["official_detail"]["max_age_seconds"] == 3660
    assert live_reuse["official_detail"]["max_age_seconds"] == 3600
    assert (
        fast_reuse["official_detail"]["max_age_seconds"]
        - live_reuse["official_detail"]["max_age_seconds"]
    ) == 60

    # Core Official state remains a same-job-only bounded reuse surface.
    assert fast_reuse["official_snapshot"]["max_age_seconds"] == 60

    # Prediction can never become age-reused merely to meet the runtime SLO.
    assert fast_reuse["prediction"]["max_age_seconds"] == 0
    assert live_reuse["prediction"]["max_age_seconds"] == 0

    # Complete profiles still refresh all declared capabilities.
    assert profiles["full_refresh"]["reuse_services"] == {}
    assert profiles["deep_stats"]["reuse_services"] == {}

    description = fast["description"].lower()
    assert "60-second scheduler/retry jitter grace" in description
    assert "core official current-state evidence remains freshly acquired every production job" in description
