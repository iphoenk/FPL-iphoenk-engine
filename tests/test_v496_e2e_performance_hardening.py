from __future__ import annotations

import copy
import json
from datetime import timedelta

from src.engines import v4_decision_pipeline
from src.services import enrichment_service, prediction_model_cache
from src.sources import official_fpl
from src.utils import iso_now, utcnow


def _prediction_row(point_in_time: str, xpts: float = 5.0) -> dict:
    return {
        "element": 1,
        "name": "Example",
        "position": "MID",
        "xpts_3": xpts,
        "xpts_5": xpts,
        "xpts_10": xpts,
        "xpts_15": xpts,
        "uncertainty": 0.2,
        "fixtures": [
            {
                "event": 3,
                "xpts": xpts,
                "lower80": xpts - 1.0,
                "upper80": xpts + 1.0,
                "xmins": {
                    "start_probability": 0.82,
                    "start_probability_confidence": 0.76,
                    "bench_probability": 0.13,
                    "dnp_probability": 0.05,
                },
                "provenance": {"point_in_time": point_in_time, "model": "v4.9.2-truthful-health"},
            }
        ],
        "priors": {"tactical_role": "attacking_midfielder"},
    }


def _universe() -> dict:
    return {
        "players": [
            {
                "element": 1,
                "name": "Example",
                "position": "MID",
                "team_id": 1,
                "team": "A",
                "now_cost": 70,
                "status": "a",
            }
        ]
    }


def _locked() -> dict:
    return {"players": [{"element": 1, "sell_cost": 70}], "planning_gw": 3}


def test_semantic_decision_fingerprint_ignores_runtime_timestamps(monkeypatch):
    monkeypatch.setattr(v4_decision_pipeline, "read_json", lambda path, default=None: {})
    universe = _universe()
    locked = _locked()
    first = {"model_version": "v4.9.2-truthful-health", "players": [_prediction_row("2026-08-29T10:00:00+00:00")]}
    second = {"model_version": "v4.9.2-truthful-health", "players": [_prediction_row("2026-08-29T11:00:00+00:00")]}
    assert v4_decision_pipeline._semantic_fingerprint(first, universe, locked) == v4_decision_pipeline._semantic_fingerprint(second, universe, locked)


def test_semantic_decision_fingerprint_changes_when_decision_input_changes(monkeypatch):
    monkeypatch.setattr(v4_decision_pipeline, "read_json", lambda path, default=None: {})
    universe = _universe()
    locked = _locked()
    first = {"model_version": "v4.9.2-truthful-health", "players": [_prediction_row("2026-08-29T10:00:00+00:00", 5.0)]}
    changed = {"model_version": "v4.9.2-truthful-health", "players": [_prediction_row("2026-08-29T10:00:00+00:00", 5.1)]}
    assert v4_decision_pipeline._semantic_fingerprint(first, universe, locked) != v4_decision_pipeline._semantic_fingerprint(changed, universe, locked)


def test_semantic_decision_fingerprint_changes_on_owned_lineup_xmins(monkeypatch):
    monkeypatch.setattr(v4_decision_pipeline, "read_json", lambda path, default=None: {})
    universe = _universe()
    locked = _locked()
    first = {"model_version": "v4.9.2-truthful-health", "players": [_prediction_row("2026-08-29T10:00:00+00:00")]}
    changed = copy.deepcopy(first)
    changed["players"][0]["fixtures"][0]["xmins"]["start_probability"] = 0.61
    assert v4_decision_pipeline._semantic_fingerprint(first, universe, locked) != v4_decision_pipeline._semantic_fingerprint(changed, universe, locked)


def test_semantic_decision_fingerprint_ignores_nonconsumed_provenance(monkeypatch):
    monkeypatch.setattr(v4_decision_pipeline, "read_json", lambda path, default=None: {})
    universe = _universe()
    locked = _locked()
    first = {"model_version": "v4.9.2-truthful-health", "players": [_prediction_row("2026-08-29T10:00:00+00:00")]}
    changed = copy.deepcopy(first)
    changed["players"][0]["fixtures"][0]["provenance"]["debug_trace"] = {"opaque": [1, 2, 3]}
    changed["players"][0]["unused_explanation"] = "does not feed cached optimizers"
    assert v4_decision_pipeline._semantic_fingerprint(first, universe, locked) == v4_decision_pipeline._semantic_fingerprint(changed, universe, locked)


