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


def test_watchlist_ranking_primitives_are_config_owned_and_fpl_scoring_is_rule_owned():
    policy = json.loads((ROOT / "config" / "intelligence" / "dss_watchlist.json").read_text())
    implementation = (ROOT / "src" / "engines" / "dss_watchlist.py").read_text()
    primitives = policy["ranking_primitives"]

    assert policy["schema_version"] >= 2
    assert abs(sum(float(v) for v in primitives["role_security"].values()) - 1.0) < 1e-9
    assert abs(
        float(primitives["xmins_security"]["base_weight"])
        + float(primitives["xmins_security"]["expected_minutes_share_weight"])
        - 1.0
    ) < 1e-9
    assert 0.0 <= float(primitives["xmins_security"]["dnp_penalty"]) <= 1.0
    assert float(primitives["price_floor_millions"]) > 0
    assert float(primitives["score_scale"]) > 0
    assert set(primitives["market_overlay_scores"]) == {"RISE", "FALL", "NEUTRAL"}
    assert "_ranking_primitives()" in implementation
    assert "SAVE_INTERVAL" in implementation
    assert "SAVE_POINTS_PER_INTERVAL" in implementation
    assert "role_security = 0.55" not in implementation
    assert "evidence_factor = 0.85" not in implementation
    assert "_f(rates.get(\"saves90\")) / 3.0" not in implementation


def test_public_official_transport_imports_are_explicitly_owned_even_in_helper_modules():
    ownership = json.loads((ROOT / "config" / "runtime" / "logic_ownership.json").read_text())
    allowed = ownership["approved_engine_official_fetch_modules"]
    found = {}
    for path in sorted((ROOT / "src" / "engines").rglob("*.py")):
        text = path.read_text()
        if "src.sources.official_fpl" not in text:
            continue
        module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
        found[module] = allowed.get(module)
    assert set(found) == set(allowed)
    assert all(found.values())
    assert "src.engines.price_radar" not in found


def test_price_artifacts_have_raw_market_intermediate_and_one_canonical_writer():
    services = json.loads((ROOT / "config" / "v3_service_registry.json").read_text())["services"]
    flow = json.loads((ROOT / "config" / "runtime" / "artifact_flow_registry.json").read_text())
    assert "market_prices.json" in services["market_state"]["artifacts"]
    assert "prices.json" not in services["market_state"]["artifacts"]
    assert "market_prices.json" in services["base_snapshot"]["artifacts"]
    assert "prices.json" not in services["base_snapshot"]["artifacts"]
    assert "market_prices.json" in services["price"]["inputs"]
    assert "official_snapshot.json" in services["price"]["inputs"]
    assert "prices.json" in services["price"]["artifacts"]
    assert flow["canonical_final_owners"]["market_prices.json"] == "market_state"
    assert flow["canonical_final_owners"]["prices.json"] == "price"
    assert "prices.json" not in flow["staged_mutation_chains"]


def test_onefpl_report_time_queries_and_domains_are_registry_owned():
    machine_registry = json.loads((ROOT / "config" / "sources" / "registry.json").read_text())
    report_registry = json.loads((ROOT / "config" / "sources" / "report_time_registry.json").read_text())
    machine = next(row for row in machine_registry["sources"] if row["id"] == "onefpl")
    report = next(row for row in report_registry["sources"] if row["id"] == "onefpl")
    adapter = (ROOT / "src" / "sources" / "onefpl.py").read_text()

    assert machine["enabled"] is False
    assert machine["adapter"] == "disabled"
    assert machine["delegated_to"] == "REPORT_TIME_SOURCE_REGISTRY_V1"
    assert "probe_url" not in machine
    assert "structured_url" not in machine
    assert report["retrieval"] == "REPORT_TIME_WEB"
    assert report["domains"]
    assert report["queries"]
    for domain in report["domains"]:
        assert domain not in adapter
    for query in report["queries"]:
        assert query not in adapter


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
