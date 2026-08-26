import json
from pathlib import Path

from src.engines import price_radar
from src.engines.refresh_policy import load_policy as load_refresh_policy
from src.settings import PROJECTION_HORIZON_GWS, STRATEGIC_HORIZON_GWS, TEAM_ID

ROOT = Path(__file__).resolve().parents[1]


def _json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_projection_horizons_are_owned_by_engine_config():
    engine = _json("config/engine.json")
    assert PROJECTION_HORIZON_GWS == int(engine["projection_horizon_gws"])
    assert STRATEGIC_HORIZON_GWS == int(engine["strategic_horizon_gws"])
    assert STRATEGIC_HORIZON_GWS >= PROJECTION_HORIZON_GWS
    service = (ROOT / "src/engines/prediction_service.py").read_text(encoding="utf-8")
    assert "horizon=15" not in service
    assert "STRATEGIC_HORIZON_GWS" in service


def test_price_radar_runtime_policy_is_registry_driven():
    policy = _json("config/intelligence/price_radar.json")
    market = policy["market_filter"]
    serving = policy["serving"]
    assert price_radar.MIN_OWNERSHIP_PCT == float(market["minimum_ownership_pct"])
    assert price_radar.MIN_ABS_NET == int(market["minimum_abs_net_transfers"])
    assert price_radar.HIGH_NET == int(market["high_confidence_abs_net_transfers"])
    assert price_radar.MAX_MARKET_WATCH == int(serving["market_watch_capacity"])
    source = (ROOT / "src/engines/price_radar.py").read_text(encoding="utf-8")
    for snippet in ("MIN_OWNERSHIP_PCT = 0.5", "MIN_ABS_NET = 5_000", "HIGH_NET = 25_000", "MAX_MARKET_WATCH = 50"):
        assert snippet not in source


def test_refresh_policy_is_config_owned():
    policy = load_refresh_policy()
    assert policy == _json("config/intelligence/refresh_policy.json")
    source = (ROOT / "src/engines/refresh_policy.py").read_text(encoding="utf-8")
    assert "if hours<=1: return 10" not in source
    assert "if hours<=4: return 15" not in source


def test_framework_registry_expected_counts_are_declared_by_registries():
    specs = {
        "config/dss_core_registry.json": ("modules", 50),
        "config/dss_extension_registry.json": ("modules", 16),
        "config/enhancement_layers_registry.json": ("layers", 8),
        "config/gate0_registry.json": ("checks", 16),
    }
    for path, (rows_key, expected) in specs.items():
        payload = _json(path)
        assert int(payload["expected_count"]) == expected
        assert len(payload[rows_key]) == int(payload["expected_count"])


def test_active_service_registry_uses_version_neutral_module_entrypoints():
    registry = _json("config/v3_service_registry.json")
    assert registry["schema_version"] >= 9
    assert registry["policy"]["version_neutral_service_entrypoints"] is True
    assert registry["policy"]["inline_python_service_commands_forbidden"] is True
    assert registry["services"]["prediction"]["commands"] == [{"module": "src.engines.prediction_service", "args": []}]
    assert registry["services"]["price"]["commands"] == [{"module": "src.engines.price_service", "args": []}]
    for service in registry["services"].values():
        for command in service.get("commands") or []:
            assert "code" not in command
            module = str(command.get("module") or "")
            assert "decision_intelligence_v313" not in module


def test_optimizer_random_seed_is_not_user_identity():
    optimizer = _json("config/intelligence/package_optimizer.json")
    assert int(optimizer["monte_carlo_seed"]) != TEAM_ID
    assert "independent of user/team identity" in optimizer["monte_carlo_seed_policy"]
