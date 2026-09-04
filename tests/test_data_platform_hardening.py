from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from src.runtime_v6.http_client import _redact_url
from src.runtime_v6.registry import RegistryError, _apply_activation, load_registry, source_map, validate_registry


def test_workflow_cron_matches_registry_cadence_metadata():
    registry = load_registry()
    workflow = Path(".github/workflows/v6-hourly-data-ingestion.yml").read_text(encoding="utf-8")
    cron = str((registry.get("cadence") or {}).get("workflow_cron_utc") or "")

    assert cron == "0 * * * *"
    assert f'cron: "{cron}"' in workflow


def test_required_platform_sources_are_active_critical_and_dependencies_are_closed():
    registry = load_registry()
    sources = source_map(registry)
    required = {
        source_id
        for source_id, source in sources.items()
        if source.get("required_for_platform") is True
    }

    assert required == {"official_fpl", "official_price_predictor", "open_meteo_weather"}
    assert all(sources[source_id]["critical"] is True for source_id in required)
    assert sources["official_price_predictor"]["depends_on"] == ["official_fpl"]
    assert sources["open_meteo_weather"]["depends_on"] == ["official_fpl"]
    assert set(registry["activation"]["required_active_sources"]) == required


def test_activation_cannot_prune_required_platform_source(tmp_path: Path):
    activation = tmp_path / "activation.json"
    activation.write_text(
        json.dumps(
            {
                "disabled_sources": {"official_fpl": "TEST"},
                "reference_only_sources": {},
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "sources": [
            {
                "id": "official_fpl",
                "required_for_platform": True,
            }
        ]
    }

    with pytest.raises(RegistryError, match="required V6 platform sources cannot be pruned"):
        _apply_activation(payload, activation)


def test_required_platform_source_cannot_be_noncritical():
    registry = load_registry()
    registry["sources"] = [dict(source) for source in registry["sources"]]
    target = next(source for source in registry["sources"] if source["id"] == "open_meteo_weather")
    target["critical"] = False

    with pytest.raises(RegistryError, match="required V6 platform source must be critical"):
        validate_registry(registry)


def test_query_auth_redaction_is_key_based_and_encoding_safe():
    secret = "a+b/c?d"
    encoded_secret = "a%2Bb%2Fc%3Fd"
    url = f"https://provider.example/fixtures?league=39&api_token={encoded_secret}&season=2026"

    safe = _redact_url(url, secret, "api_token")
    query = parse_qs(urlsplit(safe).query)

    assert query["api_token"] == ["<redacted>"]
    assert secret not in safe
    assert encoded_secret not in safe
    assert query["league"] == ["39"]
    assert query["season"] == ["2026"]
