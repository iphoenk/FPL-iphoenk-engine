from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.runtime_v6.historical_backfill import (
    COHORT_SEMANTICS,
    HistoricalBackfillError,
    HistoricalBackfillService,
    LIVE_HISTORICAL,
    REUSED_HISTORICAL,
    acquire_historical_picks,
    validate_gw_range,
)
from src.runtime_v6.prefetch_contract import resolve_scope, write_json


def result(endpoint: str, payload=None, status="LIVE", code=200, attempts=1):
    return {
        "status": status,
        "endpoint_class": endpoint,
        "checked_at": "2026-09-05T12:00:00+00:00",
        "http_status": code,
        "payload_digest": hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        if status == "LIVE"
        else None,
        "payload": payload if status == "LIVE" else None,
        "attempts": attempts,
        "duration_ms": 1,
        "error": None,
    }


def bootstrap_payload():
    return {
        "events": [
            {"id": 1, "finished": True, "is_current": False},
            {"id": 2, "finished": True, "is_current": False},
            {"id": 3, "finished": True, "is_current": True},
            {"id": 4, "finished": False, "is_next": True},
        ],
        "teams": [
            {"id": 1, "name": "Alpha", "short_name": "ALP"},
            {"id": 2, "name": "Beta", "short_name": "BET"},
        ],
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
                "team": 1 if element_id <= 10 else 2,
                "element_type": 1
                if element_id <= 2
                else (2 if element_id <= 7 else (3 if element_id <= 12 else 4)),
            }
            for element_id in range(1, 31)
        ],
    }


def entry_payload(league_id=9477):
    return {
        "id": 3462711,
        "leagues": {
            "classic": [
                {
                    "id": league_id,
                    "name": "ICON+ League",
                    "league_type": "x",
                    "rank": 4,
                    "last_rank": 5,
                    "entry_can_leave": True,
                },
                {"id": 314, "name": "Overall", "league_type": "s", "rank": 123},
            ],
            "h2h": [],
        },
    }


def manager_row(entry_id: int, rank: int):
    return {
        "entry": entry_id,
        "entry_name": f"Team {entry_id}",
        "player_name": f"Manager {entry_id}",
        "rank": rank,
        "last_rank": rank + 1,
        "event_total": 40 - rank,
        "total": 200 - rank,
    }


def submitted_payload(entry_id: int, gw: int, *, chip=None):
    shift = (entry_id + gw) % 5
    elements = list(range(1 + shift, 16 + shift))
    return {
        "active_chip": chip,
        "picks": [
            {
                "element": element_id,
                "position": position,
                "multiplier": (
                    3
                    if chip == "3xc" and position == 1
                    else (
                        2
                        if position == 1
                        else (
                            1
                            if chip == "bboost" and position > 11
                            else (0 if position > 11 else 1)
                        )
                    )
                ),
                "is_captain": position == 1,
                "is_vice_captain": position == 2,
            }
            for position, element_id in enumerate(elements, start=1)
        ],
    }


def history_payload(entry_id: int, chips=None):
    chips = chips or {}
    running = 0
    current = []
    for gw in (1, 2, 3):
        points = 40 + gw + entry_id % 7
        running += points
        current.append(
            {
                "event": gw,
                "points": points,
                "total_points": running,
                "overall_rank": 100000 - entry_id - gw,
            }
        )
    return {
        "current": current,
        "chips": [{"name": name, "event": gw} for gw, name in sorted(chips.items())],
    }


