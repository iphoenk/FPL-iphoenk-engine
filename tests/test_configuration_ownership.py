import json
from pathlib import Path

from src.rules import ELEMENT_TYPE_TO_POSITION, SQUAD_RULES
from src.settings import (
    API_BACKOFF_SECONDS,
    API_RETRIES,
    API_TIMEOUT_SECONDS,
    DEADLINE_STALE_MINUTES,
    LIVE_POLL_SECONDS,
    MATCHDAY_STALE_MINUTES,
    NORMAL_STALE_MINUTES,
    PRICE_PRESSURE_LIST_SIZE,
    PRICE_SUMMARY_LIST_SIZE,
    PURCHASE_RECONSTRUCTION_BASELINE_GW,
    TEAM_ID,
)

ROOT = Path(__file__).resolve().parents[1]


def test_mutable_runtime_settings_are_owned_by_engine_config():
    config = json.loads((ROOT / "config" / "engine.json").read_text())
    assert TEAM_ID == int(config["team_id"])
    assert LIVE_POLL_SECONDS == int(config["live_poll_seconds"])
    assert NORMAL_STALE_MINUTES == int(config["normal_stale_minutes"])
    assert DEADLINE_STALE_MINUTES == int(config["deadline_stale_minutes"])
    assert MATCHDAY_STALE_MINUTES == int(config["matchday_stale_minutes"])
    assert PURCHASE_RECONSTRUCTION_BASELINE_GW == int(config["purchase_reconstruction_baseline_gw"])
    assert PRICE_PRESSURE_LIST_SIZE == int(config["price_pressure_list_size"])
    assert PRICE_SUMMARY_LIST_SIZE == int(config["price_summary_list_size"])
    assert API_RETRIES == int(config["api_retries"])
    assert API_BACKOFF_SECONDS == float(config["api_backoff_seconds"])
    assert API_TIMEOUT_SECONDS == int(config["api_timeout_seconds"])


def test_squad_constraints_are_owned_by_active_ruleset():
    assert int(SQUAD_RULES["squad_size"]) == sum(int(v) for v in SQUAD_RULES["position_counts"].values())
    assert set(SQUAD_RULES["position_counts"]) == set(ELEMENT_TYPE_TO_POSITION.values())
    assert int(SQUAD_RULES["max_players_per_club"]) > 0


def test_onefpl_report_time_queries_and_domains_are_registry_owned():
    machine_registry = json.loads((ROOT / "config" / "sources" / "registry.json").read_text())
    report_registry = json.loads((ROOT / "config" / "sources" / "report_time_registry.json").read_text())
    challenger_registry = json.loads((ROOT / "config" / "intelligence" / "challenger_registry.json").read_text())
    machine = next(row for row in machine_registry["sources"] if row["id"] == "onefpl")
    report = next(row for row in report_registry["sources"] if row["id"] == "onefpl")
    challenger_ids = {row["id"] for row in challenger_registry["providers"]}

    assert machine["enabled"] is False
    assert machine["adapter"] == "disabled"
    assert machine["delegated_to"] == report_registry["registry"]
    assert "probe_url" not in machine
    assert "structured_url" not in machine
    assert report["retrieval"] == "REPORT_TIME_WEB"
    assert report["domains"]
    assert report["queries"]
    assert "onefpl" not in challenger_ids
    assert not (ROOT / "src" / "sources" / "onefpl.py").exists()


def test_legacy_runtime_hardcodes_do_not_return():
    engine = (ROOT / "src" / "engine.py").read_text()
    workflow = (ROOT / ".github" / "workflows" / "fpl-engine.yml").read_text()
    forbidden = [
        "TEAM_ID=3462711",
        'pos={1:"GK",2:"DEF",3:"MID",4:"FWD"}',
        "len(squad)!=15",
        'counts!={"GK":2,"DEF":5,"MID":5,"FWD":3}',
        "max(club_counts.values(), default=0)>3",
        'event/1/picks/',
        "momentum[:25]",
        "momentum[:10]",
    ]
    for snippet in forbidden:
        assert snippet not in engine
    assert "FPL_TEAM_ID:" not in workflow
    assert not (ROOT / "config" / "sources.json").exists()
