from __future__ import annotations

import importlib
import json


def _module(monkeypatch, tmp_path, profile: str):
    monkeypatch.setenv("FPL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FPL_EXECUTION_PROFILE", profile)
    import src.engines.official_player_detail_enrichment as module
    return importlib.reload(module)


def test_target_selection_prioritizes_missing_then_rotates(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path, "full_refresh")
    selected, cursor, mode = module._targets([1, 2, 3, 4], {1, 2}, 0, 2)
    assert selected == [3, 4]
    assert cursor == 0
    assert mode == "MISSING_FIRST"
    selected, cursor, mode = module._targets([1, 2, 3, 4], {1, 2, 3, 4}, 1, 2)
    assert selected == [2, 3]
    assert cursor == 3
    assert mode == "ROTATING_REFRESH"


def test_fast_and_live_profiles_are_cache_only(monkeypatch, tmp_path):
    assert _module(monkeypatch, tmp_path, "fast_decision")._batch_limit(623) == 0
    assert _module(monkeypatch, tmp_path, "live")._batch_limit(623) == 0


def test_full_and_deep_profiles_are_bounded(monkeypatch, tmp_path):
    assert _module(monkeypatch, tmp_path, "full_refresh")._batch_limit(623) == 160
    assert _module(monkeypatch, tmp_path, "deep_stats")._batch_limit(623) == 623


def test_missing_external_detail_is_non_blocking_and_preserves_cache(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path, "full_refresh")
    (tmp_path / "official_detail.json").write_text(json.dumps({"element_summaries": {"1": {"history": [{"round": 1}]}}}))
    (tmp_path / "latest.json").write_text("{}")
    monkeypatch.setattr(module, "load_snapshot", lambda *_: {"bootstrap": {"elements": [{"id": 1}, {"id": 2}]}})
    monkeypatch.setattr(module, "_batch_limit", lambda total: 2)
    monkeypatch.setattr(module, "_fetch_many", lambda ids: ({}, {str(eid): {"status": "UNAVAILABLE"} for eid in ids}))
    result = module.run()
    saved = json.loads((tmp_path / "official_detail.json").read_text())
    assert result["evidence_state"] == "PARTIAL"
    assert result["governance"]["decision_blocking"] is False
    assert result["governance"]["missing_data_is_not_zero"] is True
    assert result["governance"]["missing_external_evidence_fabricated"] is False
    assert saved["element_summaries"]["1"]["history"][0]["round"] == 1
    assert "2" not in saved["element_summaries"]


def test_zero_detail_coverage_is_safe_fallback(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path, "full_refresh")
    (tmp_path / "official_detail.json").write_text("{}")
    (tmp_path / "latest.json").write_text("{}")
    monkeypatch.setattr(module, "load_snapshot", lambda *_: {"bootstrap": {"elements": [{"id": 1}]}})
    monkeypatch.setattr(module, "_batch_limit", lambda total: 1)
    monkeypatch.setattr(module, "_fetch_many", lambda ids: ({}, {"1": {"status": "UNAVAILABLE"}}))
    result = module.run()
    assert result["evidence_state"] == "UNAVAILABLE_WITH_SAFE_FALLBACK"
    assert result["current_refresh"]["failed_or_unavailable"] == 1
    assert result["governance"]["decision_blocking"] is False
