from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from src.runtime_v6.adapters import collect_http
from src.runtime_v6.http_client import AcquisitionClient
from src.runtime_v6.source_native import build_source_native_datasets


class _Response:
    def __init__(self, payload: dict):
        raw = json.dumps(payload).encode("utf-8")
        self._raw = raw
        self.status_code = 200
        self.url = "https://understat.com/main/getPlayersStats/"
        self.headers = {
            "content-type": "application/json",
            "content-length": str(len(raw)),
        }
        self.encoding = "utf-8"
        self.closed = False

    def iter_content(self, chunk_size: int):
        yield self._raw

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, response: _Response):
        self.response = response
        self.post_calls: list[dict] = []
        self.get_calls: list[dict] = []

    def post(self, url: str, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        return self.response

    def get(self, url: str, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        return self.response


class _ConcurrencyClient:
    request_workers = 4
    conditional_revalidation = True

    def __init__(self):
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def fetch(self, source, request_cfg, previous=None):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.02)
            return {
                "request_id": request_cfg["id"],
                "status": "AVAILABLE",
                "health": "GREEN",
                "url": request_cfg["url"],
                "checked_at": "2026-09-13T09:00:00+00:00",
                "content_changed": True,
            }
        finally:
            with self._lock:
                self.active -= 1


def test_acquisition_client_supports_registry_driven_form_post_without_get_fallback():
    response = _Response(
        {
            "players": [
                {
                    "id": "700",
                    "player_name": "External Alpha",
                    "team_title": "Alpha FC",
                    "position": "M",
                    "games": "3",
                    "time": "250",
                    "goals": "2",
                    "assists": "1",
                    "shots": "8",
                    "key_passes": "5",
                    "xG": "1.75",
                    "xA": "0.84",
                    "npxG": "1.75",
                    "xGChain": "2.30",
                    "xGBuildup": "0.90",
                }
            ]
        }
    )
    session = _Session(response)
    client = AcquisitionClient(
        {
            "timeout_seconds": 10,
            "max_body_bytes": 100000,
            "retry_attempts": 1,
            "conditional_revalidation": True,
        }
    )
    client._local.session = session

    result = client.fetch(
        {"id": "understat", "critical": False},
        {
            "id": "players_api",
            "url": "https://understat.com/main/getPlayersStats/",
            "method": "POST",
            "form": {"league": "EPL", "season": "2026"},
            "headers": {
                "Referer": "https://understat.com/league/EPL/2026",
                "X-Requested-With": "XMLHttpRequest",
            },
            "expect": "json",
            "validation": {"required_json_paths": ["players"]},
        },
        previous={"etag": "must-not-be-sent-on-post"},
    )

    assert result["status"] == "AVAILABLE"
    assert result["health"] == "GREEN"
    assert result["json"]["players"][0]["id"] == "700"
    assert len(session.post_calls) == 1
    assert session.get_calls == []
    call = session.post_calls[0]
    assert call["data"] == {"league": "EPL", "season": "2026"}
    assert call["headers"]["X-Requested-With"] == "XMLHttpRequest"
    assert "If-None-Match" not in call["headers"]


def test_understat_normalizer_prefers_modern_players_api_and_keeps_identity_unmapped():
    results = {
        "understat": {
            "source_id": "understat",
            "health": "GREEN",
            "effective_state": "LIVE_CHANGED",
            "checked_at": "2026-09-06T17:00:00+00:00",
            "current_run_action": "FETCHED",
            "data": {
                "epl_2026": {
                    "sha256": "html-sha",
                    "body": "<html><title>2026/2027 xG</title></html>",
                },
                "players_api": {
                    "sha256": "api-sha",
                    "json": {
                        "players": [
                            {
                                "id": "700",
                                "player_name": "External Alpha",
                                "team_title": "Alpha FC",
                                "position": "M",
                                "games": "3",
                                "time": "250",
                                "goals": "2",
                                "assists": "1",
                                "shots": "8",
                                "key_passes": "5",
                                "xG": "1.75",
                                "xA": "0.84",
                                "npxG": "1.75",
                                "xGChain": "2.30",
                                "xGBuildup": "0.90",
                            }
                        ]
                    },
                },
            },
        }
    }
    identity_map = {"mappings": {}, "entity_bridges": {}}

    dataset = build_source_native_datasets(results, identity_map)["understat"]

    assert dataset["normalization_status"] == "NORMALIZED"
    assert dataset["semantic_class"] == "UPSTREAM_MODEL_SIGNAL"
    assert dataset["model_author"] == "UNDERSTAT"
    assert dataset["v6_computation"] == "NONE"
    assert dataset["record_count"] == 1
    player = dataset["record_groups"]["players"][0]
    assert player["source_native_id"] == 700
    assert player["xg"] == 1.75
    assert player["xa"] == 0.84
    assert player["official_element_id"] is None
    assert player["identity_status"] == "UNMAPPED"
    assert set(dataset["source_snapshot_ids"]) == {"api-sha", "html-sha"}


def test_understat_source_worker_override_serializes_requests():
    client = _ConcurrencyClient()
    source = {
        "id": "understat",
        "name": "Understat",
        "category": "advanced_performance",
        "adapter": "http",
        "critical": False,
        "request_workers": 1,
        "requests": [
            {"id": "epl_2026", "url": "https://understat.com/league/EPL/2026"},
            {"id": "players_api", "url": "https://understat.com/main/getPlayersStats/"},
        ],
    }

    result = collect_http(source, client)

    assert client.max_active == 1
    assert result["health"] == "GREEN"
    assert result["current_run_action"] == "FETCHED"
    assert result["coverage"]["successful_checks_this_cycle"] == 2


def test_understat_transport_override_is_temporary_and_preserves_last_good_cache_contract():
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "config" / "v6" / "source_overrides.json").read_text())

    override = payload["sources"]["understat"]
    lifecycle = payload["lifecycle"]["understat"]

    assert override["connect_timeout_seconds"] == 10
    assert override["request_workers"] == 1
    assert lifecycle["temporary"] is True
    assert lifecycle["review_by"] == "2026-09-20"
    assert "last-good-cache fallback" in lifecycle["reason"]
