import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "intelligence" / "competitive_load.json"
LEGACY_POLICY_PATH = ROOT / "config" / "intelligence" / "recent_competitive_load.json"


def test_competitive_load_is_single_canonical_policy_for_runtime_and_reports():
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    assert policy["contract"] == "COMPETITIVE_LOAD_PRIMITIVE_V1"
    assert policy["scope"]["mandatory_before_visible_report"] is True
    assert policy["scope"]["mandatory_on_deadline_day"] is True
    assert "EFL Cup" in policy["known_competitions"]
    assert "UEFA Conference League" in policy["known_competitions"]
    assert policy["xmins_handoff"]["enabled"] is True
    assert policy["xmins_handoff"]["application"] == "REPORT_TIME_EVIDENCE_HANDOFF_ONLY"
    assert policy["xmins_handoff"]["direct_xpts_mutation_forbidden"] is True
    assert policy["xmins_handoff"]["direct_xmins_model_mutation_forbidden_until_calibrated"] is True
    assert set(policy["xmins_handoff"]["allowed_targets"]) >= {
        "manager_start_probability",
        "rotation_risk",
        "congestion_factor",
        "xmins_confidence",
    }
    assert policy["governance"]["direct_xmins_mutation_forbidden_until_calibrated"] is True
    assert not LEGACY_POLICY_PATH.exists(), "legacy duplicate competitive-load policy must not return"


def test_report_time_registry_requires_pressers_latest_match_and_canonical_load_policy():
    registry = json.loads((ROOT / "config" / "sources" / "report_time_registry.json").read_text(encoding="utf-8"))
    p = registry["policy"]
    assert p["press_conference_sweep_required"] is True
    assert p["last_competitive_match_sweep_required"] is True
    assert p["recent_competitive_load_policy_ref"] == "config/intelligence/competitive_load.json"
    sources = {row["id"]: row for row in registry["sources"]}
    official = sources["premier_league_official_news"]
    matches = sources["official_competitive_match_news"]
    assert "press_conference" in official["capabilities"]
    assert "recent_competitive_match" in matches["capabilities"]
    assert "minutes_load" in matches["capabilities"]
    assert matches["class"] == "VERIFIED_NEWS"
    assert matches["consensus_vote"] is False
