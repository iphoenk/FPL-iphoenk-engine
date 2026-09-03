from __future__ import annotations

import json

from src.engines import v4_serving_contract
from src.utils import CONFIG


def test_weather_publication_uses_runtime_weather_context_artifact():
    assert v4_serving_contract.WEATHER_EVIDENCE.name == "weather_context_v4.json"


def test_governed_weather_status_overrides_raw_collection_without_hiding_raw():
    weather = {
        "health": {
            "status": "PARTIAL",
            "reason": "RETAINED_HISTORY_GAP",
            "tactical_context_completeness": "PARTIAL",
        },
        "fixtures": [{"fixture_id": 1}],
    }
    framework = {
        "weather_context": {
            "status": "PASS",
            "reason": "GOVERNED_DECISION_RELEVANT_WEATHER_EVIDENCE_AVAILABLE",
            "tactical_context_completeness": "FULL",
        }
    }

    out = v4_serving_contract._governed_weather_for_publication(framework, weather)

    assert out["health"]["status"] == "PASS"
    assert out["health"]["raw_collection_status"] == "PARTIAL"
    assert out["health"]["reason"] == "GOVERNED_DECISION_RELEVANT_WEATHER_EVIDENCE_AVAILABLE"
    assert out["health"]["tactical_context_completeness"] == "FULL"
    assert out["fixtures"] == weather["fixtures"]


def test_governed_weather_falls_back_to_raw_when_overlay_missing():
    weather = {"health": {"status": "STALE", "reason": "ONLY_STALE_FORECAST_AVAILABLE"}}

    out = v4_serving_contract._governed_weather_for_publication({}, weather)

    assert out["health"]["status"] == "STALE"
    assert out["health"]["raw_collection_status"] == "STALE"


def test_weather_provider_hardening_is_bounded_and_semantics_unchanged():
    cfg = json.loads((CONFIG / "intelligence" / "weather_context.json").read_text(encoding="utf-8"))

    assert cfg["api"]["max_concurrency"] == 1
    assert cfg["api"]["request_timeout_seconds"] >= 15
    assert cfg["evidence_policy"]["precedence"] == [
        "LIVE_OBSERVED",
        "CLOSEST_TO_KICKOFF_OBSERVATION",
        "FRESH_FORECAST",
        "STALE_FORECAST",
    ]
    assert cfg["governance"]["advisory_only"] is True
    assert cfg["governance"]["may_directly_change_xpts"] is False
    assert cfg["governance"]["may_directly_change_xmins"] is False
