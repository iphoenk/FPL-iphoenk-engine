import json

import pytest

from src.engines import official_history_reconciliation as mod


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_gw1_public_official_history_is_proxy_only(monkeypatch, tmp_path):
    data = tmp_path / "data"
    cfg = tmp_path / "prediction_evaluation.json"
    gw1_picks = {
        "active_chip": "bboost",
        "entry_history": {"event": 1, "points": 71, "total_points": 71, "points_on_bench": 8},
        "picks": [
            {"element": 411, "position": 1, "multiplier": 2, "is_captain": True, "is_vice_captain": False},
            {"element": 426, "position": 2, "multiplier": 1, "is_captain": False, "is_vice_captain": True},
        ],
        "automatic_subs": [],
    }
    _write(data / "team.json", {"team_id": 3462711})
    _write(data / "latest.json", {"official_detail_summary": {}})
    _write(data / "official_detail.json", {"generated_at": "before"})
    _write(data / "official_snapshot.json", {
        "team_id": 3462711,
        "phase": {"submitted_gw": 1},
        "history": {"current": [{"event": 1, "points": 71, "total_points": 71, "overall_rank": 462166}]},
        "picks": gw1_picks,
        "purchase_baseline": {"gw": 1, "picks": gw1_picks},
        "endpoint_health": {"history": {"status": "LIVE"}, "picks": {"status": "LIVE"}},
    })
    _write(cfg, {
        "retrospective_proxy_baseline": {
            "enabled": True,
            "label": "RETROSPECTIVE_PROXY_BASELINE",
            "gameweeks": [1],
            "max_historical_gameweeks": 5,
            "count_toward_predictive_accuracy": False,
            "count_toward_dynamic_weight": False,
        }
    })

    def fail_on_network(path, retries=1):
        raise AssertionError(f"GW1 should reuse canonical snapshot, unexpected network fetch: {path}")

    monkeypatch.setattr(mod, "DATA", data)
    monkeypatch.setattr(mod, "CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "get_json", fail_on_network)

    out = mod.run()
    gw1 = out["gameweeks"]["1"]
    proxy = out["retrospective_proxy_baseline"]
    assert gw1["status"] == "PUBLIC_OFFICIAL_SUBMITTED_TEAM"
    assert gw1["authority"] == "PUBLIC_OFFICIAL_POST_DEADLINE"
    assert gw1["submitted"]["entry_history"]["points"] == 71
    assert gw1["submitted"]["picks"][0]["is_captain"] is True
    assert proxy["gameweeks"] == [1]
    assert proxy["use_for_predictive_accuracy"] is False
    assert proxy["use_for_dynamic_weight"] is False
    assert out["authority_split"]["historical_submitted_team"] == "GREEN_PUBLIC_OFFICIAL"
    assert out["authority_split"]["current_private_pre_deadline_draft"] == "OPTIONAL_AUTHENTICATED_MONITOR"
    assert out["governance"]["entry_history_reused_from_snapshot"] is True
    assert out["governance"]["snapshot_pick_reuses"] == 1
    assert out["governance"]["historical_pick_network_fetches"] == 0

    latest = json.loads((data / "latest.json").read_text())
    assert latest["official_detail_summary"]["historical_submitted_team_authority"] == "GREEN_PUBLIC_OFFICIAL"
    assert latest["official_detail_summary"]["retrospective_proxy_gameweeks"] == [1]
    assert latest["official_detail_summary"]["historical_pick_network_fetches"] == 0


def test_history_reconciliation_requires_authoritative_team_id(monkeypatch, tmp_path):
    data = tmp_path / "data"
    cfg = tmp_path / "prediction_evaluation.json"
    _write(data / "team.json", {})
    _write(data / "latest.json", {})
    _write(data / "official_detail.json", {})
    _write(cfg, {"retrospective_proxy_baseline": {"gameweeks": [1]}})
    monkeypatch.setattr(mod, "DATA", data)
    monkeypatch.setattr(mod, "CONFIG_PATH", cfg)
    with pytest.raises(RuntimeError, match="team_id"):
        mod.run()
