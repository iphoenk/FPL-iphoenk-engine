from __future__ import annotations

import json

from src.sources.base import SourceResult
from src.sources.manager import collect_sources
from src.sources.registry import load_source_registry, registry_integrity, source_specs
from src.utils import ROOT


def test_source_registry_has_single_official_authority_and_named_challengers():
    registry = load_source_registry()
    integrity = registry_integrity()
    specs = source_specs()
    assert registry["registry"] == "SOURCE_REGISTRY_V4"
    assert integrity["integrity_ok"] is True
    authorities = [s.source_id for s in specs if s.source_class == "AUTHORITATIVE"]
    assert authorities == ["official_fpl"]
    official = next(s for s in specs if s.source_id == "official_fpl")
    assert "prices" in official.capabilities
    assert "price_prediction" in official.capabilities
    challengers = {s.source_id for s in specs if s.source_class == "CHALLENGER"}
    assert {"onefpl", "fffix", "ffhub"}.issubset(challengers)
    assert "livefpl" not in {s.source_id for s in specs}
    enrichments = {s.source_id for s in specs if s.source_class == "ENRICHMENT"}
    assert "open_meteo" in enrichments
    weather = next(s for s in specs if s.source_id == "open_meteo")
    assert weather.critical is False
    assert weather.adapter == "weather_artifact"
    assert registry["policy"]["challengers_never_override_official_native_fields"] is True
    assert registry["policy"]["missing_challenger_data_is_never_fabricated"] is True
    assert registry["policy"]["source_network_locations_are_registry_owned"] is True
    assert registry["policy"]["source_ingestion_timeouts_are_registry_owned"] is True
    assert registry["policy"]["weather_is_advisory_enrichment_only"] is True


def test_livefpl_is_retired_from_active_v3_registries():
    challenger = json.loads((ROOT / "config" / "intelligence" / "challenger_registry.json").read_text(encoding="utf-8"))
    benchmark = json.loads((ROOT / "config" / "sources" / "external_benchmark_consensus.json").read_text(encoding="utf-8"))
    assert "livefpl" not in {row["id"] for row in challenger["providers"]}
    assert "livefpl" not in {row["id"] for row in benchmark["sources"]}


def test_probe_only_sources_share_the_generic_public_web_adapter():
    specs = {spec.source_id: spec for spec in source_specs()}
    for source_id in ("fffix", "ffhub", "ffscout"):
        spec = specs[source_id]
        assert spec.adapter == "public_web"
        assert spec.config.get("probe_url", "").startswith("https://")


def test_source_manager_keeps_challenger_failure_non_blocking(tmp_path, monkeypatch):
    (tmp_path / "health.json").write_text(json.dumps({
        name: {"status": "LIVE", "latency_ms": 10}
        for name in ("bootstrap", "fixtures", "entry", "history", "transfers")
    }), encoding="utf-8")
    for rel in ("stats/shots_current.json", "stats/playermatchstats_current.json", "stats/vaastav_previous_season.json"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    (tmp_path / "fixture_weather.json").write_text(json.dumps({
        "schema_version": 1,
        "model": "weather_context_observational_v1",
        "provider": "open_meteo",
        "fixture_count": 0,
        "available_count": 0,
        "material_count": 0,
        "fixtures": [],
        "material_fixtures": [],
        "governance": {"advisory_only": True},
    }), encoding="utf-8")

    def fake_web(spec, timeout_seconds):
        if spec.source_id == "fffix":
            return SourceResult(spec.source_id, "UNAVAILABLE", False, 12.0, 0, {c: "UNAVAILABLE" for c in spec.capabilities}, {"probe_only": True})
        return SourceResult(spec.source_id, "LIVE", True, 8.0, 0, {c: "SOURCE_REACHABLE_NOT_INGESTED" for c in spec.capabilities}, {"probe_only": True})

    monkeypatch.setattr("src.sources.manager._web_result", fake_web)
    payload = collect_sources(tmp_path)
    assert payload["decision_blocking"] is False
    assert payload["critical_failed"] == []
    assert payload["overall"] == "AMBER"
    fffix = next(row for row in payload["sources"] if row["id"] == "fffix")
    assert fffix["status"] == "UNAVAILABLE"
    assert fffix["observation_count"] == 0
    weather = next(row for row in payload["sources"] if row["id"] == "open_meteo")
    assert weather["status"] == "LIVE"
    assert set(weather["capabilities"].values()) == {"NO_FORECAST_IN_WINDOW"}


def test_public_probe_contract_never_claims_observations_from_reachability():
    spec = next(s for s in source_specs() if s.source_id == "fffix")
    assert "price_prediction" in spec.capabilities
    assert spec.critical is False
    assert spec.source_class == "CHALLENGER"
    assert spec.adapter == "public_web"
