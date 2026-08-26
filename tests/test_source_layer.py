from __future__ import annotations

import json

from src.sources.base import SourceResult
from src.sources.manager import collect_sources
from src.sources.registry import load_source_registry, registry_integrity, source_specs


def test_source_registry_has_single_official_authority_and_named_challengers():
    registry = load_source_registry()
    integrity = registry_integrity()
    specs = source_specs()
    assert integrity["integrity_ok"] is True
    authorities = [s.source_id for s in specs if s.source_class == "AUTHORITATIVE"]
    assert authorities == ["official_fpl"]
    challengers = {s.source_id for s in specs if s.source_class == "CHALLENGER"}
    assert {"livefpl", "onefpl", "fffix", "ffhub"}.issubset(challengers)
    assert registry["policy"]["challengers_never_override_official_native_fields"] is True
    assert registry["policy"]["missing_challenger_data_is_never_fabricated"] is True


def test_source_manager_keeps_challenger_failure_non_blocking(tmp_path, monkeypatch):
    (tmp_path / "health.json").write_text(json.dumps({
        name: {"status": "LIVE", "latency_ms": 10}
        for name in ("bootstrap", "fixtures", "entry", "history", "transfers")
    }), encoding="utf-8")
    for rel in ("stats/shots_gw1.json", "stats/playermatchstats_gw1.json", "stats/vaastav_previous_season.json"):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    def fake_web(spec, timeout_seconds):
        if spec.source_id == "livefpl":
            return SourceResult(spec.source_id, "UNAVAILABLE", False, 12.0, 0, {c: "UNAVAILABLE" for c in spec.capabilities}, {"probe_only": True})
        return SourceResult(spec.source_id, "LIVE", True, 8.0, 0, {c: "SOURCE_REACHABLE_NOT_INGESTED" for c in spec.capabilities}, {"probe_only": True})

    monkeypatch.setattr("src.sources.manager._web_result", fake_web)
    payload = collect_sources(tmp_path)
    assert payload["decision_blocking"] is False
    assert payload["critical_failed"] == []
    assert payload["overall"] == "AMBER"
    livefpl = next(row for row in payload["sources"] if row["id"] == "livefpl")
    assert livefpl["status"] == "UNAVAILABLE"
    assert livefpl["observation_count"] == 0


def test_public_probe_contract_never_claims_observations_from_reachability():
    spec = next(s for s in source_specs() if s.source_id == "livefpl")
    assert "price_prediction" in spec.capabilities
    assert spec.critical is False
    assert spec.source_class == "CHALLENGER"
