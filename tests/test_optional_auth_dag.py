from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.engines import authenticated_official, framework_health_service
from src.runtime_v3 import domain_process_runner
from src.sources import official_auth

ROOT = Path(__file__).resolve().parents[1]


def _registry() -> dict:
    return json.loads((ROOT / "config/v3_service_registry.json").read_text(encoding="utf-8"))


def test_authenticated_official_is_topologically_optional() -> None:
    registry = _registry()
    services = registry["services"]
    auth = services["authenticated_official"]

    assert registry["policy"]["required_core_and_optional_private_enrichment_are_distinct"] is True
    assert registry["policy"]["optional_private_enrichment_never_blocks_required_core"] is True
    assert auth["critical"] is False
    assert auth["criticality_class"] == "OPTIONAL_PRIVATE_ENRICHMENT"
    assert auth["failure_policy"] == "FAIL_SOFT"
    assert "authenticated_official" not in services["governance"]["depends_on"]
    assert services["official_snapshot"]["critical"] is True

    required_services = {
        name for name, spec in services.items() if bool(spec.get("critical", True))
    }
    assert all(
        "authenticated_official" not in set(services[name].get("depends_on") or [])
        for name in required_services
    )


def test_optional_service_failure_does_not_abort_domain_scheduler(monkeypatch) -> None:
    services = {
        "authenticated_official": {
            "critical": False,
            "depends_on": [],
            "artifacts": ["auth.json"],
        },
        "required_core": {
            "critical": True,
            "depends_on": ["authenticated_official"],
            "artifacts": [],
        },
    }
    monkeypatch.setattr(domain_process_runner, "_service_registry", lambda: {"services": services})
    monkeypatch.setattr(domain_process_runner, "_profiles", lambda: {"profiles": {"test": {}}})
    monkeypatch.setattr(
        domain_process_runner,
        "_domains",
        lambda: {"test_domain": {"capabilities": ["authenticated_official", "required_core"]}},
    )

    def fake_run(name, spec, context, profile_name, profile_cfg):
        if name == "authenticated_official":
            return {"service": name, "status": "FAILED", "error": "simulated optional failure"}
        return {"service": name, "status": "SUCCESS"}

    monkeypatch.setattr(domain_process_runner, "_run_service", fake_run)
    monkeypatch.setattr(domain_process_runner.legacy, "_clear_failed_service_outputs", lambda *args: [])

    out = domain_process_runner.run_domain("test_domain", "daily", True, False, "test")
    assert out["status"] == "SUCCESS"
    assert out["results"]["authenticated_official"]["status"] == "FAILED"
    assert out["results"]["required_core"]["status"] == "SUCCESS"


def test_disabled_auth_is_deterministic_non_blocking_enrichment(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(authenticated_official, "DATA", tmp_path)
    monkeypatch.setenv("FPL_AUTH_MODE", "disabled")

    result = authenticated_official.run()

    assert result["state"] == "DISABLED"
    assert result["policy"]["role"] == "OPTIONAL_PRIVATE_ENRICHMENT"
    assert result["policy"]["production_blocking"] is False
    assert result["enhancement_health"] == {
        "required": False,
        "ready": True,
        "status": "NOT_CONFIGURED",
        "reasons": [],
    }
    assert result["raw_authenticated_payload_persisted"] is False


def test_unexpected_auth_service_error_persists_safe_fail_soft_health(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(authenticated_official, "DATA", tmp_path)
    monkeypatch.setenv("FPL_AUTH_MODE", "session_cookie")
    monkeypatch.setattr(authenticated_official, "_run_once", lambda: (_ for _ in ()).throw(RuntimeError("secret-value")))

    result = authenticated_official.run()

    assert result["state"] == "UNAVAILABLE"
    assert result["failure_reason"] == "SERVICE_FAILURE"
    assert result["enhancement_health"]["required"] is False
    assert result["enhancement_health"]["status"] == "DEGRADED"
    assert result["raw_authenticated_payload_persisted"] is False
    assert "secret-value" not in json.dumps(result)


def test_malformed_private_payload_degrades_enrichment_without_raw_persistence(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(authenticated_official, "DATA", tmp_path)
    monkeypatch.setenv("FPL_AUTH_MODE", "session_cookie")
    monkeypatch.setattr(
        authenticated_official,
        "auth_material_from_env",
        lambda: SimpleNamespace(mode="session_cookie"),
    )
    responses = iter(
        [
            ({"player": {"entry": authenticated_official.EXPECTED_TEAM_ID}}, {"status": "LIVE"}),
            ([{"malformed": True}], {"status": "LIVE"}),
            ([], {"status": "LIVE"}),
        ]
    )
    monkeypatch.setattr(authenticated_official, "safe_get", lambda *args, **kwargs: next(responses))

    result = authenticated_official.run()

    assert result["state"] == "UNAVAILABLE"
    assert result["failure_reason"] == "SERVICE_FAILURE"
    assert result["policy"]["production_blocking"] is False
    assert result["raw_authenticated_payload_persisted"] is False


def test_framework_reports_optional_auth_without_global_blocking(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(framework_health_service, "DATA", tmp_path)

    missing = framework_health_service._optional_auth_health()
    assert missing["class"] == "OPTIONAL_PRIVATE_ENRICHMENT"
    assert missing["status"] == "UNAVAILABLE"
    assert missing["decision_blocking"] is False
    assert missing["finance"] == {
        "exact_private": False,
        "provenance": "PUBLIC_RECONSTRUCTION_NON_EXACT",
    }

    auth = {
        "expected_entry": authenticated_official.EXPECTED_TEAM_ID,
        "verified_entry": authenticated_official.EXPECTED_TEAM_ID,
        "state": "VALID",
        "enhancement_health": {"required": False, "ready": True, "status": "AVAILABLE", "reasons": []},
        "safe_finance": {"private_exact_sell_total": 1000, "private_exact_purchase_total": 1000},
    }
    (tmp_path / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    valid = framework_health_service._optional_auth_health()
    assert valid["status"] == "AVAILABLE"
    assert valid["decision_blocking"] is False
    assert valid["finance"] == {
        "exact_private": True,
        "provenance": "AUTHENTICATED_OFFICIAL",
    }


def test_authenticated_client_has_no_competitor_or_mutating_route() -> None:
    own = authenticated_official.EXPECTED_TEAM_ID
    assert official_auth.ALLOWED_API_PATHS == {
        "me/",
        f"my-team/{own}/",
        f"entry/{own}/transfers-latest/",
    }
    assert all("leagues" not in path and "picks" not in path for path in official_auth.ALLOWED_API_PATHS)
