from __future__ import annotations

from pathlib import Path

from src.sources import understat


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[dict] = []

    def get(self, url, *, timeout, headers):
        self.calls.append({"url": url, "timeout": timeout, "headers": dict(headers)})
        return _Response(self.payload)


def _policy() -> dict:
    return {
        "league": "EPL",
        "season_start_year": 2026,
        "network": {
            "base_url": "https://understat.com",
            "endpoint_template": "getLeagueData/{league}/{season}",
            "transport_revision": "TEST_XHR_REVISION",
            "timeout_seconds": 5,
            "max_attempts": 3,
            "max_requests_per_refresh": 2,
            "backoff_seconds": [0, 0],
            "minimum_request_interval_seconds": 0,
            "user_agent": "test-agent",
        },
        "cache": {
            "raw_ttl_minutes": 360,
            "fresh_minutes": 360,
            "stale_after_minutes": 2880,
            "retain_last_known_good": True,
        },
    }


def _ajax_payload() -> dict:
    return {
        "teams": {
            "1": {
                "id": "1",
                "title": "Arsenal",
                "history": [],
            }
        },
        "players": [
            {
                "id": "10",
                "player_name": "Alpha",
                "team_title": "Arsenal",
            }
        ],
        "dates": [
            {
                "id": "100",
                "datetime": "2026-08-30 16:30:00",
                "isResult": True,
                "goals": {"h": "2", "a": "1"},
            }
        ],
    }


def test_ajax_payload_is_normalized_without_changing_downstream_raw_contract():
    normalized = understat._normalize_ajax_payload(_ajax_payload())
    assert set(normalized) == {"teamsData", "playersData", "datesData"}
    assert normalized["teamsData"]["1"]["title"] == "Arsenal"
    assert normalized["playersData"][0]["player_name"] == "Alpha"
    assert normalized["datesData"][0]["id"] == "100"


def test_xhr_request_uses_required_header_and_single_batched_endpoint():
    session = _Session(_ajax_payload())
    payload, calls = understat._request_json(
        "https://understat.com/getLeagueData/EPL/2026",
        _policy(),
        session=session,
    )
    assert calls == 1
    assert payload["players"][0]["id"] == "10"
    assert len(session.calls) == 1
    request = session.calls[0]
    assert request["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert request["headers"]["User-Agent"] == "test-agent"
    assert request["url"].endswith("/getLeagueData/EPL/2026")


def test_sync_persists_current_transport_revision_and_available_evidence(monkeypatch, tmp_path: Path):
    cache = tmp_path / "stats" / "understat_epl_2026.json"
    monkeypatch.setattr(understat, "CACHE", cache)
    monkeypatch.setattr(understat, "_policy", _policy)
    session = _Session(_ajax_payload())

    result = understat.sync(force=True, session=session)

    assert result["source_availability"] == "AVAILABLE"
    assert result["freshness"] == "FRESH"
    assert result["schema_valid"] is True
    assert result["transport_revision"] == _policy()["network"]["transport_revision"]
    assert result["refresh_transport_revision"] == _policy()["network"]["transport_revision"]
    assert result["provenance"]["transport"] == "HTTPS_JSON_XHR"
    assert result["request_strategy"] == "single_league_xhr_snapshot_no_per_player_network_calls"
    assert result["latest_fixture_represented"]["id"] == "100"
    assert cache.exists()


def test_same_revision_fresh_cache_is_reused_without_network(monkeypatch, tmp_path: Path):
    cache = tmp_path / "stats" / "understat_epl_2026.json"
    monkeypatch.setattr(understat, "CACHE", cache)
    monkeypatch.setattr(understat, "_policy", _policy)
    first_session = _Session(_ajax_payload())
    first = understat.sync(force=True, session=first_session)
    assert first["source_availability"] == "AVAILABLE"

    second_session = _Session({"unexpected": True})
    second = understat.sync(force=False, session=second_session)

    assert second["runtime_reused"] is True
    assert second["source_availability"] == "AVAILABLE"
    assert second_session.calls == []
