from __future__ import annotations

from src.runtime_v6 import collector


def test_registry_is_data_only_and_has_exact_sources():
    cfg = collector._load_config()
    ids = [row["id"] for row in cfg["sources"]]
    assert ids == [
        "official_fpl",
        "official_price_predictor",
        "understat",
        "opta_the_analyst",
        "statmuse",
        "onside",
        "ben_crellin",
        "fffix",
        "ffhub",
        "onefpl",
        "livefpl",
        "ffscout",
    ]
    assert cfg["policy"]["data_only"] is True


def test_price_predictor_is_derived_from_official_without_web_scraping():
    source = {
        "id": "official_price_predictor",
        "name": "Official FPL Price Predictor",
        "kind": "official_price_predictor",
        "critical": True,
        "fields": ["id", "web_name", "price_change_percent", "price_change_projections"],
    }
    official = {
        "official": {
            "bootstrap": {
                "elements": [{
                    "id": 1,
                    "web_name": "Example",
                    "price_change_percent": 72.4,
                    "price_change_projections": [{"offset": 0, "projected_percent": 101.2}],
                }]
            }
        }
    }
    result = collector._collect_price_predictor(source, official)
    assert result["status"] == "AVAILABLE"
    assert result["player_count"] == 1
    assert result["coverage_ratio"] == 1.0
    assert result["governance"]["source"] == "OFFICIAL_FPL"
    assert result["governance"]["ui_scraping"] is False


def test_http_failure_is_explicit_not_fabricated(monkeypatch):
    def fail(*args, **kwargs):
        raise collector.requests.RequestException("down")

    monkeypatch.setattr(collector.requests, "get", fail)
    result = collector._request("https://example.invalid/", 0.01, 1000)
    assert result["status"] == "UNAVAILABLE"
    assert result["body"] is None
    assert result["json"] is None
    assert result["error"] == "RequestException"
