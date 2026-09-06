from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import src.runtime_v6.league_prefetch as league_prefetch
from src.runtime_v6.league_prefetch import acquire_manager_picks, fetch_all_standings
from src.runtime_v6.personal_prefetch import discover_memberships, normalise_team, resolve_priority_leagues
from src.runtime_v6.prefetch_contract import (
    PrefetchContractError,
    freshness,
    parse_slot,
    resolve_scope,
    write_json,
)
from src.runtime_v6.report_prefetch import PrefetchService
from src.runtime_v6.security import SecretLeakError, assert_publish_safe


NOW = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)
SLOT = "2026-09-05T07:30:00+07:00"


def result(endpoint: str, payload=None, status="LIVE", code=200):
    return {
        "status": status,
        "endpoint_class": endpoint,
        "checked_at": "2026-09-05T00:00:01+00:00",
        "http_status": code,
        "payload_digest": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() if status == "LIVE" else None,
        "payload": payload if status == "LIVE" else None,
        "attempts": 1,
        "duration_ms": 1,
        "error": None,
    }


def bootstrap_payload():
    return {
        "events": [{"id": 3, "is_current": True, "is_next": False, "deadline_time": "2026-09-04T17:30:00Z"}],
        "teams": [{"id": 1, "name": "Alpha", "short_name": "ALP"}],
        "element_types": [
            {"id": 1, "singular_name_short": "GKP"},
            {"id": 2, "singular_name_short": "DEF"},
            {"id": 3, "singular_name_short": "MID"},
            {"id": 4, "singular_name_short": "FWD"},
        ],
        "elements": [
            {"id": element_id, "web_name": f"P{element_id}", "team": 1, "element_type": 3, "now_cost": 50 + element_id}
            for element_id in range(1, 21)
        ],
    }


def entry_payload(duplicate_priority=False):
    classic = [
        {"id": 10 + i, "name": f"Private {i}", "league_type": "x", "rank": i + 1, "last_rank": i + 2}
        for i in range(7)
    ]
    classic.append({"id": 99, "name": "ICON+ League", "league_type": "x", "rank": 3, "last_rank": 4, "entry_can_leave": True})
    if duplicate_priority:
        classic.append({"id": 100, "name": "ICON+ League", "league_type": "x", "rank": 8})
    classic.append({"id": 314, "name": "Overall", "league_type": "s", "rank": 123})
    return {"id": 3462711, "leagues": {"classic": classic, "h2h": [{"id": 201, "name": "H2H Friends", "league_type": "x", "rank": 2}]}}


def submitted_payload(entry_id: int):
    return {
        "active_chip": None,
        "picks": [
            {
                "element": index,
                "position": index,
                "multiplier": 2 if index == 1 else (0 if index > 11 else 1),
                "is_captain": index == 1,
                "is_vice_captain": index == 2,
            }
            for index in range(1, 16)
        ],
        "entry_history": {"event": 3, "points": 20 + entry_id % 10},
    }


def standings_page(rows, has_next=False):
    return {"standings": {"results": rows, "has_next": has_next}}


def manager_row(entry_id, rank):
    return {
        "entry": entry_id,
        "entry_name": f"Team {entry_id}",
        "player_name": f"Manager {entry_id}",
        "rank": rank,
        "last_rank": rank + 1,
        "event_total": 40 - rank,
        "total": 200 - rank,
    }


