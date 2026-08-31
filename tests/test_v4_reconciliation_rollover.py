from __future__ import annotations

from datetime import datetime, timezone

import src.engines.v4_backtest_store as store
import src.engines.v4_validation_cycle as lifecycle
import src.services.raw_snapshot_service as raw_service


MODEL = "v4.9.2-truthful-health"
DEADLINE = "2026-08-28T17:30:00+00:00"
PRE = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
POST = datetime(2026, 9, 1, 4, 0, tzinfo=timezone.utc)


def _prediction():
    return {
        "generated_at": "2026-08-27T09:00:00+00:00",
        "model_version": MODEL,
        "players": [{
            "element": 1, "name": "A", "position": "MID",
            "fixtures": [{
                "event": 2, "xpts": 5.0, "lower80": 1.0, "upper80": 9.0,
                "xmins": {"expected_minutes": 80, "start_probability": 0.9, "p60": 0.8},
            }],
        }],
    }


def _live():
    return {"elements": [{"id": 1, "stats": {"total_points": 7, "minutes": 90, "starts": 1}}]}


def _isolate_store(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "SNAPDIR", tmp_path / "validation" / "deadline")
    monkeypatch.setattr(store, "ARCHIVE_RECDIR", tmp_path / "validation" / "archive" / "reconciled")
    monkeypatch.setattr(store, "RECDIR", tmp_path / "validation" / "reconciled")


def test_raw_snapshot_requests_rollover_actuals_only_while_reconciliation_pending(monkeypatch, tmp_path):
    monkeypatch.setattr(raw_service, "DATA", tmp_path)
    phase = {"last_finished_gw": 2, "scoring_gw": 3}
    deadline = tmp_path / "validation" / "deadline" / "gw02.json"
    deadline.parent.mkdir(parents=True)
    deadline.write_text("{}")

    assert raw_service._pending_reconciliation_actuals_gw(phase) == 2

    archive = tmp_path / "validation" / "archive" / "reconciled" / "gw02.json"
    archive.parent.mkdir(parents=True)
    archive.write_text("{}")
    assert raw_service._pending_reconciliation_actuals_gw(phase) is None
    assert raw_service._pending_reconciliation_actuals_gw({"last_finished_gw": 2, "scoring_gw": 2}) is None


def test_validation_reconciles_event_bound_rollover_payload(monkeypatch, tmp_path):
    _isolate_store(monkeypatch, tmp_path)
    store.persist_deadline_snapshot(2, DEADLINE, _prediction(), now=PRE)
    raw = {
        "schema": "snapshot.v1",
        "as_of": None,
        "checkpoint_context": {"is_simulation": False},
        "phase": {"last_finished_gw": 2, "scoring_gw": 3},
        "reconciliation_actuals": {"event": 2, "source_key": "reconciliation_event_live", "endpoint_status": "LIVE"},
        "official": {"event_live": {}, "reconciliation_event_live": _live()},
    }

    result = lifecycle.reconcile_latest_finished(raw, now=POST)

    assert result["status"] == "PASS"
    assert result["action"] == "CREATED"
    assert result["gw"] == 2
    assert result["actuals_source_key"] == "reconciliation_event_live"
    assert result["actual_elements"] == 1


def test_validation_rejects_rollover_actuals_event_mismatch(monkeypatch, tmp_path):
    _isolate_store(monkeypatch, tmp_path)
    store.persist_deadline_snapshot(2, DEADLINE, _prediction(), now=PRE)
    raw = {
        "schema": "snapshot.v1",
        "as_of": None,
        "checkpoint_context": {"is_simulation": False},
        "phase": {"last_finished_gw": 2, "scoring_gw": 3},
        "reconciliation_actuals": {"event": 1, "source_key": "reconciliation_event_live"},
        "official": {"reconciliation_event_live": _live()},
    }

    result = lifecycle.reconcile_latest_finished(raw, now=POST)

    assert result["status"] == "SKIP"
    assert result["reason"] == "raw_snapshot_reconciliation_actuals_event_mismatch"
    assert not store.reconciled_path(2).exists()


def test_validation_preserves_same_gw_event_live_contract(monkeypatch, tmp_path):
    _isolate_store(monkeypatch, tmp_path)
    store.persist_deadline_snapshot(2, DEADLINE, _prediction(), now=PRE)
    raw = {
        "schema": "snapshot.v1",
        "as_of": None,
        "checkpoint_context": {"is_simulation": False},
        "phase": {"last_finished_gw": 2, "scoring_gw": 2},
        "official": {"event_live": _live()},
    }

    result = lifecycle.reconcile_latest_finished(raw, now=POST)

    assert result["status"] == "PASS"
    assert result["actuals_source_key"] == "event_live"
