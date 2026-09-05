from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.runtime_v6.historical_backfill import (
    HistoricalBackfillError,
    HistoricalBackfillService,
    LIVE_CURRENT,
    REUSED_CURRENT,
    acquire_historical_picks,
    validate_gw_range,
)
from src.runtime_v6.prefetch_contract import write_json


def result(endpoint: str, payload=None, status="LIVE", code=200):
    return {
        "status": status,
        "endpoint_class": endpoint,
        "checked_at": "2026-09-05T14:00:00+00:00",
        "http_status": code,
        "payload_digest": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() if status == "LIVE" else None,
        "payload": payload if status == "LIVE" else None,
        "attempts": 1,
        "duration_ms": 1,
        "error": None,
    }


def current_bootstrap(*, deadline="2026-09-05T12:00:00Z"):
    return {
        "events": [
            {"id": 1, "finished": True, "is_current": False, "deadline_time": "2026-08-22T12:00:00Z"},
            {"id": 2, "finished": True, "is_current": False, "deadline_time": "2026-08-29T12:00:00Z"},
            {"id": 3, "finished": False, "is_current": True, "deadline_time": deadline},
            {"id": 4, "finished": False, "is_current": False, "is_next": True, "deadline_time": "2026-09-12T12:00:00Z"},
        ],
        "teams": [{"id": 1, "name": "Alpha", "short_name": "ALP"}],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "elements": [
            {
                "id": element_id,
                "web_name": f"P{element_id}",
                "team": 1,
                "element_type": 1 if element_id <= 2 else (2 if element_id <= 7 else (3 if element_id <= 12 else 4)),
            }
            for element_id in range(1, 21)
        ],
    }


def submitted_payload(entry_id: int, gw: int):
    shift = (entry_id + gw) % 3
    elements = list(range(1 + shift, 16 + shift))
    return {
        "active_chip": None,
        "picks": [
            {
                "element": element_id,
                "position": position,
                "multiplier": 2 if position == 1 else (0 if position > 11 else 1),
                "is_captain": position == 1,
                "is_vice_captain": position == 2,
            }
            for position, element_id in enumerate(elements, start=1)
        ],
    }


class CurrentGWClient:
    def __init__(self):
        self.calls: list[str] = []

    @property
    def secret_values(self):
        return ()

    def bootstrap(self):
        self.calls.append("bootstrap")
        return result("bootstrap_static", current_bootstrap())

    def entry(self, entry_id):
        self.calls.append(f"entry:{entry_id}")
        return result(
            "entry",
            {
                "id": entry_id,
                "leagues": {
                    "classic": [
                        {
                            "id": 9477,
                            "name": "ICON+ League",
                            "league_type": "x",
                            "rank": 1,
                            "last_rank": 1,
                            "entry_can_leave": True,
                        }
                    ],
                    "h2h": [],
                },
            },
        )

    def classic_standings(self, league_id, page):
        self.calls.append(f"standings:{league_id}:{page}")
        rows = [
            {"entry": 3462711, "entry_name": "Ours", "player_name": "Us", "rank": 1, "last_rank": 1, "event_total": 50, "total": 150},
            {"entry": 4000001, "entry_name": "Rival", "player_name": "Rival", "rank": 2, "last_rank": 2, "event_total": 48, "total": 148},
        ]
        return result("classic_standings", {"standings": {"results": rows, "has_next": False}})

    def h2h_standings(self, league_id, page):
        raise AssertionError("classic league must not call h2h")

    def submitted_picks(self, entry_id, gw):
        self.calls.append(f"picks:{entry_id}:{gw}")
        return result("submitted_picks", submitted_payload(entry_id, gw))

    def entry_history(self, entry_id):
        self.calls.append(f"history:{entry_id}")
        # Deliberately omit current GW3: Official may not expose the row until later.
        return result(
            "entry_history",
            {
                "current": [
                    {"event": 1, "points": 50, "total_points": 50, "overall_rank": 1000},
                    {"event": 2, "points": 48, "total_points": 98, "overall_rank": 900},
                ],
                "chips": [],
            },
        )

    def event_live(self, gw):
        self.calls.append(f"live:{gw}")
        return result(
            "event_live",
            {"elements": [{"id": element_id, "stats": {"total_points": element_id % 6}} for element_id in range(1, 21)]},
        )

    def telemetry(self):
        return {"request_count": len(self.calls), "failed_requests": 0, "maximum_concurrency_used": 1}