class FakeClient:
    def __init__(self, *, manager_count=3, fail_pick=None, league_id=9477, chips=None):
        self.manager_count = manager_count
        self.fail_pick = fail_pick
        self.league_id = league_id
        self.chips = chips or {}
        self.calls = []

    @property
    def secret_values(self):
        return ("sessionid=never-publish",)

    def bootstrap(self):
        self.calls.append("bootstrap")
        return result("bootstrap_static", bootstrap_payload())

    def entry(self, entry_id):
        self.calls.append(f"entry:{entry_id}")
        return result("entry", entry_payload(self.league_id))

    def classic_standings(self, league_id, page):
        self.calls.append(f"classic:{league_id}:{page}")
        ids = [3462711] + [
            4000000 + i for i in range(1, self.manager_count)
        ]
        return result(
            "classic_standings",
            {
                "standings": {
                    "results": [
                        manager_row(entry_id, rank)
                        for rank, entry_id in enumerate(ids, start=1)
                    ],
                    "has_next": False,
                }
            },
        )

    def h2h_standings(self, league_id, page):
        raise AssertionError("classic priority league must not use h2h endpoint")

    def submitted_picks(self, entry_id, gw):
        self.calls.append(f"picks:{entry_id}:{gw}")
        if self.fail_pick == (entry_id, gw):
            return result("submitted_picks", status="FAILED", code=503)
        return result(
            "submitted_picks",
            submitted_payload(
                entry_id,
                gw,
                chip=self.chips.get((entry_id, gw)),
            ),
        )

    def entry_history(self, entry_id):
        self.calls.append(f"history:{entry_id}")
        chip_events = {
            gw: name
            for (candidate, gw), name in self.chips.items()
            if candidate == entry_id
        }
        return result("entry_history", history_payload(entry_id, chip_events))

    def event_live(self, gw):
        self.calls.append(f"live:{gw}")
        return result(
            "event_live",
            {
                "elements": [
                    {"id": element_id, "stats": {"total_points": element_id % 10}}
                    for element_id in range(1, 31)
                ]
            },
        )

    def telemetry(self):
        return {
            "request_count": len(self.calls),
            "failed_requests": int(self.fail_pick is not None),
            "maximum_concurrency_used": 1,
        }


def config():
    return {
        "schema_version": 1,
        "season": "2026-2027",
        "entry_id": 3462711,
        "priority_leagues": [
            {
                "name": "ICON+ League",
                "kind": "classic",
                "full_submitted_picks": True,
            }
        ],
        "personal_team_enabled": True,
        "mini_league_enabled": True,
        "submitted_picks_cache_enabled": True,
        "prefetch_lead_minutes": 30,
        "prefetch_max_age_minutes": 35,
        "rival_picks_max_workers": 8,
    }


def test_historical_range_parsing_finished_only_and_reversed():
    bootstrap = bootstrap_payload()
    assert validate_gw_range(1, 3, bootstrap) == (1, 3)
    with pytest.raises(HistoricalBackfillError):
        validate_gw_range(3, 1, bootstrap)
    with pytest.raises(HistoricalBackfillError):
        validate_gw_range(0, 1, bootstrap)
    with pytest.raises(HistoricalBackfillError):
        validate_gw_range(1, 4, bootstrap)


def test_historical_picks_exact_15_and_immutable_cache(tmp_path):
    path = tmp_path / "manager_picks.json"
    client = FakeClient()
    first, metrics = acquire_historical_picks(
        client,
        previous_path=path,
        season="2026-2027",
        league_id=9477,
        gw=2,
        manager_ids=[1, 2],
        workers=4,
        force=False,
        cache_enabled=True,
    )
    assert metrics["cache_misses"] == 2
    for record in first["entries"].values():
        assert record["status"] == "AVAILABLE"
        assert len(record["picks"]) == 15
        assert len([p for p in record["picks"] if p["squad_position"] <= 11]) == 11
        assert [p["bench_order"] for p in record["picks"] if p["squad_position"] > 11] == [1, 2, 3, 4]
        assert sum(bool(p["captain"]) for p in record["picks"]) == 1
        assert sum(bool(p["vice_captain"]) for p in record["picks"]) == 1
        assert record["origin"] == LIVE_HISTORICAL

    write_json(path, first)
    second_client = FakeClient()
    second, second_metrics = acquire_historical_picks(
        second_client,
        previous_path=path,
        season="2026-2027",
        league_id=9477,
        gw=2,
        manager_ids=[1, 2],
        workers=4,
        force=False,
        cache_enabled=True,
    )
    assert second_metrics["cache_hits"] == 2
    assert second_metrics["cache_misses"] == 0
    assert all(row["origin"] == REUSED_HISTORICAL for row in second["entries"].values())
    assert not any(call.startswith("picks:") for call in second_client.calls)


