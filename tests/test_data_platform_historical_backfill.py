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
        "payload_digest": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() if status == "LIVE" else None,
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
        "teams": [{"id": 1, "name": "Alpha", "short_name": "ALP"}, {"id": 2, "name": "Beta", "short_name": "BET"}],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "elements": [{"id": element_id, "web_name": f"P{element_id}", "team": 1 if element_id <= 10 else 2, "element_type": 3} for element_id in range(1, 31)],
    }


def entry_payload(league_id=9477):
    return {"id": 3462711, "leagues": {"classic": [{"id": league_id, "name": "ICON+ League", "league_type": "x", "rank": 4, "last_rank": 5, "entry_can_leave": True}, {"id": 314, "name": "Overall", "league_type": "s", "rank": 123}], "h2h": []}}


def manager_row(entry_id: int, rank: int):
    return {"entry": entry_id, "entry_name": f"Team {entry_id}", "player_name": f"Manager {entry_id}", "rank": rank, "last_rank": rank + 1, "event_total": 40 - rank, "total": 200 - rank}


def submitted_payload(entry_id: int, gw: int, *, chip=None):
    shift = (entry_id + gw) % 5
    elements = list(range(1 + shift, 16 + shift))
    return {
        "active_chip": chip,
        "picks": [
            {
                "element": element_id,
                "position": position,
                "multiplier": 3 if chip == "3xc" and position == 1 else (2 if position == 1 else (1 if chip == "bboost" and position > 11 else (0 if position > 11 else 1))),
                "is_captain": position == 1,
                "is_vice_captain": position == 2,
            }
            for position, element_id in enumerate(elements, start=1)
        ],
        "entry_history": {"event": gw, "points": 50 + gw},
    }


def history_payload(entry_id: int, chips=None):
    chips = chips or {}
    running = 0
    current = []
    for gw in (1, 2, 3):
        points = 40 + gw + entry_id % 7
        running += points
        current.append({"event": gw, "points": points, "total_points": running, "overall_rank": 100000 - entry_id - gw})
    return {"current": current, "chips": [{"name": name, "event": gw} for gw, name in sorted(chips.items())]}


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
        ids = [3462711] + [4000000 + i for i in range(1, self.manager_count)]
        return result("classic_standings", {"standings": {"results": [manager_row(entry_id, rank) for rank, entry_id in enumerate(ids, start=1)], "has_next": False}})

    def h2h_standings(self, league_id, page):
        raise AssertionError("classic priority league must not use h2h endpoint")

    def submitted_picks(self, entry_id, gw):
        self.calls.append(f"picks:{entry_id}:{gw}")
        if self.fail_pick == (entry_id, gw):
            return result("submitted_picks", status="FAILED", code=503)
        return result("submitted_picks", submitted_payload(entry_id, gw, chip=self.chips.get((entry_id, gw))))

    def entry_history(self, entry_id):
        self.calls.append(f"history:{entry_id}")
        chip_events = {gw: name for (candidate, gw), name in self.chips.items() if candidate == entry_id}
        return result("entry_history", history_payload(entry_id, chip_events))

    def event_live(self, gw):
        self.calls.append(f"live:{gw}")
        return result("event_live", {"elements": [{"id": element_id, "stats": {"total_points": element_id % 10, "minutes": 90, "bonus": 0, "bps": 1}} for element_id in range(1, 31)]})

    def telemetry(self):
        return {"request_count": len(self.calls), "failed_requests": int(self.fail_pick is not None), "maximum_concurrency_used": 1}


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


def test_historical_picks_exact_15_and_cache(tmp_path):
    client = FakeClient(chips={(1, 2): "3xc"})
    path = tmp_path / "manager_picks.json"
    artifact, metrics = acquire_historical_picks(client, previous_path=path, season="2026-2027", league_id=9477, gw=2, manager_ids=[1], workers=8, force=False, cache_enabled=True)
    record = artifact["entries"]["1"]
    assert record["status"] == "AVAILABLE"
    assert len(record["picks"]) == 15
    assert record["origin"] == LIVE_HISTORICAL
    assert metrics["cache_misses"] == 1
    write_json(path, artifact)
    second_client = FakeClient()
    reused, reuse_metrics = acquire_historical_picks(second_client, previous_path=path, season="2026-2027", league_id=9477, gw=2, manager_ids=[1], workers=8, force=False, cache_enabled=True)
    assert reuse_metrics["cache_hits"] == 1
    assert reused["entries"]["1"]["origin"] == REUSED_HISTORICAL


