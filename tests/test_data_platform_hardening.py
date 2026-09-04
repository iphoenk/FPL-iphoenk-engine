from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from src.runtime_v6.http_client import _read_bounded, _redact_url
from src.runtime_v6.registry import (
    ZERO_AUTHORITY_KEYS,
    RegistryError,
    _apply_activation,
    _read_json,
    config_layer_metadata,
    dependency_layers,
    load_registry,
    resolved_registry_snapshot,
    source_map,
    validate_registry,
)


def test_workflow_cron_matches_v6_schedule_policy():
    workflow = Path(".github/workflows/v6-hourly-data-ingestion.yml").read_text(encoding="utf-8")
    policy = json.loads(Path("config/v6/schedule_policy.json").read_text(encoding="utf-8"))
    source_registry = json.loads(Path("config/v6/source_registry.json").read_text(encoding="utf-8"))
    workflow_crons = re.findall(r'^\s+- cron: "([^"]+)"$', workflow, flags=re.MULTILINE)

    assert policy["schema_version"] == 1
    assert policy["engine"] == "V6_FRESH_DATA_PLATFORM"
    assert workflow_crons == [policy["primary_cron_utc"], policy["recovery_cron_utc"]]
    assert workflow_crons == ["5 * * * *", "35 * * * *"]
    assert policy["schedule_authority"] is True
    assert policy["source_registry_schedule_metadata_authoritative"] is False
    assert policy["governance"]["single_schedule_owner"] == "config/v6/schedule_policy.json"
    assert "workflow_cron_utc" not in source_registry["cadence"]
    assert source_registry["cadence"]["schedule"] == "hourly"
    assert policy["manual_recovery"]["counts_as_completed_scheduled_slot"] is False
    assert policy["manual_recovery"]["authoritative_runtime_snapshot"] is False


def test_required_platform_sources_are_active_but_context_source_is_not_availability_critical():
    registry = load_registry()
    sources = source_map(registry)
    required = {
        source_id
        for source_id, source in sources.items()
        if source.get("required_for_platform") is True
    }

    assert required == {"official_fpl", "official_price_predictor", "open_meteo_weather"}
    assert sources["official_fpl"]["critical"] is True
    assert sources["official_price_predictor"]["critical"] is True
    assert sources["open_meteo_weather"]["critical"] is False
    assert sources["official_price_predictor"]["depends_on"] == ["official_fpl"]
    assert sources["open_meteo_weather"]["depends_on"] == ["official_fpl"]
    assert set(registry["activation"]["required_active_sources"]) == required


def test_large_provider_payloads_use_bounded_source_specific_budgets():
    registry = load_registry()
    sources = source_map(registry)
    global_limit = int(registry["policy"]["max_body_bytes"])

    assert global_limit == 1_000_000
    for source_id in ("official_fpl", "fantasy_football_pundit"):
        source_limit = int(sources[source_id]["max_body_bytes"])
        assert source_limit > global_limit
        assert source_limit == 4_000_000
        assert source_limit <= 4 * global_limit


def test_activation_cannot_prune_required_platform_source(tmp_path: Path):
    activation = tmp_path / "activation.json"
    activation.write_text(
        json.dumps(
            {
                "schema_version": 4,
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


def test_required_context_source_may_be_noncritical_without_becoming_optional():
    registry = load_registry()
    validate_registry(registry)
    weather = source_map(registry)["open_meteo_weather"]

    assert weather["required_for_platform"] is True
    assert weather["critical"] is False
    assert "open_meteo_weather" in registry["activation"]["required_active_sources"]


def test_config_layers_fail_closed_on_schema_version_mismatch(tmp_path: Path):
    path = tmp_path / "source_registry.json"
    path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")

    with pytest.raises(RegistryError, match="config schema mismatch"):
        _read_json(path, expected_schema_version=3)


def test_all_config_layer_versions_are_explicitly_governed():
    layers = config_layer_metadata()

    assert layers == {
        "registry": {"path": "config/v6/source_registry.json", "schema_version": 3},
        "additions": {"path": "config/v6/source_additions.json", "schema_version": 1},
        "overrides": {"path": "config/v6/source_overrides.json", "schema_version": 2},
        "activation": {"path": "config/v6/source_activation.json", "schema_version": 4},
    }


def test_dependency_layers_are_topological_and_cycle_safe():
    registry = load_registry()
    layers = dependency_layers(registry)
    positions = {
        source_id: layer_index
        for layer_index, layer in enumerate(layers)
        for source_id in layer
    }

    assert positions["official_fpl"] < positions["official_price_predictor"]
    assert positions["official_fpl"] < positions["open_meteo_weather"]

    cyclic = deepcopy(registry)
    sources = source_map(cyclic)
    sources["official_fpl"]["depends_on"] = ["official_price_predictor"]
    cyclic["sources"] = [sources[source["id"]] for source in registry["sources"]]
    with pytest.raises(RegistryError, match="cyclic V6 source dependency graph"):
        dependency_layers(cyclic)


def test_resolved_registry_snapshot_exposes_effective_layers_without_hidden_authority():
    registry = load_registry()
    resolved = resolved_registry_snapshot(registry)

    assert resolved["source_count"] == registry["activation"]["active_source_count"]
    assert resolved["dependency_layers"] == dependency_layers(registry)
    assert resolved["policy"]["data_only"] is True
    assert tuple(ZERO_AUTHORITY_KEYS) == (
        "decision_authority",
        "prediction_authority",
        "optimizer_authority",
        "tactical_authority",
        "transfer_authority",
        "captain_authority",
        "chip_authority",
        "formation_authority",
    )
    assert all(resolved["policy"][key] == "NONE" for key in ZERO_AUTHORITY_KEYS)
    assert resolved["config_layers"]["overrides"]["schema_version"] == 2


def test_zero_authority_contract_fails_closed_for_every_business_authority():
    registry = load_registry()
    for key in ZERO_AUTHORITY_KEYS:
        mutated = deepcopy(registry)
        mutated["policy"][key] = "ENABLED"
        with pytest.raises(RegistryError, match="zero authority"):
            validate_registry(mutated)


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


def test_http_body_reader_stops_at_configured_storage_cap():
    class FakeResponse:
        headers = {"content-length": "10"}

        def iter_content(self, chunk_size):
            assert chunk_size > 0
            yield b"1234"
            yield b"5678"
            yield b"90"

    kept, content_length, truncated, declared = _read_bounded(FakeResponse(), 5)

    assert kept == b"12345"
    assert content_length == 10
    assert declared == 10
    assert truncated is True


def test_http_body_reader_detects_unknown_length_overflow_without_buffering_full_body():
    class FakeResponse:
        headers = {}

        def iter_content(self, chunk_size):
            yield b"12345"
            yield b"67890"
            raise AssertionError("reader should stop after proving overflow")

    kept, content_length, truncated, declared = _read_bounded(FakeResponse(), 5)

    assert kept == b"12345"
    assert content_length == 6
    assert declared is None
    assert truncated is True
