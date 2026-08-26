import json

from src.services.contracts import file_digest
import src.services.prediction_service as service


def test_prediction_preserves_v480_artifacts_and_archives(tmp_path, monkeypatch):
    data = tmp_path / "data"
    runtime = data / "runtime"
    runtime.mkdir(parents=True)
    bootstrap = {
        "total_players": 100,
        "elements": [{"id": 1, "web_name": "Test", "now_cost": 50, "selected_by_percent": "10", "transfers_in_event": 5, "transfers_out_event": 2}],
    }
    raw = {"schema": "snapshot.v1", "mode": "deadline", "team_id": 1, "checkpoint_context": {"policy_id": "test", "is_simulation": True}, "phase": {"submitted_gw": 1, "planning_gw": 2, "scoring_gw": None}, "official": {"bootstrap": bootstrap, "fixtures": [], "history": {"chips": []}}, "endpoint_health": {}, "squad_authority": "LOCKED_PRE_DEADLINE", "squad": [], "team_value_ledger": [], "itb_tenths": 10}
    snapshot = runtime / "snapshot.v1.json"
    snapshot.write_text(json.dumps(raw))
    enrichment = {"schema": "enrichment.v1", "lineage": {"snapshot_sha256": file_digest(snapshot)}, "stats_gw": 1, "advanced_stats_sync": {}, "universe": []}
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
