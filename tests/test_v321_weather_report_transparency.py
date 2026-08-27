import json
from pathlib import Path

from src.engines.report_transparency_overlay import _confidence_calibration
from src.sources.weather_open_meteo import _severity

ROOT = Path(__file__).resolve().parents[1]


def _load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_weather_is_optional_enrichment_not_new_microservice():
    sources = _load("config/sources/registry.json")
    services = _load("config/v3_service_registry.json")
    source_map = {row["id"]: row for row in sources["sources"]}
    weather = source_map["open_meteo"]
    assert weather["class"] == "ENRICHMENT"
    assert weather["critical"] is False
    assert weather["adapter"] == "weather_artifact"
    assert len(services["services"]) == 20
    assert not any("weather" in name.lower() for name in services["services"])
    source_layer = services["services"]["source_layer"]
    assert "official_snapshot.json" in source_layer["inputs"]
    assert "fixture_weather.json" in source_layer["artifacts"]


def test_weather_policy_cannot_directly_mutate_decisions():
    cfg = _load("config/intelligence/weather_context.json")
    governance = cfg["governance"]
    assert governance["advisory_only"] is True
    for key in (
        "may_directly_change_xpts",
        "may_directly_change_captaincy",
        "may_directly_change_starting_xi",
        "may_directly_change_transfer_decision",
        "may_directly_change_watchlist_membership",
    ):
        assert governance[key] is False
    assert governance["rain_probability_is_not_rain_intensity"] is True
    assert governance["post_match_attribution_label"] == "POSSIBLE_CONTRIBUTING_FACTOR"


def test_weather_severity_uses_intensity_and_gusts_from_config():
    cfg = _load("config/intelligence/weather_context.json")
    label, signals = _severity(
        {
            "temperature_c": 14,
            "precipitation_probability_pct": 90,
            "precipitation_mm_h": 0.0,
            "wind_speed_kmh": 12,
            "wind_gust_kmh": 46,
        },
        cfg,
    )
    assert label == "ADVERSE"
    assert "wind_gust" in signals
    assert "precipitation_intensity" not in signals


def test_venue_registry_has_current_unique_pl_coverage():
    venues = _load("config/venues/premier_league_2026_27.json")["venues"]
    names = [row["team_name"] for row in venues]
    assert len(venues) == 20
    assert len(set(names)) == 20
    assert all(-90 <= float(row["latitude"]) <= 90 for row in venues)
    assert all(-180 <= float(row["longitude"]) <= 180 for row in venues)


def _owned_rows(confidence="MEDIUM"):
    return [{"element": idx + 1, "model_confidence": confidence} for idx in range(15)]


def test_projection_confidence_guard_is_early_season_conservative_before_gw5():
    state = _confidence_calibration(_owned_rows("MEDIUM"), 2)
    assert state["state"] == "EARLY_SEASON_CONSERVATIVE"
    assert state["counts"]["HIGH"] == 0


def test_projection_confidence_guard_requires_review_from_gw5_if_no_high():
    state = _confidence_calibration(_owned_rows("MEDIUM"), 5)
    assert state["state"] == "CALIBRATION_REVIEW_REQUIRED"


def test_report_contract_requires_xpts_weather_and_settled_validation():
    report = _load("config/report_artifact_registry.json")
    contract = report["consumer_contract"]
    assert report["registry"] == "REPORT_ARTIFACT_REGISTRY_V3"
    assert contract["owned_rows_require_current_gw_xpts"] is True
    assert contract["owned_rows_require_lineup_status"] is True
    assert contract["owned_rows_require_choice_state"] is True
    assert contract["model_validation_required"] is True
    assert contract["weather_context_required"] is True


def test_report_materializer_runs_transparency_before_serving_validation():
    services = _load("config/v3_service_registry.json")
    commands = [row["module"] for row in services["services"]["report_materializer"]["commands"]]
    assert commands == [
        "src.engines.report_materializer",
        "src.engines.report_transparency_overlay",
        "src.engines.report_serving_validate",
    ]