class FakeClient:
    def __init__(self, *, auth=True, fail_pick=None, duplicate_priority=False, pages=None):
        self.auth_available = auth
        self.auth_configuration_state = "CONFIGURED" if auth else "UNAVAILABLE"
        self.secret_values = ("sessionid=never-publish",) if auth else ()
        self.calls = []
        self.fail_pick = fail_pick
        self.duplicate_priority = duplicate_priority
        self.pages = pages or {1: standings_page([manager_row(3462711, 1), manager_row(4000001, 2)], False)}

    def _call(self, name):
        self.calls.append(name)

    def bootstrap(self):
        self._call("bootstrap")
        return result("bootstrap_static", bootstrap_payload())

    def entry(self, entry_id):
        self._call(f"entry:{entry_id}")
        return result("entry", entry_payload(self.duplicate_priority))

    def submitted_picks(self, entry_id, gw):
        self._call(f"picks:{entry_id}:{gw}")
        if entry_id == self.fail_pick:
            return result("submitted_picks", status="FAILED", code=503)
        return result("submitted_picks", submitted_payload(entry_id))

    def classic_standings(self, league_id, page):
        self._call(f"classic:{league_id}:{page}")
        value = self.pages.get(page)
        return result("classic_standings", value) if value is not None else result("classic_standings", status="FAILED", code=503)

    def h2h_standings(self, league_id, page):
        self._call(f"h2h:{league_id}:{page}")
        return result("h2h_standings", standings_page([], False))

    def event_live(self, gw):
        self._call(f"live:{gw}")
        payload = {"elements": [{"id": element_id, "stats": {"total_points": element_id, "minutes": 90, "bonus": 0, "bps": 10}} for element_id in range(1, 21)]}
        return result("event_live", payload)

    def me(self):
        self._call("me")
        return result("me", {"player": {"entry": 3462711}})

    def my_team(self, entry_id):
        self._call(f"my-team:{entry_id}")
        return result(
            "my_team",
            {
                "transfers": {"bank": 10, "value": 1010, "made": 1, "cost": 4, "free_transfers": 0},
                "picks": [{"element": index, "position": index, "purchase_price": 45 + index, "selling_price": 46 + index} for index in range(1, 16)],
                "chips": [{"name": "wildcard", "status_for_entry": "played", "played_by_entry": [2]}],
            },
        )

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
        "priority_full_picks_enabled": True,
        "deadline_review_mini_league_enabled": False,
        "submitted_picks_cache_enabled": True,
        "prefetch_lead_minutes": 30,
        "prefetch_max_age_minutes": 35,
        "rival_picks_max_workers": 4,
    }


def test_report_kind_routing():
    cfg = config()
    assert resolve_scope("full_master", cfg).__dict__ == {"personal": True, "mini_league": True, "live": False}
    assert resolve_scope("match_mode", cfg).__dict__ == {"personal": True, "mini_league": True, "live": True}
    assert resolve_scope("deadline_review", cfg).__dict__ == {"personal": True, "mini_league": False, "live": False}
    assert resolve_scope("05:30_price", cfg).__dict__ == {"personal": False, "mini_league": False, "live": False}


def test_membership_discovery_and_priority_resolution():
    memberships = discover_memberships(entry_payload(), "now")
    assert len([item for item in memberships if item["league_kind"] == "classic"]) == 8
    assert any(item["league_kind"] == "h2h" for item in memberships)
    assert not any(item["league_name"] == "Overall" for item in memberships)
    ambiguous = resolve_priority_leagues(
        discover_memberships(entry_payload(True), "now"),
        [{"name": "ICON+ League", "kind": "classic", "full_submitted_picks": True}],
    )
    assert ambiguous[0]["resolution_status"] == "AMBIGUOUS"
    assert ambiguous[0]["league_id"] is None


def test_standings_single_multi_page_and_failure():
    client = FakeClient(pages={1: standings_page([manager_row(1, 1)], True), 2: standings_page([manager_row(2, 2)], False)})
    state = fetch_all_standings(client, {"league_id": 99, "league_kind": "classic"})
    assert state["complete"] is True
    assert [row["entry_id"] for row in state["rows"]] == [1, 2]
    failing = FakeClient(pages={1: standings_page([manager_row(1, 1)], True)})
    partial = fetch_all_standings(failing, {"league_id": 99, "league_kind": "classic"})
    assert partial["complete"] is False
    assert partial["failed_pages"][0]["page"] == 2


def test_rival_picks_cache_and_partial_coverage(tmp_path):
    path = tmp_path / "gw_3_manager_picks.json"
    first, metrics = acquire_manager_picks(FakeClient(), previous_path=path, season="2026-2027", league_id=99, gw=3, manager_ids=[1, 2], deadline_passed=True, workers=4, force=False, cache_enabled=True)
    assert first["complete"] is True
    assert metrics["cache_misses"] == 2
    write_json(path, first)
    second_client = FakeClient()
    second, metrics2 = acquire_manager_picks(second_client, previous_path=path, season="2026-2027", league_id=99, gw=3, manager_ids=[1, 2], deadline_passed=True, workers=4, force=False, cache_enabled=True)
    assert metrics2 == {"cache_hits": 2, "cache_misses": 0, "maximum_concurrency_used": 0}
    assert not [call for call in second_client.calls if call.startswith("picks:")]
    failure, _ = acquire_manager_picks(FakeClient(fail_pick=2), previous_path=tmp_path / "missing.json", season="2026-2027", league_id=99, gw=3, manager_ids=[1, 2], deadline_passed=True, workers=4, force=False, cache_enabled=True)
    assert failure["coverage_percent"] == 50.0
    assert failure["missing_entry_ids"] == [2]


