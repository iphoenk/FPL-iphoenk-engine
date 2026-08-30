from types import SimpleNamespace

from src.v5.decision import dss_evaluator
from src.v5.governance import core as governance_core
from src.v5 import service_registry


def test_noncritical_partial_dss_blocks_unqualified_go_when_policy_requires_all_active(monkeypatch):
    policy = {
        "evaluation_model": "test",
        "statuses": {"active": "ACTIVE", "partial": "PARTIAL"},
        "governance": {
            "registry_integrity_required": True,
            "critical_partial_blocks_unqualified_go": True,
            "all_modules_active_for_unqualified_go": True,
        },
    }
    core_rows = [{"id": "DSS-01", "name": "noncritical", "critical": False, "operational_probe": "missing_probe"}]
    ext_rows = [{"id": "DSS-X01", "name": "active", "critical": False, "operational_probe": "ext_probe"}]
    core_spec = {"expected_count": 1, "first_index": 1, "zero_pad": 2, "id_prefix": "DSS-"}
    ext_spec = {"expected_count": 1, "first_index": 1, "zero_pad": 2, "id_prefix": "DSS-X"}

    monkeypatch.setattr(dss_evaluator, "_policy", lambda: policy)
    monkeypatch.setattr(
        dss_evaluator,
        "_registry",
        lambda name: (core_rows, core_spec) if name == "core" else (ext_rows, ext_spec),
    )

    result = dss_evaluator.evaluate_dss(
        truth={"capabilities": []},
        price={"capabilities": []},
        prediction={"capabilities": ["ext_probe"]},
    )

    assert result["registry_integrity"] is True
    assert result["critical_partial_count"] == 0
    assert result["all_modules_active"] is False
    assert result["all_modules_active_required_for_unqualified_go"] is True
    assert result["unqualified_go_allowed"] is False


def test_governance_all_dss_active_helper_rejects_noncritical_partial():
    core = {"expected": 50, "integrity_ok": True, "counts": {"ACTIVE": 49, "PARTIAL": 1}}
    extensions = {"expected": 16, "integrity_ok": True, "counts": {"ACTIVE": 16}}
    assert governance_core._all_dss_active(core, extensions) is False


def test_service_registry_rejects_duplicate_handler_and_bounded_context(monkeypatch):
    specs = (
        service_registry.ServiceSpec("a", 8101, "same-context", "pkg.same:handle", ("m1",), (), "ACTIVE", True),
        service_registry.ServiceSpec("b", 8102, "same-context", "pkg.same:handle", ("m2",), (), "ACTIVE", True),
    )
    monkeypatch.setattr(service_registry, "service_specs", lambda: specs)
    monkeypatch.setattr(
        service_registry,
        "module_specs",
        lambda: (SimpleNamespace(name="m1"), SimpleNamespace(name="m2")),
    )

    errors = service_registry.validate_registry()
    assert "duplicate service handlers" in errors
    assert "duplicate bounded-context authority" in errors
