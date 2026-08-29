from __future__ import annotations

import json

from src.runtime_v3 import incremental_reuse


def _policy():
    return {
        "registry": "V3_INCREMENTAL_REUSE_V1",
        "policy": {
            "enabled_profiles": ["fast_decision", "live"],
            "disable_when_current_scoring_fixture_live": True,
        },
        "services": {},
    }


def _write_snapshot(tmp_path, fixtures):
    payload = {
        "phase": {"scoring_gw": 2, "is_live_event": True},
        "fixtures": fixtures,
    }
    (tmp_path / "official_snapshot.json").write_text(json.dumps(payload), encoding="utf-8")


def test_active_gw_without_live_fixture_keeps_reuse_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(incremental_reuse, "DATA", tmp_path)
    monkeypatch.setattr(incremental_reuse, "_registry", _policy)
    _write_snapshot(tmp_path, [
        {
            "event": 2,
            "started": False,
            "finished": False,
            "kickoff_time": "2999-01-01T12:00:00Z",
        }
    ])
    assert incremental_reuse.active("fast_decision") is True
    assert incremental_reuse.inactive_reason("fast_decision") is None


def test_current_scoring_fixture_live_disables_reuse(tmp_path, monkeypatch):
    monkeypatch.setattr(incremental_reuse, "DATA", tmp_path)
    monkeypatch.setattr(incremental_reuse, "_registry", _policy)
    _write_snapshot(tmp_path, [
        {
            "event": 2,
            "started": True,
            "finished": False,
            "kickoff_time": "2000-01-01T12:00:00Z",
        }
    ])
    assert incremental_reuse.active("fast_decision") is False
    assert incremental_reuse.inactive_reason("fast_decision") == "CURRENT_SCORING_FIXTURE_LIVE"


def test_future_or_other_gw_fixture_does_not_disable_reuse(tmp_path, monkeypatch):
    monkeypatch.setattr(incremental_reuse, "DATA", tmp_path)
    monkeypatch.setattr(incremental_reuse, "_registry", _policy)
    _write_snapshot(tmp_path, [
        {
            "event": 2,
            "started": True,
            "finished": False,
            "kickoff_time": "2999-01-01T12:00:00Z",
        },
        {
            "event": 3,
            "started": True,
            "finished": False,
            "kickoff_time": "2000-01-01T12:00:00Z",
        },
    ])
    assert incremental_reuse.active("fast_decision") is True
