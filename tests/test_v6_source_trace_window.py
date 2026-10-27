from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.engines.v12_v6_source_trace import (
    V6_ACQUISITION_UPPER_MINUTES,
    build_v6_source_trace,
)

SLOT = "2026-10-26T21:30:00+07:00"


def _stamp(minutes):
    return (datetime.fromisoformat(SLOT) + timedelta(minutes=minutes)).astimezone(timezone.utc).isoformat()


def _write(root, *, generated, checked, slot=SLOT):
    files = {
        "data/v6/health/publish_integrity.json": {"status": "PASS", "logical_slot": slot, "run_id": "40349899515"},
        "data/v6/evidence/latest_index.json": {
            "generated_at": generated,
            "sources": [{
                "source_id": "official_fpl", "checked_at": checked,
                "health": "GREEN", "availability": "AVAILABLE",
                "source_snapshot_ids": ["official_fpl:bootstrap:h"],
            }],
        },
        "data/v6/evidence/resolved_registry.json": {"sources": [{"id": "official_fpl"}]},
        "data/v6/normalized/canonical_teams.json": {
            "authority": "official_fpl", "team_count": 20,
            "teams": [{"official_fpl_team_id": i} for i in range(1, 21)],
        },
    }
    for rel, payload in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload), encoding="utf-8")


def test_window_matches_downstream_occurrence_window():
    from ops.render_external_clock import DOWNSTREAM_WINDOW_MINUTES

    assert V6_ACQUISITION_UPPER_MINUTES == DOWNSTREAM_WINDOW_MINUTES[1]


def test_production_26_oct_late_tick_acquisition_is_accepted(tmp_path):
    # Real shape: V6 acquired 15:30:25Z for a 21:30 WIB slot (+60m25s).
    _write(tmp_path, generated="2026-10-26T15:30:25.561931+00:00",
           checked="2026-10-26T15:30:20+00:00")
    assert build_v6_source_trace(runtime_data_root=tmp_path, report_slot=SLOT)["status"] == "PASS"


@pytest.mark.parametrize("minutes", [-90, -5, 0, 15, 60, 70])
def test_acquisition_inside_window_passes(tmp_path, minutes):
    _write(tmp_path, generated=_stamp(minutes), checked=_stamp(minutes))
    assert build_v6_source_trace(runtime_data_root=tmp_path, report_slot=SLOT)["status"] == "PASS"


@pytest.mark.parametrize("minutes", [-91, 71, 600])
def test_acquisition_outside_window_fails_closed(tmp_path, minutes):
    _write(tmp_path, generated=_stamp(minutes), checked=_stamp(minutes))
    trace = build_v6_source_trace(runtime_data_root=tmp_path, report_slot=SLOT)
    assert trace["status"] == "FAIL"
    assert "V6_ACQUISITION_OUTSIDE_OCCURRENCE_WINDOW" in trace["failures"]
    assert trace["providers"] == []


def test_source_attempt_outside_window_fails_closed(tmp_path):
    _write(tmp_path, generated=_stamp(30), checked=_stamp(75))
    trace = build_v6_source_trace(runtime_data_root=tmp_path, report_slot=SLOT)
    assert "V6_SOURCE_ATTEMPT_TIME_INVALID:official_fpl" in trace["failures"]


@pytest.mark.parametrize("bad", ["", "nope", "2026-10-26T22:00:00"])
def test_missing_or_naive_timestamps_fail_closed(tmp_path, bad):
    _write(tmp_path, generated=bad, checked=_stamp(30))
    trace = build_v6_source_trace(runtime_data_root=tmp_path, report_slot=SLOT)
    assert trace["status"] == "FAIL"
    assert "V6_ACQUISITION_TIME_INVALID" in trace["failures"]


def test_mismatched_occurrence_slot_fails_closed(tmp_path):
    _write(tmp_path, generated=_stamp(30), checked=_stamp(30), slot="2026-10-26T12:30:00+07:00")
    trace = build_v6_source_trace(runtime_data_root=tmp_path, report_slot=SLOT)
    assert "V6_PUBLICATION_SLOT_MISMATCH" in trace["failures"]


def test_late_acquisition_still_never_proves_news_or_counterpart(tmp_path):
    _write(tmp_path, generated=_stamp(60), checked=_stamp(60))
    trace = build_v6_source_trace(runtime_data_root=tmp_path, report_slot=SLOT)
    assert trace["status"] == "PASS"
    assert trace["sufficient_for_full_source_gate"] is False
    assert trace["seven_category_news_scan"] == "NOT_PROVEN"
    assert trace["club_news_verification"] == "NOT_PROVEN"
    assert trace["five_domain_independent_counterpart"] == "NOT_PROVEN"
