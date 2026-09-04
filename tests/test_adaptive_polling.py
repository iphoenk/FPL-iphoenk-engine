from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.runtime_v6.polling import (
    attach_poll_result,
    deadline_window_active,
    effective_poll_interval_minutes,
    poll_decision,
)
from src.runtime_v6.registry import EXPECTED_SOURCE_IDS, load_registry, source_map


def test_registry_keeps_full_27_source_contract_and_adds_ingestion_metadata():
    registry = load_registry()
    sources = source_map(registry)

    assert tuple(sources) == EXPECTED_SOURCE_IDS
    assert len(sources) == 27
    assert sources["official_fpl"]["acquisition_kind"] == "rest_json"
    assert sources["understat"]["acquisition_kind"] == "html_scrape"
    assert sources["understat"]["content_hash_dedup"] is True
    assert sources["api_football"]["daily_request_budget"] == 100
    assert sources["api_football"]["poll_interval_minutes"] == 1440
    assert sources["api_football"]["poll_interval_minutes_deadline_window"] == 360
    assert sources["api_football"]["verification_required"] is True
    assert sources["api_football"]["verification_status"] == "PENDING"


def test_non_configured_sources_preserve_legacy_every_cycle_behavior():
    now = datetime(2026, 9, 4, 5, 0, tzinfo=timezone.utc)
    source = {"id": "example", "requests": [{"id": "one"}]}
    previous = {"checked_at": (now - timedelta(minutes=2)).isoformat()}

    decision = poll_decision(source, previous, now=now)

    assert decision["due"] is True
    assert decision["poll_interval_minutes"] is None


def test_poll_interval_skips_until_source_is_due():
    now = datetime(2026, 9, 4, 5, 0, tzinfo=timezone.utc)
    source = {
        "id": "example",
        "poll_interval_minutes": 60,
        "requests": [{"id": "one"}],
    }
    previous = {
        "polling": {"last_polled_at": (now - timedelta(minutes=30)).isoformat()},
    }

    assert poll_decision(source, previous, now=now)["reason"] == "NOT_DUE"
    previous["polling"]["last_polled_at"] = (now - timedelta(minutes=61)).isoformat()
    assert poll_decision(source, previous, now=now)["reason"] == "DUE"


def test_deadline_window_uses_tighter_configured_interval():
    source = {
        "poll_interval_minutes": 1440,
        "poll_interval_minutes_deadline_window": 360,
    }

    assert effective_poll_interval_minutes(source, deadline_window=False) == 1440
    assert effective_poll_interval_minutes(source, deadline_window=True) == 360


def test_deadline_window_detects_upcoming_official_fpl_deadline():
    now = datetime(2026, 9, 4, 5, 0, tzinfo=timezone.utc)
    previous = {
        "official_fpl": {
            "data": {
                "bootstrap": {
                    "json": {
                        "events": [
                            {"deadline_time": (now + timedelta(hours=30)).isoformat()}
                        ]
                    }
                }
            }
        }
    }

    assert deadline_window_active(previous, hours=48, now=now) is True
    assert deadline_window_active(previous, hours=24, now=now) is False


def test_verification_gate_blocks_scheduled_poll_until_verified():
    now = datetime(2026, 9, 4, 5, 0, tzinfo=timezone.utc)
    source = {
        "id": "api_football",
        "verification_required": True,
        "verification_status": "PENDING",
        "poll_interval_minutes": 1440,
        "requests": [{"id": "fixtures"}],
    }

    decision = poll_decision(source, None, now=now)
    assert decision["due"] is False
    assert decision["reason"] == "VERIFICATION_REQUIRED"

    source["verification_status"] = "VERIFIED"
    assert poll_decision(source, None, now=now)["due"] is True


def test_daily_budget_reserves_worst_case_retry_attempts_before_poll():
    now = datetime(2026, 9, 4, 5, 0, tzinfo=timezone.utc)
    source = {
        "id": "budgeted",
        "daily_request_budget": 3,
        "requests": [{"id": "one"}],
    }
    previous = {
        "budget": {
            "date_wib": "2026-09-04",
            "requests_used": 2,
        }
    }

    decision = poll_decision(
        source,
        previous,
        now=now,
        max_attempts_per_request=2,
    )

    assert decision["due"] is False
    assert decision["reason"] == "BUDGET_EXHAUSTED"
    assert decision["budget"]["reserved_requests_next_poll"] == 2
    assert decision["budget"]["remaining"] == 1


def test_daily_budget_is_counted_from_real_provider_attempts():
    now = datetime(2026, 9, 4, 5, 0, tzinfo=timezone.utc)
    source = {
        "id": "budgeted",
        "daily_request_budget": 3,
        "requests": [{"id": "one"}],
    }
    decision = poll_decision(source, None, now=now)
    payload = {
        "checked_at": now.isoformat(),
        "attempts": [{"request_id": "one", "attempt_count": 2}],
        "governance": {},
    }

    result = attach_poll_result(source, payload, None, decision)

    assert result["budget"]["requests_used"] == 2
    assert result["budget"]["remaining"] == 1
    assert result["polling"]["provider_calls_this_poll"] == 2