def test_factual_only_history_publication_and_chip_facts(tmp_path):
    chips = {
        (3462711, 1): "wildcard",
        (3462711, 2): "bboost",
        (3462711, 3): "3xc",
    }
    manifest = HistoricalBackfillService(
        config=config(),
        output_root=tmp_path,
        client=FakeClient(chips=chips),
    ).run(gw_from=1, gw_to=3)

    assert manifest["overall_status"] == "GREEN"
    assert manifest["cohort_semantics"] == COHORT_SEMANTICS
    assert manifest["publication_contract"]["canonical_atomic_facts_only"] is True
    assert manifest["publication_contract"]["mini_league_analytics_authority"] == "NONE"

    root = tmp_path / "mini_leagues" / str(manifest["league_id"]) / "history"
    managers = json.loads((root / "managers.json").read_text())
    assert all(row["current_cohort_member"] is True for row in managers["managers"])
    assert all(row["historical_membership_confirmed"] is None for row in managers["managers"])

    picks = json.loads((root / "gw_1" / "manager_picks.json").read_text())
    assert all(len(row["picks"]) == 15 for row in picks["entries"].values())

    points = json.loads((root / "gw_1" / "event_points.json").read_text())
    assert points["semantic_class"] == "FACT"
    assert points["points_semantics"] == "FINAL_COMPLETED_GW"
    assert points["elements"]

    entry_history = json.loads((root / "gw_1" / "entry_history.json").read_text())
    assert entry_history["semantic_class"] == "NORMALIZED_FACT"
    assert all("official_overall_rank" in row for row in entry_history["reconciliations"])
    assert "reconstructed_current_cohort_rank" not in json.dumps(entry_history)

    manager_history = json.loads((root / "longitudinal" / "manager_history.json").read_text())
    user = next(row for row in manager_history["managers"] if row["entry_id"] == 3462711)
    assert [row["active_chip"] for row in user["gws"]] == ["wildcard", "bboost", "3xc"]
    assert all("squad_overlap_percent_vs_previous_gw" not in row for row in user["gws"])


def test_legacy_analytics_are_removed_on_migration(tmp_path):
    history = tmp_path / "mini_leagues" / "9477" / "history"
    legacy = [
        history / "gw_1" / "exposure.json",
        history / "gw_1" / "standings_or_points.json",
        history / "gw_1" / "transitions.json",
        history / "longitudinal" / "player_ownership_history.json",
        history / "longitudinal" / "captain_history.json",
        history / "longitudinal" / "squad_overlap_history.json",
        history / "longitudinal" / "transitions.json",
    ]
    for path in legacy:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"legacy": true}')

    manifest = HistoricalBackfillService(
        config=config(),
        output_root=tmp_path,
        client=FakeClient(),
    ).run(gw_from=1, gw_to=1)

    assert all(not path.exists() for path in legacy)
    removed = set(manifest["publication_contract"]["removed_from_runtime_tree"])
    assert "gw_1/exposure.json" in removed
    assert "longitudinal/squad_overlap_history.json" in removed


def test_full_service_rerun_reuses_picks_and_entry_history_cache(tmp_path):
    first = HistoricalBackfillService(
        config=config(), output_root=tmp_path, client=FakeClient()
    ).run(gw_from=1, gw_to=3)
    assert first["cache"]["cache_misses"] == 9
    assert first["cache"]["history_cache_misses"] == 3

    second_client = FakeClient()
    second = HistoricalBackfillService(
        config=config(), output_root=tmp_path, client=second_client
    ).run(gw_from=1, gw_to=3)
    assert second["cache"]["cache_hits"] == 9
    assert second["cache"]["cache_misses"] == 0
    assert second["cache"]["history_cache_hits"] == 3
    assert second["cache"]["history_cache_misses"] == 0
    assert not any(call.startswith("picks:") for call in second_client.calls)
    assert not any(call.startswith("history:") for call in second_client.calls)
    assert second["telemetry"]["manager_requests"] == 0
    assert second["telemetry"]["history_requests"] == 0


