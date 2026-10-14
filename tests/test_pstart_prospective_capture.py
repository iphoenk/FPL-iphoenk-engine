from datetime import datetime, timezone
import hashlib
import json

import pytest

from src.engines import v12_pstart_prospective as module


def _sample(tmp_path):
    base = tmp_path / "data/v6"
    (base / "normalized/sources").mkdir(parents=True)
    (base / "current").mkdir()
    (base / "normalized/sources/official_fpl.json").write_text(
        json.dumps({"source_id": "official_fpl", "source_snapshot_ids": ["official_fpl:historical:sha"]})
    )
    (base / "current/official_fpl.json").write_text('{"official":{"bootstrap":{}}}')
    bootstrap = {
        "elements": [
            {"id": 11, "element_type": 1, "team": 1, "starts": 3, "minutes": 270, "status": "a"},
            {"id": 22, "element_type": 3, "team": 2, "starts": 2, "minutes": 180, "status": "a"},
        ],
        "events": [{"id": 7, "finished": False, "deadline_time": "2026-10-17T10:00:00Z"}],
    }
    projections = {
        "planning_gw": 7,
        "players": [
            {"element": 11, "current_season": {"starts": 3, "minutes": 270},
             "selection_evidence": {"status": "AVAILABLE", "observed_matches": 3},
             "xmins": {"start_probability": .83, "expected_minutes": 71,
                       "dnp_probability": .08, "cameo_probability": .09}},
            {"element": 22, "current_season": {"starts": 2, "minutes": 180},
             "selection_evidence": {"status": "AVAILABLE", "observed_matches": 3},
             "xmins": {"start_probability": .72, "expected_minutes": 65,
                       "dnp_probability": .16, "cameo_probability": .12}},
        ],
    }
    return bootstrap, projections


def _capture(tmp_path, monkeypatch):
    bootstrap, projections = _sample(tmp_path)
    observed = []
    def estimate(player, context):
        assert "selection_evidence" not in context
        observed.append(player["id"])
        return {
            "start_probability": .70, "expected_minutes": 60,
            "dnp_probability": .20, "cameo_probability": .10,
        }
    monkeypatch.setattr(module, "estimate_player_minutes", estimate)
    monkeypatch.setattr(module, "_verify_original_v6_inputs", lambda *a: {
        "git_commit": "b" * 40,
        "git_commit_at": "2026-10-14T03:50:00+00:00",
        "git_object_readback": "PASS",
        "private_remote_readback": "UNVERIFIED",
    })
    result = module.build_prospective_capture(
        bootstrap=bootstrap,
        projections=projections,
        strength={"teams": [
            {"team_id": 1, "matches_played": 3},
            {"team_id": 2, "matches_played": 3},
        ]},
        foundation={"player_match_rows": []},
        runtime_data_root=tmp_path,
        report_slot="2026-10-14T11:00:00+07:00",
        prefetch_run_id="verified-source-prefetch-run",
        model_sha="a" * 40,
        observed_at=datetime(2026, 10, 14, 4, 0, tzinfo=timezone.utc),
    )
    return result, observed


def test_prospective_capture_is_full_universe_and_paired(tmp_path, monkeypatch):
    result, observed = _capture(tmp_path, monkeypatch)
    assert observed == [11, 22]
    assert result["status"] == "CAPTURED_AWAITING_IMMUTABLE_REMOTE_READBACK"
    assert result["universe_expected"] == result["universe_observed"] == 2
    assert result["positions"]["GK"] == result["positions"]["MID"] == 1
    rows = result["forecast_rows"]
    assert rows[0]["baseline"]["start_probability"] == .70
    assert rows[0]["individualized"]["start_probability"] == .83
    assert rows[0]["role_manager_fit"] == "ADVISORY_UNCALIBRATED"
    assert result["source"]["identity_verified_by_original_git_readback"] is True
    assert result["source"]["original_git_evidence"]["git_object_readback"] == "PASS"
    assert result["source"]["original_git_evidence"]["private_remote_readback"] == "UNVERIFIED"
    assert all(len(value) == 64 for value in result["source"]["source_file_sha256"].values())
    expected = hashlib.sha256(
        json.dumps(rows, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert result["forecast_rows_sha256"] == expected
    assert result["calibration"] == "PENDING_FUTURE_GW_SETTLEMENT"


def test_prospective_capture_rejects_postdeadline_without_backdating(tmp_path, monkeypatch):
    bootstrap, projections = _sample(tmp_path)
    monkeypatch.setattr(module, "estimate_player_minutes", lambda p, c: {})
    with pytest.raises(module.ProspectiveCaptureError, match="NO_PREDEADLINE_CAPTURE"):
        module.build_prospective_capture(
            bootstrap=bootstrap, projections=projections,
            strength={}, foundation={}, runtime_data_root=tmp_path,
            report_slot="2026-10-14T11:00:00+07:00",
            prefetch_run_id="run", model_sha="a" * 40,
            observed_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
        )


def test_prospective_capture_rejects_missing_universe(tmp_path, monkeypatch):
    bootstrap, projections = _sample(tmp_path)
    projections["players"].pop()
    with pytest.raises(module.ProspectiveCaptureError, match="UNIVERSE_INCOMPLETE"):
        module.build_prospective_capture(
            bootstrap=bootstrap, projections=projections,
            strength={}, foundation={}, runtime_data_root=tmp_path,
            report_slot="2026-10-14T11:00:00+07:00",
            prefetch_run_id="run", model_sha="a" * 40,
            observed_at=datetime(2026, 10, 14, tzinfo=timezone.utc),
        )
