from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json

import pytest

from scripts.v12_gw6_original_archive_asof import (
    ORIGINAL_COMMIT, ORIGINAL_RUN_ID, SOURCE_PATH, NORMALIZED_PATH,
    HistoricalAsOfError, verify_original_gw6_archive,
)


def _payloads():
    stamp = "2026-09-22T12:28:59+00:00"
    snapshots = {}
    fixtures = []
    events = []
    rows = []
    for gw in range(1, 6):
        events.append({"id": gw, "finished": True, "data_checked": True,
                       "deadline_time": f"2026-09-{gw+10:02d}T10:00:00Z"})
        for game in range(10):
            fixtures.append({"id": (gw-1)*10+game+1, "event": gw, "finished": True})
        entries = {}
        for pid in range(1, {1:593,2:618,3:654,4:659,5:667}[gw]+1):
            fixture = (gw-1)*10+((pid-1)%10)+1
            start = int(pid <= 220)
            minutes = 90 if start else 0
            points = 6 if start else 0
            entries[str(pid - 1)] = {
                "stats": {"starts": start, "minutes": minutes, "total_points": points},
                "explain": [{"fixture": fixture, "stats": []}],
            }
            rows.append({
                "gw": gw, "official_element_id": pid, "official_fixture_id": fixture,
                "identity_status": "EXACT", "fixture_identity_status": "EXACT",
                "opponent_identity_status": "EXACT", "starts": start,
                "starter": bool(start), "minutes": minutes, "fpl_points": points,
            })
        snapshots[f"event_live_gw{gw}"] = {
            "status": "AVAILABLE", "checked_at": stamp,
            "sha256": f"{gw}" * 64, "json": {"elements": entries},
        }
    events.append({"id": 6, "finished": False,
                   "deadline_time": "2026-10-10T10:00:00Z"})
    source = {
        "source_id": "official_fpl", "checked_at": stamp,
        "data": {
            "bootstrap": {"json": {"events": events}},
            "fixtures": {"json": fixtures}, **snapshots,
        },
    }
    normalized = {
        "source_id": "official_fpl",
        "normalization_status": "NORMALIZED",
        "effective_at": stamp, "generated_at": stamp,
        "source_snapshot_ids": [f"{gw}" * 64 for gw in range(1, 6)],
        "record_groups": {"player_matches": rows},
    }
    return source, normalized


def _run(source, normalized, *, when="2026-09-22T12:29:19+00:00",
         commit=ORIGINAL_COMMIT, corrupt_catalog=False):
    raw = json.dumps(source, separators=(",", ":")).encode()
    norm = json.dumps(normalized, separators=(",", ":")).encode()
    catalog = {"artifacts": [
        {"path": path, "sha256": hashlib.sha256(data).hexdigest(),
         "source_id": "official_fpl", "status": "PROVEN",
         "origin_run_id": ORIGINAL_RUN_ID}
        for path, data in ((SOURCE_PATH, raw), (NORMALIZED_PATH, norm))
    ]}
    if corrupt_catalog:
        catalog["artifacts"][0]["sha256"] = "a" * 64
    return verify_original_gw6_archive(
        source_bytes=raw, normalized_bytes=norm,
        catalog_bytes=json.dumps(catalog).encode(),
        immutable_commit_at=when, immutable_commit_sha=commit,
    )


def test_original_archived_gw6_input_asof_passes_without_promoting_older_gws():
    source, normalized = _payloads()
    out = _run(source, normalized)
    assert out["gw6_training_input_asof"] == "PASS"
    assert out["verified_original_player_match_rows"] == 3191
    assert out["verified_finished_fixtures"] == 50
    assert out["historical_gw1_gw6_complete_asof"] == "PARTIAL_NOT_FULL"
    assert out["predeadline_model_prediction"] == "NOT_ESTABLISHED"
    assert out["prospective_gw7_settlement"] == "PENDING_FUTURE_GW_RESULTS"
    assert out["numeric_pstart_effect"] == "NONE"


@pytest.mark.parametrize("mutation", [
    "source_sha", "missing_snapshot", "unfinalized", "duplicate_row",
    "bad_starter", "wrong_explain_fixture", "late_archive", "wrong_commit",
    "missing_identity", "short_gw", "source_after_commit",
])
def test_original_archived_gw6_asof_fails_closed(mutation):
    source, normalized = _payloads()
    if mutation == "source_sha":
        assert_error = lambda: _run(source, normalized, corrupt_catalog=True)
    else:
        when, commit = "2026-09-22T12:29:19+00:00", ORIGINAL_COMMIT
        if mutation == "missing_snapshot":
            del source["data"]["event_live_gw3"]
        elif mutation == "unfinalized":
            source["data"]["bootstrap"]["json"]["events"][3]["data_checked"] = False
        elif mutation == "duplicate_row":
            normalized["record_groups"]["player_matches"].append(
                deepcopy(normalized["record_groups"]["player_matches"][0]))
        elif mutation == "bad_starter":
            normalized["record_groups"]["player_matches"][0]["starts"] = 0
        elif mutation == "wrong_explain_fixture":
            normalized["record_groups"]["player_matches"][0]["official_fixture_id"] = 50
        elif mutation == "late_archive":
            when = "2026-10-11T12:29:19+00:00"
        elif mutation == "wrong_commit":
            commit = "a" * 40
        elif mutation == "missing_identity":
            normalized["record_groups"]["player_matches"][0]["identity_status"] = "UNMAPPED"
        elif mutation == "short_gw":
            normalized["record_groups"]["player_matches"].pop()
        elif mutation == "source_after_commit":
            source["checked_at"] = "2026-09-23T12:29:19+00:00"
        assert_error = lambda: _run(source, normalized, when=when, commit=commit)
    with pytest.raises(HistoricalAsOfError):
        assert_error()