def test_coverage_58_of_58_and_partial_57_of_58(tmp_path):
    full = HistoricalBackfillService(
        config=config(),
        output_root=tmp_path / "full",
        client=FakeClient(manager_count=58),
    ).run(gw_from=1, gw_to=1)
    assert full["current_cohort_manager_count"] == 58
    assert full["gw_health"][0]["coverage_percent"] == 100.0
    assert full["overall_status"] == "GREEN"

    failed_entry = 4000057
    partial = HistoricalBackfillService(
        config=config(),
        output_root=tmp_path / "partial",
        client=FakeClient(manager_count=58, fail_pick=(failed_entry, 1)),
    ).run(gw_from=1, gw_to=1)
    assert partial["gw_health"][0]["submitted_picks_available_count"] == 57
    assert partial["gw_health"][0]["coverage_percent"] == round(57 * 100 / 58, 4)
    assert partial["gw_health"][0]["failed_entry_ids"] == [failed_entry]
    assert partial["overall_status"] == "AMBER"


def test_runtime_tree_is_factual_only_secret_safe_and_v6_isolated(tmp_path):
    manifest = HistoricalBackfillService(
        config=config(), output_root=tmp_path, client=FakeClient()
    ).run(gw_from=1, gw_to=1)
    root = tmp_path / "mini_leagues" / str(manifest["league_id"]) / "history"
    expected = {
        "manifest.json",
        "managers.json",
        "gw_1/manager_picks.json",
        "gw_1/event_points.json",
        "gw_1/entry_history.json",
        "longitudinal/manager_history.json",
    }
    actual = {str(path.relative_to(root)) for path in root.rglob("*.json")}
    assert expected == actual

    all_published = "\n".join(path.read_text() for path in tmp_path.rglob("*.json"))
    assert "sessionid=never-publish" not in all_published
    for token in ("runtime-data-v3", "runtime-data-v4", "runtime-data-v5"):
        assert token not in all_published

    factual_paths = [
        path
        for path in root.rglob("*.json")
        if path.name != "manifest.json"
    ]
    factual_published = "\n".join(path.read_text() for path in factual_paths)
    for token in (
        "ownership_percent",
        "effective_ownership",
        "squad_overlap",
        "captain_concentration",
        "player_concentration",
        "reconstructed_current_cohort_rank",
    ):
        assert token not in factual_published


def test_zero_authority_contract_and_no_decision_payloads(tmp_path):
    manifest = HistoricalBackfillService(
        config=config(), output_root=tmp_path, client=FakeClient()
    ).run(gw_from=1, gw_to=1)
    assert manifest["governance"] == {
        "data_only": True,
        "decision_authority": "NONE",
        "prediction_authority": "NONE",
        "optimizer_authority": "NONE",
        "tactical_authority": "NONE",
        "bayesian_authority": "NONE",
        "monte_carlo_authority": "NONE",
    }

    forbidden_keys = {
        "decision",
        "prediction",
        "optimizer",
        "tactical_score",
        "transfer_recommendation",
        "captain_recommendation",
        "chip_recommendation",
        "formation_recommendation",
        "xpts",
        "xmins",
        "bayesian_posterior_recommendation",
        "monte_carlo_result",
        "p_top1",
        "p_top3",
        "action_state",
    }
    for path in tmp_path.rglob("*.json"):
        payload = json.loads(path.read_text())
        stack = [payload]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                assert not ({str(key).lower() for key in value} & forbidden_keys)
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
            elif isinstance(value, str):
                assert value not in {"WAIT", "PREPARE", "ACT"}


def test_v6_historical_source_isolation_static():
    shim = Path("src/runtime_v6/historical_backfill.py").read_text(encoding="utf-8")
    source = Path("src/runtime_v6/historical_facts.py").read_text(encoding="utf-8")
    forbidden = [
        "src.v3",
        "src.v4",
        "src.v5",
        "runtime-data-v3",
        "runtime-data-v4",
        "runtime-data-v5",
    ]
    for token in forbidden:
        assert token not in shim
        assert token not in source
    assert "OfficialFPLClient" in source
    assert "fetch_all_standings" in source
    assert "resolve_priority_leagues" in source
    assert "statistics" not in source
    assert "9477" not in source
    assert "ICON+ League" not in source


def test_regression_scope_routing_unchanged_for_current_modes():
    cfg = config()
    assert resolve_scope("full_master", cfg).__dict__ == {
        "personal": True,
        "mini_league": True,
        "live": False,
    }
    assert resolve_scope("match_mode", cfg).__dict__ == {
        "personal": True,
        "mini_league": True,
        "live": True,
    }
    assert resolve_scope("05:30_price", cfg).__dict__ == {
        "personal": False,
        "mini_league": False,
        "live": False,
    }
