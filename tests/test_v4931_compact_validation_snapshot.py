import json
from datetime import datetime, timezone

import src.engines.v4_backtest_store as store
from src.engines.v4_validation import reconcile_prediction_snapshot


def _predictions(player_count=24, first_event=3):
    players = []
    for element in range(1, player_count + 1):
        fixtures = []
        for event in range(first_event, first_event + 15):
            fixtures.append(
                {
                    "event": event,
                    "xpts": round(2.0 + element * 0.03 + event * 0.1, 3),
                    "lower80": 0.5,
                    "upper80": 9.5,
                    "xmins": {
                        "expected_minutes": 72 + element % 10,
                        "start_probability": 0.72 + (element % 5) * 0.03,
                        "p60": 0.68 + (element % 4) * 0.04,
                        "bench_probability": 0.1,
                        "dnp_probability": 0.05,
                        "availability_probability": 0.99,
                    },
                    "components": {
                        "appearance": 1.8,
                        "attack": 2.2,
                        "clean_sheet": 0.5,
                        "defcon": 0.4,
                        "bonus": 0.3,
                    },
                    "calibration": {
                        "nailed_prior": 0.8,
                        "competition_pressure": 0.15,
                        "set_piece_share": 0.2,
                        "penalty_share": 0.1,
                    },
                    "provenance": {
                        "xmins_prior_source": "synthetic_regression",
                        "opponent_defence_source": "synthetic_regression",
                        "role_scoring_mode": "synthetic_regression",
                    },
                }
            )
        players.append(
            {
                "element": element,
                "name": f"P{element}",
                "position": "MID" if element % 2 else "DEF",
                "xpts_3": 10.0,
                "xpts_5": 16.0,
                "xpts_10": 31.0,
                "xpts_15": 45.0,
                "uncertainty": 1.2,
                "priors": {"tactical_role": "synthetic", "competition_factor": 0.95},
                "value": {"xpts5_per_million": 2.4},
                "fixtures": fixtures,
            }
        )
    return {
        "schema_version": 493,
        "model_version": "v4.9.3.1-test",
        "generated_at": "2026-08-27T10:00:00+00:00",
        "point_in_time": True,
        "players": players,
    }


def test_compact_projection_is_reconciliation_lossless():
    predictions = _predictions()
    projected, fixture_rows = store.deadline_player_projection(predictions["players"], 3)
    assert len(projected) == len(predictions["players"])
    assert fixture_rows == len(predictions["players"])
    assert all(len(player["fixtures"]) == 1 for player in projected)
    assert all(player["fixtures"][0]["event"] == 3 for player in projected)

    full_snapshot = {"generated_at": predictions["generated_at"], "players": predictions["players"]}
    compact_snapshot = {"generated_at": predictions["generated_at"], "players": projected}
    actual = {
        element: {"total_points": element % 9, "minutes": 90 if element % 3 else 22, "started": element % 3 != 0}
        for element in range(1, len(projected) + 1)
    }
    deadline = "2026-08-30T17:30:00+00:00"
    reference = reconcile_prediction_snapshot(full_snapshot, actual, 3, deadline)
    compact = reconcile_prediction_snapshot(compact_snapshot, actual, 3, deadline)
    assert compact == reference


def test_new_snapshot_is_compact_and_existing_snapshot_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "SNAPDIR", tmp_path / "deadline")
    predictions = _predictions()
    deadline = "2026-08-30T17:30:00+00:00"
    now = datetime(2026, 8, 27, 10, 30, tzinfo=timezone.utc)

    frozen = store.persist_deadline_snapshot(3, deadline, predictions, now=now)
    path = store.deadline_snapshot_path(3)
    original_bytes = path.read_bytes()
    assert frozen["projection"] == store.COMPACT_PROJECTION
    assert frozen["source_players"] == len(predictions["players"])
    assert frozen["target_fixture_rows"] == len(predictions["players"])
    assert all(len(player["fixtures"]) <= 1 for player in frozen["players"])
    assert store.snapshot_integrity(frozen, 3) == (True, None)

    changed = _predictions()
    changed["players"][0]["fixtures"][0]["xpts"] = 99.0
    preserved = store.persist_deadline_snapshot(3, deadline, changed, now=now)
    assert path.read_bytes() == original_bytes
    assert preserved == frozen


def test_compact_snapshot_has_strict_storage_budget():
    predictions = _predictions(player_count=60)
    projected, fixture_rows = store.deadline_player_projection(predictions["players"], 3)
    compact = {
        "model_version": predictions["model_version"],
        "generated_at": predictions["generated_at"],
        "projection": store.COMPACT_PROJECTION,
        "source_players": len(predictions["players"]),
        "target_fixture_rows": fixture_rows,
        "players": projected,
    }
    full_bytes = len(json.dumps(predictions, separators=(",", ":")).encode("utf-8"))
    compact_bytes = len(json.dumps(compact, separators=(",", ":")).encode("utf-8"))
    assert compact_bytes < full_bytes * 0.15, (compact_bytes, full_bytes)


def test_legacy_full_snapshot_remains_backward_compatible():
    predictions = _predictions(player_count=2)
    legacy = {
        "schema_version": 493,
        "kind": "deadline_prediction_snapshot",
        "gw": 3,
        "deadline_time": "2026-08-30T17:30:00+00:00",
        "generated_at": predictions["generated_at"],
        "prediction_generated_at": predictions["generated_at"],
        "captured_at": "2026-08-27T10:30:00+00:00",
        "model_version": predictions["model_version"],
        "point_in_time": True,
        "immutable": True,
        "prediction_sha256": "legacy-digest",
        "players": predictions["players"],
    }
    assert store.snapshot_integrity(legacy, 3) == (True, None)
