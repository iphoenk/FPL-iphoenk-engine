import json
from pathlib import Path

from src.sources.registry import load_source_registry, source_specs
from src.sources.api_football import probe as api_football_probe

ROOT = Path(__file__).resolve().parents[1]


def test_source_registry_declares_new_enrichments_without_changing_authority():
    registry = load_source_registry()
    specs = {spec.source_id: spec for spec in source_specs()}
    assert registry["schema_version"] >= 2
    assert specs["official_fpl"].source_class == "AUTHORITATIVE"
    assert specs["understat"].source_class == "ENRICHMENT"
    assert specs["api_football"].source_class == "ENRICHMENT"
    assert specs["sportmonks"].enabled is False
    assert registry["policy"]["source_reachability_does_not_equal_data_ingestion"] is True


def test_dss_source_map_labels_box_touch_proxy_and_runtime_league_resolution():
    payload = json.loads((ROOT / "config/sources/dss_source_map.json").read_text(encoding="utf-8"))
    rows = {row["dss_id"]: row for row in payload["mappings"]}
    assert rows["DSS-14"]["evidence_status"] == "PARTIAL_PROXY"
    assert "not actual box touches" in rows["DSS-14"]["note"]
    assert "runtime" in rows["DSS-30"]["note"].lower()
    assert rows["DSS-32"]["evidence_status"] == "PARTIAL"
    assert payload["policy"]["competition_ids_must_be_resolved_runtime_not_hardcoded"] is True


def test_api_football_without_secret_is_non_blocking_config_required(monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_KEY", raising=False)
    spec = next(spec for spec in source_specs() if spec.source_id == "api_football")
    result = api_football_probe(spec, 0.1)
    assert result.status == "CONFIG_REQUIRED"
    assert result.reachable is False
    assert result.detail["credential_exposed"] is False
    assert result.detail["decision_blocking"] is False