def config():
    return {
        "schema_version": 1,
        "season": "2026-2027",
        "entry_id": 3462711,
        "priority_leagues": [{"name": "ICON+ League", "kind": "classic", "full_submitted_picks": True}],
        "personal_team_enabled": True,
        "mini_league_enabled": True,
        "submitted_picks_cache_enabled": True,
        "prefetch_lead_minutes": 30,
        "prefetch_max_age_minutes": 35,
        "rival_picks_max_workers": 4,
    }


def test_current_post_deadline_is_eligible_but_pre_deadline_and_future_are_not():
    after = datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc)
    assert validate_gw_range(1, 3, current_bootstrap(), now=after) == (1, 3)
    with pytest.raises(HistoricalBackfillError):
        validate_gw_range(1, 4, current_bootstrap(), now=after)

    before = datetime(2026, 9, 5, 11, 59, tzinfo=timezone.utc)
    with pytest.raises(HistoricalBackfillError):
        validate_gw_range(1, 3, current_bootstrap(), now=before)


def test_current_submitted_picks_cache_reuse_has_explicit_current_origin(tmp_path: Path):
    path = tmp_path / "manager_picks.json"
    first_client = CurrentGWClient()
    first, first_metrics = acquire_historical_picks(
        first_client,
        previous_path=path,
        season="2026-2027",
        league_id=9477,
        gw=3,
        manager_ids=[3462711],
        workers=2,
        force=False,
        cache_enabled=True,
        completed=False,
    )
    assert first_metrics["cache_misses"] == 1
    assert first["entries"]["3462711"]["origin"] == LIVE_CURRENT
    assert first["immutable_completed_gw_facts"] is False
    write_json(path, first)

    second_client = CurrentGWClient()
    second, second_metrics = acquire_historical_picks(
        second_client,
        previous_path=path,
        season="2026-2027",
        league_id=9477,
        gw=3,
        manager_ids=[3462711],
        workers=2,
        force=False,
        cache_enabled=True,
        completed=False,
    )
    assert second_metrics == {"cache_hits": 1, "cache_misses": 0, "maximum_concurrency_used": 0, "retry_count": 0}
    assert second["entries"]["3462711"]["origin"] == REUSED_CURRENT
    assert not any(call.startswith("picks:") for call in second_client.calls)


def test_service_current_gw_is_green_with_explicit_provisional_semantics_and_refreshes_history(tmp_path: Path):
    first_client = CurrentGWClient()
    first = HistoricalBackfillService(config=config(), output_root=tmp_path, client=first_client).run(gw_from=1, gw_to=3)
    assert first["overall_status"] == "GREEN"
    assert first["completed_requested_gw_count"] == 2
    assert first["provisional_current_gw_count"] == 1

    gw3 = first["gw_health"][2]
    assert gw3["gw_semantics"] == "CURRENT_GW_POST_DEADLINE"
    assert gw3["entry_history_required_for_complete"] is False
    assert gw3["entry_history_missing_count"] == 2
    assert gw3["officially_unavailable_or_optional_entry_ids"] == [3462711, 4000001]
    assert gw3["final_points_available"] is False
    assert gw3["live_points_available"] is True
    assert gw3["complete"] is True

    exposure = json.loads((tmp_path / "mini_leagues" / "9477" / "history" / "gw_3" / "exposure.json").read_text())
    assert exposure["gw_semantics"] == "CURRENT_GW_POST_DEADLINE"
    assert all(row["final_points"] is None for row in exposure["players"])
    assert all(row["points_semantics"] == "LIVE_CURRENT_GW" for row in exposure["players"])

    second_client = CurrentGWClient()
    second = HistoricalBackfillService(config=config(), output_root=tmp_path, client=second_client).run(gw_from=1, gw_to=3)
    assert second["overall_status"] == "GREEN"
    assert second["cache"]["cache_hits"] == 6
    assert second["cache"]["cache_misses"] == 0
    assert second["cache"]["history_cache_hits"] == 0
    assert second["cache"]["history_cache_misses"] == 2
    assert second["cache"]["current_gw_entry_history_cache_reused"] is False
    assert not any(call.startswith("picks:") for call in second_client.calls)
    assert sorted(call for call in second_client.calls if call.startswith("history:")) == ["history:3462711", "history:4000001"]
