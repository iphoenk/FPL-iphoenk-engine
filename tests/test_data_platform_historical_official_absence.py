from __future__ import annotations

import hashlib
import json

from src.runtime_v6.historical_availability import (
    BEFORE_FIRST_OFFICIAL_ENTRY_HISTORY_GW,
    OFFICIAL_GW_RECORD_NOT_AVAILABLE,
    captain_multiplier_consistent,
    classify_completed_gw_official_absence,
)
from src.runtime_v6.historical_backfill import HistoricalBackfillService


def result(endpoint: str, payload=None, status="LIVE", code=200):
    return {
        "status": status,
        "endpoint_class": endpoint,
        "checked_at": "2026-09-06T00:00:00+00:00",
        "http_status": code,
        "payload_digest": hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        if status == "LIVE"
        else None,
        "payload": payload if status == "LIVE" else None,
        "attempts": 1,
        "duration_ms": 1,
        "error": None,
    }


def picks_payload(offset: int = 0, *, captain_multiplier: int = 2, vice_multiplier: int = 1):
    elements = list(range(1 + offset, 16 + offset))
    rows = []
    for position, element_id in enumerate(elements, start=1):
        multiplier = 0 if position > 11 else 1
        if position == 1:
            multiplier = captain_multiplier
        elif position == 2:
            multiplier = vice_multiplier
        rows.append(
            {
                "element": element_id,
                "position": position,
                "multiplier": multiplier,
                "is_captain": position == 1,
                "is_vice_captain": position == 2,
            }
        )
    return {"active_chip": None, "picks": rows}


def test_designated_captain_multiplier_zero_is_valid_official_no_show_fact():
    picks = [
        {"captain": True, "vice_captain": False, "multiplier": 0},
        {"captain": False, "vice_captain": True, "multiplier": 2},
    ]
    assert captain_multiplier_consistent(picks) is True
    assert captain_multiplier_consistent([{**picks[0], "multiplier": 1}, picks[1]]) is False


def test_official_absence_requires_404_and_later_first_history_row():
    pick = {"status": "UNAVAILABLE", "http_status": 404}
    history = result(
        "entry_history",
        {"current": [{"event": 2, "points": 40, "total_points": 40}], "chips": []},
    )
    classified = classify_completed_gw_official_absence(
        pick_record=pick,
        history_result=history,
        gw=1,
        completed=True,
    )
    assert classified is not None
    assert classified["official_availability_status"] == OFFICIAL_GW_RECORD_NOT_AVAILABLE
    assert classified["official_exclusion_reason"] == BEFORE_FIRST_OFFICIAL_ENTRY_HISTORY_GW
    assert classified["first_official_entry_history_gw"] == 2
    assert classified["historical_league_membership_inferred"] is False

    assert classify_completed_gw_official_absence(
        pick_record={"status": "UNAVAILABLE", "http_status": 503},
        history_result=history,
        gw=1,
        completed=True,
    ) is None
    assert classify_completed_gw_official_absence(
        pick_record=pick,
        history_result=result("entry_history", status="FAILED", code=503),
        gw=1,
        completed=True,
    ) is None


