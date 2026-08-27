import json
from pathlib import Path

from src.rules import ELEMENT_TYPE_TO_POSITION, SQUAD_RULES
from src.settings import (
    API_BACKOFF_SECONDS,
    API_RETRIES,
    API_TIMEOUT_SECONDS,
    LIVE_POLL_SECONDS,
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


def test_onefpl_endpoints_and_fallbacks_are_registry_owned():
    registry = json.loads((ROOT / "config" / "sources" / "registry.json").read_text())
    onefpl = next(row for row in registry["sources"] if row["id"] == "onefpl")
    adapter = (ROOT / "src" / "sources" / "onefpl.py").read_text()

    assert onefpl["probe_url"].startswith("https://")
    assert onefpl["structured_url"].startswith("https://")
    assert onefpl["fallback_structured_urls"]
    assert onefpl["allowed_hosts"]
    for url in onefpl["fallback_structured_urls"]:
        assert url not in adapter
    for host in onefpl["allowed_hosts"]:
        assert host not in adapter


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