def test_optimizer_exact_cache_write_uses_path_artifacts(monkeypatch, tmp_path):
    wc = tmp_path / "wc.json"
    packages = tmp_path / "packages.json"
    lineup = tmp_path / "lineup.json"
    cache = tmp_path / "cache.json"
    for path, payload in ((wc, {"ok": "wc"}), (packages, {"ok": "packages"}), (lineup, {"ok": "lineup"})):
        path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(v4_decision_pipeline, "WC_OUTFILE", wc)
    monkeypatch.setattr(v4_decision_pipeline, "PACKAGE_OUTFILE", packages)
    monkeypatch.setattr(v4_decision_pipeline, "LINEUP_OUTFILE", lineup)
    monkeypatch.setattr(v4_decision_pipeline, "DECISION_CACHE", cache)
    artifacts = v4_decision_pipeline._cache_artifacts()
    assert all(hasattr(path, "open") for path in artifacts.values())
    v4_decision_pipeline._write_cache("fingerprint")
    stored = json.loads(cache.read_text(encoding="utf-8"))
    assert stored["fingerprint"] == "fingerprint"
    assert stored["schema_version"] == 3
    assert stored["guardrails"]["bounded_consumer_projection_not_full_payload"] is True
    assert stored["guardrails"]["full_universe_package_policy_in_cache_key"] is True
    assert stored["guardrails"]["tactical_interaction_semantics_in_cache_key"] is True
    assert stored["guardrails"]["price_scenario_semantics_in_cache_key"] is True
    assert stored["guardrails"]["package_search_width_is_not_silently_bounded"] is True
    assert set(stored["artifact_sha256"]) == {"wc", "packages", "lineup"}
    assert all(len(value) == 64 for value in stored["artifact_sha256"].values())


def test_prediction_cache_restamp_preserves_boolean_point_in_time():
    payload = {
        "generated_at": "old",
        "point_in_time": True,
        "players": [{"fixtures": [{"provenance": {"point_in_time": "old"}}]}],
    }
    out = prediction_model_cache._restamp(payload, "new")
    assert out["generated_at"] == "new"
    assert out["point_in_time"] is True
    assert out["players"][0]["fixtures"][0]["provenance"]["point_in_time"] == "new"


def test_prediction_cache_second_same_snapshot_is_exact_hit(monkeypatch, tmp_path):
    cache = tmp_path / "predictions_base_hot_cache_v4.json"
    calls = {"count": 0}

    def builder(bootstrap, fixtures, generated_at, stats_gw=None):
        calls["count"] += 1
        return {
            "generated_at": generated_at,
            "point_in_time": True,
            "model_version": "model",
            "players": [{"element": 1, "fixtures": [{"provenance": {"point_in_time": generated_at}}]}],
        }

    monkeypatch.setattr(prediction_model_cache, "CACHE", cache)
    monkeypatch.setattr(prediction_model_cache, "semantic_fingerprint", lambda bootstrap, fixtures, stats_gw: "same")
    monkeypatch.setattr(prediction_model_cache, "canonical_build_predictions", builder)
    first = prediction_model_cache.build_predictions_cached({}, [], "t1", stats_gw=2)
    second = prediction_model_cache.build_predictions_cached({}, [], "t2", stats_gw=2)
    assert calls["count"] == 1
    assert first["point_in_time"] is True
    assert second["point_in_time"] is True
    assert second["generated_at"] == "t2"
    assert second["players"][0]["fixtures"][0]["provenance"]["point_in_time"] == "t2"
    assert prediction_model_cache.last_status()["hit"] is True


def test_fresh_enrichment_cache_is_reused_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(enrichment_service, "STATS", tmp_path)
    payload = {
        "source": "FPL-Core-Insights",
        "schema_valid": True,
        "row_count": 1,
        "rows": [{"id": 1}],
        "fetched_at": iso_now(),
    }
    (tmp_path / "core_insights_gw2.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(enrichment_service.core_insights, "sync_gw", lambda gw: (_ for _ in ()).throw(AssertionError("network refresh should not run")))
    out = enrichment_service._core_insights_task(2, 60)
    assert out["runtime_reused"] is True
    assert out["row_count"] == 1


def test_stale_enrichment_cache_refreshes(monkeypatch, tmp_path):
    monkeypatch.setattr(enrichment_service, "STATS", tmp_path)
    stale = (utcnow() - timedelta(minutes=61)).isoformat()
    payload = {
        "source": "FPL-Core-Insights",
        "schema_valid": True,
        "row_count": 1,
        "rows": [{"id": 1}],
        "fetched_at": stale,
    }
    (tmp_path / "core_insights_gw2.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        enrichment_service.core_insights,
        "sync_gw",
        lambda gw: {"source": "FPL-Core-Insights", "schema_valid": True, "row_count": 2, "rows": [{"id": 1}, {"id": 2}], "fetched_at": iso_now()},
    )
    out = enrichment_service._core_insights_task(2, 60)
    assert out["runtime_reused"] is False
    assert out["row_count"] == 2


def test_official_fpl_http_session_is_reused():
    first = official_fpl._session()
    second = official_fpl._session()
    assert first is second
    assert first.headers.get("Connection") == "keep-alive"
