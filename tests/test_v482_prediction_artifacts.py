import json

from src.services.contracts import file_digest
import src.services.prediction_service as service


def test_v482_prediction_preserves_compatibility_artifacts_and_archives(tmp_path, monkeypatch):
    data = tmp_path / "data"
    runtime = data / "runtime"
    runtime.mkdir(parents=True)
    bootstrap = {
        "total_players": 100,
        "teams": [{"id": 1, "name": "Test Team"}],
        "elements": [{"id": 1, "web_name": "Test", "team": 1, "element_type": 3, "now_cost": 50, "selected_by_percent": "10", "transfers_in_event": 5, "transfers_out_event": 2}],
    }
    raw = {"schema": "snapshot.v1", "duration_ms": 10, "mode": "deadline", "team_id": 1, "checkpoint_context": {"policy_id": "test", "is_simulation": True}, "phase": {"submitted_gw": 1, "planning_gw": 2, "scoring_gw": 1, "is_live_event": True}, "official": {"bootstrap": bootstrap, "fixtures": [], "history": {"chips": []}, "picks": {"picks": [{"element": 1, "position": 1, "multiplier": 2, "is_captain": True, "is_vice_captain": False}], "entry_history": {"event_transfers_cost": 0}}, "event_live": {"elements": [{"id": 1, "stats": {"total_points": 5, "minutes": 90}}]}}, "endpoint_health": {}, "squad_authority": "LOCKED_PRE_DEADLINE", "squad": [], "team_value_ledger": [], "itb_tenths": 10}
    snapshot = runtime / "snapshot.v1.json"
    snapshot.write_text(json.dumps(raw))
    enrichment = {"schema": "enrichment.v1", "duration_ms": 20, "lineage": {"snapshot_sha256": file_digest(snapshot)}, "stats_gw": 1, "advanced_stats_sync": {}, "universe": []}
    enrichment_path = runtime / "enrichment.v1.json"
    enrichment_path.write_text(json.dumps(enrichment))
    monkeypatch.setattr(service, "DATA", data)
    monkeypatch.setattr(service, "SNAPSHOT", snapshot)
    monkeypatch.setattr(service, "ENRICHMENT", enrichment_path)
    monkeypatch.setattr(service, "build_predictions", lambda *args, **kwargs: {"model_version": "v4.7.1-correctness-hotfix", "players": []})

    latest = service.run()

    for name in ("live.json", "prices.json", "price_cache.json", "health.json", "chips.json"):
        assert (data / name).is_file(), name
    assert (data / "gw/01.json").is_file()
    assert len((data / "history.jsonl").read_text().splitlines()) == 1
    assert latest["files"]["live"] == "data/live.json"
    assert latest["files"]["prices"] == "data/prices.json"
    assert latest["files"]["health"] == "data/health.json"
    assert latest["files"]["chips"] == "data/chips.json"
    live = json.loads((data / "live.json").read_text())
    player = live["players"][0]
    assert {key: player[key] for key in ("team", "position", "captain", "vice")} == {"team": "Test Team", "position": "MID", "captain": True, "vice": False}
    performance = latest["performance"]
    assert performance["raw_snapshot_ms"] == 10
    assert performance["enrichment_ms"] == 20
    assert performance["engine_before_snapshot_write_ms"] >= 30