def test_v6_league_prefetch_exposes_no_ownership_or_rival_analytics_api():
    assert not hasattr(league_prefetch, "exposure_artifact")
    assert not hasattr(league_prefetch, "add_manager_live_totals")
    source = Path("src/runtime_v6/league_prefetch.py").read_text(encoding="utf-8")
    for forbidden in (
        "mini_league_effective_ownership_percent",
        "ownership_percent",
        "manager_multiplier_points",
        "raw_multiplier_points",
    ):
        assert forbidden not in source


def test_personal_normalization_missing_fields_are_truthful():
    submitted = {"picks": [{"element_id": 1, "squad_position": 1, "multiplier": 2, "captain": True, "vice_captain": False, "bench_order": None}], "lineage": {}}
    team = normalise_team(
        entry_id=1,
        gw=3,
        element_index={1: {"position": "MID", "current_price": 70}},
        bootstrap_lineage={},
        submitted=submitted,
        auth_state="AVAILABLE",
        my_team_payload={"transfers": {"bank": 5, "made": 1, "cost": 4}, "picks": [{"element": 1, "purchase_price": 60}]},
        auth_lineage=[],
        generated_at="now",
    )
    assert team["bank"] == 5
    assert team["effective_sell_value"] is None
    assert team["free_transfers"] is None
    assert team["availability"]["free_transfers"] == "NOT_SUPPORTED"


def test_full_prefetch_publishes_atomic_facts_only_and_is_idempotent(tmp_path):
    client = FakeClient(auth=True)
    service = PrefetchService(config=config(), output_root=tmp_path, client=client, now=NOW)
    first = service.run(report_kind="full_master", logical_slot=SLOT)
    assert first["personal_status"] == "AVAILABLE"
    assert first["mini_league_status"] == "AVAILABLE"
    assert first["priority_league_id"] == 99
    assert first["expected_manager_count"] == 2
    assert first["submitted_picks_available_count"] == 2
    assert first["complete"] is True
    assert (tmp_path / "personal/current_team.json").exists()
    assert (tmp_path / "mini_leagues/99/standings.json").exists()
    assert (tmp_path / "mini_leagues/99/gw_3_manager_picks.json").exists()
    assert not (tmp_path / "mini_leagues/99/gw_3_exposure.json").exists()
    calls = list(client.calls)
    second = service.run(report_kind="full_master", logical_slot=SLOT)
    assert second["idempotency"]["reused"] is True
    assert second["reuse_telemetry"]["request_count"] == 0
    assert client.calls == calls


def test_personal_auth_unavailable_degrades_without_guessing(tmp_path):
    manifest = PrefetchService(config={**config(), "mini_league_enabled": False}, output_root=tmp_path, client=FakeClient(auth=False), now=NOW).run(report_kind="full_master", logical_slot=SLOT)
    team = json.loads((tmp_path / "personal/current_team.json").read_text())
    assert manifest["personal_status"] == "DEGRADED"
    assert team["auth_state"] == "AUTH_UNAVAILABLE"
    assert team["bank"] is None
    assert team["free_transfers"] is None
    assert team["players"][0]["purchase_price"] is None


def test_match_mode_reuses_picks_refreshes_raw_live_without_manager_analytics(tmp_path):
    first_client = FakeClient()
    PrefetchService(config=config(), output_root=tmp_path, client=first_client, now=NOW).run(report_kind="full_master", logical_slot=SLOT)
    second_client = FakeClient()
    manifest = PrefetchService(config=config(), output_root=tmp_path, client=second_client, now=NOW + timedelta(minutes=10)).run(report_kind="match_mode", logical_slot="2026-09-05T07:40:00+07:00")
    assert [c for c in second_client.calls if c.startswith("picks:4000001")] == []
    assert "live:3" in second_client.calls
    assert manifest["telemetry"]["cache_hits"] == 2
    live = json.loads((tmp_path / "mini_leagues/99/live_state.json").read_text())
    assert live["status"] == "AVAILABLE"
    assert "manager_multiplier_points" not in live