def test_end_to_end_atomic_history_shape_and_membership_semantics(tmp_path):
    manifest = HistoricalBackfillService(config=config(), output_root=tmp_path, client=FakeClient()).run(gw_from=1, gw_to=3)
    assert manifest["overall_status"] == "GREEN"
    assert manifest["cohort_semantics"] == COHORT_SEMANTICS
    assert manifest["historical_membership_confirmed"] is False
    root = tmp_path / "mini_leagues" / str(manifest["league_id"]) / "history"
    managers = json.loads((root / "managers.json").read_text())
    assert all(row["current_cohort_member"] is True for row in managers["managers"])
    assert (root / "entry_histories.json").exists()
    for gw in (1, 2, 3):
        assert (root / f"gw_{gw}/manager_picks.json").exists()
        assert (root / f"gw_{gw}/event_live.json").exists()
        assert (root / f"gw_{gw}/reconciliation.json").exists()
        assert not (root / f"gw_{gw}/exposure.json").exists()
        assert not (root / f"gw_{gw}/transitions.json").exists()
    assert not (root / "longitudinal").exists()


def test_full_service_rerun_reuses_picks_and_entry_history_cache(tmp_path):
    first_client = FakeClient()
    first = HistoricalBackfillService(config=config(), output_root=tmp_path, client=first_client).run(gw_from=1, gw_to=3)
    assert first["cache"]["cache_misses"] == 9
    assert first["cache"]["history_cache_misses"] == 3
    second_client = FakeClient()
    second = HistoricalBackfillService(config=config(), output_root=tmp_path, client=second_client).run(gw_from=1, gw_to=3)
    assert second["cache"]["cache_hits"] == 9
    assert second["cache"]["cache_misses"] == 0
    assert second["cache"]["history_cache_hits"] == 3
    assert second["cache"]["history_cache_misses"] == 0
    assert not any(call.startswith("picks:") for call in second_client.calls)
    assert not any(call.startswith("history:") for call in second_client.calls)


def test_coverage_58_of_58_and_partial_57_of_58(tmp_path):
    full = HistoricalBackfillService(config=config(), output_root=tmp_path / "full", client=FakeClient(manager_count=58)).run(gw_from=1, gw_to=1)
    assert full["gw_health"][0]["coverage_percent"] == 100.0
    failed_entry = 4000057
    partial = HistoricalBackfillService(config=config(), output_root=tmp_path / "partial", client=FakeClient(manager_count=58, fail_pick=(failed_entry, 1))).run(gw_from=1, gw_to=1)
    assert partial["gw_health"][0]["submitted_picks_available_count"] == 57
    assert partial["gw_health"][0]["coverage_percent"] == round(57 * 100 / 58, 4)
    assert partial["gw_health"][0]["failed_entry_ids"] == [failed_entry]
    assert partial["overall_status"] == "AMBER"


def test_runtime_tree_contains_atomic_facts_only_and_is_secret_safe(tmp_path):
    manifest = HistoricalBackfillService(config=config(), output_root=tmp_path, client=FakeClient()).run(gw_from=1, gw_to=1)
    root = tmp_path / "mini_leagues" / str(manifest["league_id"]) / "history"
    expected = {
        "manifest.json",
        "managers.json",
        "entry_histories.json",
        "gw_1/manager_picks.json",
        "gw_1/event_live.json",
        "gw_1/reconciliation.json",
    }
    actual = {str(path.relative_to(root)) for path in root.rglob("*.json")}
    assert expected == actual
    published = "\n".join(path.read_text() for path in tmp_path.rglob("*.json"))
    assert "sessionid=never-publish" not in published
    for forbidden in ("player_ownership_history", "squad_overlap_history", "effective_ownership_percent", "reconstructed_current_cohort_ranks"):
        assert forbidden not in published


def test_zero_authority_contract_and_no_decision_or_analytics_payloads(tmp_path):
    manifest = HistoricalBackfillService(config=config(), output_root=tmp_path, client=FakeClient()).run(gw_from=1, gw_to=1)
    governance = manifest["governance"]
    for key in (
        "decision_authority",
        "prediction_authority",
        "optimizer_authority",
        "tactical_authority",
        "bayesian_authority",
        "monte_carlo_authority",
        "ownership_analytics_authority",
        "effective_ownership_authority",
        "rival_analytics_authority",
    ):
        assert governance[key] == "NONE"
    source = Path("src/runtime_v6/historical_backfill.py").read_text(encoding="utf-8")
    for forbidden in ("ownership_percent", "effective_ownership_percent", "squad_overlap", "captain_concentration", "reconstructed_current_cohort_ranks"):
        assert forbidden not in source


def test_v6_historical_source_isolation_static():
    source = Path("src/runtime_v6/historical_backfill.py").read_text(encoding="utf-8")
    for token in ("src.v3", "src.v4", "src.v5", "runtime-data-v3", "runtime-data-v4", "runtime-data-v5"):
        assert token not in source
    assert "OfficialFPLClient" in source
    assert "fetch_all_standings" in source
    assert "resolve_priority_leagues" in source
    assert "9477" not in source
    assert "ICON+ League" not in source


def test_regression_scope_routing_unchanged_for_current_modes():
    cfg = config()
    assert resolve_scope("full_master", cfg).__dict__ == {"personal": True, "mini_league": True, "live": False}
    assert resolve_scope("match_mode", cfg).__dict__ == {"personal": True, "mini_league": True, "live": True}
    assert resolve_scope("05:30_price", cfg).__dict__ == {"personal": False, "mini_league": False, "live": False}