class LateEntryClient:
    def __init__(self):
        self.calls: list[str] = []

    @property
    def secret_values(self):
        return ()

    def bootstrap(self):
        self.calls.append("bootstrap")
        return result(
            "bootstrap_static",
            {
                "events": [
                    {"id": 1, "finished": True, "is_current": False},
                    {"id": 2, "finished": True, "is_current": True},
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
                        "element_type": 1
                        if element_id <= 2
                        else (2 if element_id <= 7 else (3 if element_id <= 12 else 4)),
                    }
                    for element_id in range(1, 25)
                ],
            },
        )

    def entry(self, entry_id):
        self.calls.append(f"entry:{entry_id}")
        return result(
            "entry",
            {
                "id": entry_id,
                "leagues": {
                    "classic": [
                        {
                            "id": 9911,
                            "name": "Priority League",
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
        return result(
            "classic_standings",
            {
                "standings": {
                    "results": [
                        {
                            "entry": 100,
                            "entry_name": "A",
                            "player_name": "A",
                            "rank": 1,
                            "last_rank": 1,
                            "event_total": 50,
                            "total": 100,
                        },
                        {
                            "entry": 200,
                            "entry_name": "B",
                            "player_name": "B",
                            "rank": 2,
                            "last_rank": 2,
                            "event_total": 40,
                            "total": 40,
                        },
                    ],
                    "has_next": False,
                }
            },
        )

    def h2h_standings(self, league_id, page):
        raise AssertionError("classic league only")

    def submitted_picks(self, entry_id, gw):
        self.calls.append(f"picks:{entry_id}:{gw}")
        if entry_id == 200 and gw == 1:
            return result("submitted_picks", status="NOT_FOUND", code=404)
        captain_multiplier = 0 if entry_id == 100 and gw == 1 else 2
        vice_multiplier = 2 if captain_multiplier == 0 else 1
        return result(
            "submitted_picks",
            picks_payload(
                (entry_id + gw) % 3,
                captain_multiplier=captain_multiplier,
                vice_multiplier=vice_multiplier,
            ),
        )

    def entry_history(self, entry_id):
        self.calls.append(f"history:{entry_id}")
        if entry_id == 200:
            current = [
                {"event": 2, "points": 40, "total_points": 40, "overall_rank": 5000}
            ]
        else:
            current = [
                {"event": 1, "points": 50, "total_points": 50, "overall_rank": 1000},
                {"event": 2, "points": 50, "total_points": 100, "overall_rank": 900},
            ]
        return result("entry_history", {"current": current, "chips": []})

    def event_live(self, gw):
        self.calls.append(f"live:{gw}")
        return result(
            "event_live",
            {
                "elements": [
                    {"id": element_id, "stats": {"total_points": element_id % 5}}
                    for element_id in range(1, 25)
                ]
            },
        )

    def telemetry(self):
        return {
            "request_count": len(self.calls),
            "failed_requests": sum(1 for call in self.calls if call == "picks:200:1"),
            "maximum_concurrency_used": 1,
        }


def config():
    return {
        "schema_version": 1,
        "season": "2026-2027",
        "entry_id": 100,
        "priority_leagues": [
            {
                "name": "Priority League",
                "kind": "classic",
                "full_submitted_picks": True,
            }
        ],
        "personal_team_enabled": True,
        "mini_league_enabled": True,
        "submitted_picks_cache_enabled": True,
        "prefetch_lead_minutes": 30,
        "prefetch_max_age_minutes": 35,
        "rival_picks_max_workers": 4,
    }


def test_completed_gw_can_be_green_with_strict_official_exclusion_and_raw_coverage_preserved(
    tmp_path,
):
    manifest = HistoricalBackfillService(
        config=config(), output_root=tmp_path, client=LateEntryClient()
    ).run(gw_from=1, gw_to=2)
    assert manifest["overall_status"] == "GREEN"
    gw1 = manifest["gw_health"][0]
    assert gw1["expected_manager_count"] == 2
    assert gw1["eligible_manager_count"] == 1
    assert gw1["officially_excluded_manager_count"] == 1
    assert gw1["officially_excluded_entry_ids"] == [200]
    assert gw1["coverage_percent"] == 50.0
    assert gw1["eligible_coverage_percent"] == 100.0
    assert gw1["failed_entry_ids"] == []
    assert gw1["complete"] is True
    assert gw1["complete_with_explicit_official_exclusions"] is True

    root = tmp_path / "mini_leagues" / str(manifest["league_id"]) / "history"
    picks = json.loads((root / "gw_1" / "manager_picks.json").read_text())
    excluded = picks["entries"]["200"]
    assert excluded["status"] == "UNAVAILABLE"
    assert excluded["official_exclusion"] is True
    assert excluded["official_exclusion_reason"] == BEFORE_FIRST_OFFICIAL_ENTRY_HISTORY_GW
    assert excluded["historical_membership_confirmed"] is None

    reconciliation = json.loads((root / "gw_1" / "entry_history.json").read_text())
    ours = next(row for row in reconciliation["reconciliations"] if row["entry_id"] == 100)
    assert ours["checks"]["captain_multiplier_consistent"] is True
    assert "reconstructed_current_cohort_rank" not in json.dumps(reconciliation)


def test_second_run_reuses_cached_strict_official_absence_without_refetching_missing_gw(
    tmp_path,
):
    first = HistoricalBackfillService(
        config=config(), output_root=tmp_path, client=LateEntryClient()
    ).run(gw_from=1, gw_to=2)
    assert first["overall_status"] == "GREEN"

    second_client = LateEntryClient()
    second = HistoricalBackfillService(
        config=config(), output_root=tmp_path, client=second_client
    ).run(gw_from=1, gw_to=2)
    assert second["overall_status"] == "GREEN"
    assert second["cache"]["cache_hits"] == 4
    assert second["cache"]["cache_misses"] == 0
    assert not any(call.startswith("picks:") for call in second_client.calls)
    assert second["gw_health"][0]["officially_excluded_entry_ids"] == [200]
