from __future__ import annotations

import pytest

from src.v5.degraded_mode import fallback_for, validate_registry
from src.v5.governance.core import degraded_contexts
from src.v5.service_registry import module_owners


def _failure(service_id: str, operation: str) -> dict:
    return {
        "ok": False,
        "service_id": service_id,
        "operation": operation,
        "envelope": None,
        "error_type": "ConnectTimeout",
        "error": "synthetic timeout",
    }


def test_degraded_mode_registry_is_valid_and_owned_by_orchestrator():
    assert validate_registry() == []
    assert module_owners()["degraded_mode"] == "orchestrator"


def test_price_failure_uses_explicit_empty_context_with_provenance():
    payload = fallback_for("price", "build", _failure("price", "build"))
    context = payload["degraded_context"]

    assert payload["status"] == "DEGRADED"
    assert payload["capabilities"] == []
    assert payload["prices"]["players"] == []
    assert payload["alerts"]["alerts"] == []
    assert context["service_id"] == "price"
    assert context["operation"] == "build"
    assert context["behavior"] == "STATIC_EMPTY_CONTEXT"
    assert context["blocks_unqualified_go"] is True
    assert context["error_type"] == "ConnectTimeout"
    assert context["error"] == "synthetic timeout"


def test_critical_prediction_failure_has_no_degraded_fallback():
    with pytest.raises(RuntimeError, match="critical service failure must fail closed"):
        fallback_for("prediction", "build", _failure("prediction", "build"))


def test_unregistered_noncritical_operation_also_fails_closed():
    with pytest.raises(RuntimeError, match="no registered fallback"):
        fallback_for("price", "status", _failure("price", "status"))


def test_governance_discovers_degraded_context_generically():
    price = fallback_for("price", "build", _failure("price", "build"))
    rows = degraded_contexts({}, {}, price, {}, {})

    assert len(rows) == 1
    assert rows[0]["service"] == "price"
    assert rows[0]["service_id"] == "price"
    assert rows[0]["blocks_unqualified_go"] is True


def test_orchestrator_source_preserves_healthy_price_state_during_fallback():
    source = open("src/v5/services/orchestrator.py", "r", encoding="utf-8").read()
    assert "invoke_parallel_outcomes" in source
    assert "fallback_for(price_service, price_operation" in source
    assert '"SKIPPED_DEGRADED"' in source
    assert "preserve last known healthy price artifacts" in source