def test_priority_partial_coverage_is_explicit_without_exposure_artifact(tmp_path):
    manifest = PrefetchService(config=config(), output_root=tmp_path, client=FakeClient(fail_pick=4000001), now=NOW).run(report_kind="full_master", logical_slot=SLOT)
    picks = json.loads((tmp_path / "mini_leagues/99/gw_3_manager_picks.json").read_text())
    assert manifest["mini_league_status"] == "PARTIAL"
    assert picks["missing_entry_ids"] == [4000001]
    assert picks["coverage_percent"] == 50.0
    assert manifest["coverage_percent"] == 50.0
    assert not (tmp_path / "mini_leagues/99/gw_3_exposure.json").exists()


class ExplodingClient:
    calls = []

    def __getattr__(self, name):
        raise AssertionError(f"05:30 must not touch Official client: {name}")


def test_0530_p0_cannot_fetch_personal_league_or_rival_picks(tmp_path):
    personal = tmp_path / "personal/current_team.json"
    personal.parent.mkdir(parents=True)
    personal.write_text(json.dumps({"generated_at": "2026-09-04T20:00:00+00:00", "marker": "old"}))
    before = personal.read_text()
    manifest = PrefetchService(config=config(), output_root=tmp_path, client=ExplodingClient(), now=NOW).run(report_kind="05:30_price", logical_slot=SLOT)
    assert manifest["telemetry"]["request_count"] == 0
    assert manifest["personal_requested"] is False
    assert manifest["mini_league_requested"] is False
    assert personal.read_text() == before
    assert not (tmp_path / "mini_leagues").exists()


def test_security_blocks_sensitive_keys_and_secret_values(tmp_path):
    with pytest.raises(SecretLeakError):
        assert_publish_safe({"Authorization": "Bearer bad"})
    with pytest.raises(SecretLeakError):
        assert_publish_safe({"safe": "sessionid=never"}, secret_values=("sessionid=never",))
    PrefetchService(config=config(), output_root=tmp_path, client=FakeClient(auth=True), now=NOW).run(report_kind="full_master", logical_slot=SLOT)
    published = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.rglob("*.json"))
    assert "sessionid=never-publish" not in published
    assert "Authorization" not in published
    assert "csrf" not in published.lower()


def test_freshness_t30_age34_stale_and_slot_validation():
    slot = datetime(2026, 9, 5, 1, 0, tzinfo=timezone.utc)
    assert freshness(slot - timedelta(minutes=30), slot, 35) == (30.0, True)
    assert freshness(slot - timedelta(minutes=34), slot, 35) == (34.0, True)
    assert freshness(slot - timedelta(minutes=36), slot, 35) == (36.0, False)
    with pytest.raises(PrefetchContractError):
        parse_slot("2026-09-05T12:30:00")


def test_manifest_artifact_references_have_exact_digests(tmp_path):
    manifest = PrefetchService(config=config(), output_root=tmp_path, client=FakeClient(), now=NOW).run(report_kind="full_master", logical_slot=SLOT)
    assert manifest["slot_key"].startswith("2026-2027|3|full_master|")
    for artifact in manifest["artifacts"]:
        relative = artifact["path"].removeprefix("data/v6/")
        raw = (tmp_path / relative).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]


def test_v6_report_prefetch_sources_are_version_isolated():
    paths = [
        "src/runtime_v6/official_fpl_client.py",
        "src/runtime_v6/prefetch_contract.py",
        "src/runtime_v6/personal_prefetch.py",
        "src/runtime_v6/league_prefetch.py",
        "src/runtime_v6/report_prefetch.py",
    ]
    forbidden = ["src.v3", "src.v4", "src.v5", "runtime-data-v3", "runtime-data-v4", "runtime-data-v5", "config/strategy/mini_leagues.json"]
    combined = "\n".join(Path(path).read_text(encoding="utf-8") for path in paths)
    for token in forbidden:
        assert token not in combined


def test_priority_ambiguity_fails_closed_end_to_end(tmp_path):
    manifest = PrefetchService(config=config(), output_root=tmp_path, client=FakeClient(duplicate_priority=True), now=NOW).run(report_kind="full_master", logical_slot=SLOT)
    assert manifest["mini_league_status"] == "UNAVAILABLE"
    assert any("AMBIGUOUS" in failure for failure in manifest["control_failures"])
    assert not (tmp_path / "mini_leagues/99/standings.json").exists()
