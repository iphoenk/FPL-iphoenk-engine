import json

from src.engines import framework_health_audit as audit_engine
from src.engines.framework_health_service import activate_freshness_contract, activate_registry_contract
from src.settings import NORMAL_STALE_MINUTES


def test_framework_expected_counts_are_loaded_from_registries():
    expected = activate_registry_contract()
    declared = {
        name: int(json.loads(path.read_text(encoding="utf-8"))["expected_count"])
        for name, path in audit_engine.REGISTRIES.items()
    }
    assert expected == declared
    assert audit_engine.EXPECTED_COUNTS == declared
    assert set(declared) == {"dss_core", "dss_extensions", "enhancements", "gate0"}


def test_active_framework_freshness_is_owned_by_engine_config():
    configured = activate_freshness_contract()
    assert configured == NORMAL_STALE_MINUTES
    ok, detail = audit_engine._probe_freshness(max_age_minutes=NORMAL_STALE_MINUTES)
    assert detail["max_age_minutes"] == NORMAL_STALE_MINUTES
    assert isinstance(ok, bool)
