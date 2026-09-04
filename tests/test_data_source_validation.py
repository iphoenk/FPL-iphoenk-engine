from __future__ import annotations

from src.runtime_v6 import registry
from src.runtime_v6.http_client import _validate_payload


def test_source_overrides_preserve_27_and_repair_routes():
    cfg = registry.load_registry()
    sources = registry.source_map(cfg)
    assert tuple(row["id"] for row in cfg["sources"]) == registry.EXPECTED_SOURCE_IDS
    assert len(cfg["sources"]) == 27
    assert sources["opta_the_analyst"]["requests"][0]["url"] == "https://theanalyst.com/competition/premier-league/stats"
    assert sources["fotmob"]["requests"][0]["url"] == "https://www.fotmob.com/api/data/leagues"
    clubelo_request = sources["clubelo"]["requests"][0]
    assert clubelo_request["url"] == "https://clubelo.com/Ranking"
    assert clubelo_request["expect"] == "text"
    assert set(clubelo_request["validation"]["required_text_all"]) == {"Ranking", "Elo"}
    assert clubelo_request["read_timeout_seconds"] == 6
    assert sources["espn"]["requests"][0]["use_default_user_agent"] is True


def test_login_redirect_is_not_false_green():
    status, health, error, classification = _validate_payload(
        {"validation": {"reject_redirect_contains": ["/signin/", "/login"]}},
        requested_url="https://example.test/price/",
        final_url="https://example.test/signin/?next=/price/",
        parsed_json=None,
        text="<title>Log in</title>",
        raw_size=1000,
    )
    assert (status, health, classification) == ("AUTH_REQUIRED", "AMBER", "AUTH_REQUIRED")
    assert error == "authentication_required"


def test_robot_challenge_is_not_false_green():
    status, health, error, classification = _validate_payload(
        {},
        requested_url="https://example.test/data",
        final_url="https://example.test/data",
        parsed_json=None,
        text="JavaScript is disabled. We need to verify that you're not a robot.",
        raw_size=2000,
    )
    assert (status, health, classification) == ("ACCESS_RESTRICTED", "AMBER", "ACCESS_RESTRICTED")
    assert error == "access_challenge_detected"


def test_provider_plan_error_is_not_false_green():
    status, health, error, classification = _validate_payload(
        {"validation": {"reject_json_truthy_paths": ["errors"], "required_json_paths": ["response"]}},
        requested_url="https://api.example.test/fixtures",
        final_url="https://api.example.test/fixtures",
        parsed_json={"errors": {"plan": "not available"}, "response": []},
        text="",
        raw_size=200,
    )
    assert (status, health, classification) == ("PROVIDER_REJECTED", "AMBER", "PROVIDER_REJECTED")
    assert error == "provider_rejected:errors"


def test_required_text_and_json_validation_accepts_usable_payloads():
    status, health, error, classification = _validate_payload(
        {"validation": {"required_text_all": ["Premier League", "xG"]}},
        requested_url="https://example.test/stats",
        final_url="https://example.test/stats",
        parsed_json=None,
        text="Premier League 2026/27 xG table",
        raw_size=5000,
    )
    assert (status, health, error, classification) == ("AVAILABLE", "GREEN", None, "USABLE_DATA")

    status, health, error, classification = _validate_payload(
        {"validation": {"required_json_paths": ["details.id", "details.selectedSeason"]}},
        requested_url="https://example.test/league",
        final_url="https://example.test/league",
        parsed_json={"details": {"id": 47, "selectedSeason": "2026/2027"}},
        text="",
        raw_size=5000,
    )
    assert (status, health, error, classification) == ("AVAILABLE", "GREEN", None, "USABLE_DATA")
