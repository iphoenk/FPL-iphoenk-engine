import json
from pathlib import Path


def test_recent_competitive_load_is_mandatory_for_visible_reports():
    policy = json.loads(Path("config/intelligence/recent_competitive_load.json").read_text(encoding="utf-8"))
    assert policy["contract"] == "RECENT_COMPETITIVE_LOAD_V1"
    assert policy["scope"]["mandatory_before_visible_report"] is True
    assert policy["scope"]["mandatory_on_deadline_day"] is True
    assert "EFL Cup" in policy["competitions"]
    assert "UEFA Conference League" in policy["competitions"]
    assert policy["xmins_handoff"]["enabled"] is True
    assert policy["xmins_handoff"]["direct_xpts_mutation_forbidden"] is True
    assert set(policy["xmins_handoff"]["allowed_targets"]) >= {
        "manager_start_probability",
        "rotation_risk",
        "congestion_factor",
        "xmins_confidence",
    }


def test_report_time_registry_requires_pressers_and_latest_competitive_match():
    registry = json.loads(Path("config/sources/report_time_registry.json").read_text(encoding="utf-8"))
    p = registry["policy"]
    assert p["press_conference_sweep_required"] is True
    assert p["last_competitive_match_sweep_required"] is True
    assert p["recent_competitive_load_policy_ref"] == "config/intelligence/recent_competitive_load.json"
    sources = {row["id"]: row for row in registry["sources"]}
    official = sources["premier_league_official_news"]
    matches = sources["official_competitive_match_news"]
    assert "press_conference" in official["capabilities"]
    assert "recent_competitive_match" in matches["capabilities"]
    assert "minutes_load" in matches["capabilities"]
    assert matches["class"] == "VERIFIED_NEWS"
    assert matches["consensus_vote"] is False
