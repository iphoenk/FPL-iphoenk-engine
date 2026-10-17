from __future__ import annotations

import requests

from src.runtime_v6.http_client import AcquisitionClient


def _response(url: str, status: int, body: str) -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result.url = url
    result.encoding = "utf-8"
    result.headers["Content-Type"] = "text/plain"
    result._content = body.encode("utf-8")
    result._content_consumed = True
    return result


def test_thesportsdb_free_api_maintenance_is_explicit_and_still_degraded(monkeypatch) -> None:
    url = "https://www.thesportsdb.com/api/v1/json/123/lookupleague.php"
    response = _response(url, 403, "Free API temporarily disabled while we rebuild the site")
    class Session:
        def get(self, *args, **kwargs):
            return response
    monkeypatch.setattr(AcquisitionClient, "_session", lambda self: Session())

    result = AcquisitionClient({"retry_attempts": 1}).fetch(
        {"id": "thesportsdb_v1", "critical": False},
        {"id": "league", "url": url, "expect": "json"},
    )

    assert result["http_status"] == 403
    assert result["status"] == "UNAVAILABLE"
    assert result["health"] == "AMBER"
    assert result["json"] is None
    assert result["validation_classification"] == "UPSTREAM_PROVIDER_MAINTENANCE"
    assert result["error"] == "provider_free_api_temporarily_disabled"


def test_other_provider_403_remains_transport_failure_not_maintenance(monkeypatch) -> None:
    url = "https://example.invalid/fpl"
    response = _response(url, 403, "Free API temporarily disabled while we rebuild the site")
    class Session:
        def get(self, *args, **kwargs):
            return response
    monkeypatch.setattr(AcquisitionClient, "_session", lambda self: Session())

    result = AcquisitionClient({"retry_attempts": 1}).fetch(
        {"id": "official_fpl", "critical": True},
        {"id": "bootstrap", "url": url, "expect": "json"},
    )
    assert result["health"] == "RED"
    assert result["validation_classification"] == "TRANSPORT_FAILURE"
    assert result["error"] == "http_403"
