import gzip
import json

from src.engines import report_materializer as mod


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_s02_loads_occurrence_bound_v6_history(monkeypatch, tmp_path):
    v6 = tmp_path / "v6"
    generated = "2026-10-12T05:30:00+00:00"
    _write_json(v6 / "report_prefetch" / "latest.json", {
        "report_kind": "full_master",
        "target_logical_report_slot": "2026-10-12T12:30:00+07:00",
        "generated_at": generated,
        "report_prefetch_run_id": "prefetch-1",
    })
    payload = {
        "contract": "OFFICIAL_DETAIL_FULL_SEASON_HISTORY_V1",
        "generated_at": generated,
        "full_season_history": {
            "contract": "OFFICIAL_FULL_SEASON_PLAYER_HISTORY_V1",
            "as_of": {"planning_gw": 7, "historical_gws": [1, 2, 3, 4, 5, 6]},
            "coverage_gate": {"status": "PASS", "available_gw_slots": 4002},
            "universe": {"expected_players": 667, "covered_players": 667},
        },
    }
    history = v6 / "history" / "official_detail.json.gz"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_bytes(gzip.compress(json.dumps(payload).encode("utf-8")))
    monkeypatch.setattr(mod, "DATA", tmp_path)
    out = mod._load_occurrence_bound_official_detail(
        report_kind="full_master",
        logical_slot="2026-10-12T12:30:00+07:00",
    )
    assert out["full_season_history"]["coverage_gate"]["status"] == "PASS"


def test_s02_rejects_history_from_another_occurrence(monkeypatch, tmp_path):
    v6 = tmp_path / "v6"
    _write_json(v6 / "report_prefetch" / "latest.json", {
        "report_kind": "full_master",
        "target_logical_report_slot": "2026-10-12T12:30:00+07:00",
        "generated_at": "2026-10-12T05:30:00+00:00",
        "report_prefetch_run_id": "prefetch-1",
    })
    _write_json(v6 / "history" / "official_detail.json", {
        "contract": "OFFICIAL_DETAIL_FULL_SEASON_HISTORY_V1",
        "generated_at": "2026-10-12T04:00:00+00:00",
        "full_season_history": {"coverage_gate": {"status": "PASS"}},
    })
    monkeypatch.setattr(mod, "DATA", tmp_path)
    out = mod._load_occurrence_bound_official_detail(
        report_kind="full_master",
        logical_slot="2026-10-12T12:30:00+07:00",
    )
    assert out == {}


def test_s02_requires_full_master_slot_binding(monkeypatch, tmp_path):
    v6 = tmp_path / "v6"
    _write_json(v6 / "report_prefetch" / "latest.json", {
        "report_kind": "match_mode",
        "target_logical_report_slot": "2026-10-12T12:30:00+07:00",
        "generated_at": "2026-10-12T05:30:00+00:00",
    })
    _write_json(v6 / "history" / "official_detail.json", {
        "contract": "OFFICIAL_DETAIL_FULL_SEASON_HISTORY_V1",
        "generated_at": "2026-10-12T05:30:00+00:00",
        "full_season_history": {"coverage_gate": {"status": "PASS"}},
    })
    monkeypatch.setattr(mod, "DATA", tmp_path)
    out = mod._load_occurrence_bound_official_detail(
        report_kind="full_master",
        logical_slot="2026-10-12T12:30:00+07:00",
    )
    assert out == {}
