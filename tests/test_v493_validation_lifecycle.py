from datetime import datetime, timezone
import json

import pytest

import src.engines.v4_backtest_store as store
import src.engines.v4_validation_cycle as lifecycle


MODEL = "v4.9.2-truthful-health"
DEADLINE = "2026-08-28T17:30:00+00:00"
PRE_DEADLINE = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
POST_DEADLINE = datetime(2026, 8, 28, 18, 0, tzinfo=timezone.utc)


def _prediction(model=MODEL, xpts=5.0, event=2):
    return {
        "generated_at": "2026-08-27T09:00:00+00:00",
        "model_version": model,
        "players": [
            {
                "element": 1,
                "name": "A",
                "position": "MID",
                "fixtures": [
                    {
                        "event": event,
                        "xpts": xpts,
                        "lower80": 1,
                        "upper80": 9,
                        "xmins": {
                            "expected_minutes": 80,
                            "start_probability": 0.9,
                            "p60": 0.8,
                        },
                    }
                ],
            }
        ],
    }


def _live(points=7, minutes=90):
    return {"elements": [{"id": 1, "stats": {"total_points": points, "minutes": minutes}}]}


def _isolate(monkeypatch, tmp_path):
    snapdir = tmp_path / "validation" / "deadline"
    archive = tmp_path / "validation" / "archive" / "reconciled"
    view = tmp_path / "validation" / "reconciled"
    monkeypatch.setattr(store, "SNAPDIR", snapdir)
    monkeypatch.setattr(store, "ARCHIVE_RECDIR", archive)
    monkeypatch.setattr(store, "RECDIR", view)

    runtime = tmp_path / "runtime" / "snapshot.v1.json"
    predictions = tmp_path / "predictions_v4.json"
    outfile = tmp_path / "validation" / "lifecycle_v4.json"
    monkeypatch.setattr(lifecycle, "RAW_SNAPSHOT", runtime)
    monkeypatch.setattr(lifecycle, "PREDICTIONS", predictions)
    monkeypatch.setattr(lifecycle, "OUTFILE", outfile)
    return runtime, predictions, outfile


def test_deadline_snapshot_is_frozen_and_preserved(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    first = store.persist_deadline_snapshot(2, DEADLINE, _prediction(xpts=5), now=PRE_DEADLINE)
    second = store.persist_deadline_snapshot(2, DEADLINE, _prediction(xpts=12), now=PRE_DEADLINE)

    assert first == second
    assert second["players"][0]["fixtures"][0]["xpts"] == 5
    assert second["immutable"] is True
    assert second["captured_at"] < DEADLINE


def test_retroactive_deadline_snapshot_is_rejected(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="retroactive deadline snapshot rejected"):
        store.persist_deadline_snapshot(2, DEADLINE, _prediction(), now=POST_DEADLINE)
    assert not store.deadline_snapshot_path(2).exists()


def test_reconciliation_is_idempotent_and_uses_frozen_snapshot(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    store.persist_deadline_snapshot(2, DEADLINE, _prediction(), now=PRE_DEADLINE)
    first = store.reconcile_finished_gw(2, _live(points=7), now=POST_DEADLINE)
    second = store.reconcile_finished_gw(2, _live(points=1), now=POST_DEADLINE)

    assert first == second
    assert first["report"]["rows"][0]["actual"] == 7
    assert first["report"]["metrics"]["status"] == "PASS"
    assert first["immutable"] is True


def test_health_view_only_materializes_current_model(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    store.persist_deadline_snapshot(2, DEADLINE, _prediction(model=MODEL), now=PRE_DEADLINE)
    store.reconcile_finished_gw(2, _live(), now=POST_DEADLINE)

    mismatch = store.refresh_eligible_view("v4.9.9-future-model")
    assert mismatch["eligible_samples"] == 0
    assert not store.eligible_reconciled_path(2).exists()
    assert mismatch["rejected_samples"][0]["reason"] == "model_version_mismatch"

    matched = store.refresh_eligible_view(MODEL)
    assert matched["eligible_samples"] == 1
    assert matched["eligible_gws"] == [2]
    assert store.eligible_reconciled_path(2).exists()


def test_malformed_sample_cannot_keep_health_active(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    store.ARCHIVE_RECDIR.mkdir(parents=True)
    store.RECDIR.mkdir(parents=True)
    (store.ARCHIVE_RECDIR / "gw03.json").write_text(json.dumps({"kind": "post_gw_reconciliation", "model_version": MODEL}))
    (store.RECDIR / "gw99.json").write_text("{}")

    result = store.refresh_eligible_view(MODEL)
    assert result["eligible_samples"] == 0
    assert result["rejected_samples"]
    assert list(store.RECDIR.glob("gw*.json")) == []


def test_cycle_does_not_backfill_finished_gw_without_predeadline_snapshot(monkeypatch, tmp_path):
    runtime, predictions_path, outfile = _isolate(monkeypatch, tmp_path)
    runtime.parent.mkdir(parents=True)
    raw = {
        "schema": "snapshot.v1",
        "as_of": None,
        "checkpoint_context": {"is_simulation": False},
        "phase": {
            "planning_gw": 2,
            "last_finished_gw": 1,
            "scoring_gw": 1,
            "deadline_time": DEADLINE,
        },
        "official": {"event_live": _live()},
    }
    runtime.write_text(json.dumps(raw))
    predictions_path.write_text(json.dumps(_prediction()))

    result = lifecycle.cycle(now=PRE_DEADLINE)
    assert result["status"] == "PASS"
    assert result["reconciliation"] == {"status": "SKIP", "reason": "no_predeadline_snapshot", "gw": 1}
    assert result["snapshot"]["status"] == "PASS"
    assert result["snapshot"]["action"] == "FROZEN"
    assert store.deadline_snapshot_path(2).exists()
    assert not store.deadline_snapshot_path(1).exists()
    assert result["eligibility"]["eligible_samples"] == 0
    assert outfile.exists()


def test_simulation_never_mutates_validation_store(monkeypatch, tmp_path):
    runtime, predictions_path, outfile = _isolate(monkeypatch, tmp_path)
    runtime.parent.mkdir(parents=True)
    runtime.write_text(
        json.dumps(
            {
                "schema": "snapshot.v1",
                "as_of": "2026-08-28T12:00:00+00:00",
                "checkpoint_context": {"is_simulation": True},
                "phase": {"planning_gw": 2, "deadline_time": DEADLINE},
                "official": {},
            }
        )
    )
    predictions_path.write_text(json.dumps(_prediction()))

    result = lifecycle.cycle(now=PRE_DEADLINE)
    assert result["simulated"] is True
    assert result["snapshot"]["status"] == "SKIP"
    assert result["reconciliation"]["status"] == "SKIP"
    assert result["eligibility"]["health_view_rebuilt"] is False
    assert not store.deadline_snapshot_path(2).exists()
    assert not store.ARCHIVE_RECDIR.exists()
    assert outfile.exists()
