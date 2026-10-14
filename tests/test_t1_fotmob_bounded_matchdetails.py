from __future__ import annotations

from copy import deepcopy

from src.runtime_v6.domains.acquisition import adapters
from src.runtime_v6.domains.acquisition.fotmob_backfill import (
    collect_fotmob,
    finalized_match_ids,
)


def _match(native, gw=6, finished=True, home=8455):
    return {
        "id": native, "round": str(gw),
        "home": {"id": home}, "away": {"id": 8678},
        "status": {"finished": finished, "cancelled": False},
    }


def _source():
    return {
        "id": "fotmob", "adapter": "http", "critical": False,
        "match_details_history": {
            "enabled": True,
            "historical_gws": [1, 2, 3, 4, 5, 6],
            "priority_native_team_ids": [8455],
            "max_backfill_requests_per_cycle": 2,
            "daily_request_budget": 4,
            "max_body_bytes": 200000,
            "endpoint_template": "https://www.fotmob.com/api/matchDetails?matchId={match_id}",
        },
    }


def _base():
    return {
        "health": "GREEN", "checked_at": "2026-10-15T00:00:00Z",
        "data": {"league": {
            "status": "AVAILABLE", "sha256": "f" * 64,
            "json": {"details": {"id": 47, "selectedSeason": "2026/2027"},
                     "matches": [_match(102, 1, home=9825), _match(101),
                                 _match(103, 7), _match(104, 3, finished=False)]},
        }},
        "coverage": {}, "changed": False,
    }


class _Client:
    retry_attempts = 2

    def __init__(self):
        self.requests = []

    def fetch(self, source, request, previous=None):
        self.requests.append(request["id"])
        native = int(request["id"].removeprefix("match_details_"))
        return {
            "request_id": request["id"], "status": "AVAILABLE",
            "json": {"general": {"matchId": native},
                     "content": {"lineup": {"homeTeam": {}, "awayTeam": {}}}},
            "sha256": f"{native:064x}",
            "checked_at": "2026-10-15T00:20:00Z",
        }


def test_t1_fotmob_candidate_selection_requires_finality_and_prioritizes_chelsea():
    league = _base()["data"]["league"]["json"]
    cfg = _source()["match_details_history"]
    assert finalized_match_ids(league, cfg) == [101, 102]
    # Three repeated provider fixture IDs must never be re-admitted.
    league["matches"].extend([_match(101), _match(101)])
    assert finalized_match_ids(league, cfg) == [102]


def test_t1_fotmob_backfill_uses_original_v6_poll_and_keeps_immutable_source_sha(monkeypatch):
    client = _Client()
    source = _source()
    monkeypatch.setattr(adapters, "collect_http", lambda *args: deepcopy(_base()))
    first = adapters.collect_source(source, client)
    assert client.requests == ["match_details_101", "match_details_102"] or sorted(client.requests) == [
        "match_details_101", "match_details_102",
    ]
    assert first["match_details_history"]["status"] == "RETRIEVAL_COMPLETE"
    assert first["match_details_history"]["historical_predeadline_asof_proven"] is False
    assert first["match_details_history"]["identity_and_tactical_admission"] == "NOT_ASSERTED"
    assert first["data"]["match_details_101"]["sha256"] == f"{101:064x}"
    assert first["data"]["match_details_102"]["sha256"] == f"{102:064x}"
    next_run = collect_fotmob(source, client, first)
    assert len(client.requests) == 2
    assert next_run["match_details_history"]["cached_finalized_match_details"] == 2
    assert next_run["data"]["match_details_101"]["data_origin"] == "FINALIZED_MATCH_DETAILS_CACHE"
    assert next_run["data"]["match_details_101"]["checked_at"] == "2026-10-15T00:20:00Z"
    assert next_run["match_details_history"]["new_scheduler_created"] is False


def test_t1_fotmob_budget_and_provider_failure_stay_partial(monkeypatch):
    source = _source()
    monkeypatch.setattr(adapters, "collect_http", lambda *args: deepcopy(_base()))
    class Unavailable(_Client):
        def fetch(self, source, request, previous=None):
            self.requests.append(request["id"])
            return {"request_id": request["id"], "status": "UNAVAILABLE", "http_status": 403}
    client = Unavailable()
    first = collect_fotmob(source, client)
    assert first["health"] == "GREEN"  # League still works, noncritical enrichment is isolated.
    assert first["match_details_history"]["status"] == "PARTIAL"
    assert first["match_details_history"]["remaining_without_usable_details"] == 2
    assert first["match_details_history"]["reserved_attempts_today"] == 4
    assert first["match_details_history"]["attempt_failures"]
    second = collect_fotmob(source, client, first)
    assert second["match_details_history"]["attempted_this_cycle"] == 0
    assert len(client.requests) == 2
