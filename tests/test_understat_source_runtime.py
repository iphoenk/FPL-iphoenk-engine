from __future__ import annotations

import json

import requests

from src.sources import understat


def _policy() -> dict:
    return {
        "league": "EPL",
        "season_start_year": 2026,
        "network": {
            "base_url": "https://understat.com",
            "max_attempts": 4,
            "max_requests_per_refresh": 2,
            "timeout_seconds": 1,
            "backoff_seconds": [0, 0, 0],
            "minimum_request_interval_seconds": 0,
            "user_agent": "test",
        },
        "cache": {
            "raw_ttl_minutes": 60,
            "failure_retry_minutes": 15,
            "fresh_minutes": 60,
            "stale_after_minutes": 120,
            "retain_last_known_good": True,
        },
    }


class _Response:
    def __init__(self, text: str = "", error: Exception | None = None):
        self.text = text
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        return self.responses.pop(0)


def _embedded_html() -> str:
    teams = {"1": {"id": "1", "title": "Arsenal", "history": []}}
    players = [{"id": "10", "player_name": "Saka"}]
    dates = [
        {"id": "past", "datetime": "2026-08-30 12:00:00", "isResult": True, "goals": {"h": "1", "a": "0"}},
        {"id": "future", "datetime": "2026-09-20 12:00:00", "isResult": False, "goals": {"h": None, "a": None}},
    ]
    return "".join(
        [
            "<script>",
            "var teamsData = JSON.parse('" + json.dumps(teams) + "');",
            "var playersData = JSON.parse('" + json.dumps(players) + "');",
            "var datesData = JSON.parse('" + json.dumps(dates) + "');",
            "</script>",
        ]
    )


def test_latest_completed_fixture_ignores_future_schedule():
    embedded = understat.parse_embedded_json(_embedded_html())
    latest = understat.latest_completed_fixture(embedded)
    assert latest["id"] == "past"
    assert latest["datetime"] == "2026-08-30 12:00:00"


def test_request_budget_caps_retries_even_when_max_attempts_is_larger():
    failure = requests.HTTPError("boom")
    session = _Session([_Response(error=failure), _Response(error=failure), _Response(text="must-not-run")])
    try:
        understat._request("https://example.invalid", _policy(), session=session)
    except RuntimeError as exc:
        assert "2 bounded attempts" in str(exc)
    else:
        raise AssertionError("expected bounded request failure")
    assert session.calls == 2


def test_request_returns_actual_attempt_count_after_retry():
    failure = requests.ConnectionError("temporary")
    session = _Session([_Response(error=failure), _Response(text="ok")])
    text, calls = understat._request("https://example.invalid", _policy(), session=session)
    assert text == "ok"
    assert calls == 2
    assert session.calls == 2


def test_failed_refresh_is_persisted_and_recent_failure_suppresses_retry(monkeypatch, tmp_path):
    cache = tmp_path / "understat.json"
    monkeypatch.setattr(understat, "CACHE", cache)
    monkeypatch.setattr(understat, "_policy", _policy)

    failure = requests.ConnectionError("provider unavailable")
    first_session = _Session([_Response(error=failure), _Response(error=failure)])
    first = understat.sync(session=first_session)

    assert first_session.calls == 2
    assert first["source_availability"] == "UNAVAILABLE"
    assert first["schema_valid"] is False
    assert cache.exists()
    persisted = json.loads(cache.read_text())
    assert persisted["source_availability"] == "UNAVAILABLE"
    assert persisted.get("refresh_attempted_at")

    second_session = _Session([_Response(text="must-not-run")])
    second = understat.sync(session=second_session)

    assert second_session.calls == 0
    assert second["source_availability"] == "UNAVAILABLE"
    assert second["runtime_reused"] is True
    assert second["retry_suppressed"] is True
    assert second["freshness"] == "UNKNOWN"
    assert second["failure_retry_minutes"] == 15.0


def test_force_refresh_bypasses_recent_failure_cooldown(monkeypatch, tmp_path):
    cache = tmp_path / "understat.json"
    monkeypatch.setattr(understat, "CACHE", cache)
    monkeypatch.setattr(understat, "_policy", _policy)

    failure = requests.ConnectionError("provider unavailable")
    failed_session = _Session([_Response(error=failure), _Response(error=failure)])
    understat.sync(session=failed_session)
    assert failed_session.calls == 2

    forced_session = _Session([_Response(text=_embedded_html())])
    refreshed = understat.sync(force=True, session=forced_session)

    assert forced_session.calls == 1
    assert refreshed["source_availability"] == "AVAILABLE"
    assert refreshed["schema_valid"] is True
    assert refreshed["runtime_reused"] is False
    assert refreshed["retry_suppressed"] is False
