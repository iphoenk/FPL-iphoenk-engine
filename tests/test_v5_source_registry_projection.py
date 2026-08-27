from __future__ import annotations

from src.v5.config_cache import clear_config_cache, load_json_config
from src.v5.sources import fusion


def _registry_by_id() -> dict[str, dict]:
    registry = load_json_config("config/sources/registry.json")
    return {
        str(row["id"]): row
        for row in registry.get("sources") or []
        if isinstance(row, dict) and row.get("id")
    }


def test_source_runtime_projection_uses_canonical_registry():
    clear_config_cache()
    cfg = load_json_config("config/intelligence/source_fusion.json")
    by_id = _registry_by_id()

    api = cfg["api_football"]
    api_authority = by_id["api_football"]
    assert api["enabled"] is bool(api_authority["enabled"])
    assert api["base_url"] == api_authority["ingestion"]["base_url"]
    assert api["api_key_env"] == api_authority["credential_env"]
    assert api["resolve_league_ids_dynamically"] is True
    assert "season" not in api

    understat = cfg["understat"]
    understat_authority = by_id["understat"]
    assert understat["enabled"] is bool(understat_authority["enabled"])
    assert understat["cache_path_template"] == understat_authority["ingestion"]["cache_path_template"]
    assert "season" not in understat
    assert cfg["season_authority"]["registry_path"] == "config/rules/registry.json"


def test_fusion_does_not_execute_canonical_disabled_understat(monkeypatch):
    calls = {"understat": 0, "api_football": 0}

    def forbidden_understat():
        calls["understat"] += 1
        raise AssertionError("disabled Understat collector must not execute")

    def fake_api_football(_bootstrap):
        calls["api_football"] += 1
        return {
            "source": "api_football",
            "status": "UNAVAILABLE",
            "availability_class": "CREDENTIAL_MISSING",
            "reason": "API_KEY_MISSING",
            "fixtures": [],
            "observability": {"credential_present": False},
            "governance": {"fail_neutral": True},
        }

    monkeypatch.setattr(fusion, "collect_understat", forbidden_understat)
    monkeypatch.setattr(fusion, "collect_api_football", fake_api_football)
    result = fusion.collect({"teams": []})

    assert calls["understat"] == 0
    assert calls["api_football"] == 1
    assert result["sources"]["understat"]["status"] == "DISABLED"
    assert result["health"]["disabled_sources"] == ["understat"]
    assert result["health"]["workers_used"] == 1
    assert result["governance"]["disabled_sources_are_not_executed"] is True
