import json

import pytest

from src.engines import official_history_reconciliation as mod
from src.runtime_v6.domains.report_plane import report_prefetch


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_gw1_public_official_history_is_proxy_only(monkeypatch, tmp_path):
    data = tmp_path / "data"
    cfg = tmp_path / "prediction_evaluation.json"
    _write(data / "team.json", {"team_id": 3462711})
    _write(data / "latest.json", {"official_detail_summary": {}})
    _write(data / "official_detail.json", {"generated_at": "before"})
    _write(data / "official_snapshot.json", {
        "bootstrap": {"elements": []},
        "history": {"current": [{"event": 1, "points": 71, "total_points": 71, "overall_rank": 462166}]},
        "phase": {"submitted_gw": 0},
        "endpoint_health": {"history": {"status": "LIVE"}},
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

    def fake_get_json(path, retries=1):
        if path == "entry/3462711/event/1/picks/":
            return {
                "active_chip": "bboost",
                "entry_history": {"event": 1, "points": 71, "total_points": 71, "points_on_bench": 8},
                "picks": [
                    {"element": 411, "position": 1, "multiplier": 2, "is_captain": True, "is_vice_captain": False},
                    {"element": 426, "position": 2, "multiplier": 1, "is_captain": False, "is_vice_captain": True},
                ],
                "automatic_subs": [],
            }, {"status": "LIVE"}
        raise AssertionError(path)

    monkeypatch.setattr(mod, "DATA", data)
    monkeypatch.setattr(mod, "CONFIG_PATH", cfg)
    monkeypatch.setattr(mod, "get_json", fake_get_json)

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

    latest = json.loads((data / "latest.json").read_text())
    assert latest["official_detail_summary"]["historical_submitted_team_authority"] == "GREEN_PUBLIC_OFFICIAL"
    assert latest["official_detail_summary"]["retrospective_proxy_gameweeks"] == [1]


def test_history_reconciliation_requires_authoritative_team_id(monkeypatch, tmp_path):
    data = tmp_path / "data"
    cfg = tmp_path / "prediction_evaluation.json"
    _write(data / "team.json", {})
    _write(data / "latest.json", {})
    _write(data / "official_detail.json", {})
    _write(data / "official_snapshot.json", {
        "bootstrap": {"elements": []},
        "history": {"current": []},
        "endpoint_health": {"history": {"status": "LIVE"}},
    })
    _write(cfg, {"retrospective_proxy_baseline": {"gameweeks": [1]}})
    monkeypatch.setattr(mod, "DATA", data)
    monkeypatch.setattr(mod, "CONFIG_PATH", cfg)
    with pytest.raises(RuntimeError, match="team_id"):
        mod.run()


def test_full_season_history_covers_all_slots_and_aggregates_dgw():
    snapshot = {"generated_at": "2026-10-12T00:00:00Z", "phase": {"current_gw": 4}, "fixtures": [{"id": 101, "event": 1}, {"id": 102, "event": 2}, {"id": 103, "event": 2}], "bootstrap": {"events": [{"id": 1, "finished": True}, {"id": 2, "finished": True}, {"id": 3, "finished": True}], "elements": [{"id": 10, "element_type": 1, "team": 1}]}}
    detail = {"element_summaries": {"10": {"history": [{"event": 1, "fixture": 101, "minutes": 90, "total_points": 6, "saves": 3}, {"event": 2, "fixture": 102, "minutes": 0, "total_points": 0, "saves": 0}, {"event": 2, "fixture": 103, "minutes": 90, "total_points": 8, "saves": 6}], "fixtures": [{"event": 1, "id": 101, "finished": True}, {"event": 2, "id": 102, "finished": True}, {"event": 2, "id": 103, "finished": True}]}}}
    out = mod.build_full_season_history(snapshot=snapshot, detail=detail)
    assert out["coverage_gate"]["status"] == "PASS"
    assert out["as_of"]["historical_gws"] == [1, 2, 3]
    assert out["players"]["10"]["history"]["2"]["status"] == "FINAL"
    assert out["players"]["10"]["history"]["2"]["aggregate"]["minutes"] == 90
    assert out["players"]["10"]["history"]["2"]["fixture_count"] == 2
    assert out["coverage_gate"]["verified_fixture_rows"] == 3
    assert out["coverage_gate"]["fixture_identity_status"] == "PASS"

def test_full_season_history_marks_missing_detail_without_zero_fill():
    snapshot = {"generated_at": "2026-10-12T00:00:00Z", "phase": {"current_gw": 3}, "bootstrap": {"events": [{"id": 1, "finished": True}, {"id": 2, "finished": True}], "elements": [{"id": 10}]}}
    out = mod.build_full_season_history(snapshot=snapshot, detail={"element_summaries": {}})
    assert out["coverage_gate"]["status"] == "PARTIAL"
    assert out["coverage_gate"]["missing_records"]
    assert out["coverage_gate"]["pending_never_coerced_to_zero"] is True


def test_full_history_fetch_retries_per_player_and_isolates_failure(monkeypatch):
    calls = {}

    class Client:
        def element_summary(self, element_id):
            calls[element_id] = calls.get(element_id, 0) + 1
            if element_id == 10 and calls[element_id] < 2:
                raise RuntimeError("transient timeout")
            if element_id == 11:
                raise RuntimeError("permanent failure")
            return {"status": "LIVE", "payload": {"history": [], "fixtures": [], "history_past": []}}

    monkeypatch.setattr(report_prefetch.time, "sleep", lambda _: None)
    artifact, health = report_prefetch._build_full_history_artifact(
        client=Client(),
        bootstrap_payload={"elements": [{"id": 10}, {"id": 11}], "events": []},
        fixtures=[],
        planning_gw=2,
        generated_at="2026-10-12T06:00:00Z",
        workers=2,
    )
    assert health["status"] == "PARTIAL"
    assert health["expected_players"] == 2
    assert health["covered_players"] == 1
    assert health["failed_requests"] == 1
    assert calls[10] == 2
    assert calls[11] == 3
    assert set(artifact["element_summaries"]) == {"10"}
    assert artifact["enrichment"]["health"]["11"]["status"] == "UNAVAILABLE"


def test_full_history_identity_gate_rejects_mismatched_fixture_event():
    snapshot = {
        "generated_at": "2026-10-13T00:00:00Z",
        "phase": {"current_gw": 3},
        "fixtures": [{"id": 101, "event": 2}],
        "bootstrap": {
            "events": [{"id": 1, "finished": True}, {"id": 2, "finished": True}],
            "elements": [{"id": 10, "element_type": 3, "team": 1}],
        },
    }
    detail = {"element_summaries": {"10": {
        "history": [{"event": 1, "fixture": 101, "minutes": 90, "total_points": 5}],
        "fixtures": [],
    }}}
    result = mod.build_full_season_history(snapshot=snapshot, detail=detail)
    assert result["coverage_gate"]["status"] == "PARTIAL"
    assert result["coverage_gate"]["fixture_identity_status"] == "PARTIAL"
    assert result["coverage_gate"]["fixture_identity_anomalies"][0]["reason"] == "OFFICIAL_FIXTURE_GW_MISMATCH"
    assert result["players"]["10"]["history"]["1"]["fixtures"][0]["minutes"] == 90


def test_full_history_identity_gate_fails_closed_without_fixture_catalog():
    snapshot = {
        "phase": {"current_gw": 2},
        "bootstrap": {
            "events": [{"id": 1, "finished": True}],
            "elements": [{"id": 10, "element_type": 1, "team": 1}],
        },
    }
    detail = {"element_summaries": {"10": {
        "history": [{"event": 1, "fixture": 101, "minutes": 90}],
        "fixtures": [],
    }}}
    result = mod.build_full_season_history(snapshot=snapshot, detail=detail)
    assert result["coverage_gate"]["status"] == "PARTIAL"
    assert result["coverage_gate"]["fixture_catalog_count"] == 0
    assert result["coverage_gate"]["verified_fixture_rows"] == 0


def test_full_history_identity_gate_rejects_duplicate_player_fixture():
    snapshot = {
        "phase": {"current_gw": 2},
        "fixtures": [{"id": 101, "event": 1}],
        "bootstrap": {
            "events": [{"id": 1, "finished": True}],
            "elements": [{"id": 10, "element_type": 2, "team": 1}],
        },
    }
    detail = {"element_summaries": {"10": {
        "history": [
            {"event": 1, "fixture": 101, "minutes": 45},
            {"event": 1, "fixture": 101, "minutes": 45},
        ],
        "fixtures": [],
    }}}
    result = mod.build_full_season_history(snapshot=snapshot, detail=detail)
    assert result["coverage_gate"]["status"] == "PARTIAL"
    assert result["coverage_gate"]["fixture_identity_anomalies"][0]["reason"] == "DUPLICATE_PLAYER_FIXTURE_ID"
    # Preserve raw rows for diagnosis; do not silently drop or fabricate.
    assert len(result["players"]["10"]["history"]["1"]["fixtures"]) == 2


def test_v6_production_reconciliation_rejects_bad_fixture_identity():
    snapshot = {
        "generated_at": "2026-10-13T04:00:00Z",
        "bootstrap": {
            "elements": [{"id": 10, "element_type": 3, "team": 1}],
            "events": [{"id": 1, "finished": True}],
        },
        "fixtures": [{"id": 101, "event": 1, "finished": True}],
        "phase": {"current_gw": 2},
    }
    valid = {"10": {"history": [
        {"fixture": 101, "round": 1, "minutes": 90, "total_points": 6},
    ]}}
    result = report_prefetch._reconcile_full_history(snapshot, valid)
    assert result["coverage_gate"]["status"] == "PASS"
    assert result["coverage_gate"]["verified_fixture_rows"] == 1

    invalid = {"10": {"history": [
        {"fixture": 101, "round": 1, "minutes": 90},
        {"fixture": 101, "round": 1, "minutes": 0},
    ]}}
    duplicate = report_prefetch._reconcile_full_history(snapshot, invalid)
    assert duplicate["coverage_gate"]["status"] == "PARTIAL"
    assert duplicate["coverage_gate"]["fixture_identity_anomalies"][0]["reason"] == "DUPLICATE_PLAYER_FIXTURE_ID"
    assert len(duplicate["players"]["10"]["history"]["1"]["fixtures"]) == 2


def test_v6_production_reconciliation_fails_closed_without_catalog_and_on_cross_gw_mismatch():
    snapshot = {
        "generated_at": "2026-10-13T04:00:00Z",
        "bootstrap": {
            "elements": [{"id": 10, "element_type": 2, "team": 1}],
            "events": [{"id": 1, "finished": True}],
        },
        "fixtures": [],
        "phase": {"current_gw": 2},
    }
    summaries = {"10": {"history": [{"fixture": 101, "round": 1, "minutes": 90}]}}
    without_catalog = report_prefetch._reconcile_full_history(snapshot, summaries)
    assert without_catalog["coverage_gate"]["status"] == "PARTIAL"
    assert without_catalog["coverage_gate"]["fixture_catalog_count"] == 0
    snapshot["fixtures"] = [{"id": 101, "event": 2}]
    wrong_gw = report_prefetch._reconcile_full_history(snapshot, summaries)
    assert wrong_gw["coverage_gate"]["status"] == "PARTIAL"
    assert wrong_gw["coverage_gate"]["fixture_identity_anomalies"][0]["reason"] == "OFFICIAL_FIXTURE_GW_MISMATCH"
