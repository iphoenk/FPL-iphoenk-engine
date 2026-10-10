"""GW6 news ingestion is strictly bounded, source-labelled, and non-authoritative."""

from datetime import datetime
from pathlib import Path
import json

from src.engines.v12_deadline_team_news import merge_gw6_deadline_team_news
from src.engines.report_time_intelligence import validate_evidence


def test_gw6_news_merged_as_secondary_and_schema_accepted():
    prior = {"contract": "report_time_evidence_v1", "signals": []}
    merged = merge_gw6_deadline_team_news(
        prior, report_slot="2026-10-10T12:30:00+07:00", target_gw=6
    )
    assert len(merged["signals"]) >= 100
    assert all(r["source_class"] == "SECONDARY_AVAILABILITY" for r in merged["signals"])
    assert all(r["availability_evidence"]["target_gw"] == 6 for r in merged["signals"])
    checked = validate_evidence(
        merged, now=datetime.fromisoformat("2026-10-10T12:30:00+07:00")
    )
    assert checked["rejected_count"] == 0
    assert checked["accepted_count"] == len(merged["signals"])
    assert all(r["current"] is True for r in checked["accepted"])
    assert prior["signals"] == []


def test_gw6_news_expires_and_cannot_become_gw7_fact():
    for gw, slot in [
        (7, "2026-10-10T12:30:00+07:00"),
        (6, "2026-10-10T17:00:00+07:00"),
        (6, "2026-10-10T09:00:00+07:00"),
    ]:
        base = {"contract": "report_time_evidence_v1", "signals": []}
        assert merge_gw6_deadline_team_news(
            base, report_slot=slot, target_gw=gw
        ) == base


def test_no_double_addition_of_same_root_observation():
    first = merge_gw6_deadline_team_news(
        {"contract": "report_time_evidence_v1"},
        report_slot="2026-10-10T12:30:00+07:00", target_gw=6
    )
    second = merge_gw6_deadline_team_news(
        first, report_slot="2026-10-10T12:30:00+07:00", target_gw=6
    )
    assert len(first["signals"]) == len(second["signals"])
